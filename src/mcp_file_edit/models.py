"""Typed models for shell execution and process tracking."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field


class ExecutionRequest(BaseModel):
    """Normalized execution input after policy resolution."""

    command: str
    cwd: str
    shell: str = "bash"
    trusted: bool = False


class ExecutionResult(BaseModel):
    """Command execution result payload."""

    stdout: str = ""
    stderr: str = ""
    exit_code: int = -1
    command: str
    shell: str
    cwd: str
    timed_out: bool = False
    cancelled: bool = False
    pid: int | None = None


class ProcessRecord(BaseModel):
    """Tracked subprocess metadata."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    pid: int
    process: asyncio.subprocess.Process
    shell: str
    command: str
    cwd: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ExecuteCommandInput(BaseModel):
    command: str
    cwd: str
    shell: str = "bash"


class NameInput(BaseModel):
    name: str


class PidInput(BaseModel):
    pid: int


class TmuxExecuteInput(BaseModel):
    command: str
    cwd: str
    session_name: str = ""
    shell: str = "bash"


class TmuxSessionInput(BaseModel):
    session_name: str
    cwd: str = "."
    shell: str = "bash"


class TmuxGetOutputInput(TmuxSessionInput):
    clear_after: bool = False


class TmuxListInput(BaseModel):
    cwd: str = "."
    shell: str = "bash"
