"""Runtime fixes for upstream bugs, applied by the unified server only.

The upstream packages (mcp-file-edit, shell-mcp-server) are left untouched;
these patches replace module-level names they look up at call time.  Each fix
is idempotent and checks that the upstream code still has the shape it
expects, so an upstream change can't be silently overridden.
"""

from __future__ import annotations

import logging
import shlex
import shutil
import sys
import types

logger = logging.getLogger(__name__)

_APPLIED: set[str] = set()


# ---------------------------------------------------------------- rmtree
class _ShutilCompat(types.ModuleType):
    """``shutil`` stand-in whose ``rmtree`` accepts ``onexc`` on Python < 3.12.

    mcp-file-edit calls ``shutil.rmtree(path, onexc=handler)``; ``onexc`` was
    added in 3.12, so on 3.11 ``remove_directory``/``delete_file`` raise
    ``TypeError``.  ``onexc(func, path, exc)`` maps onto the older
    ``onerror(func, path, exc_info)``.
    """

    def __init__(self) -> None:
        super().__init__("shutil")

    def __getattr__(self, name: str):
        return getattr(shutil, name)

    @staticmethod
    def rmtree(path, ignore_errors=False, onerror=None, *, onexc=None, dir_fd=None):
        if onexc is not None:
            if onerror is not None:
                raise TypeError("rmtree() got both onerror and onexc")

            def onerror(func, p, exc_info, _onexc=onexc):
                return _onexc(func, p, exc_info[1])

        kwargs = {} if dir_fd is None else {"dir_fd": dir_fd}
        return shutil.rmtree(path, ignore_errors, onerror, **kwargs)


def fix_rmtree_onexc() -> bool:
    """Make mcp-file-edit's rmtree work on Python < 3.12."""
    if sys.version_info >= (3, 12) or "rmtree" in _APPLIED:
        return False
    from mcp_file_edit import file_operations

    if file_operations.shutil is not shutil:
        logger.warning("mcp_file_edit.file_operations.shutil changed upstream; rmtree fix skipped")
        return False
    file_operations.shutil = _ShutilCompat()
    _APPLIED.add("rmtree")
    return True


# ------------------------------------------------------------------ tmux
#: How long tmux_execute waits for a new pane's shell to show its prompt.
TMUX_READY_TIMEOUT_S = 10.0
_TMUX_POLL_S = 0.05


def build_tmux_bootstrap_command(session_name: str) -> str:
    """Create the session, then wait until its shell has drawn a prompt.

    Upstream returned right after ``new-session``, so keys sent next could reach
    the pane before its shell had started.
    """
    from shell_mcp_server.execution_policy import validate_tmux_session_name

    session = shlex.quote(validate_tmux_session_name(session_name))
    tries = int(TMUX_READY_TIMEOUT_S / _TMUX_POLL_S)
    # Non-empty pane == the shell has printed its prompt. If the prompt is
    # empty we fall through after the timeout instead of failing.
    return (
        f"tmux new-session -s {session} -d && "
        f"i=0; while [ $i -lt {tries} ]; do "
        f'[ -n "$(tmux capture-pane -t {session} -p | tr -d \'[:space:]\')" ] && break; '
        f"i=$((i + 1)); sleep {_TMUX_POLL_S}; done"
    )


def build_tmux_reset_pane_command(session_name: str) -> list[str]:
    """Reset a fresh pane without sending C-c.

    tmux_execute always creates a new session (new-session fails on an
    existing name), so there is never a running command to interrupt; the
    upstream C-c only served to kill a shell that was still starting.
    """
    from shell_mcp_server.execution_policy import validate_tmux_session_name

    session = shlex.quote(validate_tmux_session_name(session_name))
    return [
        f"tmux send-keys -t {session} clear Enter",
        f"tmux clear-history -t {session}",
    ]


def fix_tmux_startup_race(platform: str) -> bool:
    """Stop tmux_execute from killing the new pane's shell on slow machines."""
    if "tmux" in _APPLIED:
        return False
    if platform == "windows":
        # The bootstrap wait is POSIX shell; tmux sessions aren't expected there.
        return False
    from shell_mcp_server import tmux_commands, tool_handlers

    upstream_reset = tmux_commands.build_tmux_reset_pane_command("probe")
    if not any(cmd.split()[-2:] == ["C-c", "Enter"] for cmd in upstream_reset):
        logger.info("upstream tmux reset no longer sends C-c; tmux fix not needed")
        return False
    tool_handlers.build_tmux_bootstrap_command = build_tmux_bootstrap_command
    tool_handlers.build_tmux_reset_pane_command = build_tmux_reset_pane_command
    _APPLIED.add("tmux")
    return True


