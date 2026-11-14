# Derived from shell-mcp-server (Apache-2.0, https://github.com/waxz/shell-mcp-server);
# modified for unified-mcp-server. See NOTICE and LICENSE-APACHE.
"""Windows command adapter with strict argument escaping."""

from __future__ import annotations

import base64
import logging
from pathlib import PurePosixPath, PureWindowsPath


def _ps_single_quoted(value: str) -> str:
    """Escape a string for PowerShell single-quoted literal context."""
    return value.replace("'", "''")


logger = logging.getLogger(__name__)


def _map_host_cwd_to_sandbox(
    cwd: str,
    host_root: str | None,
    work_dir: str | None,
) -> str:
    """Map a Windows host cwd into the Linux sandbox path space."""
    if not work_dir:
        return cwd or "."
    if not cwd:
        return str(PurePosixPath(work_dir))

    cwd_win = PureWindowsPath(cwd.replace("/", "\\"))
    host_root_win = PureWindowsPath(host_root.replace("/", "\\")) if host_root else None
    work_dir_posix = PurePosixPath(work_dir)

    if host_root_win and cwd_win.is_absolute() and host_root_win in (cwd_win, *cwd_win.parents):
        rel = cwd_win.relative_to(host_root_win)
        return str(PurePosixPath(work_dir_posix, *rel.parts))

    return str(work_dir_posix)


def build_windows_shell_command(
    shell: str,
    shell_path: str,
    command: str,
    cwd: str,
    trusted: bool = False,
    work_dir: str | None = None,
    host_root: str | None = None,
) -> list[str]:
    """Build a Windows shell invocation argument list."""


    logger.debug(
        "build_windows_shell_command shell=%s trusted=%s work_dir=%s host_root=%s cwd=%s",
        shell,
        trusted,
        work_dir,
        host_root,
        cwd,
    )
    if shell == "wsl":
        return [shell_path, "--cd", cwd, "bash", "-c", command]

    if shell == "cmd":
        return [shell_path, "/c", command]


    quoted_cwd = _ps_single_quoted(cwd)

    if shell == "bash" and not trusted:
        if quoted_cwd in {"", "."}:
            wrapped_command = command
        else:
            wrapped_command = (
                f"if [ -d '{quoted_cwd}' ]; then cd '{quoted_cwd}'; {command}; "
                f"else echo 'Directory {quoted_cwd} does not exist'; fi "
            )
            wrapped_command =  f"( cd '{quoted_cwd}' &&  {command} )"
            
        logger.debug("Wrapped command: %s", wrapped_command)
        encoded_command = base64.b64encode(wrapped_command.encode("utf-8")).decode("ascii")
        safe_runner = f"echo {encoded_command} | base64 -d | bash"
        quoted_host_root = _ps_single_quoted(host_root)
        quoted_work_dir = _ps_single_quoted(work_dir)

        final_command = f"""
                $ENV:DOCKER_SANDBOX_HOST_ROOT_OVERRIDE="{quoted_host_root}";
                $ENV:DOCKER_SANDBOX_WORKDIR_OVERRIDE="{quoted_work_dir}";
                drun "{safe_runner}"
                """ 
        logger.debug("Final command: %s", final_command)

        return [
            "powershell.exe",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            final_command,
        ]

    return [shell_path, "-ExecutionPolicy", "Bypass", "-Command", command]
