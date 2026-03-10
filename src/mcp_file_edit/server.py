"""Server bootstrap and MCP tool registration."""

from __future__ import annotations

import argparse
import logging
import sys
from anyio import ClosedResourceError
from fastmcp import FastMCP
from mcp.server.session import ServerSession

from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.server.dependencies import get_http_headers
from fastmcp.exceptions import ToolError

from . import config
from .mcp_utils import ApiKeyAuth,build_server,parse_args
from .tool_handlers import register_tools




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

    args, shells, shells_from_cli = parse_args()

    config.SETTINGS = config.Settings.from_runtime(args, shells, shells_from_cli)

    app = build_server(config.SETTINGS)
    


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
