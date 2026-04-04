"""
File operations tools for MCP file editor
"""

import re
import asyncio
import base64
from pathlib import Path
from typing import List, Dict, Any, Optional, AsyncIterator, Iterator
from datetime import datetime
from dataclasses import dataclass, field

from . import utils


async def walk_with_depth_async(path: Path, pattern: str, max_depth: Optional[int] = None) -> AsyncIterator[Path]:
    """Walk directory tree with optional depth limit using current file operations backend"""
    import fnmatch
    
    async def _walk(current_path: Path, current_depth: int = 0) -> AsyncIterator[Path]:
        if max_depth is not None and current_depth > max_depth:
            return
        
        try:
            entries = await utils.FILE_OPS.listdir(current_path)
            for entry_name in entries:
                entry_path = current_path / entry_name
                
                if fnmatch.fnmatch(entry_name, pattern):
                    yield entry_path
                
                if await utils.FILE_OPS.is_dir(entry_path):
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
                old_content = lines[i:i + len(context_normalized)]
                
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
        """Apply a minimal unified diff hunk to content."""
        change_info = {"type": "unified_diff", "success": False}
        patch_lines = patch_content.splitlines()
        hunks: List[PatchHunk] = []
        current_hunk: Optional[PatchHunk] = None

        for line in patch_lines:
            if line.startswith(("--- ", "+++ ")):
                continue
            if line.startswith("@@"):
                if current_hunk and current_hunk.lines:
                    hunks.append(current_hunk)
                current_hunk = PatchHunk()
                continue
            if line == "*** End of File":
                if current_hunk is None:
                    current_hunk = PatchHunk()
                current_hunk.no_newline_at_end = True
                continue
            if line[:1] in {" ", "+", "-"}:
                if current_hunk is None:
                    current_hunk = PatchHunk()
                current_hunk.lines.append(line)

        if current_hunk and current_hunk.lines:
            hunks.append(current_hunk)

        if not hunks:
            change_info["error"] = "Unified diff contained no hunks"
            return content, change_info

        try:
            updated = ApplyPatchExecutor._apply_update_hunks(content, hunks)
        except Exception as exc:
            change_info["error"] = str(exc)
            return content, change_info

        change_info["success"] = True
        change_info["hunks"] = len(hunks)
        return updated, change_info


@dataclass
class PatchHunk:
    lines: List[str] = field(default_factory=list)
    no_newline_at_end: bool = False


@dataclass
class PatchOperation:
    kind: str
    path: str
    hunks: List[PatchHunk] = field(default_factory=list)
    move_to: Optional[str] = None


