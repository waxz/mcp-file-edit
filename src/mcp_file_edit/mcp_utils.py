import argparse

import mcp.types as types
from fastmcp import FastMCP
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.server.dependencies import get_http_headers
from fastmcp.exceptions import ToolError
from mcp.server.session import ServerSession


from . import config

from .models import (
    ExecutionResult, ProcessRecord, ExecutionRequest,
    ExecuteCommandInput,
    NameInput,
    PidInput,
    TmuxExecuteInput,
    TmuxGetOutputInput,
    TmuxListInput,
    TmuxSessionInput,
)

from .tool_handlers import register_tools
from .config import parse_args


class ApiKeyAuth(Middleware):
    def __init__(self, valid_keys: set[str]):
        self.valid_keys = valid_keys

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        tool_name = context.message.name

         
        # if self.protected_tools and tool_name not in self.protected_tools:
        #     return await call_next(context)

        headers = get_http_headers()


        # Authentication may be stripped by reverse proxy, so check both cases
        api_key = headers.get("X-Api-Key") or headers.get("x-api-key") or None
        
        if api_key == self.valid_keys:
            return await call_next(context)
        else:
            raise ToolError(f"Invalid api_key : {api_key}, headers: {headers}, for protected tool: {tool_name}")

        return await call_next(context)



def build_server(settings: config.Settings ) -> FastMCP:
    """Initialize runtime settings and return configured FastMCP server."""
    

    # Patch ServerSession to swallow ClosedResourceError when sending response after client disconnects
    _original_send_response = ServerSession._send_response

    async def _patched_send_response(self, request_id, response):
        try:
            await _original_send_response(self, request_id, response)
        except ClosedResourceError:
            logging.info("ClosedResourceError suppressed while sending response")

    ServerSession._send_response = _patched_send_response




    app = FastMCP(config.SETTINGS.APP_NAME)


    # 2. Initialize the verifier
    if config.SETTINGS.API_KEYS:
        app.add_middleware(ApiKeyAuth(
            valid_keys=config.SETTINGS.API_KEYS
        ))
    register_tools(app)
    return app