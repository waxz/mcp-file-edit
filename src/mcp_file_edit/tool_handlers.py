"""MCP tool handlers for shell execution and process management."""

from __future__ import annotations

import logging
import uuid
import json
import mcp.types as types
from anyio import ClosedResourceError
from fastmcp import Context, FastMCP
from typing import Dict, List, Any, Optional

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
from .file_patch_tools import(
    apply_patch as apply_patch_,  # CHANGED: Removed _with_recovery suffix
    apply_preview_changes as apply_preview_changes_,
    preview_patch as preview_patch_,
    preview_patch_with_vscode as preview_patch_with_vscode_,
    attach_patch_preview_session,

)
from .text_editor_tool import (
    str_replace_based_edit_tool as str_replace_based_edit_tool_,
)
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
    create_directory as create_directory_,
    remove_directory as remove_directory_,
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

from .mcp_types_utils import create_shell_result, create_str_result
from .patch_preview_store import (
    get_patch_preview_session,
    mark_patch_preview_applied,
    set_patch_preview_status,
)

logger = logging.getLogger(__name__)


def _http_base_url() -> str:
    assert config.SETTINGS is not None
    if config.SETTINGS.PUBLIC_URL is not None:
        return config.SETTINGS.PUBLIC_URL
    host = config.SETTINGS.HOST
    if host in {"0.0.0.0", "::"}:
        host = "localhost"
    return f"http://{host}:{config.SETTINGS.PORT}"


