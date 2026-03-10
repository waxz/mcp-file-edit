"""MCP tool handlers for shell execution and process management."""

from __future__ import annotations

import logging
import uuid
import json
import mcp.types as types
from anyio import ClosedResourceError
from fastmcp import Context, FastMCP
from typing import Dict, List,Any, Optional

from pathlib import Path

from fastmcp.server.tasks import TaskConfig

from . import config


# Import all utilities and helpers
# Import path normalization functions for cross-platform compatibility
from .utils import (
    SSH_MANAGER,
    normalize_path,
    normalize_absolute_path,
)
from .file_operations import LocalFileOperations, SSHFileOperations
from .ssh_manager import SSHConnectionManager
from .git_operations import LocalGitOperations, SSHGitOperations, GitOperations



# Import tool functions
from .file_tools import (
    list_files as list_files_,
    read_file as read_file_,
    write_file as write_file_,
    create_file as create_file_,
    delete_file as delete_file_,
    move_file as move_file_,
    copy_file as copy_file_,
    search_files as search_files_,
    replace_in_files as replace_in_files_,
    patch_file as patch_file_,
    get_file_info as get_file_info_,
)


from .git_tools import (
    git_status as git_status_,
    git_init as git_init_,
    git_clone as git_clone_,
    git_add as git_add_,
    git_commit as git_commit_,
    git_push as git_push_,
    git_pull as git_pull_,
    git_log as git_log_,
    git_branch as git_branch_,
    git_checkout as git_checkout_,
    git_diff as git_diff_,
    git_remote as git_remote_,
)
from .ssh_tools import (
    ssh_upload as ssh_upload_,
    ssh_download as ssh_download_,
    ssh_sync as ssh_sync_,
)
from .code_analyzer import (
    list_functions as list_functions_,
    get_function_at_line as get_function_at_line_,
    get_code_structure as get_code_structure_,
    search_functions as search_functions_,
)
from .linting_tools import (
    detect_linters as detect_linters_,
    run_linter as run_linter_,
    lint_file as lint_file_,
    run_type_checker as run_type_checker_,
    type_check_file as type_check_file_,
    format_file as format_file_,
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

from .mcp_utils import create_shell_result,create_str_result

logger = logging.getLogger(__name__)


def register_tools(server: FastMCP) -> None:
    """Register MCP tools."""

    async def _execute_with_stream(
        command: str,
        cwd: str,
        ctx: Context,
        shell: str,
        is_trusted: bool|None = None,
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
                is_trusted=is_trusted
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

    # File Management Tools
    @server.tool(task=TaskConfig(mode="optional"))
    async def list_files(
        path: str = ".",
        pattern: str = "*",
        recursive: bool = False,
        include_hidden: bool = False,
        max_depth: Optional[int] = None,
    ) -> Any:
        """List files/directories in a path. Returns matching entries with metadata; raises ValueError for invalid paths."""
        return await list_files_(path, pattern, recursive, include_hidden, max_depth)


    @server.tool
    async def read_file(
        path: str,
        encoding: str = "utf-8",
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
    ) -> Any:
        """Read a file. Returns text or base64 content depending on file type; raises ValueError for invalid or missing targets."""
        return await read_file_(path, encoding, start_line, end_line)


    @server.tool
    async def write_file(
        path: str, content: str, encoding: str = "utf-8", create_dirs: bool = False
    ) -> Any:
        """Write content to a file. Returns path and size; raises ValueError for invalid paths or write errors."""
        return await write_file_(path, content, encoding, create_dirs)


    @server.tool
    async def create_file(path: str, content: str = "", encoding:str = "utf-8", create_dirs: bool = False) -> Any:
        """Create a new file with optional content. Returns created file info; raises ValueError when file already exists or path is invalid."""
        return await create_file_(path, content, encoding, create_dirs)


    @server.tool
    async def delete_file(path: str, recursive: bool = False) -> Any:
        """Delete a file or directory. Returns deleted path info; raises ValueError for invalid paths or blocked delete operations."""
        return await delete_file_(path, recursive)


    @server.tool
    async def move_file(source: str, destination: str, overwrite: bool = False) -> Any:
        """Move or rename a file/directory. Returns source/destination info; raises ValueError for invalid paths or conflicts."""
        return await move_file_(source, destination, overwrite)


    @server.tool
    async def copy_file(source: str, destination: str, overwrite: bool = False) -> Any:
        """Copy a file or directory. Returns source/destination info; raises ValueError for invalid paths or conflicts."""
        return await copy_file_(source, destination, overwrite)


    @server.tool
    async def search_files(
        pattern: str,
        path: str = ".",
        file_pattern: str = "*",
        recursive: bool = True,
        max_depth: Optional[int] = None,
        timeout: float = 30.0,
    ) -> Any:
        """Search text by regex across files. Returns matches and stats, including timeout/error metadata."""
        return await search_files_(
            pattern, path, file_pattern, recursive, max_depth, timeout
        )


    @server.tool
    async def replace_in_files(
        search: str,
        replace: str,
        path: str = ".",
        file_pattern: str = "*",
        recursive: bool = True,
        max_depth: Optional[int] = None,
        timeout: float = 30.0,
    ) -> Any:
        """Replace text by regex across files. Returns replacement stats per file, including timeout/error metadata."""
        return await replace_in_files_(
            search, replace, path, file_pattern, recursive, max_depth, timeout
        )


    @server.tool
    async def patch_file(
        path: str,
        patches: list,
        backup: bool = True,
        dry_run: bool = False,
        create_dirs: bool = False,
    ) -> Any:
        """Apply targeted patches to one file. Returns per-patch results and final status."""
        return await patch_file_(path, patches, backup, dry_run, create_dirs)


    @server.tool
    async def get_file_info(path: str) -> Any:
        """Get metadata for a file/directory. Returns type, size, timestamps, and normalized paths."""
        return await get_file_info_(path)


    # Git Operations Tools
    @server.tool
    async def git_status(path: Optional[str] = None) -> Any:
        """Get repository status for a path. Returns branch and file-state details."""
        return await git_status_(path)


    @server.tool
    async def git_init(path: Optional[str] = None) -> Any:
        """Initialize a git repository at a path. Returns operation result details."""
        return await git_init_(path)


    @server.tool
    async def git_clone(
        url: str, path: Optional[str] = None, branch: Optional[str] = None, depth: Optional[int] = None
    ) -> Any:
        """Clone a repository URL to a destination path. Returns clone result details."""
        return await git_clone_(url, path, branch, depth)


    @server.tool
    async def git_add(files: list[str] | str, path: Optional[str] = None) -> Any:
        """Stage files for commit. Returns staging result details."""
        return await git_add_(files, path)


    @server.tool
    async def git_commit(message: str, path: Optional[str] = None) -> Any:
        """Commit staged changes with a message. Returns commit result details."""
        return await git_commit_(message, path)


    @server.tool
    async def git_push(
        remote: str = "origin",
        branch: Optional[str] = None,
        set_upstream: bool = False,
        path: Optional[str] = None,
    ) -> Any:
        """Push commits to a remote. Returns push result details."""
        return await git_push_(remote, branch, set_upstream, path)


    @server.tool
    async def git_pull(
        remote: str = "origin", branch: Optional[str] = None, path: Optional[str] = None
    ) -> Any:
        """Pull changes from a remote. Returns pull result details."""
        return await git_pull_(remote, branch, path)


    @server.tool
    async def git_log(
        limit: int = 10, oneline: bool = True, path: Optional[str] = None
    ) -> Any:
        """Get commit history. Returns parsed commit entries."""
        return await git_log_(limit, oneline, path)


    @server.tool
    async def git_branch(
        create: Optional[str] = None,
        delete: Optional[str] = None,
        list_all: bool = False,
        path: Optional[str] = None,
    ) -> Any:
        """List/create/delete branches. Returns branch operation details."""
        return await git_branch_(create, delete, list_all, path)


    @server.tool
    async def git_checkout(
        branch: str, create: bool = False, path: Optional[str] = None
    ) -> Any:
        """Switch to a branch/commit, optionally creating a branch. Returns checkout result details."""
        return await git_checkout_(branch, create, path)


    @server.tool
    async def git_diff(cached: bool = False, path: Optional[str] = None) -> Any:
        """Get diff output for working tree or staged changes. Returns diff content and status."""
        return await git_diff_(cached, path)


    @server.tool
    async def git_remote(
        action: str = "list",
        name: Optional[str] = None,
        url: Optional[str] = None,
        path: Optional[str] = None,
    ) -> Any:
        """List/add/remove/set-url for remotes. Returns remote operation details."""
        return await git_remote_(action, name, url, path)


    # SSH Operations Tools
    @server.tool
    async def ssh_upload(
        local_path: str, remote_path: str, recursive: bool = False, overwrite: bool = True
    ) -> Any:
        """Upload local file(s) to the connected remote path. Returns uploaded files, sizes, and errors."""
        return await ssh_upload_(local_path, remote_path, recursive, overwrite)


    @server.tool
    async def ssh_download(
        remote_path: str, local_path: str, recursive: bool = False, overwrite: bool = True
    ) -> Any:
        """Download remote file(s) to local path. Returns downloaded files, sizes, and errors."""
        return await ssh_download_(remote_path, local_path, recursive, overwrite)


    @server.tool
    async def ssh_sync(
        local_path: str,
        remote_path: str,
        direction: str = "upload",
        delete: bool = False,
        exclude_patterns: Optional[list] = None,
        update_only: bool = True,
        show_progress: bool = True,
    ) -> Any:
        """Sync local and remote directories using rsync. Returns sync summary, transferred files, and command output."""
        return await ssh_sync_(
            local_path,
            remote_path,
            direction,
            delete,
            exclude_patterns,
            update_only,
            show_progress,
        )


    # Code Analysis Tools
    @server.tool
    async def list_functions(path: str, language: Optional[str] = None) -> Any:
        """List functions in a source file. Returns names, signatures, and locations."""
        return await list_functions_(path, language)


    @server.tool
    async def get_function_at_line(
        path: str, line_number: int, language: Optional[str] = None
    ) -> Any:
        """Find the function containing a line number. Returns function details or no match."""
        return await get_function_at_line_(path, line_number, language)


    @server.tool
    async def get_code_structure(path: str, language: Optional[str] = None) -> Any:
        """Get structural summary for a source file. Returns imports, classes, functions, and top-level items."""
        return await get_code_structure_(path, language)


    @server.tool
    async def search_functions(
        pattern: str,
        path: str = ".",
        file_pattern: str = "*.py",
        recursive: bool = True,
        max_depth: Optional[int] = None,
    ) -> Any:
        """Search function definitions by name pattern across files. Returns matching functions and file locations."""
        return await search_functions_(pattern, path, file_pattern, recursive, max_depth)


    # Project Management Tools
    @server.tool
    async def set_project_directory(
        path: str,
        connection_type: str = "local",
        ssh_host: Optional[str] = None,
        ssh_username: Optional[str] = None,
        ssh_port: int = 22,
        ssh_key_filename: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Set active project directory and connection mode. For local mode, path must be inside ALLOW_DIRECTORIES."""
        from . import utils
        utils.validate_path_input(path)

        if connection_type == "ssh":
            # Parse SSH URL if provided
            if path.startswith("ssh://"):
                ssh_params = SSHConnectionManager.parse_ssh_url(path)
                ssh_host = ssh_params["host"]
                ssh_username = ssh_params.get("username") or ssh_username
                ssh_port = ssh_params.get("port", ssh_port)
                path = ssh_params["path"]

            # Validate SSH parameters
            if not ssh_host:
                raise ValueError("SSH host is required for SSH connection")
            if not ssh_username:
                raise ValueError("SSH username is required for SSH connection")

            # Set default key if not provided
            if not ssh_key_filename:
                ssh_key_filename = "~/.ssh/id_rsa"

            # Connect via SSH
            try:
                conn, sftp = await SSH_MANAGER.connect(
                    host=ssh_host,
                    username=ssh_username,
                    port=ssh_port,
                    key_filename=ssh_key_filename,
                )

                # Update global state
                utils.FILE_OPS = SSHFileOperations(conn, sftp)
                utils.CONNECTION_TYPE = "ssh"
                utils.GIT_OPS = None
                utils.PROJECT_DIR = Path(path)

                # Verify the directory exists on remote
                if not await utils.FILE_OPS.exists(utils.PROJECT_DIR):
                    raise ValueError(f"Remote directory does not exist: {path}")

                if not await utils.FILE_OPS.is_dir(utils.PROJECT_DIR):
                    raise ValueError(f"Remote path is not a directory: {path}")

                # Return normalized paths for cross-platform compatibility
                return {
                    "project_directory": normalize_path(utils.PROJECT_DIR),
                    "connection_type": "ssh",
                    "ssh_host": ssh_host,
                    "ssh_username": ssh_username,
                    "ssh_port": ssh_port,
                    "absolute_path": normalize_absolute_path(utils.PROJECT_DIR),
                }

            except Exception as e:
                # Reset to local on error
                utils.FILE_OPS = LocalFileOperations()
                utils.CONNECTION_TYPE = "local"
                raise ValueError(f"Failed to establish SSH connection: {str(e)}")

        else:
            # Local connection
            from . import utils

            utils.FILE_OPS = LocalFileOperations()
            utils.CONNECTION_TYPE = "local"
            utils.GIT_OPS = None

            await SSH_MANAGER.close()

            project_path = Path(path).resolve()

            if not project_path.exists():
                raise ValueError(f"Project directory does not exist: {path}")

            if not project_path.is_dir():
                raise ValueError(f"Path is not a directory: {path}")

            allowed_roots = utils.get_allow_directories()
            if not utils.is_within_allowed_directories(project_path, allowed_roots):
                allowed_display = [normalize_path(root) for root in allowed_roots]
                raise ValueError(
                    f"Project directory is not allowed: {normalize_path(project_path)}. "
                    f"Allowed roots: {allowed_display}"
                )

            utils.PROJECT_DIR = project_path

            # Return normalized paths for cross-platform compatibility
            result = {
                "project_directory": normalize_path(utils.PROJECT_DIR),
                "connection_type": "local",
                "relative_to_project": ".",
                "absolute_path": normalize_absolute_path(utils.PROJECT_DIR),
            }
            try:
                result["relative_to_base"] = normalize_path(
                    utils.PROJECT_DIR.relative_to(utils.BASE_DIR)
                )
            except ValueError:
                result["relative_to_base"] = None
            return result


    @server.tool
    async def get_project_directory() -> Dict[str, Any]:
        """Get current project directory and connection details. Returns local/SSH-specific status fields."""
        from . import utils

        if utils.PROJECT_DIR is None:
            return {
                "project_directory": None,
                "connection_type": utils.CONNECTION_TYPE,
                "message": "No project directory set. Use set_project_directory to set one.",
            }

        # Return normalized paths for cross-platform compatibility
        result = {
            "project_directory": normalize_path(utils.PROJECT_DIR),
            "connection_type": utils.CONNECTION_TYPE,
            "absolute_path": normalize_absolute_path(utils.PROJECT_DIR),
        }

        # Add local-specific info
        if utils.CONNECTION_TYPE == "local":
            result["relative_to_project"] = "."
            try:
                result["relative_to_base"] = normalize_path(
                    utils.PROJECT_DIR.relative_to(utils.BASE_DIR)
                )
            except ValueError:
                result["relative_to_base"] = None
            result["exists"] = utils.PROJECT_DIR.exists()
        else:
            # For SSH, we're already connected
            result["ssh_connected"] = SSH_MANAGER.is_connected()

        return result


    # Linting and Type Checking Tools
    @server.tool
    async def detect_linters(path: str = ".") -> Any:
        """Detect available linters/type checkers/formatters for a path. Returns tools, configs, and detected languages."""
        return await detect_linters_(path)


    @server.tool
    async def run_linter(
        path: str = ".", tool: Optional[str] = None, fix: bool = False, timeout: int = 60
    ) -> Any:
        """Run a linter for a path. Returns pass/fail, issues, and raw output."""
        return await run_linter_(path, tool, fix, timeout)


    @server.tool
    async def lint_file(
        path: str, tool: Optional[str] = None, fix: bool = False, timeout: int = 30
    ) -> Any:
        """Lint a single file. Returns pass/fail, issues, and raw output."""
        return await lint_file_(path, tool, fix, timeout)


    @server.tool
    async def run_type_checker(
        path: str = ".", tool: Optional[str] = None, timeout: int = 60
    ) -> Any:
        """Run a type checker for a path. Returns pass/fail, issues, and raw output."""
        return await run_type_checker_(path, tool, timeout)


    @server.tool
    async def type_check_file(
        path: str, tool: Optional[str] = None, timeout: int = 30
    ) -> Any:
        """Type-check a single file. Returns pass/fail, issues, and raw output."""
        return await type_check_file_(path, tool, timeout)


    @server.tool
    async def format_file(
        path: str, tool: Optional[str] = None, check_only: bool = False, timeout: int = 30
    ) -> Any:
        """Format a file with an auto-detected or selected formatter. Returns formatter status and output."""
        return await format_file_(path, tool, check_only, timeout)
