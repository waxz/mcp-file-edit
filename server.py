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
from utils import (
    BASE_DIR, PROJECT_DIR, FILE_OPS, SSH_MANAGER, CONNECTION_TYPE,
    is_safe_path, resolve_path
)
from file_operations import LocalFileOperations, SSHFileOperations
from ssh_manager import SSHConnectionManager
from git_operations import LocalGitOperations, SSHGitOperations, GitOperations

# Import tool functions
from file_tools import (
    list_files as list_files_, 
    read_file as read_file_, write_file as write_file_, create_file as create_file_,
    delete_file as delete_file_, move_file as move_file_, copy_file as copy_file_, search_files as search_files_,
    replace_in_files as replace_in_files_, patch_file as patch_file_, get_file_info as get_file_info_
)

from git_tools import (
    git_status as git_status_, git_init as git_init_, git_clone as git_clone_, git_add as git_add_, git_commit as git_commit_,
    git_push as git_push_, git_pull as git_pull_, git_log as git_log_, git_branch as git_branch_, git_checkout as git_checkout_,
    git_diff as git_diff_, git_remote as git_remote_
)
from ssh_tools import (
    ssh_upload as ssh_upload_, ssh_download as ssh_download_, ssh_sync as ssh_sync_
)
from code_analyzer import (
    list_functions as list_functions_,
    get_function_at_line as get_function_at_line_,
    get_code_structure as get_code_structure_,
    search_functions as search_functions_
)


# Parse command line arguments
def parse_args() -> argparse.Namespace:
    """Parse command line arguments for directories and shells."""
    parser = argparse.ArgumentParser(description="MCP File Editor Server")
    parser.add_argument('-d', '--directories', nargs='+', help='Allowed directories for command execution')
    parser.add_argument('--shell', action='append', nargs=2, metavar=('name', 'path'),
                       help='Shell specification in format: name path')
    parser.add_argument('-t', '--transport', type=str, default='stdio', choices=['stdio', 'http'])
    parser.add_argument('-H', '--host', type=str, default='0.0.0.0')
    parser.add_argument('-P', '--port', type=int, default=8000)
    parser.add_argument('-p', '--path', type=str, default='/mcp')
    
    return parser.parse_args()


# Create the MCP server instance
mcp = FastMCP("file-editor")


# Greeting tools
@mcp.tool()
async def greet(name: str) -> str:
    """Greet someone by name."""
    return f"Hello, {name}!"


@mcp.tool()
async def bye(name: str) -> str:
    """Say goodbye to someone."""
    return f"Bye, {name}!"


# File Management Tools
@mcp.tool()
async def list_files(
    path: str = ".",
    pattern: str = "*",
    recursive: bool = False,
    include_hidden: bool = False,
    max_depth: Optional[int] = None
) -> Any:
    """List files and directories."""
    return await list_files_(path, pattern, recursive, include_hidden, max_depth)


@mcp.tool()
async def read_file(
    path: str,
    encoding: str = "utf-8",
    start_line: Optional[int] = None,
    end_line: Optional[int] = None
) -> Any:
    """Read file contents."""
    return await read_file_(path, encoding, start_line, end_line)


@mcp.tool()
async def write_file(
    path: str,
    content: str,
    encoding: str = "utf-8",
    create_dirs: bool = False
) -> Any:
    """Write content to a file."""
    return await write_file_(path, content, encoding, create_dirs)


@mcp.tool()
async def create_file(
    path: str,
    content: str = "",
    create_dirs: bool = False
) -> Any:
    """Create a new file."""
    return await create_file_(path, content, create_dirs)


@mcp.tool()
async def delete_file(
    path: str,
    recursive: bool = False
) -> Any:
    """Delete a file or directory."""
    return await delete_file_(path, recursive)


@mcp.tool()
async def move_file(
    source: str,
    destination: str,
    overwrite: bool = False
) -> Any:
    """Move or rename a file."""
    return await move_file_(source, destination, overwrite)


@mcp.tool()
async def copy_file(
    source: str,
    destination: str,
    overwrite: bool = False
) -> Any:
    """Copy a file or directory."""
    return await copy_file_(source, destination, overwrite)


@mcp.tool()
async def search_files(
    pattern: str,
    path: str = ".",
    file_pattern: str = "*",
    recursive: bool = True,
    max_depth: Optional[int] = None,
    timeout: float = 30.0
) -> Any:
    """Search for patterns in files."""
    return await search_files_(pattern, path, file_pattern, recursive, max_depth, timeout)