class ApplyPatchParser:
    """Parse a Codex-style apply_patch payload."""

    BEGIN_MARKER = "*** Begin Patch"
    END_MARKER = "*** End Patch"
    ADD_FILE = "*** Add File: "
    DELETE_FILE = "*** Delete File: "
    UPDATE_FILE = "*** Update File: "
    MOVE_TO = "*** Move to: "
    END_OF_FILE = "*** End of File"

    @classmethod
    def parse(cls, patch_text: str) -> List[PatchOperation]:
        lines = patch_text.splitlines()
        if not lines or lines[0] != cls.BEGIN_MARKER:
            raise ValueError("Patch must start with '*** Begin Patch'")
        if len(lines) < 2 or lines[-1] != cls.END_MARKER:
            raise ValueError("Patch must end with '*** End Patch'")

        operations: List[PatchOperation] = []
        index = 1

        while index < len(lines) - 1:
            line = lines[index]
            if line.startswith(cls.ADD_FILE):
                path = line[len(cls.ADD_FILE) :]
                index += 1
                hunk = PatchHunk()
                while index < len(lines) - 1 and not lines[index].startswith(
                    ("*** Add File: ", "*** Delete File: ", "*** Update File: ")
                ):
                    if lines[index] == cls.END_OF_FILE:
                        hunk.no_newline_at_end = True
                        index += 1
                        continue
                    if not lines[index].startswith("+"):
                        raise ValueError(f"Add File lines must start with '+': {lines[index]}")
                    hunk.lines.append(lines[index][1:])
                    index += 1
                operations.append(
                    PatchOperation(kind="add", path=path, hunks=[hunk])
                )
                continue

            if line.startswith(cls.DELETE_FILE):
                path = line[len(cls.DELETE_FILE) :]
                operations.append(PatchOperation(kind="delete", path=path))
                index += 1
                continue

            if line.startswith(cls.UPDATE_FILE):
                path = line[len(cls.UPDATE_FILE) :]
                index += 1
                operation = PatchOperation(kind="update", path=path)

                if index < len(lines) - 1 and lines[index].startswith(cls.MOVE_TO):
                    operation.move_to = lines[index][len(cls.MOVE_TO) :]
                    index += 1

                current_hunk: Optional[PatchHunk] = None
                while index < len(lines) - 1:
                    current_line = lines[index]
                    if current_line.startswith(("*** Add File: ", "*** Delete File: ", "*** Update File: ")):
                        break
                    if current_line == cls.END_OF_FILE:
                        if current_hunk is None:
                            current_hunk = PatchHunk()
                        current_hunk.no_newline_at_end = True
                        index += 1
                        continue
                    if current_line.startswith("@@"):
                        if current_hunk and current_hunk.lines:
                            operation.hunks.append(current_hunk)
                        current_hunk = PatchHunk()
                        index += 1
                        continue
                    if current_line[:1] in {" ", "+", "-"}:
                        if current_hunk is None:
                            current_hunk = PatchHunk()
                        current_hunk.lines.append(current_line)
                        index += 1
                        continue
                    raise ValueError(f"Unexpected patch line: {current_line}")

                if current_hunk and current_hunk.lines:
                    operation.hunks.append(current_hunk)

                if not operation.hunks and not operation.move_to:
                    raise ValueError(f"Update File has no hunks: {path}")

                operations.append(operation)
                continue

            raise ValueError(f"Unknown patch operation: {line}")

        return operations


class ApplyPatchExecutor:
    """Execute a parsed apply_patch payload against the current file backend."""

    @staticmethod
    def _match_at(lines: List[str], start: int, needle: List[str]) -> bool:
        if start < 0 or start + len(needle) > len(lines):
            return False
        return lines[start : start + len(needle)] == needle

    @classmethod
    def _find_chunk_start(
        cls, lines: List[str], needle: List[str], start_index: int
    ) -> int:
        if not needle:
            return start_index
        for index in range(start_index, len(lines) - len(needle) + 1):
            if cls._match_at(lines, index, needle):
                return index
        raise ValueError("Failed to locate patch context in target file")

    @classmethod
    def _apply_update_hunks(cls, original_content: str, hunks: List[PatchHunk]) -> str:
        original_lines = original_content.splitlines()
        original_had_newline = original_content.endswith("\n")
        result_lines: List[str] = []
        cursor = 0

        for hunk in hunks:
            old_chunk = [line[1:] for line in hunk.lines if line[:1] in {" ", "-"}]
            new_chunk = [line[1:] for line in hunk.lines if line[:1] in {" ", "+"}]

            chunk_start = cls._find_chunk_start(original_lines, old_chunk, cursor)
            result_lines.extend(original_lines[cursor:chunk_start])
            result_lines.extend(new_chunk)
            cursor = chunk_start + len(old_chunk)

        result_lines.extend(original_lines[cursor:])

        new_content = "\n".join(result_lines)
        final_hunk_has_no_newline = bool(hunks and hunks[-1].no_newline_at_end)
        if result_lines and original_had_newline and not final_hunk_has_no_newline:
            new_content += "\n"
        return new_content