# ------------------------------------------------------ async functions
def _python_functions_with_async(content: str) -> list[dict]:
    """``CodeAnalyzer.extract_functions_from_python`` that also sees ``async def``.

    Upstream's visitor only defines ``visit_FunctionDef``, so ``async def``
    functions and methods were skipped by list_functions, get_function_at_line,
    search_functions and get_code_structure.  Same fields and traversal as
    upstream; the one change is handling ``AsyncFunctionDef`` too.
    """
    import ast

    from mcp_file_edit.code_analyzer import CodeAnalyzer

    tree = CodeAnalyzer.parse_python_file(content)

    class FunctionVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.functions: list[dict] = []
            self.current_class: str | None = None

        def visit_ClassDef(self, node):
            old_class = self.current_class
            self.current_class = node.name
            self.generic_visit(node)
            self.current_class = old_class

        def visit_FunctionDef(self, node):
            info = {
                "name": node.name,
                "line_start": node.lineno,
                "line_end": node.end_lineno,
                "signature": CodeAnalyzer.get_function_signature(node),
                "docstring": CodeAnalyzer.get_docstring(node),
                "decorators": [
                    d.id if isinstance(d, ast.Name) else ast.unparse(d) for d in node.decorator_list
                ],
                "is_method": self.current_class is not None,
                "class_name": self.current_class,
                "is_async": isinstance(node, ast.AsyncFunctionDef),
            }
            if node.returns:
                info["return_type"] = ast.unparse(node.returns)
            param_types = {a.arg: ast.unparse(a.annotation) for a in node.args.args if a.annotation}
            if param_types:
                info["param_types"] = param_types
            self.functions.append(info)
            self.generic_visit(node)

        visit_AsyncFunctionDef = visit_FunctionDef

    visitor = FunctionVisitor()
    visitor.visit(tree)
    return visitor.functions


def fix_async_function_listing() -> bool:
    if "async-functions" in _APPLIED:
        return False
    from mcp_file_edit.code_analyzer import CodeAnalyzer

    if CodeAnalyzer.extract_functions_from_python("async def probe():\n    pass\n"):
        logger.info("upstream already lists async functions; fix not needed")
        return False
    CodeAnalyzer.extract_functions_from_python = staticmethod(_python_functions_with_async)
    _APPLIED.add("async-functions")
    return True


# ------------------------------------------------------- tmux sessions
def _session_names(stdout: str) -> list[str]:
    return [line.split(":", 1)[0] for line in stdout.splitlines() if line.strip()]


async def tmux_list_session(shell: str = "bash") -> list[str]:
    """List active tmux sessions."""
    from shell_mcp_server import config
    from shell_mcp_server.executor import run_shell_command

    settings = config.SETTINGS
    if shell not in settings.ALLOWED_SHELLS:
        allowed = ", ".join(sorted(settings.ALLOWED_SHELLS))
        raise ValueError(f"Shell '{shell}' is not allowed. Available: {allowed}")

    sessions: list[str] = []
    # Sandbox sessions (untrusted): only when a sandbox work dir exists.
    # Upstream always ran this, crashing with cwd=None when it wasn't set.
    if settings.DOCKER_SANDBOX_WORKDIR and not settings.IS_IN_DOCKER:
        result = await run_shell_command(
            command="tmux ls", cwd=settings.DOCKER_SANDBOX_WORKDIR, shell=shell, is_trusted=False
        )
        if result.exit_code == 0:
            sessions += _session_names(result.stdout)
    # Host sessions (trusted, the ``native_mcp_`` ones).
    if settings.IS_TMUX_INSTALLED:
        import os

        result = await run_shell_command(
            command="tmux ls",
            cwd=settings.DOCKER_SANDBOX_HOST_ROOT or os.getcwd(),
            shell=shell,
            is_trusted=True,
        )
        # Exit 1 with "no server running" just means there are no sessions;
        # upstream raised on it.
        if result.exit_code == 0:
            sessions += _session_names(result.stdout)
        elif "no server running" not in result.stderr and "error connecting" not in result.stderr:
            raise ValueError(f"tmux ls failed: {result.stderr.strip()}")
    return list(dict.fromkeys(sessions))


def fix_tmux_list_session(shell_app) -> bool:
    """Replace the registered tmux_list_session tool on this shell sub-server."""
    import inspect

    from fastmcp.server.tasks import TaskConfig
    from shell_mcp_server import tool_handlers

    src = inspect.getsource(tool_handlers.register_tools)
    if "cwd = config.SETTINGS.DOCKER_SANDBOX_WORKDIR" not in src:
        logger.warning("upstream tmux_list_session changed; fix skipped")
        return False
    shell_app.local_provider.remove_tool("tmux_list_session")
    shell_app.tool(task=TaskConfig(mode="optional"))(tmux_list_session)
    return True


def apply_upstream_fixes(*, files: bool, shell_app=None, platform: str = "") -> list[str]:
    """Apply every fix relevant to the enabled sub-servers.

    Module-level fixes apply once per process; the tool replacement applies to
    each newly built shell sub-server.
    """
    applied = []
    if files and fix_rmtree_onexc():
        applied.append("rmtree-onexc")
    if files and fix_async_function_listing():
        applied.append("async-functions")
    if shell_app is not None and fix_tmux_startup_race(platform):
        applied.append("tmux-startup-race")
    if shell_app is not None and fix_tmux_list_session(shell_app):
        applied.append("tmux-list-session")
    if applied:
        logger.info("Applied upstream fixes: %s", ", ".join(applied))
    return applied