@mcp.tool()
async def replace_in_files(
    search: str,
    replace: str,
    path: str = ".",
    file_pattern: str = "*",
    recursive: bool = True,
    max_depth: Optional[int] = None,
    timeout: float = 30.0
) -> Any:
    """Replace text in files."""
    return await replace_in_files_(search, replace, path, file_pattern, recursive, max_depth, timeout)


@mcp.tool()
async def patch_file(
    path: str,
    patches: list,
    backup: bool = True,
    dry_run: bool = False,
    create_dirs: bool = False
) -> Any:
    """Apply patches to a file."""
    return await patch_file_(path, patches, backup, dry_run, create_dirs)


@mcp.tool()
async def get_file_info(path: str) -> Any:
    """Get detailed file information."""
    return await get_file_info_(path)


# Git Operations Tools
@mcp.tool()
async def git_status(path: Optional[str] = None) -> Any:
    """Get git repository status."""
    return await git_status_(path)


@mcp.tool()
async def git_init(path: Optional[str] = None) -> Any:
    """Initialize a new git repository."""
    return await git_init_(path)


@mcp.tool()
async def git_clone(url: str, path: Optional[str] = None, branch: Optional[str] = None) -> Any:
    """Clone a remote git repository."""
    return await git_clone_(url, path, branch)


@mcp.tool()
async def git_add(files, path: Optional[str] = None) -> Any:
    """Add files to git staging area."""
    return await git_add_(files, path)


@mcp.tool()
async def git_commit(message: str, path: Optional[str] = None) -> Any:
    """Commit staged changes."""
    return await git_commit_(message, path)


@mcp.tool()
async def git_push(
    remote: str = "origin",
    branch: Optional[str] = None,
    set_upstream: bool = False,
    path: Optional[str] = None
) -> Any:
    """Push commits to remote repository."""
    return await git_push_(remote, branch, set_upstream, path)


@mcp.tool()
async def git_pull(
    remote: str = "origin",
    branch: Optional[str] = None,
    path: Optional[str] = None
) -> Any:
    """Pull changes from remote repository."""
    return await git_pull_(remote, branch, path)


@mcp.tool()
async def git_log(
    limit: int = 10,
    oneline: bool = True,
    path: Optional[str] = None
) -> Any:
    """Get git commit log."""
    return await git_log_(limit, oneline, path)


@mcp.tool()
async def git_branch(
    create: Optional[str] = None,
    delete: Optional[str] = None,
    list_all: bool = False,
    path: Optional[str] = None
) -> Any:
    """Manage git branches."""
    return await git_branch_(create, delete, list_all, path)


@mcp.tool()
async def git_checkout(
    branch: str,
    create: bool = False,
    path: Optional[str] = None
) -> Any:
    """Checkout a branch or commit."""
    return await git_checkout_(branch, create, path)


@mcp.tool()
async def git_diff(cached: bool = False, path: Optional[str] = None) -> Any:
    """Get git diff output."""
    return await git_diff_(cached, path)


@mcp.tool()
async def git_remote(
    action: str = "list",
    name: Optional[str] = None,
    url: Optional[str] = None,
    path: Optional[str] = None
) -> Any:
    """Manage git remotes."""
    return await git_remote_(action, name, url, path)


# SSH Operations Tools
@mcp.tool()
async def ssh_upload(
    local_path: str,
    remote_path: str,
    recursive: bool = False,
    overwrite: bool = True
) -> Any:
    """Upload file(s) to remote SSH server."""
    return await ssh_upload_(local_path, remote_path, recursive, overwrite)


@mcp.tool()
async def ssh_download(
    remote_path: str,
    local_path: str,
    recursive: bool = False,
    overwrite: bool = True
) -> Any:
    """Download file(s) from remote SSH server."""
    return await ssh_download_(remote_path, local_path, recursive, overwrite)


@mcp.tool()
async def ssh_sync(
    local_path: str,
    remote_path: str,
    direction: str = "upload",
    delete: bool = False,
    exclude_patterns: Optional[list] = None,
    update_only: bool = True,
    show_progress: bool = True
) -> Any:
    """Synchronize files between local and remote filesystems."""
    return await ssh_sync_(local_path, remote_path, direction, delete, exclude_patterns, update_only, show_progress)


