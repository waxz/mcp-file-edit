"""Unified MCP server: file-editing and shell-execution tools in one FastMCP app."""

from __future__ import annotations

import hmac
import logging
import sys
from typing import Any, Callable, Sequence

from anyio import ClosedResourceError
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import Middleware, MiddlewareContext
from mcp.server.session import ServerSession

from . import config
from .config import Settings, load_settings

logger = logging.getLogger(__name__)

FS_PREFIX = "fs_"
SHELL_PREFIX = "shell_"


# --------------------------------------------------------------------- auth
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
    """Constant-time API-key check on every tool call over HTTP.

    Accepts ``Authorization: Bearer <key>`` or ``x-api-key: <key>`` and never
    echoes the presented key or request headers back to the caller.
    """

    def __init__(self, valid_keys: frozenset[str]):
        self.valid_keys = valid_keys

    def is_valid(self, key: str | None) -> bool:
        if not key:
            return False
        matched = False
        for valid in self.valid_keys:  # check all keys: timing doesn't reveal which
            matched |= hmac.compare_digest(key.encode(), valid.encode())
        return matched

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        # include_all: by default fastmcp strips the Authorization header.
        if not self.is_valid(_extract_api_key(get_http_headers(include_all=True))):
            raise ToolError("Unauthorized: missing or invalid API key")
        return await call_next(context)


# -------------------------------------------------------------- registration
class _PrefixedRegistrar:
    """Stand-in for a FastMCP app that adds a prefix to every tool name."""

    def __init__(self, app: FastMCP, prefix: str):
        self._app = app
        self._prefix = prefix

    def tool(self, fn: Callable[..., Any] | None = None, **kwargs: Any):
        def register(f: Callable[..., Any]):
            name = kwargs.pop("name", None) or f.__name__
            return self._app.tool(f, name=f"{self._prefix}{name}", **kwargs)

        return register(fn) if callable(fn) else register


def _suppress_disconnect_errors() -> None:
    """Don't log tracebacks when a client disconnects before its response."""
    if getattr(ServerSession._send_response, "_unified_patched", False):
        return
    original = ServerSession._send_response

    async def send_response(self, request_id, response):
        try:
            await original(self, request_id, response)
        except ClosedResourceError:
            logger.info("Client disconnected before the response was sent")

    send_response._unified_patched = True
    ServerSession._send_response = send_response


def build_server(settings: Settings) -> FastMCP:
    """Create the FastMCP app with every enabled tool registered on it."""
    config.SETTINGS = settings
    _suppress_disconnect_errors()
    app = FastMCP(settings.APP_NAME)

    if settings.ENABLE_FILES:
        from .files.preview_routes import register_preview_routes
        from .files.tool_handlers import register_tools as register_file_tools

        register_file_tools(_PrefixedRegistrar(app, FS_PREFIX) if settings.NAMESPACED else app)
        register_preview_routes(app)

    if settings.ENABLE_SHELL:
        from .shell.tool_handlers import register_tools as register_shell_tools

        # Tool names of the two families don't overlap, and FastMCP would
        # reject a duplicate name, so no collision check is needed here.
        register_shell_tools(_PrefixedRegistrar(app, SHELL_PREFIX) if settings.NAMESPACED else app)

    keys = settings.api_keys
    if keys and settings.TRANSPORT == "http":
        app.add_middleware(ApiKeyAuth(keys))
    elif keys:
        logger.info("API_KEYS ignored for stdio transport (no HTTP headers)")
    return app


# --------------------------------------------------------------------- main
def _install_disconnect_guard() -> None:
    previous = sys.excepthook

    def hook(exc_type, exc_value, tb):
        if exc_type.__name__ == "ClosedResourceError":
            logger.info("Client disconnected")
            return
        if exc_type.__name__ == "BaseExceptionGroup" and any(
            type(e).__name__ == "ClosedResourceError" for e in getattr(exc_value, "exceptions", [])
        ):
            logger.info("Client disconnected")
            return
        previous(exc_type, exc_value, tb)

    sys.excepthook = hook


def main(argv: Sequence[str] | None = None) -> None:
    # Log to stderr: with the stdio transport, stdout carries the protocol.
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    settings = load_settings(argv)
    app = build_server(settings)
    _install_disconnect_guard()

    if settings.TRANSPORT == "http":
        app.run(transport="http", host=settings.HOST, port=settings.PORT, path=settings.PATH)
    else:
        app.run()


if __name__ == "__main__":
    main()
