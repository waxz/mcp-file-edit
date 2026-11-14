"""Unified MCP server combining mcp-file-edit and shell-mcp-server."""

__version__ = "0.1.0"


def main() -> None:
    from .server import main as _main

    _main()


__all__ = ["main", "__version__"]
