"""
File operations tools for MCP file editor
"""

import re
import asyncio
import base64
from pathlib import Path
from typing import List, Dict, Any, Optional, AsyncIterator, Iterator
from datetime import datetime

from file_operations import LocalFileOperations
from utils import (
    FILE_OPS, BASE_DIR, CONNECTION_TYPE, PROJECT_DIR,
    is_safe_path, resolve_path, get_file_type,
    get_file_info_async, get_file_info_sync
)


async def walk_with_depth_async(path: Path, pattern: str, max_depth: Optional[int] = None) -> AsyncIterator[Path]:
    """Walk directory tree with optional depth limit using current file operations backend"""
    import fnmatch
    
    async def _walk(current_path: Path, current_depth: int = 0) -> AsyncIterator[Path]:
        if max_depth is not None and current_depth > max_depth:
            return
        
        try:
            entries = await FILE_OPS.listdir(current_path)
            for entry_name in entries:
                entry_path = current_path / entry_name
                
                if fnmatch.fnmatch(entry_name, pattern):
                    yield entry_path
                
                if await FILE_OPS.is_dir(entry_path):
                    async for subentry in _walk(entry_path, current_depth + 1):
                        yield subentry
        except Exception:
            pass  # Skip inaccessible directories
    
    async for item in _walk(path):
        yield item


def walk_with_depth(path: Path, pattern: str, max_depth: Optional[int] = None) -> Iterator[Path]:
    """
    Walk directory tree with optional depth limit.
    
    Args:
        path: Starting directory
        pattern: File pattern to match
        max_depth: Maximum depth to traverse (None for unlimited)
        
    Yields:
        Matching file paths
    """
    def _walk(current_path: Path, current_depth: int):
        if max_depth is not None and current_depth > max_depth:
            return
            
        try:
            for item in current_path.iterdir():
                if item.is_file() and item.match(pattern):
                    yield item
                elif item.is_dir() and not item.name.startswith('.'):
                    yield from _walk(item, current_depth + 1)
        except (PermissionError, OSError):
            # Skip directories we can't access
            pass
    
    yield from _walk(path, 0)


