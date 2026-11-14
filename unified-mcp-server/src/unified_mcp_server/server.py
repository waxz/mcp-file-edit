"""Unified MCP server: mounts mcp-file-edit and shell-mcp-server into one app.

Both upstream servers keep module-level ``config.SETTINGS`` singletons and
register their tools on a FastMCP instance.  We initialise each singleton from
the shared config, build each sub-server *without* its own auth middleware,
and mount both on a parent server that owns auth and transport.
"""

from __future__ import annotations

import hmac

import anyio
import logging
from pathlib import Path
from typing import Sequence

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import Middleware, MiddlewareContext

from .config import UnifiedSettings, load_settings
from .patches import apply_upstream_fixes

logger = logging.getLogger(__name__)

# Upstream from_runtime() first loads a bundled config.toml from this module
# attribute; point it at nothing so only our merged config applies.
_NO_FILE = "/nonexistent/unified-mcp-server/config.toml"

FS_NAMESPACE = "fs"
SHELL_NAMESPACE = "shell"


# --------------------------------------------------------------------------- auth
def _extract_api_key(headers: dict[str, str]) -> str | None:
    lowered = {k.lower(): v for k, v in headers.items()}
    auth = lowered.get("authorization")
    if auth:
        parts = auth.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1]
        return auth.strip()
    key = lowered.get("x-api-key")
    return key.strip() if key else None


class ApiKeyAuth(Middleware):
    """Constant-time API-key check for tool calls over HTTP.

    Unlike the upstream middleware, this accepts several keys and never echoes
    the presented key or request headers back to the caller.
    """

    def __init__(self, valid_keys: frozenset[str]):
        self.valid_keys = valid_keys

    def is_valid(self, key: str | None) -> bool:
        if not key:
            return False
        # Check every key so timing does not reveal which one matched.
        matched = False
        for valid in self.valid_keys:
            matched |= hmac.compare_digest(key.encode(), valid.encode())
        return matched

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        if not self.is_valid(_extract_api_key(get_http_headers(include_all=True))):
            raise ToolError("Unauthorized: missing or invalid API key")
        return await call_next(context)


# ----------------------------------------------------- shared project directory
class ProjectDirSync(Middleware):
    """Keep the shell tools' working root in step with ``set_project_directory``.

    Only active when the shell host root was not configured explicitly, so
    ``cwd="."`` in ``execute_command`` means "the current project directory".
    """

    def __init__(self, tool_name: str):
        self.tool_name = tool_name

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        result = await call_next(context)
        if context.message.name == self.tool_name:
            sync_shell_root_from_project()
        return result


def sync_shell_root_from_project() -> None:
    from mcp_file_edit import utils as fe_utils
    from shell_mcp_server import config as sh_config

    if (
        sh_config.SETTINGS is not None
        and fe_utils.CONNECTION_TYPE == "local"
        and fe_utils.PROJECT_DIR is not None
    ):
        sh_config.SETTINGS.DOCKER_SANDBOX_HOST_ROOT = str(fe_utils.PROJECT_DIR)


# ------------------------------------------------------------------ sub-servers
def _build_file_server(settings: UnifiedSettings) -> FastMCP:
    from mcp_file_edit import config as fe_config
    from mcp_file_edit import mcp_utils as fe_mcp_utils

    # Never let a wheel-bundled upstream config.toml (with author-specific
    # paths) leak in: the unified merged config replaces it.
    fe_config.CONFIG_FILE_PATH = _NO_FILE
    cfg = settings.child_config_file(fe_config.Settings.model_fields)
    fe_config.SETTINGS = fe_config.Settings.from_runtime(settings.child_args(cfg))
    fe_config.SETTINGS.API_KEYS = None  # auth is enforced once, on the parent
    # build_server also registers the /patch-preview HTTP routes.
    return fe_mcp_utils.build_server(fe_config.SETTINGS)