# Code Analysis Tools
@mcp.tool()
async def list_functions(path: str, language: Optional[str] = None) -> Any:
    """List all functions in a code file."""
    return await list_functions_(path, language)


@mcp.tool()
async def get_function_at_line(path: str, line_number: int, language: Optional[str] = None) -> Any:
    """Get the function that contains a specific line number."""
    return await get_function_at_line_(path, line_number, language)


@mcp.tool()
async def get_code_structure(path: str, language: Optional[str] = None) -> Any:
    """Get the overall code structure of a file."""
    return await get_code_structure_(path, language)


@mcp.tool()
async def search_functions(
    pattern: str,
    path: str = ".",
    file_pattern: str = "*.py",
    recursive: bool = True,
    max_depth: Optional[int] = None
) -> Any:
    """Search for functions by name pattern across files."""
    return await search_functions_(pattern, path, file_pattern, recursive, max_depth)


# Project Management Tools
@mcp.tool()
async def set_project_directory(
    path: str,
    connection_type: str = "local",
    ssh_host: Optional[str] = None,
    ssh_username: Optional[str] = None,
    ssh_port: int = 22,
    ssh_key_filename: Optional[str] = None
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
        Dictionary with project directory information
    """
    import utils
    
    if connection_type == "ssh":
        # Parse SSH URL if provided
        if path.startswith("ssh://"):
            ssh_params = SSHConnectionManager.parse_ssh_url(path)
            ssh_host = ssh_params['host']
            ssh_username = ssh_params.get('username') or ssh_username
            ssh_port = ssh_params.get('port', ssh_port)
            path = ssh_params['path']
        
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
                key_filename=ssh_key_filename
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
            
            return {
                "project_directory": str(utils.PROJECT_DIR),
                "connection_type": "ssh",
                "ssh_host": ssh_host,
                "ssh_username": ssh_username,
                "ssh_port": ssh_port,
                "absolute_path": str(utils.PROJECT_DIR)
            }
            
        except Exception as e:
            # Reset to local on error
            utils.FILE_OPS = LocalFileOperations()
            utils.CONNECTION_TYPE = "local"
            raise ValueError(f"Failed to establish SSH connection: {str(e)}")
    
    else:
        # Local connection
        import utils
        utils.FILE_OPS = LocalFileOperations()
        utils.CONNECTION_TYPE = "local"
        utils.GIT_OPS = None
        
        await SSH_MANAGER.close()
        
        project_path = utils.BASE_DIR / path if not Path(path).is_absolute() else Path(path)
        
        if not is_safe_path(project_path):
            raise ValueError("Invalid path: project directory must be within base directory")
        
        if not project_path.exists():
            raise ValueError(f"Project directory does not exist: {path}")
        
        if not project_path.is_dir():
            raise ValueError(f"Path is not a directory: {path}")
        
        utils.PROJECT_DIR = project_path
        
        return {
            "project_directory": str(utils.PROJECT_DIR),
            "connection_type": "local",
            "relative_to_base": str(utils.PROJECT_DIR.relative_to(utils.BASE_DIR)),
            "absolute_path": str(utils.PROJECT_DIR.absolute())
        }


@mcp.tool()
async def get_project_directory() -> Dict[str, Any]:
    """Get the current project directory."""
    import utils
    
    if utils.PROJECT_DIR is None:
        return {
            "project_directory": None,
            "connection_type": utils.CONNECTION_TYPE,
            "message": "No project directory set. Use set_project_directory to set one."
        }
    
    result = {
        "project_directory": str(utils.PROJECT_DIR),
        "connection_type": utils.CONNECTION_TYPE,
        "absolute_path": str(utils.PROJECT_DIR.absolute())
    }
    
    # Add local-specific info
    if utils.CONNECTION_TYPE == "local":
        result["relative_to_base"] = str(utils.PROJECT_DIR.relative_to(utils.BASE_DIR))
        result["exists"] = utils.PROJECT_DIR.exists()
    else:
        # For SSH, we're already connected
        result["ssh_connected"] = SSH_MANAGER.is_connected()
    
    return result


# Main entry point
if __name__ == "__main__":
    args = parse_args()
    print(f"Starting MCP server with transport={args.transport}")
    
    if args.transport == "stdio":
        mcp.run()
    elif args.transport == "http":
        mcp.run(transport="http", port=args.port, host=args.host, path=args.path)
