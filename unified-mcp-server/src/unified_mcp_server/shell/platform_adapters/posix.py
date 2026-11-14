# Derived from shell-mcp-server (Apache-2.0, https://github.com/waxz/shell-mcp-server);
# modified for unified-mcp-server. See NOTICE and LICENSE-APACHE.
"""POSIX command adapter."""

from __future__ import annotations

import base64
import logging
import shlex

logger = logging.getLogger(__name__)


def build_posix_shell_command(
    shell_path: str,
    command: str,
    cwd: str,
    trusted: bool = False,
    work_dir: str | None = None,
    host_root: str | None = None,
) -> list[str]:
    """Build a POSIX shell invocation argument list."""
    logger.debug(
        "build_posix_shell_command trusted=%s work_dir=%s host_root=%s cwd=%s",
        trusted,
        work_dir,
        host_root,
        cwd,
    )
    if cwd in ["", "."]:
        wrapped_command = command
    else:
        new_cwd = shlex.quote(cwd)
        wrapped_command = f" if [ -d {new_cwd} ]; then cd {new_cwd}; {command}; else echo 'Directory {new_cwd} does not exist'; fi "
        wrapped_command = f" (cd {new_cwd} && {command} ) "
   
    logger.debug("wrapped_command: %s", wrapped_command)
    logger.debug(
        "build_posix_shell_command trusted=%s work_dir=%s host_root=%s",
        trusted,
        work_dir,
        host_root,
    )
    if not trusted:
        encoded_command = base64.b64encode(wrapped_command.encode("utf-8")).decode("ascii")
        safe_runner = f"echo {encoded_command} | base64 -d | bash"
        quoted_host_root = shlex.quote(host_root or "")
        quoted_work_dir = shlex.quote(work_dir or "")
        return [
            shell_path,
            "-c",
            (
                "source ~/.bashrc > /dev/null 2>&1 && "
                f"export DOCKER_SANDBOX_HOST_ROOT_OVERRIDE={quoted_host_root} && "
                f"export DOCKER_SANDBOX_WORKDIR_OVERRIDE={quoted_work_dir} && "
                f"drun '{safe_runner}'"
            ),
        ]

    return [shell_path, "-c", wrapped_command]
