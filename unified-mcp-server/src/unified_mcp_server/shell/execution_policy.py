# Derived from shell-mcp-server (Apache-2.0, https://github.com/waxz/shell-mcp-server);
# modified for unified-mcp-server. See NOTICE and LICENSE-APACHE.
"""Execution policy and command resolution."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from pathlib import PurePosixPath, PureWindowsPath

from .. import config
from ..common.models import ExecutionRequest
from ..common.path_utils import (
    is_windows_style_path,
    normalize_posix_path,
    normalize_windows_path_text,
)

logger = logging.getLogger(__name__)

_SESSION_NAME_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_SHELL_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def validate_tmux_session_name(session_name: str) -> str:
    """Validate tmux session name against a strict allowlist."""
    if not _SESSION_NAME_RE.fullmatch(session_name):
        raise ValueError("Invalid tmux session name")
    return session_name


def _validate_string_input(value: str, field_name: str) -> str:
    if "\x00" in value:
        raise ValueError(f"Invalid {field_name}: null byte is not allowed")
    if "\r" in value:
        raise ValueError(f"Invalid {field_name}: carriage return is not allowed")
    return value


def _validate_string_cwd(value: str, field_name: str) -> str:
    if "\x00" in value:
        raise ValueError(f"Invalid {field_name}: null byte is not allowed")
    if "\n" in value or "\r" in value:
        raise ValueError(f"Invalid {field_name}: multiline input is not allowed")
    return value


def _validate_shell_name(shell: str) -> str:
    if "\x00" in shell:
        raise ValueError("Invalid shell: null byte is not allowed")
    if "\n" in shell or "\r" in shell:
        raise ValueError("Invalid shell: multiline input is not allowed")
    if not _SHELL_NAME_RE.fullmatch(shell):
        raise ValueError("Invalid shell: only [A-Za-z0-9_.-] is allowed")
    return shell


def _normalize_windows_path(path_text: str) -> str:
    return normalize_windows_path_text(path_text)


def _normalize_posix_path(path_text: str) -> PurePosixPath:
    return normalize_posix_path(path_text)


def _coerce_platform_path(
    path_text: str,
    settings: config.Settings,
    is_trusted: bool = True,
) -> str:
    if not is_trusted:
        if is_windows_style_path(path_text):
            raise ValueError(f"Invalid path {path_text} in is_trusted:{is_trusted} env")
        path = _normalize_posix_path(path_text)
        if path.is_absolute():
            resolved = path
            return str(resolved)

        work_dir = settings.DOCKER_SANDBOX_WORKDIR or "."
        host_dir = _normalize_posix_path(work_dir)
        resolved = PurePosixPath(host_dir, path)
        return str(resolved)

    if settings.PLATFORM == "windows":
        windows_path = PureWindowsPath(path_text)
        if windows_path.is_absolute():
            resolved = PureWindowsPath(path_text)
            return str(resolved)

        host_root = settings.DOCKER_SANDBOX_HOST_ROOT
        if not host_root:
            raise ValueError("DOCKER_SANDBOX_HOST_ROOT is required on windows trusted mode")
        resolved = PureWindowsPath(host_root) / windows_path
        return str(resolved)

    path = Path(path_text)
    if path.is_absolute():
        resolved = Path(path_text)
        return str(resolved)

    host_root = settings.DOCKER_SANDBOX_HOST_ROOT or "."
    resolved = Path(host_root, path)
    return str(resolved)

def _allowed_directories(settings: config.Settings, is_trusted: bool) -> list[str]:
    if is_trusted:
        return settings.ALLOWED_DIRECTORIES_HOST
    return settings.ALLOWED_DIRECTORIES_DOCKER


def _is_allowed_path(path: str, settings: config.Settings, is_trusted: bool) -> bool:
    allowed_dirs = _allowed_directories(settings, is_trusted)

    if not is_trusted:
        resolved = _normalize_posix_path(path)
        for allowed in allowed_dirs:
            allowed_path = _coerce_platform_path(allowed, settings, is_trusted)
            allowed_path = _normalize_posix_path(allowed_path)
            if resolved == allowed_path or allowed_path in resolved.parents:
                return True
    else:
        if settings.PLATFORM == "windows":
            resolved = _normalize_windows_path(path)
            for allowed in allowed_dirs:
                allowed_path = _normalize_windows_path(
                    _coerce_platform_path(allowed, settings, is_trusted)
                )
                if resolved == allowed_path or resolved.startswith(f"{allowed_path}\\"):
                    return True
            return False

        resolved = Path(path).resolve()
        for allowed in allowed_dirs:
            allowed_path = _coerce_platform_path(allowed, settings, is_trusted)
            allowed_path = Path(allowed_path).resolve()
            if resolved == allowed_path or allowed_path in resolved.parents:
                return True
    return False


def _resolve_absolute_cwd(cwd: str, settings: config.Settings, is_trusted: bool) -> str:
    resolved = _coerce_platform_path(cwd, settings, is_trusted)

    if not _is_allowed_path(resolved, settings, is_trusted):
        raise ValueError("Directory not allowed")
    return str(resolved)

def resolve_request(command: str, cwd: str, shell: str = "bash") -> ExecutionRequest:
    """Resolve trusted command mapping and validate path/shell policy."""
    settings = config.SETTINGS
    if settings is None:
        raise RuntimeError("Server settings are not initialized")

    _validate_string_input(command, "command")
    _validate_string_cwd(cwd, "cwd")
    _validate_shell_name(shell)

    is_trusted = command in settings.TRUSTED_COMMANDS
    resolved_command = command
    resolved_cwd = cwd
    resolved_shell = shell

    if is_trusted:
        command_cfg = settings.TRUSTED_COMMANDS[command]
        resolved_command = command_cfg.get("command", "")
        resolved_cwd = command_cfg.get("cwd", "")
        resolved_shell = command_cfg.get("shell", "")
        if not (resolved_command and resolved_cwd and resolved_shell):
            raise ValueError(f"Incomplete trusted command config: {command}")
    if settings.SAFETY_MODE == "strict" and not is_trusted:
        resolved_shell = "bash"
    
    
    if settings.IS_IN_DOCKER:
        is_trusted = True
        resolved_shell = "bash"

    if resolved_shell not in settings.ALLOWED_SHELLS:
        available_shells = ", ".join(sorted(settings.ALLOWED_SHELLS.keys()))
        raise ValueError(
            f"Shell '{resolved_shell}' is not allowed. Available: {available_shells}"
        )

    absolute_cwd = _resolve_absolute_cwd(
        cwd=resolved_cwd,
        settings=settings,
        is_trusted=is_trusted,
    )

    return ExecutionRequest(
        command=resolved_command,
        cwd=absolute_cwd,
        shell=resolved_shell,
        trusted=is_trusted,
    )
