"""
Shared utilities and configuration for MCP file editor
"""

import os
import sys
from pathlib import Path
from typing import Optional, Dict, Any
import mimetypes
import stat
from datetime import datetime

from .file_operations import FileOperationsInterface, LocalFileOperations
from .ssh_manager import SSHConnectionManager
from .git_operations import GitOperations, LocalGitOperations, SSHGitOperations


# =============================================================================
# Path Normalization Functions
# =============================================================================

def normalize_path(path: Path) -> str:
    """
    Convert a Path object to a normalized string that works across platforms.
    
    This function addresses a cross-platform compatibility issue:
    - On Windows, Path.absolute() returns paths like 'C:\\Users\\...'
    - When these paths are returned by the MCP server and used by clients
      running on different OSes (e.g., Linux), they fail to parse correctly
    
    Solution: Always use forward slashes and prefer relative paths when possible.
    
    Args:
        path: A Path object to convert to string
        
    Returns:
        A normalized path string using forward slashes (e.g., 'src/foo/bar')
    """
    # Convert to string and normalize slashes for cross-platform compatibility
    # This ensures paths work regardless of whether the server runs on
    # Windows, Linux, or macOS
    return str(path).replace(os.sep, '/')


def normalize_absolute_path(path: Path, base_dir: Optional[Path] = None) -> str:
    """
    Convert an absolute path to a normalized cross-platform string.
    
    On Windows, Path.absolute() returns 'C:\\Users\\name\\...'
    On Linux, it returns '/home/name/...'
    
    This function ensures consistent forward-slash output that works
    across all platforms when paths are exchanged between systems.
    
    Args:
        path: A Path object representing an absolute path
        base_dir: Optional base directory to make path relative to
        
    Returns:
        Normalized path string with forward slashes
    """
    if base_dir is not None:
        try:
            # Try to return a relative path first (preferred for cross-platform)
            return normalize_path(path.relative_to(base_dir))
        except ValueError:
            # Path is not relative to base_dir, fall through to absolute
            pass
    
    # Return absolute path with normalized slashes
    return normalize_path(path.absolute())


# =============================================================================
# File Type Classifications
# =============================================================================

# File type classifications
TEXT_EXTENSIONS = {
    '.txt', '.md', '.markdown', '.rst', '.log', '.csv', '.tsv',
    '.json', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf',
    '.xml', '.html', '.htm', '.xhtml', '.css', '.scss', '.sass',
    '.js', '.jsx', '.ts', '.tsx', '.vue', '.svelte',
    '.py', '.pyw', '.pyx', '.pyi', '.pyc',
    '.java', '.kt', '.scala', '.groovy',
    '.c', '.h', '.cpp', '.hpp', '.cc', '.cxx', '.c++',
    '.cs', '.fs', '.vb', '.swift', '.m', '.mm',
    '.go', '.rs', '.zig', '.nim', '.d',
    '.rb', '.php', '.pl', '.pm', '.lua',
    '.sh', '.bash', '.zsh', '.fish', '.ps1', '.bat', '.cmd',
    '.sql', '.r', '.R', '.jl', '.m', '.mat',
    '.tex', '.bib', '.cls', '.sty',
    '.Dockerfile', '.dockerignore', '.gitignore', '.env'
}

BINARY_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.ico', '.webp', '.svg',
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.zip', '.tar', '.gz', '.bz2', '.7z', '.rar',
    '.exe', '.dll', '.so', '.dylib', '.a', '.o',
    '.mp3', '.mp4', '.avi', '.mov', '.wmv', '.flv',
    '.ttf', '.otf', '.woff', '.woff2', '.eot'
}

# Global base directory (current working directory)
BASE_DIR = Path.cwd()

# Global project directory (optional, for project-relative paths)
PROJECT_DIR: Optional[Path] = BASE_DIR

# Global file operations backend and SSH manager
FILE_OPS: FileOperationsInterface = LocalFileOperations()
SSH_MANAGER = SSHConnectionManager()
CONNECTION_TYPE = "local"  # "local" or "ssh"
GIT_OPS: Optional[GitOperations] = None  # Initialized when needed


def is_safe_path(path: Path) -> bool:
    """
    Check if a path is safe to access (no directory traversal).
    
    Security logic:
    - For SSH connections: paths are remote, skip local BASE_DIR check
    - For local connections with PROJECT_DIR set: check against PROJECT_DIR
    - For local connections without PROJECT_DIR: check against BASE_DIR
    """
    # For SSH connections, paths are on remote server - skip local path check
    if CONNECTION_TYPE == "ssh":
        return True
    
    try:
        resolved = path.resolve()
        
        # If PROJECT_DIR is set and is within BASE_DIR, check against PROJECT_DIR
        if PROJECT_DIR and PROJECT_DIR != BASE_DIR:
            try:
                project_resolved = PROJECT_DIR.resolve()
                if project_resolved.is_relative_to(BASE_DIR):
                    return resolved.is_relative_to(project_resolved)
            except (ValueError, RuntimeError):
                pass
        
        # Otherwise check against BASE_DIR
        return resolved.is_relative_to(BASE_DIR)
    except (ValueError, RuntimeError):
        return False


