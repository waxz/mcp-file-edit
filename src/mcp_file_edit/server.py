#!/usr/bin/env python3
"""
MCP File Editor Server using FastMCP
Provides comprehensive file system operations through MCP
"""

import sys
import argparse
from pathlib import Path
from typing import Dict, Any, Optional

from fastmcp import FastMCP

# Import all utilities and helpers
# Import path normalization functions for cross-platform compatibility
from .utils import (
    BASE_DIR,
    PROJECT_DIR,
    FILE_OPS,
    SSH_MANAGER,
    CONNECTION_TYPE,
    is_safe_path,
    resolve_path,
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


# Parse command line arguments
def parse_args() -> argparse.Namespace:
    """Parse command line arguments for directories and shells."""
    parser = argparse.ArgumentParser(description="MCP File Editor Server")
    
    parser.add_argument(
        "-t", "--transport", type=str, default="stdio", choices=["stdio", "http"]
    )
    parser.add_argument("-H", "--host", type=str, default="0.0.0.0")
    parser.add_argument("-P", "--port", type=int, default=8000)
    parser.add_argument("-p", "--path", type=str, default="/mcp")
    parser.add_argument("-n", "--name", type=str, default="file-editor")

    return parser.parse_args()


args = parse_args()
# Create the MCP server instance
mcp = FastMCP(args.name)




# File Management Tools
@mcp.tool()
async def list_files(
    path: str = ".",
    pattern: str = "*",
    recursive: bool = False,
    include_hidden: bool = False,
    max_depth: Optional[int] = None,
) -> Any:
    """
    List files and directories in a given path.

    Use this tool to explore directory contents, find files matching specific patterns,
    or understand the structure of a project. This is often the first step when
    starting to work with a new codebase or exploring file organization.

    Note: By default, this tool follows .gitignore patterns. Files and directories
    listed in .gitignore will be excluded from results unless explicitly matched.

    Args:
        path: The directory path to list. Defaults to current directory (".").
              Can be relative to the project directory or absolute.
        pattern: Glob pattern to match files against (e.g., "*.py", "*.js", "*.txt").
                 Defaults to "*" (all files). Use "**/*" for recursive matching.
        recursive: If True, search subdirectories recursively. Defaults to False.
                   Use this for deep exploration of directory trees.
        include_hidden: If True, include hidden files (starting with dot). Defaults to False.
        max_depth: Maximum directory depth for recursive search. None means unlimited.
                   Use this to limit how deep the search goes.

    Returns:
        A list of file/directory paths matching the pattern. Results include:
        - File paths with extensions
        - Directory paths (ending with /)
        - Relative paths from the search directory

    Examples:
        # List all files in current directory
        >>> await list_files()

        # List all Python files recursively
        >>> await list_files(path=".", pattern="**/*.py", recursive=True)

        # List files in a specific directory
        >>> await list_files(path="/path/to/project/src")

        # List with specific pattern
        >>> await list_files(path=".", pattern="*.json")

        # Include hidden files
        >>> await list_files(include_hidden=True)
    """
    return await list_files_(path, pattern, recursive, include_hidden, max_depth)


@mcp.tool()
async def read_file(
    path: str,
    encoding: str = "utf-8",
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
) -> Any:
    """
    Read the contents of a file.

    Use this tool to read source code, configuration files, documentation, or any
    text-based file content. This is essential for understanding existing code,
    reviewing files, or preparing to edit them.

    Args:
        path: The file path to read. Can be relative to project directory or absolute.
        encoding: File encoding. Defaults to "utf-8". Common options: "utf-8", "ascii",
                  "latin-1", "utf-16". Only change if you know the file uses a different encoding.
        start_line: Line number to start reading from (1-indexed). None means from beginning.
                    Use this with end_line to read specific portions of large files.
        end_line: Line number to stop reading at (inclusive). None means to the end.
                  Use this with start_line to read a specific line range.

    Returns:
        The file contents as a string. If start_line and end_line are specified,
        returns only that portion of the file with line numbers prefixed.

    Examples:
        # Read entire file
        >>> await read_file(path="src/main.py")

        # Read first 100 lines
        >>> await read_file(path="src/main.py", end_line=100)

        # Read lines 50-100
        >>> await read_file(path="src/main.py", start_line=50, end_line=100)

        # Read from line 200 to end
        >>> await read_file(path="src/main.py", start_line=200)
    """
    return await read_file_(path, encoding, start_line, end_line)


@mcp.tool()
async def write_file(
    path: str, content: str, encoding: str = "utf-8", create_dirs: bool = False
) -> Any:
    """
    Write content to a file, overwriting existing content.

    Use this tool to create new files or completely replace the contents of existing files.
    For updating specific portions of a file without overwriting, use patch_file instead.
    For creating new files that may not exist, consider create_file which has create_dirs=True by default.

    Args:
        path: The file path to write to. Can be relative to project directory or absolute.
        content: The content to write to the file. This will completely replace any existing content.
        encoding: File encoding. Defaults to "utf-8".
        create_dirs: If True, create parent directories if they don't exist. Defaults to False.
                     Set to True when writing to new paths with non-existent parent directories.

    Returns:
        Success message indicating the file was written.

    Examples:
        # Write to a new file
        >>> await write_file(path="new_file.txt", content="Hello, World!")

        # Overwrite existing file
        >>> await write_file(path="config.txt", content="new configuration")

        # Create file in new directory
        >>> await write_file(path="src/new/file.py", content="code here", create_dirs=True)
    """
    return await write_file_(path, content, encoding, create_dirs)


@mcp.tool()
async def create_file(path: str, content: str = "", create_dirs: bool = False) -> Any:
    """
    Create a new empty file or a file with initial content.

    Use this tool to create new files in the project. Unlike write_file, this tool
    has create_dirs=True by default, making it easier to create files in new directories.
    If the file already exists, this tool will overwrite it.

    Args:
        path: The file path to create. Can be relative to project directory or absolute.
        content: Initial content for the file. Defaults to empty string.
        create_dirs: If True, create parent directories if they don't exist. Defaults to False.

    Returns:
        Success message indicating the file was created.

    Examples:
        # Create an empty file
        >>> await create_file(path="new_file.txt")

        # Create file with content
        >>> await create_file(path="script.py", content="#!/usr/bin/env python3\nprint('hello')")

        # Create file in new directory (with dir creation)
        >>> await create_file(path="src/new/module.py", content="code", create_dirs=True)
    """
    return await create_file_(path, content, create_dirs)


@mcp.tool()
async def delete_file(path: str, recursive: bool = False) -> Any:
    """
    Delete a file or directory.

    Use this tool to remove files or directories from the project. BE CAREFUL - this
    operation is irreversible. Always verify the path before deleting.

    Args:
        path: The file or directory path to delete. Can be relative to project directory or absolute.
        recursive: If True, delete directories and their contents recursively. Defaults to False.
                   When False, can only delete empty directories. When True, removes all contents.

    Returns:
        Success message indicating the file/directory was deleted.

    Examples:
        # Delete a single file
        >>> await delete_file(path="temp.txt")

        # Delete a directory and all its contents
        >>> await delete_file(path="old_project/", recursive=True)
    """
    return await delete_file_(path, recursive)


@mcp.tool()
async def move_file(source: str, destination: str, overwrite: bool = False) -> Any:
    """
    Move or rename a file or directory.

    Use this tool to:
    - Move files to different directories
    - Rename files or directories
    - Relocate project structure

    Args:
        source: The current path of the file/directory to move.
                Can be relative to project directory or absolute.
        destination: The new path for the file/directory.
        overwrite: If True, overwrite destination if it exists. Defaults to False.
                  Use with caution - will permanently replace existing files.

    Returns:
        Success message indicating the file was moved.

    Examples:
        # Rename a file
        >>> await move_file(source="old_name.txt", destination="new_name.txt")

        # Move file to different directory
        >>> await move_file(source="file.txt", destination="backup/file.txt")

        # Move and rename
        >>> await move_file(source="src/main.py", destination="lib/entry.py")
    """
    return await move_file_(source, destination, overwrite)


@mcp.tool()
async def copy_file(source: str, destination: str, overwrite: bool = False) -> Any:
    """
    Copy a file or directory to a new location.

    Use this tool to:
    - Duplicate files for backup or experimentation
    - Create copies of directories and their contents
    - Clone files to different locations in the project

    Args:
        source: The path of the file/directory to copy.
                Can be relative to project directory or absolute.
        destination: The destination path for the copy.
        overwrite: If True, overwrite destination if it exists. Defaults to False.

    Returns:
        Success message indicating the file was copied.

    Examples:
        # Copy a file
        >>> await copy_file(source="original.txt", destination="copy.txt")

        # Copy to directory (preserves filename)
        >>> await copy_file(source="file.py", destination="backup/")

        # Copy entire directory
        >>> await copy_file(source="project/", destination="project_backup/")
    """
    return await copy_file_(source, destination, overwrite)


@mcp.tool()
async def search_files(
    pattern: str,
    path: str = ".",
    file_pattern: str = "*",
    recursive: bool = True,
    max_depth: Optional[int] = None,
    timeout: float = 30.0,
) -> Any:
    """
    Search for text patterns in files.

    Use this tool to find occurrences of specific text, code, or patterns across
    multiple files in your project. This is essential for:
    - Finding function definitions or usages
    - Searching for specific strings or comments
    - Locating code that needs modification
    - Finding TODO comments or debug statements

    Note: By default, this tool follows .gitignore patterns. Files listed in
    .gitignore will be excluded from search results.

    Args:
        pattern: The regex or text pattern to search for. Can be a simple string
                 or a regex pattern (e.g., "function\\s+\\w+", "TODO", "import.*os").
        path: The directory to search in. Defaults to current directory (".").
              Can be relative to project directory or absolute.
        file_pattern: Glob pattern to filter files (e.g., "*.py", "*.{ts,tsx}", "*.js").
                      Defaults to "*" (all files). Use language-specific patterns for efficiency.
        recursive: If True, search subdirectories recursively. Defaults to True.
        max_depth: Maximum directory depth for recursive search. None means unlimited.
        timeout: Maximum time in seconds for the search. Defaults to 30 seconds.
                 Increase for large codebases.

    Returns:
        A list of matches with file paths and line numbers. Each match includes:
        - File path
        - Line number
        - The matching line content

    Examples:
        # Search for a string in all files
        >>> await search_files(pattern="TODO")

        # Search in Python files only
        >>> await search_files(pattern="def.*", file_pattern="*.py")

        # Search for function definition
        >>> await search_files(pattern="async def", file_pattern="*.py")

        # Search in specific directory
        >>> await search_files(pattern="class.*", path="src/")

        # Use regex for complex patterns
        >>> await search_files(pattern="import\\s+{.*}", file_pattern="*.ts")
    """
    return await search_files_(
        pattern, path, file_pattern, recursive, max_depth, timeout
    )


@mcp.tool()
async def replace_in_files(
    search: str,
    replace: str,
    path: str = ".",
    file_pattern: str = "*",
    recursive: bool = True,
    max_depth: Optional[int] = None,
    timeout: float = 30.0,
) -> Any:
    """
    Search and replace text across multiple files.

    Use this tool to make bulk replacements across your codebase. This is powerful but
    potentially dangerous - always:
    1. First use search_files to verify what will be changed
    2. Consider the scope (recursive, file_pattern) carefully
    3. Test on a small scope first

    This tool performs find-and-replace on ALL matching occurrences across all
    matching files. For more controlled replacements, use patch_file.

    Args:
        search: The text or regex pattern to search for.
        replace: The replacement text. Can include capture groups if using regex.
        path: The directory to search in. Defaults to current directory (".").
        file_pattern: Glob pattern to filter files (e.g., "*.py", "*.js"). Defaults to "*".
        recursive: If True, search subdirectories recursively. Defaults to True.
        max_depth: Maximum directory depth. None means unlimited.
        timeout: Maximum time in seconds. Defaults to 30 seconds.

    Returns:
        Summary of replacements made, including file paths and number of replacements.

    Examples:
        # Replace all occurrences of a string
        >>> await replace_in_files(search="old_function", replace="new_function")

        # Replace in Python files only
        >>> await replace_in_files(search="print", replace="logger.info", file_pattern="*.py")

        # Use regex with capture groups
        >>> await replace_in_files(search=r"(\\w+)\\s*=\\s*(\\d+)", replace=r"\2 as \1")

        # Replace in specific directory
        >>> await replace_in_files(search="debug", replace="info", path="src/")
    """
    return await replace_in_files_(
        search, replace, path, file_pattern, recursive, max_depth, timeout
    )


@mcp.tool()
async def patch_file(
    path: str,
    patches: list,
    backup: bool = True,
    dry_run: bool = False,
    create_dirs: bool = False,
) -> Any:
    """
    Apply targeted patches to a specific file.

    Use this tool when you need to make precise, surgical changes to a file without
    rewriting the entire content. Unlike replace_in_files which operates across
    multiple files, this tool works on a single file with explicit patch specifications.

    This is the safest way to edit files because:
    - Each patch specifies exact old and new text
    - dry_run option shows what would change without applying
    - backup option creates a copy before modifying

    Args:
        path: The file path to patch. Must be an existing file (unless create_dirs=True).
        patches: A list of patch objects. Each patch should have "search" and "replace" keys.
                 Example: [{"search": "old text", "replace": "new text"}]
        backup: If True, create a .bak backup before applying patches. Defaults to True.
        dry_run: If True, show what would change without actually modifying the file.
                 Defaults to False. USE THIS FIRST to verify changes.
        create_dirs: If True, create parent directories if they don't exist. Defaults to False.

    Returns:
        Summary of patches applied or that would be applied (if dry_run=True).

    Examples:
        # Apply a single patch (use dry_run first!)
        >>> await patch_file(path="main.py", patches=[{"search": "old", "replace": "new"}])

        # Multiple patches at once
        >>> await patch_file(path="config.py", patches=[
        ...     {"search": "DEBUG = True", "replace": "DEBUG = False"},
        ...     {"search": "PORT = 8000", "replace": "PORT = 3000"}
        ... ])

        # Preview changes without applying
        >>> await patch_file(path="app.py", patches=[...], dry_run=True)
    """
    return await patch_file_(path, patches, backup, dry_run, create_dirs)


@mcp.tool()
async def get_file_info(path: str) -> Any:
    """
    Get detailed information about a file or directory.

    Use this tool to retrieve metadata about files including:
    - File size
    - Creation/modification timestamps
    - File type
    - Permissions (on Unix systems)
    - Whether it's a file or directory

    This is useful for:
    - Checking if files exist before operations
    - Understanding file age or recent changes
    - Determining file types

    Args:
        path: The file or directory path to get information about.
              Can be relative to project directory or absolute.

    Returns:
        Dictionary containing file metadata:
        - path: File path
        - size: File size in bytes
        - is_file: Boolean indicating if it's a file
        - is_dir: Boolean indicating if it's a directory
        - modified: Last modification timestamp
        - created: Creation timestamp (may not be available on all systems)
        - permissions: Permission string (e.g., "-rw-r--r--")

    Examples:
        >>> await get_file_info(path="src/main.py")
        >>> await get_file_info(path="project/")
    """
    return await get_file_info_(path)


# Git Operations Tools
@mcp.tool()
async def git_status(path: Optional[str] = None) -> Any:
    """
    Get the status of a git repository.

    Use this tool to see which files have been modified, which are staged for commit,
    and which are untracked. This is typically the first step before making a commit
    to understand what changes exist.

    Args:
        path: Path to the git repository. Defaults to current project directory.
              Can be relative or absolute.

    Returns:
        Git status output showing:
        - Modified files (not staged)
        - Staged files (ready to commit)
        - Untracked files (new files)
        - Deleted files
        - Current branch name

    Examples:
        >>> await git_status()
        >>> await git_status(path="/path/to/repo")
    """
    return await git_status_(path)


@mcp.tool()
async def git_init(path: Optional[str] = None) -> Any:
    """
    Initialize a new git repository.

    Use this tool to create a new git repository in a directory that isn't already
    under version control. After initialization, you'll need to use git_add to stage
    files and git_commit to make your first commit.

    Args:
        path: Path where to initialize the repository. Defaults to current project directory.

    Returns:
        Success message indicating the repository was initialized.

    Examples:
        >>> await git_init()
        >>> await git_init(path="/path/to/project")
    """
    return await git_init_(path)


@mcp.tool()
async def git_clone(
    url: str, path: Optional[str] = None, branch: Optional[str] = None
) -> Any:
    """
    Clone a remote git repository.

    Use this tool to download a complete copy of a remote repository. This creates
    a new directory with all the repository's history and files.

    Args:
        url: The clone URL of the remote repository (e.g.,
             "https://github.com/user/repo.git" or "git@github.com:user/repo.git").
        path: Local directory to clone into. Defaults to the repository name.
        branch: Specific branch to clone. Defaults to the repository's default branch.

    Returns:
        Success message indicating the repository was cloned.

    Examples:
        >>> await git_clone(url="https://github.com/user/repo.git")
        >>> await git_clone(url="git@github.com:user/repo.git", path="my-project")
        >>> await git_clone(url="https://github.com/user/repo.git", branch="develop")
    """
    return await git_clone_(url, path, branch)


@mcp.tool()
async def git_add(files, path: Optional[str] = None) -> Any:
    """
    Add files to the git staging area.

    Use this tool to stage files for commit. Staged files will be included in the
    next commit. You can stage specific files, patterns, or all files at once.

    Args:
        files: File(s) or pattern to stage. Can be:
               - A single file path ("src/main.py")
               - A list of files ["file1.txt", "file2.py"]
               - A pattern ("*.py" - stages all .py files)
               - "." to stage all files
        path: Path to the git repository. Defaults to current project directory.

    Returns:
        Success message indicating files were staged.

    Examples:
        # Stage all files
        >>> await git_add(files=".")

        # Stage specific file
        >>> await git_add(files="src/main.py")

        # Stage multiple files
        >>> await git_add(files=["file1.txt", "file2.py"])

        # Stage all Python files
        >>> await git_add(files="*.py")
    """
    return await git_add_(files, path)


@mcp.tool()
async def git_commit(message: str, path: Optional[str] = None) -> Any:
    """
    Commit staged changes to the repository.

    Use this tool to create a commit with all staged changes. A commit is a snapshot
    of your staged files at a point in time. Always include a descriptive commit message.

    Before committing:
    1. Use git_status to see what files are staged
    2. Use git_add to stage files you want to include

    Args:
        message: The commit message describing the changes. Should be descriptive
                 and explain what/why, not just how.
        path: Path to the git repository. Defaults to current project directory.

    Returns:
        Success message with commit hash and details.

    Examples:
        >>> await git_commit(message="Add user authentication")
        >>> await git_commit(message="Fix bug in login flow")
    """
    return await git_commit_(message, path)


@mcp.tool()
async def git_push(
    remote: str = "origin",
    branch: Optional[str] = None,
    set_upstream: bool = False,
    path: Optional[str] = None,
) -> Any:
    """
    Push commits to a remote repository.

    Use this tool to upload your local commits to a remote repository. This shares
    your changes with collaborators and backs up your work.

    Args:
        remote: Name of the remote to push to. Defaults to "origin".
                Common remotes: origin, upstream
        branch: Branch to push. Defaults to current branch.
        set_upstream: If True, set the remote branch as upstream for this branch.
                      Useful for first push of a new branch. Defaults to False.
        path: Path to the git repository. Defaults to current project directory.

    Returns:
        Success message with push details.

    Examples:
        # Push to origin (current branch)
        >>> await git_push()

        # Push to specific branch
        >>> await git_push(branch="main")

        # Push and set upstream (first push of new branch)
        >>> await git_push(branch="feature/new-feature", set_upstream=True)
    """
    return await git_push_(remote, branch, set_upstream, path)


@mcp.tool()
async def git_pull(
    remote: str = "origin", branch: Optional[str] = None, path: Optional[str] = None
) -> Any:
    """
    Pull changes from a remote repository.

    Use this tool to download and integrate changes from a remote repository into
    your local branch. This is how you stay synchronized with collaborators.

    Best practice: Run git_status or git_pull before making changes to ensure
    you have the latest code.

    Args:
        remote: Name of the remote to pull from. Defaults to "origin".
        branch: Branch to pull. Defaults to current branch.
        path: Path to the git repository. Defaults to current project directory.

    Returns:
        Output showing what was pulled/changed.

    Examples:
        >>> await git_pull()
        >>> await git_pull(remote="upstream")
        >>> await git_pull(branch="main")
    """
    return await git_pull_(remote, branch, path)


@mcp.tool()
async def git_log(
    limit: int = 10, oneline: bool = True, path: Optional[str] = None
) -> Any:
    """
    View the commit history of a repository.

    Use this tool to see the history of commits, understand changes over time,
    and find specific commits. This is useful for:
    - Understanding project history
    - Finding when bugs were introduced
    - Reviewing changes before commits

    Args:
        limit: Number of commits to show. Defaults to 10.
        oneline: If True, show each commit on a single line (compact format).
                 If False, show full commit details. Defaults to True.
        path: Path to the git repository. Defaults to current project directory.

    Returns:
        List of commits with details (hash, message, author, date).

    Examples:
        # View last 10 commits (compact)
        >>> await git_log()

        # View more history
        >>> await git_log(limit=50)

        # View detailed commit info
        >>> await git_log(oneline=False)
    """
    return await git_log_(limit, oneline, path)


@mcp.tool()
async def git_branch(
    create: Optional[str] = None,
    delete: Optional[str] = None,
    list_all: bool = False,
    path: Optional[str] = None,
) -> Any:
    """
    Manage git branches - list, create, or delete.

    Use this tool to:
    - List all branches (local and remote)
    - Create new branches
    - Delete existing branches

    Args:
        create: Name of a new branch to create. If provided, creates this branch.
        delete: Name of a branch to delete. If provided, deletes this branch.
        list_all: If True, list both local and remote branches. Defaults to False (local only).
        path: Path to the git repository. Defaults to current project directory.

    Returns:
        List of branches or success message for create/delete.

    Examples:
        # List local branches
        >>> await git_branch()

        # List all branches (including remote)
        >>> await git_branch(list_all=True)

        # Create a new branch
        >>> await git_branch(create="feature/new-feature")

        # Delete a branch
        >>> await git_branch(delete="old-feature")
    """
    return await git_branch_(create, delete, list_all, path)


@mcp.tool()
async def git_checkout(
    branch: str, create: bool = False, path: Optional[str] = None
) -> Any:
    """
    Switch to a different branch or create a new branch.

    Use this tool to:
    - Switch to an existing branch
    - Create and switch to a new branch
    - Check out a specific commit (detached HEAD)

    Args:
        branch: Branch name or commit hash to checkout.
        create: If True, create a new branch before switching. Defaults to False.
        path: Path to the git repository. Defaults to current project directory.

    Returns:
        Success message indicating the checkout result.

    Examples:
        # Switch to existing branch
        >>> await git_checkout(branch="main")
        >>> await git_checkout(branch="develop")

        # Create and switch to new branch
        >>> await git_checkout(branch="feature/new-feature", create=True)
    """
    return await git_checkout_(branch, create, path)


@mcp.tool()
async def git_diff(cached: bool = False, path: Optional[str] = None) -> Any:
    """
    View differences between commits, branches, or working directory.

    Use this tool to see what has changed:
    - Between working directory and staging area
    - Between staging area and last commit
    - Between any two commits

    This is essential for code review before committing.

    Args:
        cached: If True, show changes in staging area (vs last commit).
               If False, show unstaged changes (working directory vs staging).
               Defaults to False.
        path: Path to the git repository. Defaults to current project directory.

    Returns:
        Diff output showing added (green/+), removed (red/-), and modified lines.

    Examples:
        # View unstaged changes
        >>> await git_diff()

        # View staged changes (what will be committed)
        >>> await git_diff(cached=True)
    """
    return await git_diff_(cached, path)


@mcp.tool()
async def git_remote(
    action: str = "list",
    name: Optional[str] = None,
    url: Optional[str] = None,
    path: Optional[str] = None,
) -> Any:
    """
    Manage git remote repositories.

    Use this tool to:
    - List configured remotes
    - Add new remotes
    - Remove remotes
    - Update remote URLs

    Args:
        action: The action to perform. Options:
                - "list" (default): Show all remotes
                - "add": Add a new remote
                - "remove": Remove a remote
                - "set-url": Change a remote's URL
        name: Name of the remote (e.g., "origin", "upstream"). Required for add/remove/set-url.
        url: The URL for the remote. Required for "add" and "set-url" actions.
        path: Path to the git repository. Defaults to current project directory.

    Returns:
        List of remotes or success message for add/remove/set-url.

    Examples:
        # List remotes
        >>> await git_remote()
        >>> await git_remote(action="list")

        # Add a remote
        >>> await git_remote(action="add", name="upstream", url="https://github.com/user/repo.git")

        # Change remote URL
        >>> await git_remote(action="set-url", name="origin", url="https://github.com/new/repo.git")
    """
    return await git_remote_(action, name, url, path)


# SSH Operations Tools
@mcp.tool()
async def ssh_upload(
    local_path: str, remote_path: str, recursive: bool = False, overwrite: bool = True
) -> Any:
    """
    Upload files from local machine to a remote SSH server.

    Use this tool to transfer local files to a remote server via SSH/SFTP.
    This requires an active SSH connection (set via set_project_directory first).

    Args:
        local_path: Path to the local file or directory to upload.
                    Can be relative to project directory or absolute.
        remote_path: Destination path on the remote SSH server.
        recursive: If True, upload directories recursively. Defaults to False.
                   Set to True when uploading folders.
        overwrite: If True, overwrite existing files on remote. Defaults to True.
                   Set to False to prevent accidental overwrites.

    Returns:
        Success message with upload details.

    Examples:
        # Upload a single file
        >>> await ssh_upload(local_path="config.txt", remote_path="/home/user/config.txt")

        # Upload a directory
        >>> await ssh_upload(local_path="src/", remote_path="/home/user/src/", recursive=True)
    """
    return await ssh_upload_(local_path, remote_path, recursive, overwrite)


@mcp.tool()
async def ssh_download(
    remote_path: str, local_path: str, recursive: bool = False, overwrite: bool = True
) -> Any:
    """
    Download files from a remote SSH server to local machine.

    Use this tool to transfer files from a remote server to your local machine
    via SSH/SFTP. This requires an active SSH connection.

    Args:
        remote_path: Path to the file or directory on the remote SSH server.
        local_path: Destination path on the local machine.
        recursive: If True, download directories recursively. Defaults to False.
                   Set to True when downloading folders.
        overwrite: If True, overwrite existing local files. Defaults to True.

    Returns:
        Success message with download details.

    Examples:
        # Download a single file
        >>> await ssh_download(remote_path="/home/user/data.txt", local_path="downloads/data.txt")

        # Download a directory
        >>> await ssh_download(remote_path="/home/user/logs/", local_path="logs/", recursive=True)
    """
    return await ssh_download_(remote_path, local_path, recursive, overwrite)


@mcp.tool()
async def ssh_sync(
    local_path: str,
    remote_path: str,
    direction: str = "upload",
    delete: bool = False,
    exclude_patterns: Optional[list] = None,
    update_only: bool = True,
    show_progress: bool = True,
) -> Any:
    """
    Synchronize files between local and remote filesystems.

    Use this tool to keep local and remote directories in sync. It compares files
    and only transfers what's different, making it efficient for large syncs.

    This is ideal for:
    - Keeping deployment directories synchronized
    - Backup scenarios
    - Moving only changed files

    Args:
        local_path: Path on the local filesystem.
        remote_path: Path on the remote SSH server.
        direction: Sync direction - "upload" (local to remote) or "download" (remote to local).
                   Defaults to "upload".
        delete: If True, delete files on destination that don't exist on source.
                Defaults to False (safer option).
        exclude_patterns: List of glob patterns to exclude from sync (e.g., ["*.log", "node_modules"]).
        update_only: If True, only update existing files, don't create new ones on destination.
                      Defaults to True.
        show_progress: If True, show progress during sync. Defaults to True.

    Returns:
        Summary of sync operation showing files transferred.

    Examples:
        # Upload sync (local -> remote)
        >>> await ssh_sync(local_path="dist/", remote_path="/var/www/app/")

        # Download sync (remote -> local)
        >>> await ssh_sync(local_path="backup/", remote_path="/home/user/data/", direction="download")

        # Sync with exclusions
        >>> await ssh_sync(local_path=".", remote_path="/repo/", exclude_patterns=["*.log", ".git"])
    """
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
@mcp.tool()
async def list_functions(path: str, language: Optional[str] = None) -> Any:
    """
    List all functions in a code file.

    Use this tool to understand the structure of a source code file by listing
    all function definitions. This is useful for:
    - Understanding what functions exist in a file
    - Finding specific functions to modify
    - Getting an overview of a module's API
    - Planning refactoring

    Args:
        path: Path to the source code file.
        language: Programming language of the file. If not provided, will be inferred
                  from the file extension. Supported: "python", "javascript", "typescript",
                  "java", "c", "cpp", "go", "rust", "ruby", "php".

    Returns:
        List of functions with their:
        - Name
        - Line number
        - Parameters/arguments
        - Visibility (for languages that support it)

    Examples:
        >>> await list_functions(path="src/utils.py")
        >>> await list_functions(path="src/main.js", language="javascript")
    """
    return await list_functions_(path, language)


@mcp.tool()
async def get_function_at_line(
    path: str, line_number: int, language: Optional[str] = None
) -> Any:
    """
    Find which function contains a specific line number.

    Use this tool to:
    - Understand the context of a specific line
    - Find the function you're currently editing
    - Determine function boundaries for refactoring
    - Map error line numbers to function names

    Args:
        path: Path to the source code file.
        line_number: The line number to look up (1-indexed).
        language: Programming language. If not provided, inferred from extension.

    Returns:
        Function information including:
        - Function name
        - Start and end line numbers
        - Parameters

    Examples:
        # What's the function at line 50?
        >>> await get_function_at_line(path="src/main.py", line_number=50)
    """
    return await get_function_at_line_(path, line_number, language)


@mcp.tool()
async def get_code_structure(path: str, language: Optional[str] = None) -> Any:
    """
    Get an overview of a file's code structure.

    Use this tool to get a comprehensive view of a source code file including:
    - All functions
    - All classes (for OOP languages)
    - Imports/dependencies
    - Module-level variables

    This is the most comprehensive code analysis tool - use it to quickly
    understand a file's structure before diving in.

    Args:
        path: Path to the source code file.
        language: Programming language. If not provided, inferred from extension.

    Returns:
        Complete code structure including:
        - Functions (name, line numbers, parameters)
        - Classes (name, line numbers, methods)
        - Imports
        - Top-level variables/constants

    Examples:
        >>> await get_code_structure(path="src/main.py")
        >>> await get_code_structure(path="src/App.tsx", language="typescript")
    """
    return await get_code_structure_(path, language)


@mcp.tool()
async def search_functions(
    pattern: str,
    path: str = ".",
    file_pattern: str = "*.py",
    recursive: bool = True,
    max_depth: Optional[int] = None,
) -> Any:
    """
    Search for functions by name across multiple files.

    Use this tool to find where functions are defined across your codebase.
    This is essential for:
    - Finding function definitions
    - Understanding function usage patterns
    - Locating functions to modify
    - Finding related functions

    Args:
        pattern: Name pattern to search for. Can be a simple string or regex.
                 Example: "test_*", "handle_*", ".*Controller"
        path: Directory to search in. Defaults to current directory.
        file_pattern: Glob pattern for files to search. Defaults to "*.py".
                      Use "*.{js,ts}" for JavaScript/TypeScript.
        recursive: If True, search subdirectories. Defaults to True.
        max_depth: Maximum directory depth. None means unlimited.

    Returns:
        List of matching functions with file paths and line numbers.

    Examples:
        # Find all functions starting with "test_"
        >>> await search_functions(pattern="test_*")

        # Find all functions containing "handle"
        >>> await search_functions(pattern="handle.*")

        # Search in JavaScript files
        >>> await search_functions(pattern="onClick", file_pattern="*.js")
    """
    return await search_functions_(pattern, path, file_pattern, recursive, max_depth)


# Project Management Tools
@mcp.tool()
async def set_project_directory(
    path: str,
    connection_type: str = "local",
    ssh_host: Optional[str] = None,
    ssh_username: Optional[str] = None,
    ssh_port: int = 22,
    ssh_key_filename: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Set the project directory for relative path operations.

    Args:
        path: Path to the project directory
        connection_type: "local" or "ssh"
        ssh_host: SSH host (required if connection_type is "ssh")
        ssh_username: SSH username (required if connection_type is "ssh")
        ssh_port: SSH port (default: 22)
        ssh_key_filename: Path to SSH private key file

    Returns:
        Dictionary with project directory information (using normalized paths)
    """
    from . import utils

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

        project_path = (
            utils.BASE_DIR / path if not Path(path).is_absolute() else Path(path)
        )

        if not is_safe_path(project_path):
            raise ValueError(
                "Invalid path: project directory must be within base directory"
            )

        if not project_path.exists():
            raise ValueError(f"Project directory does not exist: {path}")

        if not project_path.is_dir():
            raise ValueError(f"Path is not a directory: {path}")

        utils.PROJECT_DIR = project_path

        # Return normalized paths for cross-platform compatibility
        return {
            "project_directory": normalize_path(utils.PROJECT_DIR),
            "connection_type": "local",
            "relative_to_base": normalize_path(
                utils.PROJECT_DIR.relative_to(utils.BASE_DIR)
            ),
            "absolute_path": normalize_absolute_path(utils.PROJECT_DIR),
        }


@mcp.tool()
async def get_project_directory() -> Dict[str, Any]:
    """
    Get information about the currently set project directory.

    Use this tool to check:
    - What project directory is currently active
    - What connection type is being used (local or SSH)
    - Whether an SSH connection is established

    This is useful for debugging connection issues and verifying the current context.

    Returns:
        Dictionary containing:
        - project_directory: Current project path (or None if not set)
        - connection_type: "local" or "ssh"
        - absolute_path: Absolute path to the project
        - For local: relative_to_base, exists
        - For SSH: ssh_connected

    Examples:
        >>> await get_project_directory()
    """
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
        result["relative_to_base"] = normalize_path(
            utils.PROJECT_DIR.relative_to(utils.BASE_DIR)
        )
        result["exists"] = utils.PROJECT_DIR.exists()
    else:
        # For SSH, we're already connected
        result["ssh_connected"] = SSH_MANAGER.is_connected()

    return result


# Linting and Type Checking Tools
@mcp.tool()
async def detect_linters(path: str = ".") -> Any:
    """
    Detect available linters and type checkers in a project.

    Use this tool to discover which linting and type checking tools are:
    - Installed in the system
    - Configured in the project (detects config files)
    - Applicable to the project's languages

    This helps you know what tools are available before running them.

    Args:
        path: Path to the project directory. Defaults to current directory.
              Can be relative to project directory or absolute.

    Returns:
        Dictionary with:
        - linters: List of available linters (ruff, pylint, flake8, eslint, etc.)
        - type_checkers: List of available type checkers (mypy, pyright, tsc, etc.)
        - formatters: List of available formatters (ruff, prettier, rustfmt, etc.)
        - detected_config: Dict of tool -> config file path
        - detected_languages: List of programming languages found in the project

    Examples:
        # Detect available tools
        >>> await detect_linters(path=".")

        # Check specific project
        >>> await detect_linters(path="/path/to/project")
    """
    return await detect_linters_(path)


@mcp.tool()
async def run_linter(
    path: str = ".", tool: Optional[str] = None, fix: bool = False, timeout: int = 60
) -> Any:
    """
    Run a linter on a project or specific file.

    Use this tool to find code quality issues, style violations, and potential bugs.
    Supports multiple languages and linters. If no tool is specified, auto-detects
    the best available linter.

    Args:
        path: Path to lint (file or directory). Defaults to current directory.
        tool: Specific linter to use. Options: ruff, pylint, flake8, eslint, clippy, golangci-lint.
              If None, auto-detects from available tools.
        fix: If True, attempt to automatically fix issues where possible. Defaults to False.
        timeout: Maximum time in seconds to wait for linter. Defaults to 60.

    Returns:
        Dictionary with:
        - success: Boolean indicating if lint passed
        - tool: The linter that was run
        - path: The path that was linted
        - returncode: Exit code from linter
        - issues: List of issues found (file, line, column, message, severity)
        - output: Raw output from linter

    Examples:
        # Run ruff on entire project
        >>> await run_linter(path="src/", tool="ruff")

        # Run with auto-detection
        >>> await run_linter(path=".")

        # Fix issues automatically
        >>> await run_linter(path="src/", tool="ruff", fix=True)

        # Lint a specific file
        >>> await run_linter(path="main.py", tool="ruff")
    """
    return await run_linter_(path, tool, fix, timeout)


@mcp.tool()
async def lint_file(
    path: str, tool: Optional[str] = None, fix: bool = False, timeout: int = 30
) -> Any:
    """
    Lint a specific file.

    Use this to check a single file for issues. Shorthand for run_linter with a file path.

    Args:
        path: Path to the file to lint. Required.
        tool: Specific linter to use. If None, auto-detects.
        fix: If True, attempt to fix issues automatically. Defaults to False.
        timeout: Maximum time in seconds. Defaults to 30.

    Returns:
        Dictionary with lint results (same as run_linter).

    Examples:
        >>> await lint_file(path="src/main.py")
        >>> await lint_file(path="app.js", tool="eslint", fix=True)
    """
    return await lint_file_(path, tool, fix, timeout)


@mcp.tool()
async def run_type_checker(
    path: str = ".", tool: Optional[str] = None, timeout: int = 60
) -> Any:
    """
    Run a type checker on a project or file.

    Use this tool to find type errors and ensure type safety. Supports multiple
    languages. If no tool is specified, auto-detects the best available type checker.

    Args:
        path: Path to check (file or directory). Defaults to current directory.
        tool: Specific type checker to use. Options: mypy, pyright, tsc, go vet.
              If None, auto-detects from available tools.
        timeout: Maximum time in seconds to wait for type checker. Defaults to 60.

    Returns:
        Dictionary with:
        - success: Boolean indicating if type checking passed
        - tool: The type checker that was run
        - path: The path that was checked
        - returncode: Exit code from type checker
        - issues: List of type errors found (file, line, message, severity)
        - output: Raw output from type checker

    Examples:
        # Run mypy on Python project
        >>> await run_type_checker(path="src/", tool="mypy")

        # Run with auto-detection
        >>> await run_type_checker(path=".")

        # Type check TypeScript
        >>> await run_type_checker(path="src/", tool="tsc")
    """
    return await run_type_checker_(path, tool, timeout)


@mcp.tool()
async def type_check_file(
    path: str, tool: Optional[str] = None, timeout: int = 30
) -> Any:
    """
    Type check a specific file.

    Use this to check a single file for type errors. Shorthand for run_type_checker
    with a file path.

    Args:
        path: Path to the file to type check. Required.
        tool: Specific type checker to use. If None, auto-detects.
        timeout: Maximum time in seconds. Defaults to 30.

    Returns:
        Dictionary with type check results (same as run_type_checker).

    Examples:
        >>> await type_check_file(path="src/main.py", tool="mypy")
        >>> await type_check_file(path="app.ts", tool="tsc")
    """
    return await type_check_file_(path, tool, timeout)


@mcp.tool()
async def format_file(
    path: str, tool: Optional[str] = None, check_only: bool = False, timeout: int = 30
) -> Any:
    """
    Format a file using the appropriate code formatter.

    Use this tool to automatically format code according to style guides.
    Supports multiple languages. Use check_only=True to see if formatting
    is needed without modifying the file.

    Args:
        path: Path to the file to format. Required.
        tool: Specific formatter to use. Options: ruff, prettier, rustfmt, gofmt.
              If None, auto-detects from file extension.
        check_only: If True, only check if file needs formatting (don't modify).
                    Defaults to False (will format the file).
        timeout: Maximum time in seconds. Defaults to 30.

    Returns:
        Dictionary with:
        - success: Boolean indicating if formatting succeeded
        - tool: The formatter that was used
        - path: The file that was formatted
        - returncode: Exit code from formatter
        - modified: True if file was modified (False if check_only=True)
        - check_only: Echoes the check_only parameter
        - output: Raw output from formatter

    Examples:
        # Format a Python file
        >>> await format_file(path="src/main.py")

        # Check if formatting is needed (without modifying)
        >>> await format_file(path="src/main.py", check_only=True)

        # Format with specific tool
        >>> await format_file(path="app.js", tool="prettier")
    """
    return await format_file_(path, tool, check_only, timeout)


def main():
    """Main entry point for the MCP server."""
    
    print(f"Starting MCP server with transport={args.transport}")

    if args.transport == "stdio":
        mcp.run()
    elif args.transport == "http":
        mcp.run(transport="http", port=args.port, host=args.host, path=args.path)


if __name__ == "__main__":
    main()
