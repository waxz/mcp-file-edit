import mcp.types as types

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


def create_shell_result(result:ExecutionResult) -> types.TextContent:
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
    return types.TextContent(type="text", text="\n\n".join(parts))

def create_str_result(result:str) -> types.TextContent:
    return types.TextContent(type="text", text=result)

