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


def apply_upstream_fixes(*, files: bool, shell: bool, platform: str) -> list[str]:
    applied = []
    if files and fix_rmtree_onexc():
        applied.append("rmtree-onexc")
    if shell and fix_tmux_startup_race(platform):
        applied.append("tmux-startup-race")
    if applied:
        logger.info("Applied upstream fixes: %s", ", ".join(applied))
    return applied