async def apply_patch(
    patch: str,
    backup: bool = True,
    dry_run: bool = False,
    create_dirs: bool = False,
) -> Dict[str, Any]:
    """
    Apply a Codex-style multi-file patch.

    The patch format matches the common `*** Begin Patch` / `*** End Patch`
    envelope with `Add File`, `Delete File`, and `Update File` operations.
    """
    operations = ApplyPatchParser.parse(patch)
    changes: List[Dict[str, Any]] = []
    adds = updates = deletes = moves = 0

    for operation in operations:
        target_path = utils.resolve_path(operation.path)
        if utils.CONNECTION_TYPE == "local" and not utils.is_safe_path(target_path):
            raise ValueError(f"Invalid path: directory traversal detected: {operation.path}")

        if operation.kind == "add":
            if await utils.FILE_OPS.exists(target_path):
                raise ValueError(f"Cannot add file that already exists: {operation.path}")
            if create_dirs:
                await utils.FILE_OPS.makedirs(target_path.parent, exist_ok=True)
            elif not await utils.FILE_OPS.exists(target_path.parent):
                raise ValueError(f"Parent directory does not exist: {target_path.parent}")

            content = "\n".join(operation.hunks[0].lines)
            if content and not operation.hunks[0].no_newline_at_end:
                content += "\n"

            if not dry_run:
                await utils.FILE_OPS.write_file(target_path, content, encoding="utf-8")

            adds += 1
            changes.append({"type": "add", "path": str(target_path), "success": True})
            continue

        if operation.kind == "delete":
            if not await utils.FILE_OPS.exists(target_path):
                raise ValueError(f"Cannot delete missing file: {operation.path}")
            if await utils.FILE_OPS.is_dir(target_path):
                raise ValueError(f"apply_patch only deletes files, not directories: {operation.path}")
            backup_path = None
            if backup and not dry_run:
                original_content = await utils.FILE_OPS.read_file(target_path, encoding="utf-8")
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_path = target_path.parent / f"{target_path.name}.backup_{timestamp}"
                await utils.FILE_OPS.write_file(backup_path, original_content, encoding="utf-8")
            if not dry_run:
                await utils.FILE_OPS.remove(target_path)
            deletes += 1
            change: Dict[str, Any] = {"type": "delete", "path": str(target_path), "success": True}
            if backup_path is not None:
                change["backup_path"] = str(backup_path)
            changes.append(change)
            continue

        if operation.kind != "update":
            raise ValueError(f"Unsupported apply_patch operation: {operation.kind}")

        if not await utils.FILE_OPS.exists(target_path):
            raise ValueError(f"Cannot update missing file: {operation.path}")

        original_content = await utils.FILE_OPS.read_file(target_path, encoding="utf-8")
        updated_content = (
            ApplyPatchExecutor._apply_update_hunks(original_content, operation.hunks)
            if operation.hunks
            else original_content
        )

        backup_path = None
        if backup and not dry_run:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = target_path.parent / f"{target_path.name}.backup_{timestamp}"
            await utils.FILE_OPS.write_file(backup_path, original_content, encoding="utf-8")

        write_path = target_path
        if operation.move_to:
            write_path = utils.resolve_path(operation.move_to)
            if utils.CONNECTION_TYPE == "local" and not utils.is_safe_path(write_path):
                raise ValueError(f"Invalid path: directory traversal detected: {operation.move_to}")
            if await utils.FILE_OPS.exists(write_path) and write_path != target_path:
                raise ValueError(f"Destination already exists: {operation.move_to}")
            if create_dirs:
                await utils.FILE_OPS.makedirs(write_path.parent, exist_ok=True)
            elif not await utils.FILE_OPS.exists(write_path.parent):
                raise ValueError(f"Parent directory does not exist: {write_path.parent}")

        if not dry_run:
            await utils.FILE_OPS.write_file(write_path, updated_content, encoding="utf-8")
            if operation.move_to and write_path != target_path:
                await utils.FILE_OPS.remove(target_path)

        updates += 1
        change: Dict[str, Any] = {
            "type": "update",
            "path": str(target_path),
            "success": True,
        }
        if backup_path is not None:
            change["backup_path"] = str(backup_path)
        if operation.move_to:
            change["moved_to"] = str(write_path)
            moves += 1
        changes.append(change)

    return {
        "success": True,
        "operations_applied": len(changes),
        "adds": adds,
        "updates": updates,
        "deletes": deletes,
        "moves": moves,
        "changes": changes,
        "dry_run": dry_run,
    }


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
    target_path = utils.resolve_path(path)
    
    # For local connections, check if path is safe
    if utils.CONNECTION_TYPE == "local" and not utils.is_safe_path(target_path):
        raise ValueError("Invalid path: directory traversal detected")
    
    # Check if path exists
    if not await utils.FILE_OPS.exists(target_path):
        raise ValueError(f"Path does not exist: {path}")
    
    # Verify it's a directory
    if not await utils.FILE_OPS.is_dir(target_path):
        raise ValueError(f"Path is not a directory: {path}")
    
    results = []
    
    if recursive:
        # Use async walk for recursive listing
        async for item in walk_with_depth_async(target_path, pattern, max_depth):
            if not include_hidden and item.name.startswith('.'):
                continue
            info = await utils.get_file_info_async(item)
            results.append(info)
    else:
        # List directory contents
        entries = await utils.FILE_OPS.listdir(target_path)
        import fnmatch
        
        for entry_name in entries:
            if not include_hidden and entry_name.startswith('.'):
                continue
            
            if fnmatch.fnmatch(entry_name, pattern):
                entry_path = target_path / entry_name
                info = await utils.get_file_info_async(entry_path)
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
    file_path = utils.resolve_path(path)
    
    # For local connections, check if path is safe
    if utils.CONNECTION_TYPE == "local" and not utils.is_safe_path(file_path):
        raise ValueError("Invalid path: directory traversal detected")
    
    # Check if file exists
    if not await utils.FILE_OPS.exists(file_path):
        raise ValueError(f"File does not exist: {path}, file_path: {file_path}")
    
    # Verify it's a file
    if not await utils.FILE_OPS.is_file(file_path):
        raise ValueError(f"Not a file: {path}, file_path: {file_path}")
    
    file_type = utils.get_file_type(file_path)
    
    if file_type == "binary":
        # Read binary file and encode as base64
        content_bytes = await utils.FILE_OPS.read_binary(file_path)
        content = base64.b64encode(content_bytes).decode('ascii')
        return {
            "content": content,
            "encoding": "base64",
            "file_type": "binary"
        }
    else:
        # Read text file
        content = await utils.FILE_OPS.read_file(file_path, encoding=encoding)
        
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
    file_path = utils.resolve_path(path)
    
    # For local connections, check if path is safe
    if utils.CONNECTION_TYPE == "local" and not utils.is_safe_path(file_path):
        raise ValueError("Invalid path: directory traversal detected")
    
    # Create parent directories if requested
    if create_dirs:
        await utils.FILE_OPS.makedirs(file_path.parent, exist_ok=True)
    
    # Write content
    if encoding == "base64":
        # Decode base64 and write as binary
        content_bytes = base64.b64decode(content)
        await utils.FILE_OPS.write_file(file_path, content_bytes)
    else:
        # Write as text
        await utils.FILE_OPS.write_file(file_path, content, encoding=encoding)
    
    # Get file info
    stat_info = await utils.FILE_OPS.stat(file_path)
    
    result = {
        "path": str(file_path),
        "size": stat_info.st_size
    }
    
    # Add relative path for local connections
    if utils.CONNECTION_TYPE == "local":
        try:
            result["relative_path"] = str(file_path.relative_to(utils.PROJECT_DIR))
        except ValueError:
            result["relative_path"] = str(file_path)
    
    return result
