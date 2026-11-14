# Derived from shell-mcp-server (Apache-2.0, https://github.com/waxz/shell-mcp-server);
# modified for unified-mcp-server. See NOTICE and LICENSE-APACHE.
"""Safe tmux command builders."""

from __future__ import annotations

import shlex

from .execution_policy import validate_tmux_session_name


def _sanitize_value(value: str, field_name: str) -> str:
    if "\x00" in value:
        raise ValueError(f"Invalid {field_name}: null byte is not allowed")
    # if "\n" in value or "\r" in value:
    #     raise ValueError(f"Invalid {field_name}: multiline input is not allowed")
    return value


#: How long a new tmux session may take to show its shell prompt.
TMUX_READY_TIMEOUT_S = 10.0
_TMUX_POLL_S = 0.05


def build_tmux_bootstrap_command(session_name: str, wait_for_prompt: bool = True) -> str:
    """Create a detached session and (POSIX) wait until its shell shows a prompt.

    Returning right after ``new-session`` let the keys sent next reach the pane
    before its shell had started; a C-c at that point killed the shell and the
    tmux server with it.  If the prompt is empty we stop waiting at the timeout
    instead of failing.
    """
    session = shlex.quote(validate_tmux_session_name(session_name))
    create = f"tmux new-session -s {session} -d"
    if not wait_for_prompt:
        return create
    tries = int(TMUX_READY_TIMEOUT_S / _TMUX_POLL_S)
    return (
        f"{create} && i=0; while [ $i -lt {tries} ]; do "
        f"[ -n \"$(tmux capture-pane -t {session} -p | tr -d '[:space:]')\" ] && break; "
        f"i=$((i + 1)); sleep {_TMUX_POLL_S}; done"
    )


def build_tmux_send_keys_command(session_name: str, command: str) -> str:
    session = shlex.quote(validate_tmux_session_name(session_name))
    
    # Split the command into individual lines
    lines = command.strip().splitlines()
    
    tmux_segments = []
    for line in lines:
        safe_line = shlex.quote(_sanitize_value(line, "command"))
        # You MUST include 'tmux' before every 'send-keys'
        tmux_segments.append(f"tmux send-keys -t {session} -l {safe_line}")
        tmux_segments.append(f"tmux send-keys -t {session} Enter")
    
    # Join with ';' so PowerShell runs them one after another
    return " ; ".join(tmux_segments)
    
def build_tmux_reset_pane_command(session_name: str) -> list[str]:
    """Reset a freshly created pane so captures don't include startup output.

    No C-c: tmux_execute always creates a new session (new-session fails on an
    existing name), so there is never a running command to interrupt, and a C-c
    sent while the shell is still starting kills it.
    """
    session = shlex.quote(validate_tmux_session_name(session_name))
    return [
        f"tmux send-keys -t {session} clear Enter",
        f"tmux clear-history -t {session}",
    ]


def build_tmux_capture_command(session_name: str) -> str:
    session = shlex.quote(validate_tmux_session_name(session_name))
    return f"tmux capture-pane -t {session} -p"


def build_tmux_clear_command(session_name: str) -> str:
    session = shlex.quote(validate_tmux_session_name(session_name))
    return f"tmux send-keys -t {session} clear Enter"


def build_tmux_kill_command(session_name: str) -> str:
    session = shlex.quote(validate_tmux_session_name(session_name))
    return f"tmux kill-session -t {session}"
