"""
Shared utilities and configuration for MCP file editor
"""

from pathlib import Path
from typing import Optional, Dict, Any
import mimetypes
import stat
from datetime import datetime

from file_operations import FileOperationsInterface, LocalFileOperations
from ssh_manager import SSHConnectionManager
from git_operations import GitOperations, LocalGitOperations, SSHGitOperations

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
PROJECT_DIR: Optional[Path] = None

# Global file operations backend and SSH manager
FILE_OPS: FileOperationsInterface = LocalFileOperations()
SSH_MANAGER = SSHConnectionManager()
CONNECTION_TYPE = "local"  # "local" or "ssh"
GIT_OPS: Optional[GitOperations] = None  # Initialized when needed


def is_safe_path(path: Path) -> bool:
    """Check if a path is safe to access (no directory traversal)"""
    try:
        resolved = path.resolve()
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
    """
    path_obj = Path(path)
    
    # If path is absolute, return as-is
    if path_obj.is_absolute():
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
    """Get detailed file information using the current file operations backend"""
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
        
        # Add absolute path for local connections
        if CONNECTION_TYPE == "local":
            info["absolute_path"] = str(path.absolute())
            try:
                info["relative_path"] = str(path.relative_to(BASE_DIR))
            except ValueError:
                info["relative_path"] = str(path)
        
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
    """Get detailed file information"""
    try:
        stat_info = path.stat()
        file_type = get_file_type(path)
        
        info = {
            "name": path.name,
            "path": str(path.relative_to(BASE_DIR)),
            "absolute_path": str(path.absolute()),
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