async def remove_directory(path:str):
    """
    Remove a directory.

    """
    dir_path = utils.resolve_path(path)
    
    # For local connections, check if path is safe
    if utils.CONNECTION_TYPE == "local" and not utils.is_safe_path(dir_path):
        raise ValueError("Invalid path: directory traversal detected")
    
    # Check if directory already exists
    if await utils.FILE_OPS.exists(dir_path):
        await utils.FILE_OPS.rmtree(dir_path)
    else:
        raise ValueError(f"Directory not exists: {path}")

    return True



async def create_directory(
    path: str,
    create_dirs: bool = False
) -> Dict[str, Any]:
    """
    Create a new directory.

    Args:
        path: Directory path
        create_dirs: Create parent directories if needed

    Returns:
        Directory information
    """
    dir_path = utils.resolve_path(path)
    
    # For local connections, check if path is safe
    if utils.CONNECTION_TYPE == "local" and not utils.is_safe_path(dir_path):
        raise ValueError("Invalid path: directory traversal detected")
    
    # Check if directory already exists
    if await utils.FILE_OPS.exists(dir_path):
        raise ValueError(f"Directory already exists: {path}")
    
    # Create parent directories if requested
    if create_dirs:
        await utils.FILE_OPS.makedirs(dir_path.parent, exist_ok=True)
    
    # Create the directory
    await utils.FILE_OPS.makedirs(dir_path, exist_ok=True)
    
    # Return directory info
    return await utils.get_file_info_async(dir_path)

