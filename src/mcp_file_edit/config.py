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


@dataclass
class RuntimeConfig:
    allow_directories: list[Path]


def _default_allow_directories() -> list[Path]:
    return [Path.cwd().resolve()]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_config_path() -> Path:
    return _repo_root() / "config.toml"


def _parse_allow_directories(raw: str) -> list[Path]:
    roots: list[Path] = []
    for part in raw.split(os.pathsep):
        candidate = part.strip()
        if not candidate:
            continue
        roots.append(Path(candidate).expanduser().resolve())

    if not roots:
        return _default_allow_directories()

    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        unique.append(root)
    return unique


def _coerce_allow_directories(value: object) -> list[Path]:
    if isinstance(value, str):
        return _parse_allow_directories(value)
    if isinstance(value, list):
        roots: list[Path] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError("config.server.allow_directories must contain strings")
            item_str = item.strip()
            if not item_str:
                continue
            roots.append(Path(item_str).expanduser().resolve())
        return roots or _default_allow_directories()
    raise ValueError("config.server.allow_directories must be string or list of strings")


def _load_from_toml(path: Path) -> RuntimeConfig:
    if not path.exists():
        return RuntimeConfig(allow_directories=_default_allow_directories())

    if tomllib is None:
        raise RuntimeError("Reading config.toml requires Python 3.11+ or tomli")

    data = tomllib.loads(path.read_text(encoding="utf-8"))
    server_cfg = data.get("server", {}) if isinstance(data, dict) else {}
    allow_value = server_cfg.get("allow_directories")

    if allow_value is None:
        return RuntimeConfig(allow_directories=_default_allow_directories())

    return RuntimeConfig(allow_directories=_coerce_allow_directories(allow_value))


RUNTIME_CONFIG = RuntimeConfig(allow_directories=_default_allow_directories())


def configure_runtime(config_path: Optional[str] = None, allow_directories_raw: Optional[str] = None) -> RuntimeConfig:
    """Load runtime config from TOML and optional CLI override."""
    global RUNTIME_CONFIG

    path = Path(config_path).expanduser().resolve() if config_path else _default_config_path()
    config = _load_from_toml(path)

    if allow_directories_raw is not None:
        config.allow_directories = _parse_allow_directories(allow_directories_raw)

    RUNTIME_CONFIG = config
    return RUNTIME_CONFIG


def get_runtime_config() -> RuntimeConfig:
    return RUNTIME_CONFIG