class FilePatcher:
    """Handles various types of file patching operations"""
    
    @staticmethod
    def apply_line_patch(lines: List[str], patch: Dict[str, Any]) -> tuple[List[str], Dict[str, Any]]:
        """Apply a line-based patch"""
        change_info = {"type": "line", "success": False}
        
        if "line" in patch:
            # Single line replacement
            line_num = patch["line"] - 1  # Convert to 0-based
            if 0 <= line_num < len(lines):
                old_content = lines[line_num].rstrip('\n')
                new_content = patch["content"].rstrip('\n')
                lines[line_num] = new_content + '\n' if lines[line_num].endswith('\n') else new_content
                change_info.update({
                    "line": patch["line"],
                    "old": old_content,
                    "new": new_content,
                    "success": True
                })
        elif "start_line" in patch and "end_line" in patch:
            # Multi-line replacement
            start = patch["start_line"] - 1
            end = patch["end_line"]  # end_line is inclusive, so no -1
            
            if 0 <= start < len(lines) and start < end <= len(lines):
                old_content = [line.rstrip('\n') for line in lines[start:end]]
                new_lines = patch["content"].split('\n')
                
                # Preserve line endings
                for i, new_line in enumerate(new_lines):
                    if i < len(new_lines) - 1 or (start + i < len(lines) and lines[start + i].endswith('\n')):
                        new_lines[i] = new_line + '\n'
                
                lines[start:end] = new_lines
                change_info.update({
                    "start_line": patch["start_line"],
                    "end_line": patch["end_line"],
                    "old": old_content,
                    "new": [line.rstrip('\n') for line in new_lines],
                    "success": True
                })
        
        return lines, change_info
    
    @staticmethod
    def apply_pattern_patch(content: str, patch: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
        """Apply a pattern-based patch"""
        change_info = {"type": "pattern", "success": False}
        
        find_pattern = patch["find"]
        replace_with = patch["replace"]
        occurrence = patch.get("occurrence", None)  # None means all occurrences
        regex = patch.get("regex", False)
        
        if regex:
            pattern = re.compile(find_pattern, re.MULTILINE)
            matches = list(pattern.finditer(content))
            change_info["matches"] = len(matches)
            
            if matches:
                if occurrence is not None:
                    # Replace specific occurrence
                    if 0 < occurrence <= len(matches):
                        match = matches[occurrence - 1]
                        old_text = match.group(0)
                        content = content[:match.start()] + replace_with + content[match.end():]
                        change_info.update({
                            "replaced": 1,
                            "old": old_text,
                            "new": replace_with,
                            "success": True
                        })
                else:
                    # Replace all occurrences
                    old_text = pattern.findall(content)[0] if pattern.findall(content) else ""
                    content, count = pattern.subn(replace_with, content)
                    change_info.update({
                        "replaced": count,
                        "old": old_text,
                        "new": replace_with,
                        "success": count > 0
                    })
        else:
            # Literal string replacement
            occurrences = content.count(find_pattern)
            change_info["matches"] = occurrences
            
            if occurrences > 0:
                if occurrence is not None:
                    # Replace specific occurrence
                    if 0 < occurrence <= occurrences:
                        parts = content.split(find_pattern, occurrence)
                        if len(parts) > occurrence:
                            content = find_pattern.join(parts[:occurrence]) + replace_with + parts[occurrence]
                            change_info.update({
                                "replaced": 1,
                                "old": find_pattern,
                                "new": replace_with,
                                "success": True
                            })
                else:
                    # Replace all occurrences
                    content = content.replace(find_pattern, replace_with)
                    change_info.update({
                        "replaced": occurrences,
                        "old": find_pattern,
                        "new": replace_with,
                        "success": True
                    })
        
        return content, change_info
    
    @staticmethod
    def apply_context_patch(lines: List[str], patch: Dict[str, Any]) -> tuple[List[str], Dict[str, Any]]:
        """Apply a context-based patch"""
        change_info = {"type": "context", "success": False}
        
        context_lines = patch["context"]
        replacement_lines = patch["replace"]
        
        # Normalize line endings for comparison
        context_normalized = [line.rstrip('\n') for line in context_lines]
        lines_normalized = [line.rstrip('\n') for line in lines]
        
        # Find the context in the file
        for i in range(len(lines_normalized) - len(context_normalized) + 1):
            if lines_normalized[i:i + len(context_normalized)] == context_normalized:
                # Found the context, apply the replacement
                old_content = lines[i:i + len(context_normalized)]
                
                # Prepare replacement with proper line endings
                new_lines = []
                for j, new_line in enumerate(replacement_lines):
                    if j < len(old_content) and old_content[j].endswith('\n'):
                        new_lines.append(new_line + '\n' if not new_line.endswith('\n') else new_line)
                    else:
                        new_lines.append(new_line)
                
                lines[i:i + len(context_normalized)] = new_lines
                
                change_info.update({
                    "line_start": i + 1,
                    "line_end": i + len(context_normalized),
                    "old": [line.rstrip('\n') for line in old_content],
                    "new": [line.rstrip('\n') for line in new_lines],
                    "success": True
                })
                break
        
        return lines, change_info
    
    @staticmethod
    def apply_unified_diff_patch(content: str, patch_content: str) -> tuple[str, Dict[str, Any]]:
        """Apply a unified diff format patch"""
        change_info = {"type": "unified_diff", "success": False}
        
        # Parse the unified diff
        original_lines = content.splitlines(keepends=True)
        patch_lines = patch_content.splitlines(keepends=True)
        
        # Simple implementation - for more complex patches, consider using python-patch
        # This is a basic implementation that handles simple unified diffs
        try:
            # Apply the patch (simplified version)
            # In production, you'd want to use a proper patch library
            change_info["message"] = "Unified diff patching requires additional implementation"
            change_info["success"] = False
        except Exception as e:
            change_info["error"] = str(e)
        
        return content, change_info


# Tool functions that will be registered with FastMCP

async def list_files(
    path: str = ".",
    pattern: str = "*",
    recursive: bool = False,
    include_hidden: bool = False,
    max_depth: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    List files and directories.

    Args:
        path: Directory path (default: current directory)
        pattern: Glob pattern for filtering
        recursive: List recursively
        include_hidden: Include hidden files
        max_depth: Maximum depth for recursive listing (None for unlimited)

    Returns:
        List of file/directory information
    """
    target_path = resolve_path(path)
    
    # For local connections, check if path is safe
    if CONNECTION_TYPE == "local" and not is_safe_path(target_path):
        raise ValueError("Invalid path: directory traversal detected")
    
    # Check if path exists
    if not await FILE_OPS.exists(target_path):
        raise ValueError(f"Path does not exist: {path}")
    
    # Verify it's a directory
    if not await FILE_OPS.is_dir(target_path):
        raise ValueError(f"Path is not a directory: {path}")
    
    results = []
    
    if recursive:
        # Use async walk for recursive listing
        async for item in walk_with_depth_async(target_path, pattern, max_depth):
            if not include_hidden and item.name.startswith('.'):
                continue
            info = await get_file_info_async(item)
            results.append(info)
    else:
        # List directory contents
        entries = await FILE_OPS.listdir(target_path)
        import fnmatch
        
        for entry_name in entries:
            if not include_hidden and entry_name.startswith('.'):
                continue
            
            if fnmatch.fnmatch(entry_name, pattern):
                entry_path = target_path / entry_name
                info = await get_file_info_async(entry_path)
                results.append(info)
            
    return results


async def read_file(
    path: str,
    encoding: str = "utf-8",
    start_line: Optional[int] = None,
    end_line: Optional[int] = None
) -> Dict[str, Any]:
    """
    Read file contents.

    Args:
        path: File path
        encoding: File encoding (default: utf-8)
        start_line: Starting line number (1-based)
        end_line: Ending line number (inclusive)

    Returns:
        Dictionary with content, encoding, and file_type
    """
    file_path = resolve_path(path)
    
    # For local connections, check if path is safe
    if CONNECTION_TYPE == "local" and not is_safe_path(file_path):
        raise ValueError("Invalid path: directory traversal detected")
    
    # Check if file exists
    if not await FILE_OPS.exists(file_path):
        raise ValueError(f"File does not exist: {path}")
    
    # Verify it's a file
    if not await FILE_OPS.is_file(file_path):
        raise ValueError(f"Not a file: {path}")
    
    file_type = get_file_type(file_path)
    
    if file_type == "binary":
        # Read binary file and encode as base64
        content_bytes = await FILE_OPS.read_binary(file_path)
        content = base64.b64encode(content_bytes).decode('ascii')
        return {
            "content": content,
            "encoding": "base64",
            "file_type": "binary"
        }
    else:
        # Read text file
        content = await FILE_OPS.read_file(file_path, encoding=encoding)
        
        if start_line is not None or end_line is not None:
            lines = content.splitlines(keepends=True)
            start_idx = (start_line - 1) if start_line else 0
            end_idx = end_line if end_line else len(lines)
            content = ''.join(lines[start_idx:end_idx])
                
        return {
            "content": content,
            "encoding": encoding,
            "file_type": "text"
        }


async def write_file(
    path: str,
    content: str,
    encoding: str = "utf-8",
    create_dirs: bool = False
) -> Dict[str, Any]:
    """
    Write content to a file.

    Args:
        path: File path
        content: Content to write
        encoding: File encoding (default: utf-8, or 'base64' for binary)
        create_dirs: Create parent directories if needed

    Returns:
        Dictionary with path and size
    """
    file_path = resolve_path(path)
    
    # For local connections, check if path is safe
    if CONNECTION_TYPE == "local" and not is_safe_path(file_path):
        raise ValueError("Invalid path: directory traversal detected")
    
    # Create parent directories if requested
    if create_dirs:
        await FILE_OPS.makedirs(file_path.parent, exist_ok=True)
    
    # Write content
    if encoding == "base64":
        # Decode base64 and write as binary
        content_bytes = base64.b64decode(content)
        await FILE_OPS.write_file(file_path, content_bytes)
    else:
        # Write as text
        await FILE_OPS.write_file(file_path, content, encoding=encoding)
    
    # Get file info
    stat_info = await FILE_OPS.stat(file_path)
    
    result = {
        "path": str(file_path),
        "size": stat_info.st_size
    }
    
    # Add relative path for local connections
    if CONNECTION_TYPE == "local":
        try:
            result["relative_path"] = str(file_path.relative_to(BASE_DIR))
        except ValueError:
            result["relative_path"] = str(file_path)
    
    return result


async def create_file(
    path: str,
    content: str = "",
    create_dirs: bool = False
) -> Dict[str, Any]:
    """
    Create a new file.

    Args:
        path: File path
        content: Initial content (supports multi-line strings)
        create_dirs: Create parent directories if needed

    Returns:
        File information
    """
    file_path = resolve_path(path)
    
    # For local connections, check if path is safe
    if CONNECTION_TYPE == "local" and not is_safe_path(file_path):
        raise ValueError("Invalid path: directory traversal detected")
    
    # Check if file already exists
    if await FILE_OPS.exists(file_path):
        raise ValueError(f"File already exists: {path}")
    
    # Create parent directories if requested
    if create_dirs:
        await FILE_OPS.makedirs(file_path.parent, exist_ok=True)
    
    # Create the file with content
    await FILE_OPS.write_file(file_path, content, encoding='utf-8')
    
    # Return file info
    return await get_file_info_async(file_path)


async def delete_file(
    path: str,
    recursive: bool = False
) -> Dict[str, str]:
    """
    Delete a file or directory.

    Args:
        path: File or directory path
        recursive: Delete directories recursively

    Returns:
        Dictionary with deleted path
    """
    target_path = resolve_path(path)
    
    # For local connections, check if path is safe
    if CONNECTION_TYPE == "local" and not is_safe_path(target_path):
        raise ValueError("Invalid path: directory traversal detected")
    
    # Check if path exists
    if not await FILE_OPS.exists(target_path):
        raise ValueError(f"Path does not exist: {path}")
    
    # Delete based on type
    if await FILE_OPS.is_dir(target_path):
        if recursive:
            await FILE_OPS.rmtree(target_path)
        else:
            # For non-recursive directory deletion, check if empty
            entries = await FILE_OPS.listdir(target_path)
            if entries:
                raise ValueError(f"Directory not empty: {path}. Use recursive=True to delete non-empty directories.")
            await FILE_OPS.remove(target_path)
    else:
        await FILE_OPS.remove(target_path)
    
    result = {"deleted": str(target_path)}
    
    # Add relative path for local connections
    if CONNECTION_TYPE == "local":
        try:
            result["deleted_relative"] = str(target_path.relative_to(BASE_DIR))
        except ValueError:
            pass
    
    return result


async def move_file(
    source: str,
    destination: str,
    overwrite: bool = False
) -> Dict[str, str]:
    """
    Move or rename a file.

    Args:
        source: Source path
        destination: Destination path
        overwrite: Overwrite if exists

    Returns:
        Dictionary with source and destination paths
    """
    source_path = resolve_path(source)
    dest_path = resolve_path(destination)
    
    # For local connections, check if paths are safe
    if CONNECTION_TYPE == "local":
        if not is_safe_path(source_path) or not is_safe_path(dest_path):
            raise ValueError("Invalid path: directory traversal detected")
    
    # Check if source exists
    if not await FILE_OPS.exists(source_path):
        raise ValueError(f"Source does not exist: {source}")
    
    # Check destination
    if await FILE_OPS.exists(dest_path) and not overwrite:
        raise ValueError(f"Destination already exists: {destination}")
    
    # Perform the move/rename
    await FILE_OPS.rename(source_path, dest_path)
    
    result = {
        "source": str(source_path),
        "destination": str(dest_path)
    }
    
    # Add relative paths for local connections
    if CONNECTION_TYPE == "local":
        try:
            result["source_relative"] = str(source_path.relative_to(BASE_DIR))
            result["destination_relative"] = str(dest_path.relative_to(BASE_DIR))
        except ValueError:
            pass
    
    return result


async def copy_file(
    source: str,
    destination: str,
    overwrite: bool = False
) -> Dict[str, str]:
    """
    Copy a file or directory.

    Args:
        source: Source path
        destination: Destination path
        overwrite: Overwrite if exists

    Returns:
        Dictionary with source and destination paths
    """
    source_path = resolve_path(source)
    dest_path = resolve_path(destination)
    
    # For local connections, check if paths are safe
    if CONNECTION_TYPE == "local":
        if not is_safe_path(source_path) or not is_safe_path(dest_path):
            raise ValueError("Invalid path: directory traversal detected")
    
    # Check if source exists
    if not await FILE_OPS.exists(source_path):
        raise ValueError(f"Source does not exist: {source}")
    
    # Check destination
    if await FILE_OPS.exists(dest_path) and not overwrite:
        raise ValueError(f"Destination already exists: {destination}")
    
    # Copy based on type
    if await FILE_OPS.is_dir(source_path):
        await FILE_OPS.copy_tree(source_path, dest_path)
    else:
        await FILE_OPS.copy_file(source_path, dest_path)
    
    result = {
        "source": str(source_path),
        "destination": str(dest_path)
    }
    
    # Add relative paths for local connections
    if CONNECTION_TYPE == "local":
        try:
            result["source_relative"] = str(source_path.relative_to(BASE_DIR))
            result["destination_relative"] = str(dest_path.relative_to(BASE_DIR))
        except ValueError:
            pass
    
    return result


async def search_files(
    pattern: str,
    path: str = ".",
    file_pattern: str = "*",
    recursive: bool = True,
    max_depth: Optional[int] = None,
    timeout: float = 30.0
) -> Dict[str, Any]:
    """
    Search for patterns in files with timeout and depth control.

    Args:
        pattern: Search pattern (regex)
        path: Directory to search in
        file_pattern: File name pattern
        recursive: Search recursively
        max_depth: Maximum depth for recursive search (None for unlimited)
        timeout: Maximum time in seconds for search operation

    Returns:
        Dictionary containing search results and statistics
    """
    search_path = resolve_path(path)
    
    # For local connections, check if path is safe
    if CONNECTION_TYPE == "local" and not is_safe_path(search_path):
        return {
            "results": [],
            "completed": False,
            "files_searched": 0,
            "timeout_occurred": False,
            "error": "Invalid path: directory traversal detected"
        }
        
    regex = re.compile(pattern)
    results = []
    files_searched = 0
    timeout_occurred = False
    error = None
    
    async def _search():
        nonlocal files_searched
        
        # Check if search_path exists
        if not await FILE_OPS.exists(search_path):
            raise ValueError(f"Path does not exist: {path}")
        
        files_to_search = []
        
        if await FILE_OPS.is_file(search_path):
            files_to_search = [search_path]
        else:
            if recursive:
                # Use async walk for file discovery
                async for item in walk_with_depth_async(search_path, file_pattern, max_depth):
                    if await FILE_OPS.is_file(item):
                        files_to_search.append(item)
            else:
                # List directory and filter
                import fnmatch
                entries = await FILE_OPS.listdir(search_path)
                for entry_name in entries:
                    if fnmatch.fnmatch(entry_name, file_pattern):
                        entry_path = search_path / entry_name
                        if await FILE_OPS.is_file(entry_path):
                            files_to_search.append(entry_path)
                
        for file_path in files_to_search:
            # Check if we should yield control periodically
            if files_searched % 100 == 0:
                await asyncio.sleep(0)  # Allow other tasks to run
                
            file_type = get_file_type(file_path)
            if file_type != "text":
                continue
                
            matches = []
            try:
                # Read file content
                content = await FILE_OPS.read_file(file_path, encoding='utf-8')
                
                # Search line by line
                for line_num, line in enumerate(content.splitlines(), 1):
                    if regex.search(line):
                        match = regex.search(line)
                        matches.append({
                            "line_number": line_num,
                            "line": line.rstrip(),
                            "column": match.start() if match else 0
                        })
                            
                files_searched += 1
            except Exception:
                continue
                
            if matches:
                file_result = {"file": str(file_path)}
                
                # Add relative path for local connections
                if CONNECTION_TYPE == "local":
                    try:
                        file_result["file_relative"] = str(file_path.relative_to(BASE_DIR))
                    except ValueError:
                        pass
                
                file_result["matches"] = matches
                results.append(file_result)
    
    try:
        # Run search with timeout
        await asyncio.wait_for(_search(), timeout=timeout)
        completed = True
    except asyncio.TimeoutError:
        timeout_occurred = True
        completed = False
        error = f"Search timed out after {timeout} seconds. Partial results returned."
    except Exception as e:
        completed = False
        error = str(e)
    
    return {
        "results": results,
        "completed": completed,
        "files_searched": files_searched,
        "timeout_occurred": timeout_occurred,
        "error": error
    }


async def replace_in_files(
    search: str,
    replace: str,
    path: str = ".",
    file_pattern: str = "*",
    recursive: bool = True,
    max_depth: Optional[int] = None,
    timeout: float = 30.0
) -> Dict[str, Any]:
    """
    Replace text in files with timeout and depth control.

    Args:
        search: Search pattern (regex)
        replace: Replacement text
        path: Directory or file path
        file_pattern: File name pattern
        recursive: Search recursively
        max_depth: Maximum depth for recursive search (None for unlimited)
        timeout: Maximum time in seconds for operation

    Returns:
        Dictionary with replacement results
    """
    search_path = resolve_path(path)
    
    # For local connections, check if path is safe
    if CONNECTION_TYPE == "local" and not is_safe_path(search_path):
        return {
            "results": [],
            "completed": False,
            "files_processed": 0,
            "timeout_occurred": False,
            "error": "Invalid path: directory traversal detected"
        }
        
    regex = re.compile(search)
    results = []
    files_processed = 0
    timeout_occurred = False
    error = None
    
    async def _replace():
        nonlocal files_processed
        
        # Check if search_path exists
        if not await FILE_OPS.exists(search_path):
            raise ValueError(f"Path does not exist: {path}")
        
        files_to_process = []
        
        if await FILE_OPS.is_file(search_path):
            files_to_process = [search_path]
        else:
            if recursive:
                # Use async walk for file discovery
                async for item in walk_with_depth_async(search_path, file_pattern, max_depth):
                    if await FILE_OPS.is_file(item):
                        files_to_process.append(item)
            else:
                # List directory and filter
                import fnmatch
                entries = await FILE_OPS.listdir(search_path)
                for entry_name in entries:
                    if fnmatch.fnmatch(entry_name, file_pattern):
                        entry_path = search_path / entry_name
                        if await FILE_OPS.is_file(entry_path):
                            files_to_process.append(entry_path)
                
        for file_path in files_to_process:
            if files_processed % 50 == 0:
                await asyncio.sleep(0)
                
            file_type = get_file_type(file_path)
            if file_type != "text":
                continue
                
            try:
                # Read file content
                content = await FILE_OPS.read_file(file_path, encoding='utf-8')
                
                # Perform replacements
                new_content, count = regex.subn(replace, content)
                
                if count > 0:
                    # Write back the modified content
                    await FILE_OPS.write_file(file_path, new_content, encoding='utf-8')
                    
                    file_result = {"file": str(file_path), "replacements": count}
                    
                    # Add relative path for local connections
                    if CONNECTION_TYPE == "local":
                        try:
                            file_result["file_relative"] = str(file_path.relative_to(BASE_DIR))
                        except ValueError:
                            pass
                    
                    results.append(file_result)
                    
                files_processed += 1
            except Exception:
                continue
    
    try:
        await asyncio.wait_for(_replace(), timeout=timeout)
        completed = True
    except asyncio.TimeoutError:
        timeout_occurred = True
        completed = False
        error = f"Replace operation timed out after {timeout} seconds. Partial results returned."
    except Exception as e:
        completed = False
        error = str(e)
    
    return {
        "results": results,
        "completed": completed,
        "files_processed": files_processed,
        "timeout_occurred": timeout_occurred,
        "error": error
    }


async def patch_file(
    path: str,
    patches: List[Dict[str, Any]],
    backup: bool = True,
    dry_run: bool = False,
    create_dirs: bool = False
) -> Dict[str, Any]:
    """
    Apply patches to a file.

    Args:
        path: File path to patch
        patches: List of patch operations to apply
        backup: Create a backup before patching
        dry_run: Preview changes without applying them
        create_dirs: Create parent directories if needed

    Returns:
        Dict with success status, patches applied, backup path, and change details
    """
    file_path = resolve_path(path)
    
    # For local connections, check if path is safe
    if CONNECTION_TYPE == "local" and not is_safe_path(file_path):
        return {
            "success": False,
            "error": "Invalid path: directory traversal detected",
            "patches_applied": 0
        }
    
    # Check if file exists
    if not await FILE_OPS.exists(file_path):
        if create_dirs and patches:
            await FILE_OPS.makedirs(file_path.parent, exist_ok=True)
            await FILE_OPS.write_file(file_path, "", encoding='utf-8')
        else:
            return {
                "success": False,
                "error": f"File does not exist: {path}",
                "patches_applied": 0
            }
    
    # Check if file is text
    file_type = get_file_type(file_path)
    if file_type != "text":
        return {
            "success": False,
            "error": f"Cannot patch binary file: {path}",
            "patches_applied": 0
        }
    
    # Read the file
    try:
        original_content = await FILE_OPS.read_file(file_path, encoding='utf-8')
        lines = original_content.splitlines(keepends=True)
    except Exception as e:
        return {
            "success": False,
            "error": f"Error reading file: {str(e)}",
            "patches_applied": 0
        }
    
    # Create backup if requested
    backup_path = None
    if backup and not dry_run:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = file_path.parent / f"{file_path.name}.backup_{timestamp}"
        try:
            await FILE_OPS.write_file(backup_path, original_content, encoding='utf-8')
        except Exception as e:
            return {
                "success": False,
                "error": f"Error creating backup: {str(e)}",
                "patches_applied": 0
            }
    
    # Apply patches
    patcher = FilePatcher()
    changes = []
    patches_applied = 0
    content = original_content
    
    for i, patch in enumerate(patches):
        try:
            if "line" in patch or "start_line" in patch:
                # Line-based patch
                lines, change_info = patcher.apply_line_patch(lines, patch)
                if change_info["success"]:
                    patches_applied += 1
                    content = ''.join(lines)
                changes.append(change_info)
                
            elif "find" in patch:
                # Pattern-based patch
                content, change_info = patcher.apply_pattern_patch(content, patch)
                if change_info["success"]:
                    patches_applied += 1
                    lines = content.splitlines(keepends=True)
                changes.append(change_info)
                
            elif "context" in patch:
                # Context-based patch
                lines, change_info = patcher.apply_context_patch(lines, patch)
                if change_info["success"]:
                    patches_applied += 1
                    content = ''.join(lines)
                changes.append(change_info)
                
            elif "unified_diff" in patch:
                # Unified diff patch
                content, change_info = patcher.apply_unified_diff_patch(content, patch["unified_diff"])
                if change_info["success"]:
                    patches_applied += 1
                    lines = content.splitlines(keepends=True)
                changes.append(change_info)
                
            else:
                changes.append({
                    "type": "unknown",
                    "success": False,
                    "error": f"Unknown patch type in patch {i+1}"
                })
                
        except Exception as e:
            changes.append({
                "type": "error",
                "success": False,
                "error": f"Error in patch {i+1}: {str(e)}"
            })
    
    # Write the file if not dry run and at least one patch succeeded
    if not dry_run and patches_applied > 0:
        try:
            await FILE_OPS.write_file(file_path, content, encoding='utf-8')
        except Exception as e:
            return {
                "success": False,
                "error": f"Error writing file: {str(e)}",
                "patches_applied": patches_applied,
                "changes": changes
            }
    
    return {
        "success": patches_applied > 0,
        "patches_applied": patches_applied,
        "patches_total": len(patches),
        "backup_path": str(backup_path) if backup_path else None,
        "changes": changes,
        "dry_run": dry_run
    }


async def get_file_info(path: str) -> Dict[str, Any]:
    """
    Get detailed file information.

    Args:
        path: File path

    Returns:
        Detailed file information
    """
    file_path = resolve_path(path)
    
    # For local connections, check if path is safe
    if CONNECTION_TYPE == "local" and not is_safe_path(file_path):
        raise ValueError("Invalid path: directory traversal detected")
    
    # Check if path exists
    if not await FILE_OPS.exists(file_path):
        raise ValueError(f"Path does not exist: {path}")
    
    return await get_file_info_async(file_path)
