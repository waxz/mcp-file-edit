"""Shell MCP Server package."""

def main():
    """Main entry point for the package."""
    from . import server
    server.main()

__all__ = ["main"]
