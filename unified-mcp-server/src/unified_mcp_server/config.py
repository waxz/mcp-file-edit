"""Configuration for the unified MCP server: one model, one TOML file, one CLI.

The TOML format is a superset of the formats of the two projects this server
grew out of (mcp-file-edit and shell-mcp-server), so their config files load
unchanged:

* top level: ``TRANSPORT``, ``HOST``, ``PORT``, ``PATH``, ``PUBLIC_URL``,
  ``API_KEYS``, ``COMMAND_TIMEOUT``, ``SAFETY_MODE``, ``IS_IN_DOCKER``,
  ``ALLOWED_SHELLS``;
* ``[CONFIG.<os>]``: ``work_dir`` and ``allow_directories`` for the file tools;
* ``[DOCKER_CONFIG.<os>]``: ``host_root``, ``work_dir``,
  ``allow_directories_host``, ``allow_directories_docker`` for the shell tools;
* ``[TRUSTED_COMMANDS.<name>]``: commands the shell tools may run on the host;
* ``[UNIFIED]``: ``namespaced``, ``enable_files``, ``enable_shell``.

Precedence: built-in defaults -> config file -> CLI flags.  Unlike the original
projects, environment variables are *not* read: a pydantic ``BaseSettings``
model would otherwise pick up the system ``PATH``/``HOST`` variables.
"""

from __future__ import annotations

import argparse
import importlib.resources
import logging
import platform
import shutil
from pathlib import Path
from typing import Any, Dict, Sequence

import toml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .common.os_utils import check_installed
from .common.path_utils import get_platform_path, is_windows_style_path, normalize_directory_value

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = str(
    importlib.resources.files("unified_mcp_server").joinpath("default_config.toml")
)

_VIRTUAL_SHELL_ALIASES = {
    "bash", "sh", "cmd", "cmd.exe", "powershell", "powershell.exe",
    "pwsh", "pwsh.exe", "wsl", "wsl.exe",
}


def current_platform() -> str:
    name = platform.system().lower()
    if name.startswith("win"):
        return "windows"
    if name == "darwin":
        return "macos"
    return "linux"


def default_shells(platform_name: str) -> dict[str, str]:
    if platform_name == "windows":
        return {
            "bash": "powershell.exe",
            "cmd": "cmd.exe",
            "powershell": "powershell.exe",
            "wsl": "wsl.exe",
        }
    return {"bash": "/bin/bash", "sh": "/bin/sh"}


def _normalize_directory_list(value: list[str] | None) -> list[str]:
    result: list[str] = []
    for item in value or []:
        normalized = normalize_directory_value(item)
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def parse_api_keys(value: str | None) -> frozenset[str]:
    if not value:
        return frozenset()
    return frozenset(k.strip() for k in str(value).split(",") if k.strip())


