"""Runtime configuration for MCP file editor."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import os

try:
    import tomllib  # py311+
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None

import logging
import platform
import shutil
from argparse import Namespace
from pathlib import Path
from typing import Any, Dict

import toml
from pydantic import ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings
from .os_utils import check_installed
from .path_utils import is_windows_style_path, normalize_directory_value,get_platform_path



def _normalize_directory_list(value: list[str] | None) -> list[str]:
    if not value:
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        normalized = normalize_directory_value(item)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


class Settings(BaseSettings):
    """Application runtime settings."""

    APP_NAME: str = "mcp-file-edit"
    APP_VERSION: str = "0.1.3"
    API_KEYS:str|None = None
    COMMAND_TIMEOUT: int = 30
    TRANSPORT: str = "stdio"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    PATH: str = "/mcp"
    PLATFORM: str = "linux"
    IS_IN_DOCKER : bool = False
    IS_TMUX_INSTALLED: bool = check_installed("tmux")
    IS_GIT_INSTALLED: bool = check_installed("git")

    CONFIG: Dict[str, Any] = {}

    WORK_DIR: str|None = None
    ALLOWED_DIRECTORIES: list[str] = Field(default_factory=list)

    @field_validator("ALLOWED_DIRECTORIES")
    @classmethod
    def _normalize_allowed_dirs(cls, value: list[str] | None) -> list[str]:
        return _normalize_directory_list(value)

    @model_validator(mode="after")
    def _validate_runtime_contract(self) -> "Settings":
        if self.TRANSPORT == "http" and not self.PATH:
            raise ValueError("PATH is required when TRANSPORT is 'http'")

        self.ALLOWED_DIRECTORIES = [
            get_platform_path(f, self.PLATFORM, self.WORK_DIR)
            for f in self.ALLOWED_DIRECTORIES
        ]
        return self

    @classmethod
    def from_runtime(
        cls,
        args: Namespace,
        parsed_shells: dict[str, str],
        shells_from_cli: bool,
    ) -> "Settings":
        """Load settings with precedence: defaults -> config.toml -> CLI."""
        system_name = platform.system().lower()
        if system_name.startswith("win"):
            platform_name = "windows"
        elif system_name == "darwin":
            platform_name = "macos"
        else:
            platform_name = "linux"

        merged: dict[str, Any] = {
            "PLATFORM": platform_name,
        }

        config_path = Path(getattr(args, "config", "config.toml") or "config.toml")
        if config_path.exists():
            file_config = toml.load(config_path)
            merged.update(file_config)



        if getattr(args, "transport", None):
            merged["TRANSPORT"] = args.transport
        if getattr(args, "host", None):
            merged["HOST"] = args.host
        if getattr(args, "port", None):
            merged["PORT"] = args.port
        if args.path:
            merged["PATH"] = args.path


        config_os = merged.get("CONFIG", {}).get(platform_name, {})
        merged["WORK_DIR"] = config_os.get("work_dir")
        merged["ALLOWED_DIRECTORIES"] = (
            config_os.get("allow_directories")
            if config_os.get("allow_directories") is not None
            else config_os.get("allow_direcotories")
        )
        # print("merged:",merged)

        if getattr(args, "directories", None):
            merged["ALLOWED_DIRECTORIES"] = list(args.directories)


        
        settings = cls(**merged)
        return settings




SETTINGS: Settings | None = None