async def create_file(
    path: str,
    content: str = "",
    encoding:str = "utf-8",
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
    file_path = utils.resolve_path(path)
    
    # For local connections, check if path is safe
    if utils.CONNECTION_TYPE == "local" and not utils.is_safe_path(file_path):
        raise ValueError("Invalid path: directory traversal detected")
    
    # Check if file already exists
    if await utils.FILE_OPS.exists(file_path):
        raise ValueError(f"File already exists: {path}")
    
    # Create parent directories if requested
    if create_dirs:
        await utils.FILE_OPS.makedirs(file_path.parent, exist_ok=True)
    
    # Create the file with content
    await utils.FILE_OPS.write_file(file_path, content, encoding=encoding)
    
    # Return file info
    return await utils.get_file_info_async(file_path)


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
    target_path = utils.resolve_path(path)
    
    # For local connections, check if path is safe
    if utils.CONNECTION_TYPE == "local" and not utils.is_safe_path(target_path):
        raise ValueError("Invalid path: directory traversal detected")
    
    # Check if path exists
    if not await utils.FILE_OPS.exists(target_path):
        raise ValueError(f"Path does not exist: {path}")
    
    # Delete based on type
    if await utils.FILE_OPS.is_dir(target_path):
        if recursive:
            await utils.FILE_OPS.rmtree(target_path)
        else:
            # For non-recursive directory deletion, check if empty
            entries = await utils.FILE_OPS.listdir(target_path)
            if entries:
                raise ValueError(f"Directory not empty: {path}. Use recursive=True to delete non-empty directories.")
            await utils.FILE_OPS.rmtree(target_path)
    else:
        await utils.FILE_OPS.remove(target_path)
    
    result = {"deleted": str(target_path)}
    
    # Add relative path for local connections
    if utils.CONNECTION_TYPE == "local":
        try:
            result["deleted_relative"] = str(target_path.relative_to(utils.PROJECT_DIR))
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
    source_path = utils.resolve_path(source)
    dest_path = utils.resolve_path(destination)
    
    # For local connections, check if paths are safe
    if utils.CONNECTION_TYPE == "local":
        if not utils.is_safe_path(source_path) or not utils.is_safe_path(dest_path):
            raise ValueError("Invalid path: directory traversal detected")
    
    # Check if source exists
    if not await utils.FILE_OPS.exists(source_path):
        raise ValueError(f"Source does not exist: {source}")
    
    # Check destination
    if await utils.FILE_OPS.exists(dest_path) and not overwrite:
        raise ValueError(f"Destination already exists: {destination}")
    
    # Perform the move/rename
    await utils.FILE_OPS.rename(source_path, dest_path)
    
    result = {
        "source": str(source_path),
        "destination": str(dest_path)
    }
    
    # Add relative paths for local connections
    if utils.CONNECTION_TYPE == "local":
        try:
            result["source_relative"] = str(source_path.relative_to(utils.PROJECT_DIR))
            result["destination_relative"] = str(dest_path.relative_to(utils.PROJECT_DIR))
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
    source_path = utils.resolve_path(source)
    dest_path = utils.resolve_path(destination)
    
    # For local connections, check if paths are safe
    if utils.CONNECTION_TYPE == "local":
        if not utils.is_safe_path(source_path) or not utils.is_safe_path(dest_path):
            raise ValueError("Invalid path: directory traversal detected")
    
    # Check if source exists
    if not await utils.FILE_OPS.exists(source_path):
        raise ValueError(f"Source does not exist: {source}")
    
    # Check destination
    if await utils.FILE_OPS.exists(dest_path) and not overwrite:
        raise ValueError(f"Destination already exists: {destination}")
    
    # Copy based on type
    if await utils.FILE_OPS.is_dir(source_path):
        await utils.FILE_OPS.copy_tree(source_path, dest_path)
    else:
        await utils.FILE_OPS.copy_file(source_path, dest_path)
    
    result = {
        "source": str(source_path),
        "destination": str(dest_path)
    }
    
    # Add relative paths for local connections
    if utils.CONNECTION_TYPE == "local":
        try:
            result["source_relative"] = str(source_path.relative_to(utils.PROJECT_DIR))
            result["destination_relative"] = str(dest_path.relative_to(utils.PROJECT_DIR))
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
    search_path = utils.resolve_path(path)
    
    # For local connections, check if path is safe
    if utils.CONNECTION_TYPE == "local" and not utils.is_safe_path(search_path):
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
        if not await utils.FILE_OPS.exists(search_path):
            raise ValueError(f"Path does not exist: {path}")
        
        files_to_search = []
        
        if await utils.FILE_OPS.is_file(search_path):
            files_to_search = [search_path]
        else:
            if recursive:
                # Use async walk for file discovery
                async for item in walk_with_depth_async(search_path, file_pattern, max_depth):
                    if await utils.FILE_OPS.is_file(item):
                        files_to_search.append(item)
            else:
                # List directory and filter
                import fnmatch
                entries = await utils.FILE_OPS.listdir(search_path)
                for entry_name in entries:
                    if fnmatch.fnmatch(entry_name, file_pattern):
                        entry_path = search_path / entry_name
                        if await utils.FILE_OPS.is_file(entry_path):
                            files_to_search.append(entry_path)
                
        for file_path in files_to_search:
            # Check if we should yield control periodically
            if files_searched % 100 == 0:
                await asyncio.sleep(0)  # Allow other tasks to run
                
            file_type = utils.get_file_type(file_path)
            if file_type != "text":
                continue
                
            matches = []
            try:
                # Read file content
                content = await utils.FILE_OPS.read_file(file_path, encoding='utf-8')
                
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
                if utils.CONNECTION_TYPE == "local":
                    try:
                        file_result["file_relative"] = str(file_path.relative_to(utils.PROJECT_DIR))
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
    search_path = utils.resolve_path(path)
    
    # For local connections, check if path is safe
    if utils.CONNECTION_TYPE == "local" and not utils.is_safe_path(search_path):
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
        if not await utils.FILE_OPS.exists(search_path):
            raise ValueError(f"Path does not exist: {path}")
        
        files_to_process = []
        
        if await utils.FILE_OPS.is_file(search_path):
            files_to_process = [search_path]
        else:
            if recursive:
                # Use async walk for file discovery
                async for item in walk_with_depth_async(search_path, file_pattern, max_depth):
                    if await utils.FILE_OPS.is_file(item):
                        files_to_process.append(item)
            else:
                # List directory and filter
                import fnmatch
                entries = await utils.FILE_OPS.listdir(search_path)
                for entry_name in entries:
                    if fnmatch.fnmatch(entry_name, file_pattern):
                        entry_path = search_path / entry_name
                        if await utils.FILE_OPS.is_file(entry_path):
                            files_to_process.append(entry_path)
                
        for file_path in files_to_process:
            if files_processed % 50 == 0:
                await asyncio.sleep(0)
                
            file_type = utils.get_file_type(file_path)
            if file_type != "text":
                continue
                
            try:
                # Read file content
                content = await utils.FILE_OPS.read_file(file_path, encoding='utf-8')
                
                # Perform replacements
                new_content, count = regex.subn(replace, content)
                
                if count > 0:
                    # Write back the modified content
                    await utils.FILE_OPS.write_file(file_path, new_content, encoding='utf-8')
                    
                    file_result = {"file": str(file_path), "replacements": count}
                    
                    # Add relative path for local connections
                    if utils.CONNECTION_TYPE == "local":
                        try:
                            file_result["file_relative"] = str(file_path.relative_to(utils.PROJECT_DIR))
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


def normalize_patch(patch: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize patch keys to support common naming conventions.
    
    Converts various key names to standard keys expected by FilePatcher:
    - oldText/newText -> find/replace
    - old_string/new_string -> find/replace  
    - old/new -> find/replace
    - search/replace -> find/replace
    - before/after -> find/replace
    - text/replace -> find/replace
    """
    normalized = patch.copy()
    
    if "find" in normalized:
        return normalized
    
    if "text" in normalized and "replace" in normalized:
        normalized["find"] = normalized.pop("text")
        return normalized
    
    if "oldText" in normalized:
        normalized["find"] = normalized.pop("oldText")
        if "newText" in normalized:
            normalized["replace"] = normalized.pop("newText")
        return normalized
    
    if "old_string" in normalized:
        normalized["find"] = normalized.pop("old_string")
        if "new_string" in normalized:
            normalized["replace"] = normalized.pop("new_string")
        return normalized
    
    if "old" in normalized:
        normalized["find"] = normalized.pop("old")
        if "new" in normalized:
            normalized["replace"] = normalized.pop("new")
        return normalized
    
    if "search" in normalized:
        normalized["find"] = normalized.pop("search")
        return normalized
    
    if "before" in normalized:
        normalized["find"] = normalized.pop("before")
        if "after" in normalized:
            normalized["replace"] = normalized.pop("after")
        return normalized
    
    return normalized


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
    # Normalize patches to support common naming conventions
    patches = [normalize_patch(p) for p in patches]
    for patch in patches:
        if not any(key in patch for key in ("line", "start_line", "find", "context", "unified_diff")):
            raise ValueError("Invalid patch: unsupported patch shape")
    
    file_path = utils.resolve_path(path)
    
    # For local connections, check if path is safe
    if utils.CONNECTION_TYPE == "local" and not utils.is_safe_path(file_path):
        return {
            "success": False,
            "error": "Invalid path: directory traversal detected",
            "patches_applied": 0
        }
    
    # Check if file exists
    if not await utils.FILE_OPS.exists(file_path):
        if create_dirs and patches:
            await utils.FILE_OPS.makedirs(file_path.parent, exist_ok=True)
            await utils.FILE_OPS.write_file(file_path, "", encoding='utf-8')
        else:
            return {
                "success": False,
                "error": f"File does not exist: {path}",
                "patches_applied": 0
            }
    
    # Check if file is text
    file_type = utils.get_file_type(file_path)
    if file_type != "text":
        return {
            "success": False,
            "error": f"Cannot patch binary file: {path}",
            "patches_applied": 0
        }
    
    # Read the file
    try:
        original_content = await utils.FILE_OPS.read_file(file_path, encoding='utf-8')
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
            await utils.FILE_OPS.write_file(backup_path, original_content, encoding='utf-8')
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
            await utils.FILE_OPS.write_file(file_path, content, encoding='utf-8')
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
    file_path = utils.resolve_path(path)
    
    # For local connections, check if path is safe
    if utils.CONNECTION_TYPE == "local" and not utils.is_safe_path(file_path):
        raise ValueError("Invalid path: directory traversal detected")
    
    # Check if path exists
    if not await utils.FILE_OPS.exists(file_path):
        raise ValueError(f"Path does not exist: {path}")
    
    return await utils.get_file_info_async(file_path)
