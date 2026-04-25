import argparse
import difflib
import json
import logging
from html import escape

import mcp.types as types
from anyio import ClosedResourceError
from fastmcp import FastMCP
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.server.dependencies import get_http_headers
from fastmcp.exceptions import ToolError
from mcp.server.session import ServerSession
from starlette.requests import Request
from starlette.responses import HTMLResponse


from . import config
from .patch_preview_store import (
    get_patch_preview_session,
    set_patch_preview_status,
    update_patch_preview_files,
)

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


def _preview_file_diff(original: str, new: str, path: str) -> str:
    diff = difflib.unified_diff(
        original.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        lineterm="",
    )
    text = "\n".join(diff).rstrip()
    return text + ("\n" if text else "")

def extract_auth():
    headers = get_http_headers()

    # 1. Try Authorization header (Bearer token)
    auth = headers.get("Authorization") or headers.get("authorization")
    if auth:
        parts = auth.split()
        # Returns the second part if "Bearer <key>", otherwise returns the whole string
        return parts[1] if len(parts) > 1 and parts[0].lower() in ["bearer", "bear"] else parts[0]

    # 2. Fallback to x-api-key
    x_api_key = headers.get("x-api-key") or headers.get("X-API-Key")
    if x_api_key:
        return x_api_key.strip()

    return None


