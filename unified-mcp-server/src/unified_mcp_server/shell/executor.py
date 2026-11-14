# Derived from shell-mcp-server (Apache-2.0, https://github.com/waxz/shell-mcp-server);
# modified for unified-mcp-server. See NOTICE and LICENSE-APACHE.
"""Subprocess execution engine and process lifecycle management."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess as _subprocess
from contextlib import suppress
from pathlib import Path
from typing import Awaitable, Callable, Any, Dict

from .. import config
from .execution_policy import resolve_request
from ..common.models import ExecutionResult, ProcessRecord, ExecutionRequest

from .platform_adapters import build_posix_shell_command, build_windows_shell_command

logger = logging.getLogger(__name__)

try:
    from anyio import BrokenResourceError, ClosedResourceError
except ImportError:
    BrokenResourceError = OSError
    ClosedResourceError = OSError

_DISCONNECTED_ERRORS = (
    ClosedResourceError,
    BrokenResourceError,
    ConnectionError,
    BrokenPipeError,
    EOFError,
)

running_processes: dict[int, ProcessRecord] = {}


async def _terminate_process(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return

    pid = proc.pid
    try:
        if config.SETTINGS and config.SETTINGS.PLATFORM == "windows":
            killer = await asyncio.create_subprocess_exec(
                "taskkill",
                "/F",
                "/T",
                "/PID",
                str(pid),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(killer.wait(), timeout=5.0)
        else:
            with suppress(ProcessLookupError, PermissionError):
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(proc.wait(), timeout=3.0)
            if proc.returncode is None:
                with suppress(ProcessLookupError, PermissionError):
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
    except Exception:
        with suppress(ProcessLookupError):
            proc.kill()

    with suppress(Exception):
        await asyncio.wait_for(proc.wait(), timeout=2.0)


async def _ensure_compose_service_running(compose_file: str, service: str, env_file: str) -> None:
    """Ensure the compose sandbox service is running for persistent exec mode."""
    process = await asyncio.create_subprocess_exec(
        "docker",
        "compose",
        "--env-file",
        env_file,
        "-f",
        compose_file,
        "up",
        "-d",
        service,
        env=_docker_compose_env(),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await process.wait()


def _docker_compose_env() -> dict[str, str]:
    if config.SETTINGS is None:
        return os.environ.copy()
    env = os.environ.copy()
    return env


def _build_shell_command(
    command: str,
    shell: str,
    cwd: str,
    trusted: bool
) -> list[str]:
    if config.SETTINGS is None:
        raise RuntimeError("Server settings are not initialized")

    shell_path = config.SETTINGS.ALLOWED_SHELLS[shell]
    platform_name = config.SETTINGS.PLATFORM

    if platform_name == "windows":
        logger.debug("build_windows_shell_command for shell=%s", shell)
        return build_windows_shell_command(
            shell=shell,
            shell_path=shell_path,
            command=command,
            cwd=cwd,
            trusted=trusted,
            work_dir = config.SETTINGS.DOCKER_SANDBOX_WORKDIR,
            host_root = config.SETTINGS.DOCKER_SANDBOX_HOST_ROOT,
        )

    elif (
        platform_name == "linux"
    ):
        logger.debug("build_posix_shell_command for shell=%s", shell)
        return build_posix_shell_command(
            shell_path=shell_path,
            command=command,
            cwd=cwd,
            trusted=trusted,
            work_dir = config.SETTINGS.DOCKER_SANDBOX_WORKDIR,
            host_root = config.SETTINGS.DOCKER_SANDBOX_HOST_ROOT,
            
        )
    else:
        raise RuntimeError(f"Unsupported platform or shell combination: {platform_name} {shell}") 


async def run_shell_command(
    command: str,
    cwd: str,
    shell: str = "bash",
    on_stdout: Callable[[str], Awaitable[None]] | None = None,
    on_stderr: Callable[[str], Awaitable[None]] | None = None,
    is_trusted: bool|None = None,
) -> ExecutionResult:
    """Execute command with streaming callbacks and safe lifecycle handling."""
    if config.SETTINGS is None:
        raise RuntimeError("Server settings are not initialized")

    
    if is_trusted:
        request:ExecutionRequest =  ExecutionRequest(
            command = command,
            shell = shell,
            cwd = cwd,
            trusted = is_trusted
        )
    else:
        request:ExecutionRequest = resolve_request(command=command, cwd=cwd, shell=shell)


    # if (
    #     config.SETTINGS.PLATFORM == "linux"
    #     and request.shell == "bash"
    #     and not request.trusted
    #     and config.SETTINGS.UNTRUSTED_USE_DOCKER_SANDBOX
    #     and not config.SETTINGS.DOCKER_USE_DRUN_ON_LINUX
    # ):
    #     await _ensure_compose_service_running(
    #         compose_file=os.path.abspath(config.SETTINGS.DOCKER_SHELL_COMPOSE_FILE),
    #         env_file=os.path.abspath(config.SETTINGS.DOCKER_SHELL_ENV_FILE),
    #         service=config.SETTINGS.DOCKER_SHELL_SERVICE,
    #     )
    logger.debug("request: %s", request)
    shell_cmd = _build_shell_command(
        request.command,
        request.shell,
        request.cwd,
        request.trusted
    )
    logger.debug("shell_cmd: %s", shell_cmd)

    if request.trusted:
        if Path(request.cwd).exists():
            spawn_cwd = Path(request.cwd).resolve()
        else:
            raise ValueError(f"Directory {request.cwd} does not exist")
    else:
        spawn_cwd = config.SETTINGS.DOCKER_SANDBOX_HOST_ROOT

    
    logger.debug("spawn_cwd: %s", spawn_cwd)

    # ── Spawn with own process group ──────────────────────────
    spawn_kw: Dict[str, Any] = dict(
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=spawn_cwd,
    )

    if (
        config.SETTINGS.PLATFORM == "linux"
    ):
        spawn_kw_env = _docker_compose_env()
    else:
        spawn_kw_env = os.environ.copy()
    
    

    # cache_root = Path(request.cwd) / ".cache"
    # uv_cache = cache_root / "uv"
    # pip_cache = cache_root / "pip"
    # spawn_kw_env.setdefault("XDG_CACHE_HOME", str(cache_root))
    # spawn_kw_env.setdefault("UV_CACHE_DIR", str(uv_cache))
    # spawn_kw_env.setdefault("PIP_CACHE_DIR", str(pip_cache))

    # spawn_kw_env = {}


    spawn_kw: dict[str, object] = {
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.PIPE,
        "cwd": spawn_cwd,
    }
    if spawn_kw_env is not None:
        spawn_kw["env"] = spawn_kw_env
    if config.SETTINGS.PLATFORM == "windows" and request.trusted:
        spawn_kw["creationflags"] = _subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        spawn_kw["start_new_session"] = True

    try:
        process = await asyncio.create_subprocess_exec(*shell_cmd, **spawn_kw)
    except Exception as exc:
        return ExecutionResult(
            stdout="",
            stderr=f"Failed to start: {exc}",
            exit_code=-1,
            command=request.command,
            shell=request.shell,
            cwd=request.cwd,
            timed_out=False,
            cancelled=False,
            pid=None,
        )

    record = ProcessRecord(
        pid=process.pid,
        process=process,
        shell=request.shell,
        command=request.command,
        cwd=request.cwd,
    )
    running_processes[process.pid] = record

    cancel = asyncio.Event()
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    timed_out = False
    client_disconnected = False

    async def _safe_callback(
        cb: Callable[[str], Awaitable[None]] | None,
        line: str,
    ) -> bool:
        nonlocal client_disconnected
        if cb is None:
            return True
        try:
            await cb(line)
            return True
        except _DISCONNECTED_ERRORS:
            client_disconnected = True
            cancel.set()
            return False
        except asyncio.CancelledError:
            client_disconnected = True
            cancel.set()
            raise
        except Exception:
            client_disconnected = True
            cancel.set()
            return False

    async def _read_stream(
        stream: asyncio.StreamReader,
        buffer: list[str],
        callback: Callable[[str], Awaitable[None]] | None,
    ) -> None:
        partial = ""
        while not cancel.is_set():
            chunk = await stream.read(8192)
            if not chunk:
                if partial:
                    buffer.append(partial)
                    await _safe_callback(callback, partial)
                break

            text = partial + chunk.decode("utf-8", errors="replace")
            *lines, partial = text.split("\n")
            for line in lines:
                if cancel.is_set():
                    return
                cleaned = line.rstrip("\r")
                if cleaned:
                    buffer.append(cleaned)
                if not await _safe_callback(callback, cleaned):
                    return

    async def _auto_kill() -> None:
        await cancel.wait()
        await _terminate_process(process)

    kill_task = asyncio.create_task(_auto_kill())

    try:
        await asyncio.wait_for(
            asyncio.gather(
                _read_stream(process.stdout, stdout_lines, on_stdout),
                _read_stream(process.stderr, stderr_lines, on_stderr),
            ),
            timeout=config.SETTINGS.COMMAND_TIMEOUT,
        )
    except asyncio.TimeoutError:
        timed_out = True
        cancel.set()
    except asyncio.CancelledError:
        cancel.set()
        with suppress(Exception):
            await asyncio.wait_for(kill_task, timeout=10.0)
        running_processes.pop(process.pid, None)
        raise
    except Exception:
        cancel.set()
    finally:
        cancel.set()
        try:
            await asyncio.wait_for(kill_task, timeout=10.0)
        except asyncio.TimeoutError:
            kill_task.cancel()
            with suppress(asyncio.CancelledError):
                await kill_task
            with suppress(Exception):
                process.kill()
                await asyncio.wait_for(process.wait(), timeout=2.0)
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
    
    ## TODO: catch disconnection
    with suppress(Exception):
        await asyncio.wait_for(process.wait(), timeout=2.0)

    running_processes.pop(process.pid, None)

    stderr_text = "\n".join(stderr_lines)
    if timed_out:
        stderr_text = (
            f"{stderr_text}\n[Timed out after {config.SETTINGS.COMMAND_TIMEOUT}s]"
        ).strip()
    if client_disconnected:
        stderr_text = (
            f"{stderr_text}\n[Client disconnected - process killed]"
        ).strip()

    # stdout_lines = [line for line in stdout_lines if line.strip()]
    return ExecutionResult(
        stdout="\n".join(stdout_lines),
        stderr=stderr_text,
        exit_code=process.returncode if process.returncode is not None else -1,
        command=request.command,
        shell=request.shell,
        cwd=request.cwd,
        timed_out=timed_out,
        cancelled=client_disconnected,
        pid=process.pid,
    )


def list_running_process_records() -> list[ProcessRecord]:
    return list(running_processes.values())


async def terminate_process_by_pid(pid: int) -> bool:
    record = running_processes.get(pid)
    if record is None:
        return False
    await _terminate_process(record.process)
    running_processes.pop(pid, None)
    return True


async def terminate_all_processes() -> int:
    terminated = 0
    for pid, record in list(running_processes.items()):
        await _terminate_process(record.process)
        running_processes.pop(pid, None)
        terminated += 1
    return terminated