def register_tools(server: FastMCP) -> None:
    """Register MCP tools."""

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
        """Read a file for inspection. Prefer `apply_patch` for targeted edits instead of read/modify/write cycles."""
        return await read_file_(path, encoding, start_line, end_line)

    @server.tool
    async def write_file(
        path: str, content: str, encoding: str = "utf-8", create_dirs: bool = False
    ) -> Any:
        """Write full file contents. Prefer `apply_patch` for partial edits; use this for new files or full rewrites."""
        return await write_file_(path, content, encoding, create_dirs)

    @server.tool
    async def create_directory(path: str, create_dirs: bool = False) -> Any:
        """Create a new directory. Returns directory info; raises ValueError for invalid paths or directory already exists."""
        return await create_directory_(path, create_dirs)

    @server.tool
    async def remove_directory(path: str, create_dirs: bool = False) -> bool:
        """Remove a directory. raises ValueError for invalid paths or directory not exists."""
        return await remove_directory_(path)

    @server.tool
    async def create_file(
        path: str, content: str = "", encoding: str = "utf-8", create_dirs: bool = False
    ) -> Any:
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
        """Apply targeted patches to one file. For agent-driven code edits, prefer `apply_patch` when possible."""
        return await patch_file_(path, patches, backup, dry_run, create_dirs)

    @server.tool
    async def str_replace_based_edit_tool(
        command: str,
        path: str,
        file_text: Optional[str] = None,
        old_str: Optional[str] = None,
        new_str: Optional[str] = None,
        insert_line: Optional[int] = None,
        view_range: Optional[list[int]] = None,
        create_dirs: bool = False,
    ) -> Any:
        """
        Anthropic-compatible text editor tool for Claude (str_replace_based_edit_tool protocol).

        This is the native file-editing tool schema Claude models are trained to
        call. Prefer it over `apply_patch` when the calling agent is Claude;
        OpenAI/Codex-style agents should prefer `apply_patch` (Codex `apply_patch`
        envelope) instead. Both operate on the same project directory and file
        backend, so either can be used interchangeably against the same files.

        Commands:
        - view: Show a file's content (numbered like `cat -n`, optionally
          restricted to `view_range`), or list a directory up to 2 levels deep.
        - create: Create (or overwrite) a file with `file_text`.
        - str_replace: Replace the single, unique occurrence of `old_str` with
          `new_str` in an existing file. Include enough surrounding context in
          `old_str` that it matches exactly once; the call fails otherwise.
        - insert: Insert `new_str` immediately after line `insert_line`
          (0 = insert at the start of the file).
        - undo_edit: Revert the most recent create/str_replace/insert made to
          `path` through this tool.

        Workflow:
        1. `view` the file (or directory) to see current content and line numbers.
        2. Make one targeted edit with `str_replace` or `insert`.
        3. `view` again to confirm, or `undo_edit` if the edit was wrong.

        Args:
            command: One of "view", "create", "str_replace", "insert", "undo_edit".
            path: File or directory path, relative to the active project directory.
            file_text: Full file content, required for `create`.
            old_str: Exact text to replace, required for `str_replace`.
            new_str: Replacement text for `str_replace`; text to insert for `insert`.
            insert_line: Line number after which to insert, required for `insert`.
            view_range: Optional [start, end] 1-based inclusive line range for
                `view` on a file; use end=-1 to read to the end of the file.
            create_dirs: Create missing parent directories for `create`.

        Returns:
            Dict with `output` (human-readable confirmation, matching what the
            Anthropic text-editor tool returns) plus structured fields for the
            given command (e.g. `content`/`entries` for `view`).

        Raises:
            ValueError: For invalid commands, missing required parameters, path
                safety violations, or when `str_replace`/`insert` preconditions
                are not met (e.g. `old_str` not found, or not unique).
        """
        return await str_replace_based_edit_tool_(
            command,
            path,
            file_text,
            old_str,
            new_str,
            insert_line,
            view_range,
            create_dirs,
        )

    @server.tool
    async def patch_format_help() -> str:
        """
        Show patch format reference and examples.
        Use this if you're unsure how to construct a patch.

        Returns:
            Complete guide to patch syntax with examples
        """
        return """
    ╔══════════════════════════════════════════════════════════════╗
    ║                    PATCH FORMAT GUIDE                         ║
    ╚══════════════════════════════════════════════════════════════╝

    BASIC STRUCTURE:
    ───────────────
    *** Begin Patch
    *** Update File: path/to/file.ext
    @@
     context line (starts with space)
    -line to remove (starts with -)
    +line to add (starts with +)
     context line
    *** End Patch

    KEY RULES:
    ──────────
    ✓ Always start with: *** Begin Patch
    ✓ Always end with: *** End Patch
    ✓ Context lines need leading space
    ✓ Removal lines start with -
    ✓ Addition lines start with +
    ✓ Include 2-3 context lines before/after changes
    ✓ Match current file content exactly
    ✓ DO NOT include line numbers (no -1, +2, etc.)

    OPERATIONS:
    ───────────
    Update File:  *** Update File: path/to/file.txt
    Add File:     *** Add File: path/to/newfile.txt
    Delete File:  *** Delete File: path/to/oldfile.txt

    EXAMPLES:
    ─────────

    1. Single Line Change:
    *** Begin Patch
    *** Update File: config.py
    @@
     # Settings
     
    -DEBUG = False
    +DEBUG = True
     
     # Database
    *** End Patch

    2. Multi-Line Change:
    *** Begin Patch
    *** Update File: app.py
    @@
     def process():
    -    result = old_method()
    -    return result
    +    result = new_method()
    +    result = transform(result)
    +    return result
     
     def other_function():
    *** End Patch

    3. Add New File:
    *** Begin Patch
    *** Add File: new_module.py
    +def new_function():
    +    return "Hello"
    +
    +# More code here
    *** End Patch

    4. Multiple Files:
    *** Begin Patch
    *** Update File: file1.py
    @@
    -old content
    +new content
    *** Update File: file2.py
    @@
    -old content
    +new content
    *** End Patch

    COMMON MISTAKES:
    ────────────────
    ✗ Missing context lines
    ✗ No *** End Patch
    ✗ Using tabs instead of spaces for context
    ✗ Not matching current file content
    ✗ Including line numbers like -1 or +2
    ✗ Double prefixes like ++ or --

    WORKFLOW:
    ─────────
    1. read_file(path) to see current content
    2. Identify exact lines to change
    3. Copy 2-3 lines before as context
    4. Add your -/+ changes
    5. Copy 2-3 lines after as context
    6. preview_patch(patch) to verify
    7. apply_patch(patch) to apply
    8. read_file(path) to confirm

    TROUBLESHOOTING:
    ────────────────
    "Failed to locate patch context"
    → Re-read file, content may have changed
    → Add more unique context lines
    → Check whitespace matches exactly

    "Not enough context"
    → Add 2-3 lines before and after changes
    → Use distinctive nearby lines

    "Whitespace mismatch"  
    → Check indentation matches file
    → Look for tabs vs spaces
    → Preserve exact spacing
    
    TECHNICAL NOTE:
    ───────────────
    This implementation uses Google's diff-match-patch library for fuzzy
    matching and reliable patch application. It can handle minor whitespace
    differences and will attempt to find the best match location if the
    exact context isn't found.
    """

    @server.tool
    async def validate_patch_syntax(patch: str) -> Dict[str, Any]:
        """
        Check if a patch has correct syntax without applying it.
        Use this to validate patch format before preview/apply.

        Args:
            patch: Patch content to validate

        Returns:
            Validation result with errors and warnings
        """
        errors = []
        warnings = []
        suggestions = []

        lines = patch.splitlines()

        # Check basic structure
        if not lines:
            errors.append("Patch is empty")
        elif lines[0] != "*** Begin Patch":
            errors.append(f"Must start with '*** Begin Patch', got: {lines[0]}")

        if lines and lines[-1] != "*** End Patch":
            errors.append(f"Must end with '*** End Patch', got: {lines[-1]}")

        # Check for operations
        has_operation = any(
            line.startswith(("*** Update File:", "*** Add File:", "*** Delete File:"))
            for line in lines
        )
        if not has_operation:
            errors.append(
                "No file operation found (*** Update File: / *** Add File: / *** Delete File:)"
            )

        # Check for context
        context_lines = sum(1 for line in lines if line and line[0] == " ")
        if context_lines < 2:
            warnings.append(
                f"Only {context_lines} context lines found. Recommended: 4-6 for reliability"
            )
            suggestions.append("Add 2-3 context lines before and after each change")

        # Check for common mistakes
        for i, line in enumerate(lines, 1):
            if line.startswith("++") or line.startswith("--"):
                errors.append(
                    f"Line {i}: Double prefix found ({line[:3]}...), should be single + or -"
                )

            if line and line[0] in {"+", "-"} and len(line) > 1 and line[1].isdigit():
                warnings.append(
                    f"Line {i}: Line number detected ({line[:10]}...), remove numbers"
                )

            if line.startswith(" ") and len(line) > 1 and line[1] == " ":
                warnings.append(
                    f"Line {i}: Multiple leading spaces, should be single space for context"
                )

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "suggestions": suggestions,
            "summary": (
                "✓ Patch syntax is valid"
                if not errors
                else f"✗ Found {len(errors)} error(s), {len(warnings)} warning(s)"
            ),
        }

    # @server.tool
    # async def preview_patch(patch: str) -> str:
    #     """
    #     Always use preview_patch before apply_patch.

    #     Preview patch changes before applying.
    #     Shows a diff of what would change.

    #     Args:
    #         patch: Patch content in Codex format

    #     Returns:
    #         Formatted diff preview
    #     """
    #     from .file_tools import preview_patch as preview_patch_func

    #     return await preview_patch_func(patch)

    @server.tool(output_schema=None)
    async def preview_patch(patch: str) -> Any:
        """
        Preview patch changes as unified diff content.

        Returns a normal text preview plus structured diff artifacts that MCP
        clients may render in a diff viewer if they support embedded diff data.

        This tool does not create a review session and does not return a
        `preview_id`. Use it only for read-only diff inspection.

        If you need the confirm/apply workflow, call `apply_patch` with
        `dry_run=True` instead, then use the returned
        `structuredContent.preview_session.preview_id` with
        `confirm_patch_preview(preview_id=...)` and
        `apply_confirmed_patch(preview_id=...)`.
        """

        return await preview_patch_with_vscode_(patch)

    # @server.tool
    # async def preview_patch_vscode(patch: str) -> str:
    #     """
    #     Open patch diff in VSCode for visual review.

    #     Creates temp diff files and opens them in VSCode diff view.
    #     This gives you the best visual review experience.

    #     Args:
    #         patch: Patch content in Codex format

    #     Returns:
    #         Status message with VSCode launch info
    #     """
    #     from .file_tools import open_diff_in_vscode as open_diff_

    #     return await open_diff_(patch)

    # @server.tool
    # async def preview_patch_vscode(patch: str) -> str:
    #     """
    #     Preview patch with VSCode diff view instructions.

    #     Returns diff content plus commands to open in VSCode for visual review.
    #     Use this when you want to see the diff in VSCode's diff viewer.

    #     Args:
    #         patch: Patch content in Codex format

    #     Returns:
    #         Diff preview with VSCode open commands
    #     """

    #     return await preview_patch_with_vscode_(patch)

    @server.tool(output_schema=None)
    async def apply_patch(
        patch: str,
        backup: bool = True,
        dry_run: bool = False,
        create_dirs: bool = False,
        validate_first: bool = True,  # CHANGED: Added new parameter
    ) -> Any:
        """
        Preferred workflow for agents:
        1. Call `apply_patch` with `dry_run=True` first.
        2. Read the returned warnings and diff summary carefully.
        3. Review the returned diff and note `structuredContent.preview_session.preview_id`.
        4. Call `confirm_patch_preview(preview_id=...)` after review.
        5. Call `apply_confirmed_patch(preview_id=...)` after confirmation.
        6. Use `read_file` to verify the final file contents.

        This workflow works in both stdio and HTTP mode.
        When MCP HTTP returns preview URLs, the browser review UI is optional.
        Do not call `apply_patch` again with `dry_run=False` if the preview shows
        warnings, missing diffs, or unexpected files.

        # EXAMPLES:
        ─────────

        1. Single Line Change:
        *** Begin Patch
        *** Update File: config.py
        @@
        # Settings

        -DEBUG = False
        +DEBUG = True

        # Database
        *** End Patch

        2. Multi-Line Change:
        *** Begin Patch
        *** Update File: app.py
        @@
        def process():
        -    result = old_method()
        -    return result
        +    result = new_method()
        +    result = transform(result)
        +    return result

        def other_function():
        *** End Patch

        3. Add New File:
        *** Begin Patch
        *** Add File: new_module.py
        +def new_function():
        +    return "Hello"
        +
        +# More code here
        *** End Patch

        4. Multiple Files:
        *** Begin Patch
        *** Update File: file1.py
        @@
        -old content
        +new content
        *** Update File: file2.py
        @@
        -old content
        +new content
        *** End Patch




        ## PREVIEW WORKFLOW
        When `dry_run=True`, the tool returns:
        - text preview content
        - structured diff artifacts
        - `structuredContent.preview_session.preview_id`
        - optionally, HTTP preview URLs when running over HTTP

        Review the preview, call `confirm_patch_preview(preview_id=...)`, then call
        `apply_confirmed_patch(preview_id=...)`.

        ## PATCH ERROR RECOVERY PROTOCOL
        When you get ANY patch-related error (syntax, context, format, etc.):
        **DO NOT** try to fix it yourself.
        **INSTEAD:**
        1. Call the tool: `patch_format_help`
        2. Read the complete guide and examples
        3. Re-read the target file
        4. Build a new patch following the rules
        5. Test with `preview_patch` before applying

        ## TECHNICAL DETAILS:
        Uses strict exact-match validation before diff application:
        - removal/context lines must match the current file exactly
        - mismatched hunks are rejected instead of being fuzzily rewritten
        - preview sessions support confirmation before apply in both stdio and HTTP

        Args:
            patch: Patch content in Codex format
            backup: Create backup files before modifying (recommended)
            dry_run: If True, return a preview session instead of modifying files
            create_dirs: Create parent directories if needed
            validate_first: Pre-validate patches before applying (recommended)

        Returns:
            Operation result with:
            - success: bool
            - operations_applied: int
            - adds/updates/deletes/moves: int counts
            - changes: list of per-file results
            - warnings: list of validation warnings (if validate_first=True)
            - dry_run: bool

        Raises:
            ValueError: For invalid patch syntax or path errors
        """
        # CHANGED: Pass through new parameter


        if dry_run:
            preview_result = await preview_patch_with_vscode_(patch)
            return attach_patch_preview_session(
                preview_result,
                patch,
                base_url=(
                    _http_base_url()
                    if config.SETTINGS and config.SETTINGS.TRANSPORT == "http"
                    else None
                ),
            )

    
        return await apply_patch_(
            patch,
            backup,
            dry_run,
            create_dirs,
            validate_first,  # CHANGED: Added validation parameter
        )

    @server.tool
    async def get_patch_preview_status(preview_id: str) -> Dict[str, Any]:
        """Get the current status for a reviewed patch preview."""
        session = get_patch_preview_session(preview_id)
        if session is None:
            raise ValueError(f"Unknown or expired preview_id: {preview_id}")
        return {
            "preview_id": session.preview_id,
            "status": session.status,
            "created_at": session.created_at.isoformat(),
            "expires_at": session.expires_at.isoformat(),
            "confirmed_at": session.confirmed_at.isoformat() if session.confirmed_at else None,
            "rejected_at": session.rejected_at.isoformat() if session.rejected_at else None,
            "applied_at": session.applied_at.isoformat() if session.applied_at else None,
            "summary": session.structured_preview.get("summary", {}),
        }

    @server.tool
    async def confirm_patch_preview(preview_id: str) -> Dict[str, Any]:
        """Confirm a reviewed patch preview so it can be applied."""
        session = get_patch_preview_session(preview_id)
        if session is None:
            raise ValueError(f"Unknown or expired preview_id: {preview_id}")
        if session.status == "applied":
            raise ValueError(f"Preview {preview_id} is already applied")
        if session.status == "rejected":
            raise ValueError(f"Preview {preview_id} is rejected")
        if session.status != "confirmed":
            session = set_patch_preview_status(
                preview_id,
                token=session.confirm_token,
                status="confirmed",
            )
        return {
            "preview_id": session.preview_id,
            "status": session.status,
            "confirmed_at": session.confirmed_at.isoformat() if session.confirmed_at else None,
            "summary": session.structured_preview.get("summary", {}),
        }

    @server.tool
    async def reject_patch_preview(preview_id: str) -> Dict[str, Any]:
        """Reject a patch preview so it cannot be applied accidentally."""
        session = get_patch_preview_session(preview_id)
        if session is None:
            raise ValueError(f"Unknown or expired preview_id: {preview_id}")
        if session.status == "applied":
            raise ValueError(f"Preview {preview_id} is already applied")
        if session.status != "rejected":
            session = set_patch_preview_status(
                preview_id,
                token=session.reject_token,
                status="rejected",
            )
        return {
            "preview_id": session.preview_id,
            "status": session.status,
            "rejected_at": session.rejected_at.isoformat() if session.rejected_at else None,
            "summary": session.structured_preview.get("summary", {}),
        }

    @server.tool
    async def apply_confirmed_patch(
        preview_id: str,
        backup: bool = True,
        create_dirs: bool = False,
        validate_first: bool = True,
    ) -> Dict[str, Any]:
        """Apply a patch previously confirmed via the patch preview workflow."""
        session = get_patch_preview_session(preview_id)
        if session is None:
            raise ValueError(f"Unknown or expired preview_id: {preview_id}")
        if session.status != "confirmed":
            raise ValueError(
                f"Preview {preview_id} is not confirmed. Current status: {session.status}"
            )
        if session.structured_preview.get("files"):
            result = await apply_preview_changes_(
                session.structured_preview,
                backup=backup,
                create_dirs=create_dirs,
            )
        else:
            result = await apply_patch_(
                session.patch,
                backup,
                False,
                create_dirs,
                validate_first,
            )
        if result.get("success"):
            mark_patch_preview_applied(preview_id)
        return {
            **result,
            "preview_id": preview_id,
        }

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
        url: str,
        path: Optional[str] = None,
        branch: Optional[str] = None,
        depth: Optional[int] = None,
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
        local_path: str,
        remote_path: str,
        recursive: bool = False,
        overwrite: bool = True,
    ) -> Any:
        """Upload local file(s) to the connected remote path. Returns uploaded files, sizes, and errors."""
        return await ssh_upload_(local_path, remote_path, recursive, overwrite)

    @server.tool
    async def ssh_download(
        remote_path: str,
        local_path: str,
        recursive: bool = False,
        overwrite: bool = True,
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
        return await search_functions_(
            pattern, path, file_pattern, recursive, max_depth
        )

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

            project_path = utils.resolve_path(path, config.SETTINGS.WORK_DIR)
            # Path(path).resolve()

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
        path: str = ".",
        tool: Optional[str] = None,
        fix: bool = False,
        timeout: int = 60,
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
        path: str,
        tool: Optional[str] = None,
        check_only: bool = False,
        timeout: int = 30,
    ) -> Any:
        """Format a file with an auto-detected or selected formatter. Returns formatter status and output."""
        return await format_file_(path, tool, check_only, timeout)
