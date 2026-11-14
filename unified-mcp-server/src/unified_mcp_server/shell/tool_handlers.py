# Derived from shell-mcp-server (Apache-2.0, https://github.com/waxz/shell-mcp-server);
# modified for unified-mcp-server. See NOTICE and LICENSE-APACHE.
"""MCP tool handlers for shell execution and process management."""

from __future__ import annotations

import logging
import os
import uuid
import json
import mcp.types as types
from anyio import ClosedResourceError
from fastmcp import Context, FastMCP
from typing import Dict, List, Any


from fastmcp.server.tasks import TaskConfig

from .. import config
from .executor import (
    list_running_process_records,
    run_shell_command,
    terminate_all_processes as _terminate_all_processes_impl,
    terminate_process_by_pid,
)
from ..common.models import (
    ExecutionResult,
    ProcessRecord,
    ExecutionRequest,
    ExecuteCommandInput,
    NameInput,
    PidInput,
    TmuxExecuteInput,
    TmuxGetOutputInput,
    TmuxListInput,
    TmuxSessionInput,
)
from .tmux_commands import (
    build_tmux_bootstrap_command,
    build_tmux_capture_command,
    build_tmux_clear_command,
    build_tmux_kill_command,
    build_tmux_reset_pane_command,
    build_tmux_send_keys_command,
)
from .execution_policy import resolve_request
from ..common.mcp_types_utils import create_shell_result, create_str_result

logger = logging.getLogger(__name__)