def _build_shell_server(settings: UnifiedSettings) -> tuple[FastMCP, bool]:
    from shell_mcp_server import config as sh_config
    from shell_mcp_server import mcp_utils as sh_mcp_utils

    sh_config.CONFIG_FILE_PATH = _NO_FILE
    cfg = settings.child_config_file(sh_config.Settings.model_fields)
    sh_config.SETTINGS = sh_config.Settings.from_runtime(
        settings.child_args(cfg), dict(settings.shells), bool(settings.shells)
    )
    sh_config.SETTINGS.API_KEYS = None

    linked = False
    if settings.enable_files:
        # Share the file server's roots unless the shell section sets its own.
        from mcp_file_edit import config as fe_config
        from mcp_file_edit import utils as fe_utils

        if not sh_config.SETTINGS.DOCKER_SANDBOX_HOST_ROOT and fe_utils.PROJECT_DIR:
            sh_config.SETTINGS.DOCKER_SANDBOX_HOST_ROOT = str(fe_utils.PROJECT_DIR)
            linked = True
        if not sh_config.SETTINGS.ALLOWED_DIRECTORIES_HOST:
            sh_config.SETTINGS.ALLOWED_DIRECTORIES_HOST = list(
                fe_config.SETTINGS.ALLOWED_DIRECTORIES
            )
    return sh_mcp_utils.build_server(sh_config.SETTINGS), linked


async def _tool_names(server: FastMCP) -> set[str]:
    return {t.name for t in await server.list_tools()}


async def build_unified_server(settings: UnifiedSettings) -> FastMCP:
    app = FastMCP("unified-mcp-server")

    children: list[tuple[str, FastMCP]] = []
    shell_linked = False
    shell_app = None
    platform = ""
    if settings.enable_files:
        children.append((FS_NAMESPACE, _build_file_server(settings)))
    if settings.enable_shell:
        from shell_mcp_server import config as sh_config

        shell_app, shell_linked = _build_shell_server(settings)
        platform = sh_config.SETTINGS.PLATFORM
        children.append((SHELL_NAMESPACE, shell_app))

    apply_upstream_fixes(files=settings.enable_files, shell_app=shell_app, platform=platform)

    if not settings.namespaced and len(children) > 1:
        names = [await _tool_names(child) for _, child in children]
        clash = set.intersection(*names)
        if clash:
            raise RuntimeError(
                f"Tool name collision between sub-servers: {sorted(clash)}; "
                "enable namespacing with --namespaced"
            )

    for namespace, child in children:
        app.mount(child, namespace=namespace if settings.namespaced else None)

    if settings.api_keys and settings.transport == "http":
        app.add_middleware(ApiKeyAuth(settings.api_keys))
    elif settings.api_keys:
        logger.info("API_KEYS ignored for stdio transport (no HTTP headers)")

    if shell_linked:
        name = "set_project_directory"
        if settings.namespaced:
            name = f"{FS_NAMESPACE}_{name}"
        app.add_middleware(ProjectDirSync(name))

    return app


# ------------------------------------------------------------------------ main
def _install_disconnect_guard() -> None:
    """Don't crash on client disconnects (same behaviour as upstream servers)."""
    import sys

    previous = sys.excepthook

    def hook(exc_type, exc_value, tb):
        if exc_type.__name__ == "ClosedResourceError":
            logger.info("Client disconnected")
            return
        if exc_type.__name__ == "BaseExceptionGroup" and any(
            type(e).__name__ == "ClosedResourceError"
            for e in getattr(exc_value, "exceptions", [])
        ):
            logger.info("Client disconnected")
            return
        previous(exc_type, exc_value, tb)

    sys.excepthook = hook


def main(argv: Sequence[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO)
    settings = load_settings(argv)
    app = anyio.run(build_unified_server, settings)
    _install_disconnect_guard()

    if settings.transport == "http":
        app.run(transport="http", host=settings.host, port=settings.port, path=settings.path)
    else:
        app.run()


if __name__ == "__main__":
    main()
