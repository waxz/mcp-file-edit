"""Server bootstrap and MCP tool registration."""

from __future__ import annotations

import argparse
import logging
import sys
from anyio import ClosedResourceError
from fastmcp import FastMCP
from mcp.server.session import ServerSession

from . import config
from .tool_handlers import register_tools


def parse_args() -> tuple[argparse.Namespace, dict[str, str], bool]:
    """Parse CLI args and optional shell overrides."""
    parser = argparse.ArgumentParser(description="Shell MCP Server")
    parser.add_argument("-d", "--directories", nargs="+", help="Allowed directories")
    parser.add_argument(
        "--shell",
        action="append",
        nargs=2,
        metavar=("name", "path"),
        help="Shell mapping (name path)",
    )

    parser.add_argument(
        "-t",
        "--transport",
        type=str,
        choices=["stdio", "http"],
        default=None,
        help="Server transport override",
    )
    parser.add_argument("-H", "--host", type=str, default="0.0.0.0")
    parser.add_argument("-P", "--port", type=int, default="8000")
    parser.add_argument("-p", "--path", type=str, default="/mcp")
    parser.add_argument("-c", "--config", type=str, default="config.toml")

    args = parser.parse_args()
    shells_from_cli = bool(args.shell)
    shells = {name: path for name, path in (args.shell or [])}
    return args, shells, shells_from_cli


def build_server() -> FastMCP:
    """Initialize runtime settings and return configured FastMCP server."""
    args, shells, shells_from_cli = parse_args()
    config.SETTINGS = config.Settings.from_runtime(args, shells, shells_from_cli)

    # Patch ServerSession to swallow ClosedResourceError when sending response after client disconnects
    _original_send_response = ServerSession._send_response

    async def _patched_send_response(self, request_id, response):
        try:
            await _original_send_response(self, request_id, response)
        except ClosedResourceError:
            logging.info("ClosedResourceError suppressed while sending response")

    ServerSession._send_response = _patched_send_response

    app = FastMCP(config.SETTINGS.APP_NAME)
    register_tools(app)
    return app


def main() -> None:
    """Main entry point for running server with selected transport."""

    # Suppress ClosedResourceError that happens when clients disconnect
    logging.getLogger("fastmcp").setLevel(logging.INFO)
    logging.getLogger("anyio").setLevel(logging.INFO)

    logging.getLogger("mcp.server.streamable_http_manager").setLevel(logging.INFO)
    logging.getLogger("mcp.server.lowlevel.server").setLevel(logging.INFO)
    logging.getLogger("mcp.server.streamable_http").setLevel(logging.INFO)
    
    logging.getLogger("mcp").setLevel(logging.INFO)
    logging.info("Starting server...")
    app = build_server()

    assert config.SETTINGS is not None


    # Custom exception handler to suppress client disconnect errors
    old_excepthook = sys.excepthook

    def new_excepthook(exc_type, exc_value, exc_traceback):
        # Suppress ClosedResourceError from crashing the server
        if exc_type.__name__ == "ClosedResourceError":
            logging.info("Client disconnected (ClosedResourceError suppressed)")
            return
        # Also suppress ExceptionGroup containing ClosedResourceError
        if exc_type.__name__ == "BaseExceptionGroup":
            if "unhandled errors" in str(exc_value):
                # Check if it's just ClosedResourceError
                for cause in exc_value.exceptions or []:
                    if "ClosedResourceError" in str(type(cause).__name__):
                        logging.info("Client disconnected (ExceptionGroup suppressed)")
                        return
        old_excepthook(exc_type, exc_value, exc_traceback)

    sys.excepthook = new_excepthook


    if config.SETTINGS.TRANSPORT == "http":
        app.run(
            transport="http",
            port=config.SETTINGS.PORT,
            host=config.SETTINGS.HOST,
            path=config.SETTINGS.PATH,
        )
        return

    app.run()


if __name__ == "__main__":
    main()
