"""Unified configuration: one config file and one CLI for both sub-servers.

The unified config file is a superset of the two original formats, whose keys
do not overlap:

* top-level ``HOST``/``PORT``/``PATH``/``TRANSPORT``/``API_KEYS`` are shared;
* ``[CONFIG.<os>]`` feeds the file tools (mcp-file-edit);
* ``[DOCKER_CONFIG.<os>]``, ``[TRUSTED_COMMANDS.*]``, ``SAFETY_MODE``,
  ``COMMAND_TIMEOUT``, ``IS_IN_DOCKER``, ``ALLOWED_SHELLS`` feed the shell tools
  (shell-mcp-server);
* ``[UNIFIED]`` holds options of the unified server itself.
"""

from __future__ import annotations

import argparse
import atexit
import importlib.resources
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

import toml

DEFAULT_CONFIG_PATH = str(
    importlib.resources.files("unified_mcp_server").joinpath("default_config.toml")
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="unified-mcp-server",
        description="One MCP server exposing file-editing and shell-execution tools.",
    )
    parser.add_argument("-c", "--config", default="config.toml", help="Config file (TOML)")
    parser.add_argument("-t", "--transport", choices=["stdio", "http"], default=None)
    parser.add_argument("-H", "--host", default=None)
    parser.add_argument("-P", "--port", type=int, default=None)
    parser.add_argument("-p", "--path", default=None, help="HTTP endpoint path, e.g. /mcp")
    parser.add_argument("-w", "--workdir", default=None, help="Working/project directory")
    parser.add_argument(
        "-d", "--directories", nargs="+", default=None, help="Allowed root directories"
    )
    parser.add_argument(
        "--shell",
        action="append",
        nargs=2,
        metavar=("NAME", "PATH"),
        help="Shell mapping for shell tools (repeatable)",
    )
    parser.add_argument(
        "--namespaced",
        action="store_true",
        default=None,
        help="Prefix tool names with 'fs_' and 'shell_'",
    )
    parser.add_argument("--no-files", action="store_true", help="Disable file tools")
    parser.add_argument("--no-shell", action="store_true", help="Disable shell tools")
    return parser


def _load_toml(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    return toml.load(p) if p.is_file() else {}


def _parse_api_keys(value: Any) -> frozenset[str]:
    if value is None:
        return frozenset()
    items = value if isinstance(value, (list, tuple)) else str(value).split(",")
    return frozenset(k.strip() for k in items if str(k).strip())


@dataclass
class UnifiedSettings:
    config_path: str
    merged_config: dict[str, Any] = field(default_factory=dict)
    transport: str = "stdio"
    host: str = "127.0.0.1"
    port: int = 8000
    path: str = "/mcp"
    api_keys: frozenset[str] = field(default_factory=frozenset)
    namespaced: bool = False
    enable_files: bool = True
    enable_shell: bool = True
    # Pass-through CLI values for the sub-servers
    workdir: str | None = None
    directories: list[str] | None = None
    shells: dict[str, str] = field(default_factory=dict)

    def child_config_file(self, model_fields: Iterable[str]) -> str:
        """Write the merged config, restricted to one sub-server's fields.

        The upstream ``Settings`` models reject unknown keys, so each gets
        only the keys it declares.
        """
        allowed = set(model_fields)
        subset = {k: v for k, v in self.merged_config.items() if k in allowed}
        fd, path = tempfile.mkstemp(prefix="unified-mcp-", suffix=".toml")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            toml.dump(subset, fh)
        atexit.register(lambda: Path(path).unlink(missing_ok=True))
        return path

    def child_args(self, config_file: str) -> argparse.Namespace:
        """Namespace compatible with both sub-servers' ``Settings.from_runtime``."""
        return argparse.Namespace(
            config=config_file,
            transport=self.transport,
            host=self.host,
            port=self.port,
            path=self.path,
            workdir=self.workdir,
            directories=self.directories,
            shell=[[k, v] for k, v in self.shells.items()] or None,
        )


def load_settings(argv: Sequence[str] | None = None) -> UnifiedSettings:
    """Precedence: packaged defaults -> config file -> CLI flags."""
    args = build_parser().parse_args(argv)

    merged: dict[str, Any] = {}
    merged.update(_load_toml(DEFAULT_CONFIG_PATH))
    merged.update(_load_toml(args.config))
    unified = merged.get("UNIFIED", {}) or {}

    settings = UnifiedSettings(
        config_path=args.config,
        merged_config=merged,
        transport=args.transport or merged.get("TRANSPORT", "stdio"),
        host=args.host or merged.get("HOST", "127.0.0.1"),
        port=args.port or int(merged.get("PORT", 8000)),
        path=args.path or merged.get("PATH", "/mcp"),
        api_keys=_parse_api_keys(merged.get("API_KEYS")),
        namespaced=bool(args.namespaced if args.namespaced is not None else unified.get("namespaced", False)),
        enable_files=not args.no_files and unified.get("enable_files", True),
        enable_shell=not args.no_shell and unified.get("enable_shell", True),
        workdir=args.workdir,
        directories=list(args.directories) if args.directories else None,
        shells={name: path for name, path in (args.shell or [])},
    )
    if settings.transport not in {"stdio", "http"}:
        raise ValueError("TRANSPORT must be 'stdio' or 'http'")
    if not settings.path.startswith("/"):
        raise ValueError("PATH must start with '/'")
    if not (settings.enable_files or settings.enable_shell):
        raise ValueError("At least one of file tools / shell tools must be enabled")
    return settings