class ApiKeyAuth(Middleware):
    def __init__(self, valid_keys: set[str]):
        self.valid_keys = valid_keys

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        tool_name = context.message.name
         
        # if self.protected_tools and tool_name not in self.protected_tools:
        #     return await call_next(context)

        headers = get_http_headers()


        api_key = extract_auth()
        
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

    @app.custom_route("/patch-preview/{preview_id}", methods=["GET"], include_in_schema=False)
    async def patch_preview_page(request: Request) -> HTMLResponse:
        preview_id = request.path_params["preview_id"]
        session = get_patch_preview_session(preview_id)
        if session is None:
            return HTMLResponse("<h1>Preview not found or expired</h1>", status_code=404)

        summary = session.structured_preview.get("summary", {})
        files = session.structured_preview.get("files", [])
        warnings = summary.get("warnings", [])
        confirm_action = f"/patch-preview/{preview_id}/confirm?token={escape(session.confirm_token)}"
        reject_action = f"/patch-preview/{preview_id}/reject?token={escape(session.reject_token)}"
        is_pending = session.status == "pending"
        status_label = escape(session.status.title())
        status_class = f"status-{escape(session.status)}"

        file_sections = []
        raw_diff_parts = []
        for index, file_entry in enumerate(files):
            original_text = file_entry.get("original_content", "") or ""
            new_text = file_entry.get("new_content", "") or ""
            path_text = file_entry.get("path", "unknown")
            diff_text = _preview_file_diff(original_text, new_text, path_text)
            raw_diff_parts.append(diff_text.rstrip())
            file_sections.append(
                f"""
                <section class="file-card">
                  <div class="file-head">
                    <h2>{escape(path_text)}</h2>
                    <span class="file-type">{escape(file_entry.get('type', 'update'))}</span>
                  </div>
                  <div class="pane-actions">
                    <button type="button" onclick="resetToSuggested({index})">Reset To Suggested</button>
                    <button type="button" onclick="copyOriginal({index})">Copy Left To Right</button>
                  </div>
                  <div class="diff-panes">
                    <div class="pane">
                      <div class="pane-label">Original</div>
                      <textarea readonly data-pane="left" id="left_{index}">{escape(original_text)}</textarea>
                    </div>
                    <div class="pane">
                      <div class="pane-label">Reviewed / Editable</div>
                      <textarea name="content_{index}" data-pane="right" id="right_{index}">{escape(new_text)}</textarea>
                    </div>
                  </div>
                  <details class="raw-diff">
                    <summary>Raw Unified Diff</summary>
                    <pre class="diff-block">{escape(diff_text)}</pre>
                  </details>
                </section>
                """
            )

        full_diff = "\n".join(part for part in raw_diff_parts if part).rstrip()
        warning_block = ""
        if warnings:
            warning_items = "".join(
                f"<li>{escape(str(warning))}</li>" for warning in warnings
            )
            warning_block = f"""
            <section class="warnings">
              <h2>Warnings</h2>
              <ul>{warning_items}</ul>
            </section>
            """

        html = f"""
        <!doctype html>
        <html lang="en">
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <title>Patch Preview {escape(preview_id)}</title>
          <style>
            :root {{
              --bg: #f7f4ea;
              --ink: #1e1b18;
              --panel: #fffdf7;
              --line: #d8cdb7;
              --accent: #9b3d22;
              --good: #1f6d42;
              --bad: #8f2d2d;
            }}
            body {{ margin: 0; font-family: Georgia, "Times New Roman", serif; background: linear-gradient(180deg, #f0eadc 0%, var(--bg) 100%); color: var(--ink); }}
            main {{ max-width: 1000px; margin: 0 auto; padding: 32px 20px 48px; }}
            .hero {{ background: var(--panel); border: 1px solid var(--line); padding: 24px; box-shadow: 0 8px 30px rgba(0,0,0,0.05); }}
            .meta {{ display: flex; gap: 18px; flex-wrap: wrap; font-size: 14px; color: #5c5249; }}
            .actions {{ display: flex; gap: 12px; margin-top: 20px; flex-wrap: wrap; }}
            button {{ border: 0; padding: 12px 18px; font: inherit; cursor: pointer; color: white; }}
            button[disabled] {{ cursor: not-allowed; opacity: 0.5; }}
            .confirm {{ background: var(--good); }}
            .reject {{ background: var(--bad); }}
            .status {{ display: inline-block; margin-top: 12px; padding: 6px 10px; background: #efe7d5; border: 1px solid var(--line); }}
            .status-pill {{ display: inline-block; margin-top: 14px; padding: 8px 12px; border: 1px solid var(--line); background: #efe7d5; }}
            .status-confirmed {{ background: #e6f4ea; color: #144d2f; }}
            .status-rejected {{ background: #fae8e8; color: #6d2020; }}
            .status-applied {{ background: #e7f1fb; color: #1d4668; }}
            .warnings {{ margin-top: 22px; padding: 18px 20px; background: #fff4df; border: 1px solid #e4c892; }}
            .warnings h2 {{ margin: 0 0 10px; font-size: 18px; }}
            .warnings ul {{ margin: 0; padding-left: 20px; }}
            .file-card {{ margin-top: 22px; background: var(--panel); border: 1px solid var(--line); }}
            .file-head {{ display: flex; justify-content: space-between; align-items: center; gap: 16px; padding: 16px 18px; border-bottom: 1px solid var(--line); }}
            .file-card h2 {{ margin: 0; font-size: 20px; }}
            .file-type {{ padding: 6px 10px; border: 1px solid var(--line); background: #f3ecdd; font-size: 13px; text-transform: uppercase; letter-spacing: 0.08em; }}
            .pane-actions {{ display: flex; gap: 10px; padding: 12px 18px 0; flex-wrap: wrap; }}
            .pane-actions button {{ background: #46372a; }}
            .diff-panes {{ display: grid; grid-template-columns: 1fr 1fr; gap: 0; border-top: 1px solid var(--line); }}
            .pane {{ min-width: 0; border-right: 1px solid var(--line); }}
            .pane:last-child {{ border-right: 0; }}
            .pane-label {{ padding: 10px 14px; font-size: 12px; letter-spacing: 0.08em; text-transform: uppercase; color: #5c5249; background: #f8f1e4; border-bottom: 1px solid var(--line); }}
            .pane textarea {{ width: 100%; min-height: 420px; border: 0; padding: 16px; resize: vertical; box-sizing: border-box; font: 13px/1.5 "SFMono-Regular", Consolas, "Liberation Mono", monospace; background: #fffdf7; color: #1e1b18; }}
            .pane textarea[readonly] {{ background: #f4efe4; color: #54483d; }}
            .raw-diff {{ border-top: 1px solid var(--line); }}
            .raw-diff summary {{ cursor: pointer; padding: 12px 18px; background: #f8f1e4; }}
            .diff-block {{ margin: 0; padding: 18px; overflow-x: auto; background: #171411; color: #f8f3e8; line-height: 1.5; }}
            .raw-agent {{ margin-top: 22px; background: var(--panel); border: 1px solid var(--line); }}
            .raw-agent summary {{ cursor: pointer; padding: 16px 18px; background: #f8f1e4; }}
            .raw-agent pre {{ margin: 0; padding: 18px; overflow-x: auto; background: #171411; color: #f8f3e8; }}
            @media (max-width: 900px) {{ .diff-panes {{ grid-template-columns: 1fr; }} .pane {{ border-right: 0; border-bottom: 1px solid var(--line); }} .pane:last-child {{ border-bottom: 0; }} }}
          </style>
          <script>
            const suggested = {json.dumps([file_entry.get("new_content", "") or "" for file_entry in files])};
            function rightPane(index) {{ return document.getElementById(`right_${{index}}`); }}
            function leftPane(index) {{ return document.getElementById(`left_${{index}}`); }}
            function resetToSuggested(index) {{ rightPane(index).value = suggested[index]; }}
            function copyOriginal(index) {{ rightPane(index).value = leftPane(index).value; }}
            function syncScroll(source, target) {{
              target.scrollTop = source.scrollTop;
              target.scrollLeft = source.scrollLeft;
            }}
            window.addEventListener("DOMContentLoaded", () => {{
              document.querySelectorAll('textarea[data-pane="left"]').forEach((left) => {{
                const index = left.id.split("_")[1];
                const right = rightPane(index);
                left.addEventListener("scroll", () => syncScroll(left, right));
                right.addEventListener("scroll", () => syncScroll(right, left));
              }});
            }});
          </script>
        </head>
        <body>
          <main>
            <section class="hero">
              <h1>Patch Review</h1>
              <div class="meta">
                <div>Preview ID: <strong>{escape(preview_id)}</strong></div>
                <div>Status: <strong>{escape(session.status)}</strong></div>
                <div>Expires: <strong>{escape(session.expires_at.isoformat())}</strong></div>
                <div>Updates: <strong>{summary.get('updates', 0)}</strong></div>
                <div>Adds: <strong>{summary.get('adds', 0)}</strong></div>
                <div>Deletes: <strong>{summary.get('deletes', 0)}</strong></div>
              </div>
              <div class="status">Use the buttons below to approve or reject this exact patch.</div>
              <div class="status-pill {status_class}">{status_label}</div>
              <form method="post" action="{confirm_action}">
                <input type="hidden" name="token" value="{escape(session.confirm_token)}">
                <div class="actions">
                  <button class="confirm" type="submit" {"disabled" if not is_pending else ""}>Confirm Reviewed Changes</button>
                </div>
                {''.join(file_sections)}
              </form>
              <div class="actions">
                <form method="post" action="{reject_action}">
                  <button class="reject" type="submit" {"disabled" if not is_pending else ""}>Reject Patch</button>
                </form>
              </div>
            </section>
            {warning_block}
            <details class="raw-agent">
              <summary>Complete Diff Text For Automation</summary>
              <pre>{escape(full_diff)}</pre>
            </details>
          </main>
        </body>
        </html>
        """
        return HTMLResponse(html)

    @app.custom_route("/patch-preview/{preview_id}/confirm", methods=["POST"], include_in_schema=False)
    async def patch_preview_confirm(request: Request) -> HTMLResponse:
        preview_id = request.path_params["preview_id"]
        session = get_patch_preview_session(preview_id)
        if session is None:
            return HTMLResponse("<h1>Preview not found or expired</h1>", status_code=404)
        form = await request.form()
        token = request.query_params.get("token", "") or str(form.get("token", ""))
        files = list(session.structured_preview.get("files", []))
        updated_files = []
        for index, file_entry in enumerate(files):
            updated_entry = dict(file_entry)
            updated_entry["new_content"] = str(form.get(f"content_{index}", file_entry.get("new_content", "") or ""))
            updated_entry["diff"] = _preview_file_diff(
                updated_entry.get("original_content", "") or "",
                updated_entry.get("new_content", "") or "",
                updated_entry.get("path", "unknown"),
            )
            updated_files.append(updated_entry)
        try:
            update_patch_preview_files(preview_id, updated_files)
            session = set_patch_preview_status(preview_id, token=token, status="confirmed")
        except PermissionError:
            return HTMLResponse("<h1>Invalid confirmation token</h1>", status_code=403)
        return HTMLResponse(
            f"<h1>Patch confirmed</h1><p>Preview {escape(session.preview_id)} is confirmed.</p>"
            f"<p>The reviewed right-hand pane contents were saved as the confirmed result.</p>"
            f"<p>You can now call <code>apply_confirmed_patch</code> with this preview ID.</p>"
        )

    @app.custom_route("/patch-preview/{preview_id}/reject", methods=["POST"], include_in_schema=False)
    async def patch_preview_reject(request: Request) -> HTMLResponse:
        preview_id = request.path_params["preview_id"]
        token = request.query_params.get("token", "")
        try:
            session = set_patch_preview_status(preview_id, token=token, status="rejected")
        except KeyError:
            return HTMLResponse("<h1>Preview not found or expired</h1>", status_code=404)
        except PermissionError:
            return HTMLResponse("<h1>Invalid rejection token</h1>", status_code=403)
        return HTMLResponse(
            f"<h1>Patch rejected</h1><p>Preview {escape(session.preview_id)} has been rejected.</p>"
        )

    register_tools(app)
    return app