def register_tools(server: FastMCP) -> None:
    """Register MCP tools."""

    async def _execute_with_stream(
        command: str,
        cwd: str,
        ctx: Context,
        shell: str,
        is_trusted: bool | None = None,
    ) -> ExecutionResult:
        async def _on_stdout(line: str) -> None:
            try:
                await ctx.info(line)
            except ClosedResourceError:
                pass

        async def _on_stderr(line: str) -> None:
            try:
                await ctx.warning(line)
            except ClosedResourceError:
                pass

        try:
            result = await run_shell_command(
                command=command,
                cwd=cwd,
                shell=shell,
                on_stdout=_on_stdout,
                on_stderr=_on_stderr,
                is_trusted=is_trusted,
            )
        except ClosedResourceError:
            return ExecutionResult(stderr="[client disconnected]")
            # return [types.TextContent(type="text", text="[client disconnected]")]

        if result.cancelled:
            return ExecutionResult(stderr="[client disconnected]")
            # return [types.TextContent(type="text", text="[client disconnected]")]

        parts: list[str] = []
        if result.stdout:
            parts.append(result.stdout)
        if result.stderr:
            parts.append(f"[stderr]\n{result.stderr}")
        parts.append(f"[exit code: {result.exit_code}]")
        if result.timed_out and config.SETTINGS is not None:
            parts.append(f"[timed out after {config.SETTINGS.COMMAND_TIMEOUT}s]")
        if not result.exit_code == 0:
            raise ValueError(f"{parts}")
        return result
        # return [types.TextContent(type="text", text="\n\n".join(parts))]

    @server.tool(task=TaskConfig(mode="optional"))
    async def list_trusted_commands()-> dict:
        """ Get list of trusted commands"""
        return config.SETTINGS.TRUSTED_COMMANDS


    @server.tool(task=TaskConfig(mode="optional"))
    async def execute_command(
        command: str,
        cwd: str,
        ctx: Context,
        shell: str = "bash",
    ) -> list[types.TextContent]:
        """Run a shell command and stream output; returns `Execution failed: ...` on errors."""
        try:
            logger.debug(
                "Receive command: command=%s, cwd=%s, shell=%s",
                command,
                cwd,
                shell,
            )
            req = ExecuteCommandInput(command=command, cwd=cwd, shell=shell)
            logger.debug(
                "Request command: command=%s, cwd=%s, shell=%s",
                req.command,
                req.cwd,
                req.shell,
            )

            return [
                create_shell_result(
                    await _execute_with_stream(
                        command=req.command,
                        cwd=req.cwd,
                        ctx=ctx,
                        shell=req.shell,
                    )
                )
            ]
        except Exception as exc:
            raise exc
            # return [types.TextContent(type="text", text=f"Execution failed: {exc}")]

    @server.tool(task=TaskConfig(mode="optional"))
    async def list_processes() -> list[dict[str, Any]] | None:
        """List tracked child processes."""
        records = list_running_process_records()
        if not records:
            return None
            # return [types.TextContent(type="text", text="No running processes")]

        # lines = ["Running processes:"]
        pid_info_list = []
        for record in records:
            # lines.append(
            #     f"  PID {record.pid}: shell={record.shell} cwd={record.cwd} command={record.command}"
            # )
            pid_info_list.append(
                {
                    "PID": record.pid,
                    "shell": record.shell,
                    "cwd": record.cwd,
                    "command": record.command,
                }
            )

        resp = json.dumps(pid_info_list)
        logging.info(f"resp:{resp}")
        return pid_info_list
        # return [types.TextContent(type="text", text="\n".join(lines))]

    @server.tool(task=TaskConfig(mode="optional"))
    async def terminate_process(pid: int) -> list[types.TextContent]:
        """Terminate one tracked PID; returns not found when missing."""
        req = PidInput(pid=pid)
        terminated = await terminate_process_by_pid(req.pid)
        if not terminated:
            return [types.TextContent(type="text", text=f"Process {req.pid} not found")]
        return [types.TextContent(type="text", text=f"Process {req.pid} terminated")]

    @server.tool(task=TaskConfig(mode="optional"))
    async def terminate_all_processes() -> list[types.TextContent]:
        """Terminate all tracked processes."""
        count = await _terminate_all_processes_impl()
        return [types.TextContent(type="text", text=f"Terminated {count} processes")]

    @server.tool(task=TaskConfig(mode="optional"))
    async def tmux_execute(
        command: str,
        ctx: Context,
        session_name: str = "",
        shell: str = "bash",
    ) -> List[dict[str, str] | types.TextContent]:
        """Run a command in tmux; validates `session_name`."""
        cwd: str = "."

        request = resolve_request(command=command, cwd=cwd, shell=shell)
        is_trusted = request.trusted

        if is_trusted and not config.SETTINGS.IS_TMUX_INSTALLED:
            return [types.TextContent(type="text", text=f"Tmux is not installed")]

        if not session_name:
            session_name = f"{uuid.uuid4().hex[:8]}"

        if is_trusted:
            session_name = f"native_mcp_{session_name}"

        req = TmuxExecuteInput(
            command=request.command,
            cwd=request.cwd,
            session_name=session_name,
            shell=request.shell,
        )

        await _execute_with_stream(
            command=build_tmux_bootstrap_command(
                session_name=req.session_name,
                # The prompt wait is POSIX shell syntax.
                wait_for_prompt=config.SETTINGS.PLATFORM != "windows",
            ),
            cwd=req.cwd,
            ctx=ctx,
            shell=req.shell,
            is_trusted=is_trusted,
        )
        tmux_command = build_tmux_reset_pane_command(session_name=req.session_name)
        for c in tmux_command:
            await _execute_with_stream(
                command=c,
                cwd=req.cwd,
                ctx=ctx,
                shell=req.shell,
                is_trusted=request.trusted,
            )
        await _execute_with_stream(
            command=build_tmux_send_keys_command(
                session_name=req.session_name,
                command=req.command,
            ),
            cwd=req.cwd,
            ctx=ctx,
            shell=req.shell,
            is_trusted=is_trusted,
        )

        resp = [{"session_name": req.session_name}]
        output = [
            create_shell_result(
                await _execute_with_stream(
                    command=build_tmux_capture_command(session_name=req.session_name),
                    cwd=req.cwd,
                    ctx=ctx,
                    shell=req.shell,
                    is_trusted=is_trusted,
                )
            )
        ]
        resp.extend(output)
        return resp

    @server.tool(task=TaskConfig(mode="optional"))
    async def tmux_get_output(
        session_name: str,
        ctx: Context,
        clear_after: bool = False,
        shell: str = "bash",
    ) -> list[types.TextContent]:
        """Capture tmux pane output; optionally clear after reading."""

        cwd: str = "."
        is_trusted = session_name.startswith("native_mcp_")
        if is_trusted and not config.SETTINGS.IS_TMUX_INSTALLED:
            return [types.TextContent(type="text", text=f"Tmux is not installed")]

        if is_trusted:
            cwd = config.SETTINGS.DOCKER_SANDBOX_HOST_ROOT
        else:
            cwd = config.SETTINGS.DOCKER_SANDBOX_WORKDIR

        result = [
            create_shell_result(
                await _execute_with_stream(
                    command=build_tmux_capture_command(session_name=session_name),
                    cwd=cwd,
                    ctx=ctx,
                    shell=shell,
                    is_trusted=is_trusted,
                )
            )
        ]
        if clear_after:
            await _execute_with_stream(
                command=build_tmux_clear_command(session_name=session_name),
                cwd=cwd,
                ctx=ctx,
                shell=shell,
                is_trusted=is_trusted,
            )

        return result

    @server.tool(task=TaskConfig(mode="optional"))
    async def tmux_list_session(shell: str = "bash") -> list[str]:
        """List active tmux sessions (sandbox and host)."""
        settings = config.SETTINGS
        if shell not in settings.ALLOWED_SHELLS:
            allowed = ", ".join(sorted(settings.ALLOWED_SHELLS))
            raise ValueError(f"Shell '{shell}' is not allowed. Available: {allowed}")

        def names(stdout: str) -> list[str]:
            return [line.split(":", 1)[0] for line in stdout.splitlines() if line.strip()]

        sessions: list[str] = []
        # Sandbox sessions only when a sandbox exists (previously this ran with
        # cwd=None and crashed when no sandbox work_dir was configured).
        if settings.DOCKER_SANDBOX_WORKDIR and not settings.IS_IN_DOCKER:
            result = await run_shell_command(
                command="tmux ls", cwd=settings.DOCKER_SANDBOX_WORKDIR, shell=shell, is_trusted=False
            )
            if result.exit_code == 0:
                sessions += names(result.stdout)
        # Host sessions (the trusted ``native_mcp_`` ones).
        if settings.IS_TMUX_INSTALLED:
            result = await run_shell_command(
                command="tmux ls",
                cwd=settings.DOCKER_SANDBOX_HOST_ROOT or os.getcwd(),
                shell=shell,
                is_trusted=True,
            )
            # Exit 1 with "no server running" just means there are no sessions.
            if result.exit_code == 0:
                sessions += names(result.stdout)
            elif "no server running" not in result.stderr and "error connecting" not in result.stderr:
                raise ValueError(f"tmux ls failed: {result.stderr.strip()}")
        return list(dict.fromkeys(sessions))

    @server.tool(task=TaskConfig(mode="optional"))
    async def tmux_send_keys(
        session_name: str,
        keys: str,
        ctx: Context,
        shell: str = "bash",
    ) -> list[types.TextContent]:
        """Send keys to a tmux session by validated name."""

        cwd: str = "."
        req = TmuxSessionInput(session_name=session_name, cwd=cwd, shell=shell)
        is_trusted = session_name.startswith("native_mcp_")
        if is_trusted and not config.SETTINGS.IS_TMUX_INSTALLED:
            return [types.TextContent(type="text", text=f"Tmux is not installed")]

        return await _execute_with_stream(
            command=build_tmux_send_keys_command(
                session_name=req.session_name, command=keys
            ),
            cwd=req.cwd,
            ctx=ctx,
            shell=req.shell,
            is_trusted=is_trusted,
        )

    @server.tool(task=TaskConfig(mode="optional"))
    async def tmux_kill_session(
        session_name: str,
        ctx: Context,
        shell: str = "bash",
    ) -> list[types.TextContent]:
        """Kill a tmux session by validated name."""

        cwd: str = "."
        req = TmuxSessionInput(session_name=session_name, cwd=cwd, shell=shell)
        is_trusted = session_name.startswith("native_mcp_")
        if is_trusted and not config.SETTINGS.IS_TMUX_INSTALLED:
            return [types.TextContent(type="text", text=f"Tmux is not installed")]

        return await _execute_with_stream(
            command=build_tmux_kill_command(session_name=req.session_name),
            cwd=req.cwd,
            ctx=ctx,
            shell=req.shell,
            is_trusted=is_trusted,
        )