def resolve_path(path: str) -> Path:
    """
    Resolve a path relative to project directory if set, otherwise relative to BASE_DIR.
    
    Args:
        path: Input path (can be relative or absolute)
        
    Returns:
        Resolved Path object
        
    Security:
        - For SSH: absolute paths are allowed (remote paths)
        - For local: absolute paths must be within PROJECT_DIR or BASE_DIR
    """
    path_obj = Path(path)
    
    # If path is absolute
    if path_obj.is_absolute():
        # For SSH connections, return as-is (remote paths)
        if CONNECTION_TYPE == "ssh":
            return path_obj
        
        # For local connections, validate against PROJECT_DIR or BASE_DIR
        try:
            resolved = path_obj.resolve()
            
            # Check against PROJECT_DIR if it's within BASE_DIR
            if PROJECT_DIR and PROJECT_DIR != BASE_DIR:
                try:
                    project_resolved = PROJECT_DIR.resolve()
                    if project_resolved.is_relative_to(BASE_DIR):
                        if resolved.is_relative_to(project_resolved):
                            return path_obj
                        # Not within PROJECT_DIR, try BASE_DIR as fallback
                except (ValueError, RuntimeError):
                    pass
            
            # Check against BASE_DIR
            if resolved.is_relative_to(BASE_DIR):
                return path_obj
            
            # Path escapes BASE_DIR - return anyway but it will fail is_safe_path
            return path_obj
        except (ValueError, RuntimeError):
            return path_obj
    
    # If project directory is set, resolve relative to it
    if PROJECT_DIR:
        return PROJECT_DIR / path
    
    # Otherwise, resolve relative to BASE_DIR
    return BASE_DIR / path


def get_file_type(path: Path) -> str:
    """Determine file type"""
    suffix = path.suffix.lower()
    if suffix in TEXT_EXTENSIONS or path.name in TEXT_EXTENSIONS:
        return "text"
    elif suffix in BINARY_EXTENSIONS:
        return "binary"
    else:
        # Try to detect using mimetypes
        mime_type, _ = mimetypes.guess_type(str(path))
        if mime_type:
            if mime_type.startswith('text/'):
                return "text"
            elif mime_type.startswith(('image/', 'audio/', 'video/', 'application/')):
                return "binary"
        return "unknown"


async def get_file_info_async(path: Path) -> Dict[str, Any]:
    """
    Get detailed file information using the current file operations backend.
    
    Returns normalized cross-platform paths to ensure compatibility when
    the MCP server is used by clients on different operating systems.
    """
    try:
        stat_info = await FILE_OPS.stat(path)
        file_type = get_file_type(path)
        
        info = {
            "name": path.name,
            "path": str(path),
            "type": "directory" if await FILE_OPS.is_dir(path) else "file",
            "size": stat_info.st_size,
            "modified": datetime.fromtimestamp(stat_info.st_mtime).isoformat(),
            "created": datetime.fromtimestamp(stat_info.st_ctime).isoformat(),
            "permissions": stat.filemode(stat_info.st_mode),
            "file_type": file_type
        }
        
        # Cross-platform: use normalized paths instead of platform-specific paths
        # This fixes the issue where Windows paths (C:\...) cause errors on Linux
        if CONNECTION_TYPE == "local":
            info["absolute_path"] = normalize_absolute_path(path, BASE_DIR)
            try:
                info["relative_path"] = normalize_path(path.relative_to(BASE_DIR))
            except ValueError:
                info["relative_path"] = normalize_path(path)
        
        # Add line count for text files
        if file_type == "text" and not await FILE_OPS.is_dir(path):
            try:
                content = await FILE_OPS.read_file(path)
                info["line_count"] = len(content.splitlines())
            except:
                info["line_count"] = None
        
        return info
    except Exception as e:
        return {
            "name": path.name,
            "path": str(path),
            "type": "unknown",
            "error": str(e)
        }


def get_file_info_sync(path: Path) -> Dict[str, Any]:
    """
    Get detailed file information.
    
    Returns normalized cross-platform paths to ensure compatibility when
    the MCP server is used by clients on different operating systems.
    """
    try:
        stat_info = path.stat()
        file_type = get_file_type(path)
        
        # Cross-platform: use normalized paths instead of platform-specific paths
        info = {
            "name": path.name,
            # Return relative path when possible (works best across platforms)
            "path": normalize_absolute_path(path, BASE_DIR),
            # Also provide normalized absolute path
            "absolute_path": normalize_absolute_path(path),
            "type": "directory" if path.is_dir() else "file",
            "size": stat_info.st_size,
            "modified": datetime.fromtimestamp(stat_info.st_mtime).isoformat(),
            "created": datetime.fromtimestamp(stat_info.st_ctime).isoformat(),
            "permissions": stat.filemode(stat_info.st_mode),
            "file_type": file_type
        }
        
        # Add line count for text files
        if file_type == "text" and path.is_file():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    info["line_count"] = sum(1 for _ in f)
            except:
                info["line_count"] = None
                
        return info
    except Exception as e:
        return {
            "name": path.name,
            "error": str(e)
        }


def get_git_operations() -> Optional[GitOperations]:
    """Get or initialize git operations based on current connection type."""
    global GIT_OPS
    
    if GIT_OPS is None and PROJECT_DIR is not None:
        if CONNECTION_TYPE == "ssh":
            git_backend = SSHGitOperations(SSH_MANAGER.connection, SSH_MANAGER.sftp)
        else:
            git_backend = LocalGitOperations()
        
        GIT_OPS = GitOperations(git_backend, FILE_OPS, PROJECT_DIR)
    
    return GIT_OPS
