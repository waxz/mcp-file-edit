"""
Git operations tools for MCP file editor
"""

from pathlib import Path
from typing import Dict, Any, Optional, Union, List

from utils import get_git_operations


# Tool functions that will be registered with FastMCP

async def git_status(
    path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get git repository status.
    
    Args:
        path: Path to check status (defaults to project directory)
        
    Returns:
        Dictionary with repository status information
    """
    git_ops = get_git_operations()
    if not git_ops:
        raise ValueError("No project directory set. Use set_project_directory first.")
    
    work_path = Path(path) if path else None
    return await git_ops.status(work_path)


async def git_init(
    path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Initialize a new git repository.
    
    Args:
        path: Path to initialize repository (defaults to project directory)
        
    Returns:
        Dictionary with initialization result
    """
    git_ops = get_git_operations()
    if not git_ops:
        raise ValueError("No project directory set. Use set_project_directory first.")
    
    work_path = Path(path) if path else None
    return await git_ops.init(work_path)


async def git_clone(
    url: str,
    path: Optional[str] = None,
    branch: Optional[str] = None
) -> Dict[str, Any]:
    """
    Clone a remote git repository.
    
    Args:
        url: Repository URL to clone
        path: Local path to clone into (defaults to project directory)
        branch: Specific branch to clone
        
    Returns:
        Dictionary with clone result
    """
    git_ops = get_git_operations()
    if not git_ops:
        raise ValueError("No project directory set. Use set_project_directory first.")
    
    work_path = Path(path) if path else None
    return await git_ops.clone(url, work_path, branch)


async def git_add(
    files: Union[str, List[str]],
    path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Add files to git staging area.
    
    Args:
        files: File(s) to add (string or list of strings)
        path: Repository path (defaults to project directory)
        
    Returns:
        Dictionary with add result
    """
    git_ops = get_git_operations()
    if not git_ops:
        raise ValueError("No project directory set. Use set_project_directory first.")
    
    work_path = Path(path) if path else None
    return await git_ops.add(files, work_path)


async def git_commit(
    message: str,
    path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Commit staged changes.
    
    Args:
        message: Commit message
        path: Repository path (defaults to project directory)
        
    Returns:
        Dictionary with commit result including commit hash
    """
    git_ops = get_git_operations()
    if not git_ops:
        raise ValueError("No project directory set. Use set_project_directory first.")
    
    work_path = Path(path) if path else None
    return await git_ops.commit(message, work_path)


async def git_push(
    remote: str = "origin",
    branch: Optional[str] = None,
    set_upstream: bool = False,
    path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Push commits to remote repository.
    
    Args:
        remote: Remote name (default: "origin")
        branch: Branch to push (defaults to current branch)
        set_upstream: Set upstream tracking branch
        path: Repository path (defaults to project directory)
        
    Returns:
        Dictionary with push result
    """
    git_ops = get_git_operations()
    if not git_ops:
        raise ValueError("No project directory set. Use set_project_directory first.")
    
    work_path = Path(path) if path else None
    return await git_ops.push(remote, branch, work_path, set_upstream)


async def git_pull(
    remote: str = "origin",
    branch: Optional[str] = None,
    path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Pull changes from remote repository.
    
    Args:
        remote: Remote name (default: "origin")
        branch: Branch to pull (defaults to current branch)
        path: Repository path (defaults to project directory)
        
    Returns:
        Dictionary with pull result
    """
    git_ops = get_git_operations()
    if not git_ops:
        raise ValueError("No project directory set. Use set_project_directory first.")
    
    work_path = Path(path) if path else None
    return await git_ops.pull(remote, branch, work_path)


async def git_log(
    limit: int = 10,
    oneline: bool = True,
    path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get git commit log.
    
    Args:
        limit: Number of commits to show (default: 10)
        oneline: Show in compact format (default: True)
        path: Repository path (defaults to project directory)
        
    Returns:
        Dictionary with commit log
    """
    git_ops = get_git_operations()
    if not git_ops:
        raise ValueError("No project directory set. Use set_project_directory first.")
    
    work_path = Path(path) if path else None
    return await git_ops.log(limit, oneline, work_path)


async def git_branch(
    create: Optional[str] = None,
    delete: Optional[str] = None,
    list_all: bool = False,
    path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Manage git branches.
    
    Args:
        create: Create a new branch with this name
        delete: Delete branch with this name
        list_all: List all branches including remotes
        path: Repository path (defaults to project directory)
        
    Returns:
        Dictionary with branch operation result
    """
    git_ops = get_git_operations()
    if not git_ops:
        raise ValueError("No project directory set. Use set_project_directory first.")
    
    work_path = Path(path) if path else None
    return await git_ops.branch(create, delete, list_all, work_path)


async def git_checkout(
    branch: str,
    create: bool = False,
    path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Checkout a branch or commit.
    
    Args:
        branch: Branch or commit to checkout
        create: Create new branch if it doesn't exist
        path: Repository path (defaults to project directory)
        
    Returns:
        Dictionary with checkout result
    """
    git_ops = get_git_operations()
    if not git_ops:
        raise ValueError("No project directory set. Use set_project_directory first.")
    
    work_path = Path(path) if path else None
    return await git_ops.checkout(branch, create, work_path)


async def git_diff(
    cached: bool = False,
    path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get git diff output.
    
    Args:
        cached: Show staged changes instead of working directory
        path: Repository path (defaults to project directory)
        
    Returns:
        Dictionary with diff output
    """
    git_ops = get_git_operations()
    if not git_ops:
        raise ValueError("No project directory set. Use set_project_directory first.")
    
    work_path = Path(path) if path else None
    return await git_ops.diff(cached, work_path)


async def git_remote(
    action: str = "list",
    name: Optional[str] = None,
    url: Optional[str] = None,
    path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Manage git remotes.
    
    Args:
        action: Action to perform - "list", "add", "remove", "get-url"
        name: Remote name (for add/remove/get-url)
        url: Remote URL (for add)
        path: Repository path (defaults to project directory)
        
    Returns:
        Dictionary with remote operation result
    """
    git_ops = get_git_operations()
    if not git_ops:
        raise ValueError("No project directory set. Use set_project_directory first.")
    
    work_path = Path(path) if path else None
    return await git_ops.remote(action, name, url, work_path)