class Settings(BaseModel):
    """Runtime settings shared by the file and shell tools."""

    model_config = ConfigDict(extra="ignore", validate_assignment=False)

    APP_NAME: str = "unified-mcp-server"
    APP_VERSION: str = "0.2.0"

    # ---- server
    TRANSPORT: str = "stdio"
    HOST: str = "127.0.0.1"
    PORT: int = 8000
    PATH: str = "/mcp"
    PUBLIC_URL: str | None = None
    API_KEYS: str | None = None
    PLATFORM: str = Field(default_factory=current_platform)

    # ---- unified
    NAMESPACED: bool = False
    ENABLE_FILES: bool = True
    ENABLE_SHELL: bool = True
    #: True when the shell host root wasn't configured and so follows the
    #: file tools' project directory (set by the model validator).
    SHELL_FOLLOWS_PROJECT: bool = False

    # ---- file tools
    CONFIG: Dict[str, Any] = Field(default_factory=dict)
    WORK_DIR: str | None = None
    ALLOWED_DIRECTORIES: list[str] = Field(default_factory=list)
    IS_GIT_INSTALLED: bool = Field(default_factory=lambda: check_installed("git"))

    # ---- shell tools
    COMMAND_TIMEOUT: int = 30
    SAFETY_MODE: str = "strict"
    IS_IN_DOCKER: bool = False
    IS_TMUX_INSTALLED: bool = Field(default_factory=lambda: check_installed("tmux"))
    TRUSTED_COMMANDS: dict[str, dict[str, str]] = Field(default_factory=dict)
    ALLOWED_SHELLS: dict[str, str] = Field(default_factory=dict)
    ALLOWED_DIRECTORIES_HOST: list[str] = Field(default_factory=list)
    ALLOWED_DIRECTORIES_DOCKER: list[str] = Field(default_factory=list)
    DOCKER_CONFIG: Dict[str, Any] = Field(default_factory=dict)
    DOCKER_SHELL_SERVICE: str | None = None
    DOCKER_SHELL_ENV_FILE: str | None = None
    DOCKER_SHELL_COMPOSE_FILE: str | None = None
    DOCKER_SANDBOX_WORKDIR: str | None = None
    DOCKER_SANDBOX_HOST_ROOT: str | None = None
    DOCKER_SANDBOX_CPUS: str | None = None
    DOCKER_SANDBOX_MEMORY: str | None = None
    DOCKER_SANDBOX_NETWORK: str | None = None
    DOCKER_SANDBOX_ENFORCE_CWD_MAP: bool = False
    UNTRUSTED_USE_DOCKER_SANDBOX: bool = False
    DOCKER_USE_DRUN_ON_LINUX: bool = True

    # ------------------------------------------------------------ validators
    @field_validator("TRANSPORT")
    @classmethod
    def _transport(cls, value: str) -> str:
        if value not in {"stdio", "http"}:
            raise ValueError("TRANSPORT must be 'stdio' or 'http'")
        return value

    @field_validator("PORT")
    @classmethod
    def _port(cls, value: int) -> int:
        if not 1 <= value <= 65535:
            raise ValueError("PORT must be in range 1..65535")
        return value

    @field_validator("PATH")
    @classmethod
    def _http_path(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("PATH must start with '/'")
        if any(ch in value for ch in ("\n", "\r", "\x00")):
            raise ValueError("PATH contains invalid control characters")
        return value

    @field_validator("COMMAND_TIMEOUT")
    @classmethod
    def _timeout(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("COMMAND_TIMEOUT must be positive")
        return value

    @field_validator("SAFETY_MODE")
    @classmethod
    def _safety_mode(cls, value: str) -> str:
        if value not in {"strict", "relax"}:
            raise ValueError("SAFETY_MODE must be 'strict' or 'relax'")
        return value

    @field_validator("IS_IN_DOCKER")
    @classmethod
    def _is_in_docker(cls, value: bool) -> bool:
        # Heuristic kept from shell-mcp-server: inside the sandbox container
        # there is no docker CLI, and the container is Linux.
        if value:
            if check_installed("docker"):
                raise ValueError("IS_IN_DOCKER=true requires that docker is not installed")
            if current_platform() != "linux":
                raise ValueError("IS_IN_DOCKER=true requires Linux")
        return value

    @field_validator("ALLOWED_DIRECTORIES_HOST", "ALLOWED_DIRECTORIES_DOCKER")
    @classmethod
    def _normalize_dirs(cls, value: list[str] | None) -> list[str]:
        return _normalize_directory_list(value)

    @field_validator("DOCKER_SANDBOX_HOST_ROOT")
    @classmethod
    def _host_root(cls, value: str | None) -> str | None:
        if not value:
            return None
        path = Path(value).resolve()
        if not path.is_dir():
            raise ValueError(f"Host root directory does not exist: {path}")
        return str(path)

    @model_validator(mode="after")
    def _runtime_contract(self) -> "Settings":
        if not (self.ENABLE_FILES or self.ENABLE_SHELL):
            raise ValueError("At least one of the file tools / shell tools must be enabled")
        self._resolve_project_directories()
        self._validate_shells()
        self._link_shell_to_project()
        return self

    def _resolve_project_directories(self) -> None:
        """Resolve WORK_DIR and allowed roots; set the file tools' project dir."""
        from .files import utils

        self.WORK_DIR = get_platform_path(".", self.PLATFORM, self.WORK_DIR)
        roots: list[str] = []
        for item in self.ALLOWED_DIRECTORIES or ["."]:
            resolved = get_platform_path(item, self.PLATFORM, self.WORK_DIR)
            if resolved not in roots:
                roots.append(resolved)
        self.ALLOWED_DIRECTORIES = roots

        utils.BASE_DIR = Path(self.WORK_DIR)
        allowed = [Path(r).resolve() for r in roots]
        work_dir = Path(self.WORK_DIR).resolve()
        utils.PROJECT_DIR = (
            work_dir if utils.is_within_allowed_directories(work_dir, allowed) else allowed[0]
        )

    def _validate_shells(self) -> None:
        for name, path in self.ALLOWED_SHELLS.items():
            if not path:
                raise ValueError(f"Shell '{name}' has empty path")
            if is_windows_style_path(path) or "/" in path:
                if not Path(path).exists():
                    raise ValueError(f"Shell '{name}' path does not exist: {path}")
            elif path not in _VIRTUAL_SHELL_ALIASES and not shutil.which(path):
                raise ValueError(f"Shell '{name}' executable not found: {path}")

        for name, spec in self.TRUSTED_COMMANDS.items():
            shell_name = spec.get("shell")
            if not shell_name or shell_name not in self.ALLOWED_SHELLS:
                allowed = ", ".join(sorted(self.ALLOWED_SHELLS))
                raise ValueError(
                    f"Trusted command '{name}' uses invalid shell '{shell_name}'. "
                    f"Allowed shells: {allowed}"
                )
            shell_path = self.ALLOWED_SHELLS[shell_name]
            if self.PLATFORM == "windows" and shell_path.startswith("/"):
                raise ValueError(
                    f"Trusted command '{name}' shell '{shell_name}' is not Windows-compatible: {shell_path}"
                )
            if self.PLATFORM != "windows" and (
                shell_path.lower().endswith(".exe") or "\\" in shell_path
            ):
                raise ValueError(
                    f"Trusted command '{name}' shell '{shell_name}' is not POSIX-compatible: {shell_path}"
                )

    def _link_shell_to_project(self) -> None:
        """Share the file tools' project dir and roots unless the shell sets its own."""
        if not (self.ENABLE_FILES and self.ENABLE_SHELL):
            return
        from .files import utils

        if not self.DOCKER_SANDBOX_HOST_ROOT and utils.PROJECT_DIR is not None:
            self.DOCKER_SANDBOX_HOST_ROOT = str(utils.PROJECT_DIR)
            self.SHELL_FOLLOWS_PROJECT = True
        if not self.ALLOWED_DIRECTORIES_HOST:
            self.ALLOWED_DIRECTORIES_HOST = list(self.ALLOWED_DIRECTORIES)

    # ------------------------------------------------------------- helpers
    @property
    def api_keys(self) -> frozenset[str]:
        return parse_api_keys(self.API_KEYS)

    def follow_project_directory(self, project_dir: Path) -> None:
        """Called when set_project_directory changes the file tools' root."""
        if self.SHELL_FOLLOWS_PROJECT:
            self.DOCKER_SANDBOX_HOST_ROOT = str(project_dir)

    # ---------------------------------------------------------- loading
    @classmethod
    def from_mapping(cls, merged: dict[str, Any], args: argparse.Namespace | None = None) -> "Settings":
        """Build settings from merged TOML data plus optional CLI overrides."""
        merged = dict(merged)
        platform_name = merged.setdefault("PLATFORM", current_platform())
        args = args or argparse.Namespace()

        unified = merged.pop("UNIFIED", {}) or {}
        merged.setdefault("NAMESPACED", unified.get("namespaced", False))
        merged.setdefault("ENABLE_FILES", unified.get("enable_files", True))
        merged.setdefault("ENABLE_SHELL", unified.get("enable_shell", True))

        # File tools: [CONFIG.<os>]
        config_os = (merged.get("CONFIG") or {}).get(platform_name, {})
        merged.setdefault("WORK_DIR", config_os.get("work_dir"))
        allow = config_os.get("allow_directories", config_os.get("allow_direcotories"))
        merged.setdefault("ALLOWED_DIRECTORIES", allow or [])

        # Shell tools: [DOCKER_CONFIG.<os>]
        docker = merged.get("DOCKER_CONFIG") or {}
        docker_os = docker.get(platform_name, {})
        merged.setdefault("DOCKER_SHELL_SERVICE", docker.get("service"))
        merged.setdefault("DOCKER_SHELL_ENV_FILE", docker.get("env_file"))
        merged.setdefault("DOCKER_SANDBOX_HOST_ROOT", docker_os.get("host_root"))
        merged.setdefault("DOCKER_SANDBOX_WORKDIR", docker_os.get("work_dir"))
        merged.setdefault(
            "ALLOWED_DIRECTORIES_HOST",
            docker_os.get("allow_directories_host", docker_os.get("allow_direcotories_host")) or [],
        )
        merged.setdefault(
            "ALLOWED_DIRECTORIES_DOCKER",
            docker_os.get("allow_directories_docker", docker_os.get("allow_direcotories_docker")) or [],
        )
        if not merged.get("ALLOWED_SHELLS"):
            merged["ALLOWED_SHELLS"] = default_shells(platform_name)

        # CLI flags win.
        for flag, key in (
            ("transport", "TRANSPORT"), ("host", "HOST"), ("port", "PORT"),
            ("path", "PATH"), ("workdir", "WORK_DIR"),
        ):
            if getattr(args, flag, None):
                merged[key] = getattr(args, flag)
        if getattr(args, "directories", None):
            merged["ALLOWED_DIRECTORIES"] = list(args.directories)
            merged["ALLOWED_DIRECTORIES_HOST"] = list(args.directories)
        if getattr(args, "shell", None):
            merged["ALLOWED_SHELLS"] = {name: path for name, path in args.shell}
        if getattr(args, "namespaced", None):
            merged["NAMESPACED"] = True
        if getattr(args, "no_files", False):
            merged["ENABLE_FILES"] = False
        if getattr(args, "no_shell", False):
            merged["ENABLE_SHELL"] = False

        # The sandbox's own dirs are always allowed inside the sandbox.
        host_root = merged.get("DOCKER_SANDBOX_HOST_ROOT")
        if host_root and host_root not in merged["ALLOWED_DIRECTORIES_HOST"]:
            merged["ALLOWED_DIRECTORIES_HOST"] = list(merged["ALLOWED_DIRECTORIES_HOST"]) + [host_root]
        work_dir = merged.get("DOCKER_SANDBOX_WORKDIR")
        if work_dir and work_dir not in merged["ALLOWED_DIRECTORIES_DOCKER"]:
            merged["ALLOWED_DIRECTORIES_DOCKER"] = list(merged["ALLOWED_DIRECTORIES_DOCKER"]) + [work_dir]

        unknown = set(merged) - set(cls.model_fields)
        if unknown:
            logger.warning("Ignoring unknown config keys: %s", ", ".join(sorted(unknown)))
        return cls(**merged)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="unified-mcp-server",
        description="One MCP server with file-editing and shell-execution tools.",
    )
    parser.add_argument("-c", "--config", default="config.toml", help="Config file (TOML)")
    parser.add_argument("-t", "--transport", choices=["stdio", "http"], default=None)
    parser.add_argument("-H", "--host", default=None)
    parser.add_argument("-P", "--port", type=int, default=None)
    parser.add_argument("-p", "--path", default=None, help="HTTP endpoint path, e.g. /mcp")
    parser.add_argument("-w", "--workdir", default=None, help="Working/project directory")
    parser.add_argument("-d", "--directories", nargs="+", default=None, help="Allowed root directories")
    parser.add_argument(
        "--shell", action="append", nargs=2, metavar=("NAME", "PATH"),
        help="Shell mapping for shell tools (repeatable)",
    )
    parser.add_argument("--namespaced", action="store_true", default=None,
                        help="Prefix tool names with 'fs_' and 'shell_'")
    parser.add_argument("--no-files", action="store_true", help="Disable file tools")
    parser.add_argument("--no-shell", action="store_true", help="Disable shell tools")
    return parser


def _load_toml(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    return toml.load(p) if p.is_file() else {}


def load_settings(argv: Sequence[str] | None = None) -> Settings:
    """Parse CLI args, merge defaults + config file, and install as SETTINGS."""
    global SETTINGS
    args = build_parser().parse_args(argv)
    merged: dict[str, Any] = {}
    merged.update(_load_toml(DEFAULT_CONFIG_PATH))
    merged.update(_load_toml(args.config))
    SETTINGS = Settings.from_mapping(merged, args)
    return SETTINGS


SETTINGS: Settings | None = None
