
import re
import asyncio
import base64
import subprocess
import tempfile
import os
from pathlib import Path
from typing import List, Dict, Any, Optional, AsyncIterator, Iterator
from datetime import datetime
from dataclasses import dataclass, field
from urllib.parse import urlencode

import mcp.types as types
from fastmcp.tools.base import ToolResult
from . import utils
import logging
from diff_match_patch import diff_match_patch
from .patch_preview_store import create_patch_preview_session

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def _build_text_resource(uri: str, mime_type: str, text: str) -> Any | None:
    """Build an embedded MCP text resource when supported by the installed MCP types."""
    embedded_resource_cls = getattr(types, "EmbeddedResource", None)
    text_resource_cls = getattr(types, "TextResourceContents", None)
    if embedded_resource_cls is None or text_resource_cls is None:
        return None
    return embedded_resource_cls(
        type="resource",
        resource=text_resource_cls(
            uri=uri,
            mimeType=mime_type,
            text=text,
        ),
    )


def _looks_like_numbered_export(text: str, digit_end: int) -> bool:
    """Return True only for likely line-number-prefixed exports."""
    if digit_end >= len(text):
        return False
    if text[digit_end] == "\t":
        return True
    if text[digit_end] != " ":
        return False

    space_end = digit_end
    while space_end < len(text) and text[space_end] == " ":
        space_end += 1
    return (space_end - digit_end) >= 2

async def apply_patch_with_recovery(
    patch: str,
    backup: bool = True,
    dry_run: bool = False,
    create_dirs: bool = False,
    auto_recover: bool = True,  # NEW
) -> Dict[str, Any]:
    """Apply patch with automatic recovery on context mismatch"""

    result = await apply_patch(patch, backup, dry_run, create_dirs=create_dirs)

    # If failed and auto_recover is enabled
    if not result["success"] and auto_recover and not dry_run:
        failed_ops = [c for c in result["changes"] if not c.get("success")]

        for failed in failed_ops:
            if "Failed to locate patch context" in failed.get("error", ""):
                path = failed["path"]

                return {
                    **result,
                    "recovery_suggestion": {
                        "action": "read_and_retry",
                        "message": (
                            f"The patch failed because content doesn't match. "
                            f"Steps to fix:\n"
                            f"1. Read {path} to see current content\n"
                            f"2. Find the section you want to change\n"
                            f"3. Create new patch with 2-3 context lines before and after\n"
                            f"4. Include the EXACT current content in the - lines"
                        ),
                        "example": (
                            "*** Begin Patch\n"
                            f"*** Update File: {path}\n"
                            "@@\n"
                            " <line before>\n"
                            " <line before>\n"
                            "-<current content to remove>\n"
                            "+<new content to add>\n"
                            " <line after>\n"
                            " <line after>\n"
                            "*** End Patch"
                        ),
                    },
                }

    return result


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
        """Parse a Codex-style apply_patch payload with robust error handling."""

        lines = patch_text.splitlines()

        # Basic validation
        if not lines:
            raise ValueError("Patch is empty")

        if lines[0] != cls.BEGIN_MARKER:
            raise ValueError(
                f"Patch must start with '{cls.BEGIN_MARKER}'\nGot: '{lines[0]}'"
            )

        if len(lines) < 2:
            raise ValueError(
                f"Patch is incomplete. Must have at least:\n"
                f"  {cls.BEGIN_MARKER}\n"
                f"  *** Update File: path\n"
                f"  ...\n"
                f"  {cls.END_MARKER}"
            )

        if lines[-1] != cls.END_MARKER:
            raise ValueError(
                f"Patch must end with '{cls.END_MARKER}'\n"
                f"Got: '{lines[-1]}'\n"
                f"The patch may be incomplete or malformed."
            )

        # Count BEGIN/END markers to detect nesting issues
        begin_count = sum(1 for line in lines if line == cls.BEGIN_MARKER)
        end_count = sum(1 for line in lines if line == cls.END_MARKER)

        if begin_count > 1 or end_count > 1:
            logger.warning(
                f"Detected {begin_count} BEGIN and {end_count} END markers. "
                f"This may be a patch that documents patch syntax. "
                f"Only the outermost patch will be processed. "
                f"Nested markers will be treated as content."
            )

        # Normalize: Remove line numbers from diff lines while preserving structure
        normalized_lines = []
        for line_num, line in enumerate(lines, 1):
            # Markers and special lines - keep as-is
            if line.startswith(("*** ", "@@")):
                normalized_lines.append(line)
                continue

            # Empty lines - keep as-is, will be handled contextually
            if not line:
                normalized_lines.append(line)
                continue

            first_char = line[0]

            # Standard diff prefix (+, -, space)
            if first_char in {"+", "-", " "}:
                rest = line[1:]

                # Case 1: Has line number after prefix (e.g., "-3\tContent" or "+1  Content")
                if rest and rest[0].isdigit():
                    i = 0
                    # Skip all digits
                    while i < len(rest) and rest[i].isdigit():
                        i += 1
                    # Only treat as a numbered export if digits are followed by whitespace.
                    if _looks_like_numbered_export(rest, i):
                        while i < len(rest) and rest[i] in {"\t", " "}:
                            i += 1
                        content = rest[i:] if i < len(rest) else ""
                        normalized_lines.append(first_char + content)
                    else:
                        normalized_lines.append(line)

                # Case 2: Just prefix, no content (blank line with prefix)
                else:
                    # Keep prefix + content as-is
                    normalized_lines.append(line)

            # Line starts with digit (non-standard: line number without prefix)
            elif first_char.isdigit():
                i = 0
                while i < len(line) and line[i].isdigit():
                    i += 1
                if _looks_like_numbered_export(line, i):
                    while i < len(line) and line[i] in {"\t", " "}:
                        i += 1
                    content = line[i:] if i < len(line) else ""

                    # Treat as context line
                    normalized_lines.append(" " + content)

                    if line_num < 10 or line_num % 100 == 0:
                        logger.debug(
                            f"Line {line_num}: Non-standard format (line number without prefix): {line[:40]}..."
                        )
                else:
                    normalized_lines.append(line)

            # Keep as-is
            else:
                normalized_lines.append(line)

        lines = normalized_lines

        # Debug output
        logger.debug("=== NORMALIZED PATCH ===")
        for i, line in enumerate(lines[:50]):
            logger.debug(f"{i:3d}: {repr(line)}")
        logger.debug("=== END ===")

        operations: List[PatchOperation] = []
        index = 1

        while index < len(lines) - 1:
            line = lines[index]

            # ADD FILE operation
            if line.startswith(cls.ADD_FILE):
                path = line[len(cls.ADD_FILE) :].strip()

                if cls._is_placeholder_path(path):
                    logger.warning(f"Skipping placeholder path: {path}")
                    index += 1
                    continue

                index += 1
                hunk = PatchHunk()

                while index < len(lines) - 1 and not lines[index].startswith(
                    ("*** Add File: ", "*** Delete File: ", "*** Update File: ")
                ):
                    if lines[index] == cls.END_OF_FILE:
                        hunk.no_newline_at_end = True
                        index += 1
                        continue

                    current_line = lines[index]

                    # For ADD operations, lines should start with +
                    if current_line.startswith("+"):
                        hunk.lines.append(current_line)
                    elif not current_line.startswith(("*** ", "@@")):
                        # Auto-add + prefix for backwards compatibility
                        hunk.lines.append("+" + current_line)
                    else:
                        hunk.lines.append(current_line)

                    index += 1

                operations.append(PatchOperation(kind="add", path=path, hunks=[hunk]))
                continue

            # DELETE FILE operation
            if line.startswith(cls.DELETE_FILE):
                path = line[len(cls.DELETE_FILE) :].strip()

                if cls._is_placeholder_path(path):
                    logger.warning(f"Skipping placeholder path: {path}")
                    index += 1
                    continue

                operations.append(PatchOperation(kind="delete", path=path))
                index += 1
                continue

            # UPDATE FILE operation
            if line.startswith(cls.UPDATE_FILE):
                path = line[len(cls.UPDATE_FILE) :].strip()

                if cls._is_placeholder_path(path):
                    logger.warning(f"Skipping placeholder path: {path}")
                    while index < len(lines) - 1:
                        index += 1
                        if lines[index].startswith(
                            ("*** Add File: ", "*** Delete File: ", "*** Update File: ")
                        ):
                            break
                    continue

                index += 1
                operation = PatchOperation(kind="update", path=path)

                # Check for move operation
                if index < len(lines) - 1 and lines[index].startswith(cls.MOVE_TO):
                    operation.move_to = lines[index][len(cls.MOVE_TO) :].strip()
                    index += 1

                current_hunk: Optional[PatchHunk] = None
                in_hunk_body = False

                while index < len(lines) - 1:
                    current_line = lines[index]

                    # Check for next file operation
                    if current_line.startswith(
                        ("*** Add File: ", "*** Delete File: ", "*** Update File: ")
                    ):
                        break

                    # End of file marker
                    if current_line == cls.END_OF_FILE:
                        if current_hunk is None:
                            current_hunk = PatchHunk()
                        current_hunk.no_newline_at_end = True
                        index += 1
                        continue

                    # Hunk header
                    if current_line.startswith("@@"):
                        if current_hunk and current_hunk.lines:
                            operation.hunks.append(current_hunk)
                        current_hunk = PatchHunk()
                        in_hunk_body = True
                        index += 1
                        continue

                    # Only process hunk content if we're in a hunk
                    if not in_hunk_body:
                        index += 1
                        continue

                    if current_hunk is None:
                        current_hunk = PatchHunk()

                    # CRITICAL: Handle lines with explicit prefix first
                    if (
                        current_line
                        and len(current_line) > 0
                        and current_line[0] in {" ", "+", "-"}
                    ):
                        # Line has a prefix
                        if len(current_line) == 1:
                            # Just the prefix, no content - this is a blank line
                            current_hunk.lines.append(current_line[0])
                        else:
                            # Prefix + content
                            current_hunk.lines.append(current_line)
                        index += 1
                        continue

                    # CRITICAL: Empty line without prefix
                    # Look back to determine what prefix to use
                    if not current_line:
                        # Determine prefix based on surrounding context
                        # Look at the most recent non-empty line
                        inferred_prefix = " "  # Default to context

                        for prev_line in reversed(current_hunk.lines):
                            if prev_line:
                                inferred_prefix = prev_line[0]
                                break

                        # If the previous line was + or -, continue that pattern
                        # Otherwise, treat as context
                        if inferred_prefix in {"+", "-"}:
                            current_hunk.lines.append(inferred_prefix)
                        else:
                            current_hunk.lines.append(" ")

                        index += 1
                        continue

                    # Line without prefix - treat as context
                    current_hunk.lines.append(" " + current_line)
                    index += 1

                # Finalize last hunk
                if current_hunk and current_hunk.lines:
                    operation.hunks.append(current_hunk)

                # Validate operation has content
                if not operation.hunks and not operation.move_to:
                    raise ValueError(
                        f"Update File has no hunks or move operation: {path}"
                    )

                operations.append(operation)
                continue
            # Move to next line
            index += 1

        # Final validation
        if not operations:
            raise ValueError(
                "No valid file operations found in patch. "
                "All operations may have been placeholders or the patch is malformed."
            )

        logger.info(
            f"Parsed {len(operations)} operations: "
            f"{sum(1 for op in operations if op.kind == 'add')} adds, "
            f"{sum(1 for op in operations if op.kind == 'update')} updates, "
            f"{sum(1 for op in operations if op.kind == 'delete')} deletes"
        )

        return operations

    @classmethod
    def _is_placeholder_path(cls, path: str) -> bool:
        """Check if path is a placeholder/example path"""
        placeholder_patterns = [
            "path/to/",
            "file.ext",
            "example.",
            "your-project",
            "your-file",
            "/path/",
            "your_",
            "my_",
        ]

        path_lower = path.lower()
        return any(pattern in path_lower for pattern in placeholder_patterns)


class ApplyPatchExecutor:
    """Execute a parsed apply_patch payload against the current file backend."""

    @staticmethod
    def _normalize_line_for_match(line: str) -> str:
        """Normalize whitespace for safe fallback matching."""
        return re.sub(r"\s+", " ", line).strip()

    @staticmethod
    def _find_hunk_match(
        content: str, hunk: PatchHunk, search_start: int = 0
    ) -> tuple[int, int, str]:
        """Locate a hunk using exact match first, then whitespace-normalized lines."""
        old_text = ApplyPatchExecutor._old_text_from_hunk(hunk)
        if not old_text:
            raise ValueError("Hunk has no anchor text. Include context or removed lines.")

        match_pos = content.find(old_text, search_start)
        if match_pos < 0:
            match_pos = content.find(old_text)
        if match_pos >= 0:
            return match_pos, match_pos + len(old_text), "exact"

        old_lines = ApplyPatchExecutor._old_lines_from_hunk(hunk)
        content_lines = content.splitlines(keepends=True)
        candidate_spans: List[tuple[int, int]] = []
        offset = 0
        line_offsets: List[tuple[int, int]] = []
        for line in content_lines:
            line_offsets.append((offset, offset + len(line)))
            offset += len(line)

        normalized_old = [
            ApplyPatchExecutor._normalize_line_for_match(line) for line in old_lines
        ]
        normalized_old_has_signal = any(part for part in normalized_old)

        for start_line in range(len(content_lines) - len(old_lines) + 1):
            candidate_lines = [
                content_lines[start_line + i].rstrip("\r\n")
                for i in range(len(old_lines))
            ]
            normalized_candidate = [
                ApplyPatchExecutor._normalize_line_for_match(line)
                for line in candidate_lines
            ]
            if normalized_candidate != normalized_old:
                continue
            if normalized_old_has_signal:
                start_offset = line_offsets[start_line][0]
                end_offset = line_offsets[start_line + len(old_lines) - 1][1]
                candidate_spans.append((start_offset, end_offset))

        if not candidate_spans:
            snippet = old_text.rstrip("\n")
            if len(snippet) > 160:
                snippet = snippet[:157] + "..."
            raise ValueError(f"Failed to locate patch context exactly: {snippet!r}")

        after_search = [span for span in candidate_spans if span[0] >= search_start]
        candidate_pool = after_search or candidate_spans
        if len(candidate_pool) > 1:
            raise ValueError(
                "Whitespace-normalized patch context is ambiguous; include more context lines."
            )

        start_offset, end_offset = candidate_pool[0]
        return start_offset, end_offset, "whitespace_normalized"

    @staticmethod
    def _old_lines_from_hunk(hunk: PatchHunk) -> List[str]:
        """Return the exact original-file lines referenced by one hunk."""
        old_lines: List[str] = []
        for line in hunk.lines:
            if line == "":
                old_lines.append("")
                continue
            prefix = line[0] if line else " "
            if prefix in {" ", "-"}:
                old_lines.append(line[1:] if len(line) > 1 else "")
        return old_lines

    @staticmethod
    def _old_text_from_hunk(hunk: PatchHunk) -> str:
        """Build the exact original-file snippet a hunk expects to replace."""
        old_lines = ApplyPatchExecutor._old_lines_from_hunk(hunk)
        if not old_lines:
            return ""

        text = "\n".join(old_lines)
        if not hunk.no_newline_at_end:
            text += "\n"
        return text

    @staticmethod
    def _new_lines_from_hunk(hunk: PatchHunk) -> List[str]:
        """Return the exact replacement-file lines produced by one hunk."""
        new_lines: List[str] = []
        for line in hunk.lines:
            if line == "":
                new_lines.append("")
                continue
            prefix = line[0] if line else " "
            if prefix in {" ", "+"}:
                new_lines.append(line[1:] if len(line) > 1 else "")
        return new_lines

    @staticmethod
    def _new_text_from_hunk(hunk: PatchHunk) -> str:
        """Build the exact replacement snippet produced by one hunk."""
        new_lines = ApplyPatchExecutor._new_lines_from_hunk(hunk)
        text = "\n".join(new_lines)
        if new_lines and not hunk.no_newline_at_end:
            text += "\n"
        return text

    @staticmethod
    def ensure_exact_hunk_match(original_content: str, hunks: List[PatchHunk]) -> None:
        """
        Require update hunks to match the current file contents exactly.

        This prevents diff-match-patch from fuzzily rewriting unrelated content when
        the removal/context lines drift from the real file.
        """
        for index, hunk in enumerate(hunks, start=1):
            _, _, method = ApplyPatchExecutor._find_hunk_match(original_content, hunk)
            if method != "exact":
                snippet = ApplyPatchExecutor._old_text_from_hunk(hunk).rstrip("\n")
                if len(snippet) > 160:
                    snippet = snippet[:157] + "..."
                raise ValueError(
                    "Failed to locate patch context exactly for hunk "
                    f"{index}: {snippet!r}"
                )

    @staticmethod
    def validate_hunks(original_content: str, hunks: List[PatchHunk]) -> List[str]:
        """Validate hunks and return warnings for non-exact but safe matches."""
        warnings: List[str] = []
        search_start = 0
        preview_content = original_content

        for index, hunk in enumerate(hunks, start=1):
            start, end, method = ApplyPatchExecutor._find_hunk_match(
                preview_content, hunk, search_start
            )
            if method == "whitespace_normalized":
                warnings.append(
                    f"Hunk {index} matched using whitespace-normalized context"
                )

            new_text = ApplyPatchExecutor._new_text_from_hunk(hunk)
            preview_content = preview_content[:start] + new_text + preview_content[end:]
            search_start = start + len(new_text)

        return warnings

    @staticmethod
    def validate_patch(original_content: str, hunks: List[PatchHunk]) -> List[str]:
        """
        Validate that all hunks can be applied in order.
        Returns warnings, including when safe whitespace-normalized fallback was used.
        """
        warnings = []

        try:
            warnings.extend(
                ApplyPatchExecutor.validate_hunks(original_content, hunks)
            )
            ApplyPatchExecutor._apply_update_hunks(original_content, hunks)

        except Exception as e:
            warnings.append(f"Patch validation error: {str(e)}")

        return warnings

    @staticmethod
    def _apply_update_hunks(original_content: str, hunks: List[PatchHunk]) -> str:
        """Apply hunks by exact text replacement in source order, with safe whitespace fallback."""
        if not hunks:
            raise ValueError("No valid hunks to apply")

        updated_content = original_content
        search_start = 0

        for index, hunk in enumerate(hunks, start=1):
            old_text = ApplyPatchExecutor._old_text_from_hunk(hunk)
            if not old_text:
                raise ValueError(
                    f"Hunk {index} has no anchor text. Include context or removed lines."
                )

            new_text = ApplyPatchExecutor._new_text_from_hunk(hunk)
            match_pos, match_end, _ = ApplyPatchExecutor._find_hunk_match(
                updated_content, hunk, search_start
            )
            updated_content = (
                updated_content[:match_pos] + new_text + updated_content[match_end:]
            )
            search_start = match_pos + len(new_text)

        return updated_content

    @staticmethod
    def _hunks_to_unified_diff(hunks: List[PatchHunk]) -> str:
        """
        Convert Codex-style hunks to unified diff format for diff-match-patch.

        Based on diff-match-patch's behavior:
        - Newlines in diff content should be encoded as %0A
        - Each diff line in the patch ends with \n (separator)
        - To insert "Hello\n" into the file, the patch line should be "+Hello%0A\n"
        """
        if not hunks:
            return ""

        unified_parts = []

        for hunk in hunks:
            if not hunk.lines:
                continue

            diff_lines = []
            old_count = 0
            new_count = 0

            for line in hunk.lines:
                if line == "":
                    # Blank context line - encoded as %0A
                    diff_lines.append(" %0A\n")
                    old_count += 1
                    new_count += 1
                    continue

                prefix = line[0] if line else " "
                content = line[1:] if len(line) > 1 else ""

                # Strip any existing line endings
                clean_content = content.rstrip("\r\n") if content else ""

                # Encode with %0A for newline at end of each line
                if prefix == " ":
                    if clean_content:
                        diff_lines.append(f" {clean_content}%0A\n")
                    else:
                        diff_lines.append(" %0A\n")
                    old_count += 1
                    new_count += 1
                elif prefix == "-":
                    if clean_content:
                        diff_lines.append(f"-{clean_content}%0A\n")
                    else:
                        diff_lines.append("-%0A\n")
                    old_count += 1
                elif prefix == "+":
                    if clean_content:
                        diff_lines.append(f"+{clean_content}%0A\n")
                    else:
                        diff_lines.append("+%0A\n")
                    new_count += 1
                else:
                    diff_lines.append(f" {line.rstrip()}%0A\n")
                    old_count += 1
                    new_count += 1

            if not diff_lines:
                continue

            # Header
            old_start = 1
            new_start = 1
            header = f"@@ -{old_start},{old_count} +{new_start},{new_count} @@\n"

            unified_parts.append(header)
            unified_parts.extend(diff_lines)

        result = "".join(unified_parts)

        logger.debug("=== UNIFIED DIFF OUTPUT (with %0A encoding) ===")
        logger.debug(repr(result))
        logger.debug("=== END ===")

        return result


_patch_history: Dict[str, bool] = {}  # hash -> has_been_previewed


async def apply_patch(
    patch: str,
    backup: bool = True,
    dry_run: bool = False,
    create_dirs: bool = False,
    validate_first: bool = True,
) -> Dict[str, Any]:
    """Apply a Codex-style multi-file patch."""

    try:
        operations = ApplyPatchParser.parse(patch)
    except Exception as e:
        return {
            "success": False,
            "error": f"Patch parsing failed: {str(e)}",
            "operations_applied": 0,
            "adds": 0,
            "updates": 0,
            "deletes": 0,
            "moves": 0,
            "changes": [],
            "warnings": [],
            "dry_run": dry_run,
        }

    changes: List[Dict[str, Any]] = []
    adds = updates = deletes = moves = 0
    warnings: List[str] = []

    import hashlib

    patch_hash = hashlib.md5(patch.encode()).hexdigest()

    for operation in operations:
        target_path = utils.resolve_path(operation.path)
        move_target_path = (
            utils.resolve_path(operation.move_to) if operation.move_to else None
        )

        if utils.CONNECTION_TYPE == "local" and not utils.is_safe_path(target_path):
            changes.append(
                {
                    "type": operation.kind,
                    "path": str(target_path),
                    "success": False,
                    "error": f"Invalid path: {operation.path}",
                }
            )
            continue

        if move_target_path is not None:
            if utils.CONNECTION_TYPE == "local" and not utils.is_safe_path(
                move_target_path
            ):
                changes.append(
                    {
                        "type": operation.kind,
                        "path": str(target_path),
                        "success": False,
                        "error": f"Invalid move destination: {operation.move_to}",
                    }
                )
                continue
            if await utils.FILE_OPS.exists(move_target_path):
                changes.append(
                    {
                        "type": operation.kind,
                        "path": str(target_path),
                        "success": False,
                        "error": f"Move destination already exists: {operation.move_to}",
                    }
                )
                continue

        # Handle ADD operation
        if operation.kind == "add":
            if await utils.FILE_OPS.exists(target_path):
                changes.append(
                    {
                        "type": "add",
                        "path": str(target_path),
                        "success": False,
                        "error": f"File already exists: {operation.path}",
                    }
                )
                continue

            # Create content from hunk
            lines = []
            for hunk in operation.hunks:
                for line in hunk.lines:
                    # For ADD operations, lines should start with +
                    # Remove the + prefix to get actual content
                    if line.startswith("+"):
                        lines.append(line[1:].rstrip("\n\r"))
                    else:
                        # If no +, treat as-is (for backwards compatibility)
                        lines.append(line.rstrip("\n\r"))

            content = "\n".join(lines)
            if lines and not operation.hunks[0].no_newline_at_end:
                content += "\n"

            if dry_run:
                changes.append(
                    {
                        "type": "add",
                        "path": str(target_path),
                        "success": True,
                        "preview": content[:500]
                        + ("..." if len(content) > 500 else ""),
                        "lines": len(lines),
                    }
                )
                adds += 1
                continue

            # Create parent directories if needed
            if create_dirs:
                await utils.FILE_OPS.makedirs(target_path.parent, exist_ok=True)

            # Write new file
            try:
                await utils.FILE_OPS.write_file(target_path, content, encoding="utf-8")
                adds += 1
                changes.append(
                    {
                        "type": "add",
                        "path": str(target_path),
                        "success": True,
                        "lines": len(lines),
                    }
                )
            except Exception as e:
                changes.append(
                    {
                        "type": "add",
                        "path": str(target_path),
                        "success": False,
                        "error": f"Failed to create file: {str(e)}",
                    }
                )
            continue

        # Handle DELETE operation
        if operation.kind == "delete":
            if not await utils.FILE_OPS.exists(target_path):
                changes.append(
                    {
                        "type": "delete",
                        "path": str(target_path),
                        "success": False,
                        "error": f"File does not exist: {operation.path}",
                    }
                )
                continue

            if dry_run:
                stat = await utils.FILE_OPS.stat(target_path)
                changes.append(
                    {
                        "type": "delete",
                        "path": str(target_path),
                        "success": True,
                        "size": stat.st_size,
                    }
                )
                deletes += 1
                continue

            # Delete file
            try:
                await utils.FILE_OPS.remove(target_path)
                deletes += 1
                changes.append(
                    {"type": "delete", "path": str(target_path), "success": True}
                )
            except Exception as e:
                changes.append(
                    {
                        "type": "delete",
                        "path": str(target_path),
                        "success": False,
                        "error": f"Failed to delete file: {str(e)}",
                    }
                )
            continue

        # Handle UPDATE operation
        if operation.kind == "update":
            if not await utils.FILE_OPS.exists(target_path):
                changes.append(
                    {
                        "type": "update",
                        "path": str(target_path),
                        "success": False,
                        "error": f"Cannot update missing file: {operation.path}",
                    }
                )
                continue

            try:
                original_content = await utils.FILE_OPS.read_file(
                    target_path, encoding="utf-8"
                )
            except Exception as e:
                changes.append(
                    {
                        "type": "update",
                        "path": str(target_path),
                        "success": False,
                        "error": f"Failed to read file: {str(e)}",
                    }
                )
                continue

            # VALIDATE FIRST if requested
            if validate_first and operation.hunks:
                patch_warnings = ApplyPatchExecutor.validate_patch(
                    original_content, operation.hunks
                )
                if patch_warnings:
                    warnings.extend([f"{operation.path}: {w}" for w in patch_warnings])

            try:
                ApplyPatchExecutor.validate_hunks(original_content, operation.hunks)
            except Exception as e:
                changes.append(
                    {
                        "type": "update",
                        "path": str(target_path),
                        "success": False,
                        "error": str(e),
                    }
                )
                logger.error(
                    f"Rejected patch for {target_path} due to exact-match failure: {e}"
                )
                continue

            # Apply hunks
            try:
                updated_content = (
                    ApplyPatchExecutor._apply_update_hunks(
                        original_content, operation.hunks
                    )
                    if operation.hunks
                    else original_content
                )
            except Exception as e:
                changes.append(
                    {
                        "type": "update",
                        "path": str(target_path),
                        "success": False,
                        "error": f"Error applying patch: {str(e)}",
                    }
                )
                logger.error(f"Error applying patch to {target_path}: {str(e)}")
                continue

            # DRY RUN: Show diff
            if dry_run:
                import difflib

                diff = list(
                    difflib.unified_diff(
                        original_content.splitlines(keepends=True),
                        updated_content.splitlines(keepends=True),
                        fromfile=f"a/{operation.path}",
                        tofile=f"b/{operation.path}",
                        lineterm="",
                    )
                )
                diff_text = "\n".join(diff) + "\n"
                changes.append(
                    {
                        "type": "update",
                        "path": str(target_path),
                        "success": True,
                        "diff": diff_text,
                        **(
                            {"move_to": str(move_target_path)}
                            if move_target_path is not None
                            else {}
                        ),
                    }
                )
                if operation.hunks:
                    updates += 1
                if move_target_path is not None:
                    moves += 1
                continue

            # Create backup
            backup_path = None
            if backup:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_path = (
                    target_path.parent / f"{target_path.name}.backup_{timestamp}"
                )
                try:
                    await utils.FILE_OPS.write_file(
                        backup_path, original_content, encoding="utf-8"
                    )
                except Exception as e:
                    logger.warning(f"Failed to create backup: {str(e)}")

            # Write updated content
            try:
                if move_target_path is not None:
                    if create_dirs:
                        await utils.FILE_OPS.makedirs(
                            move_target_path.parent, exist_ok=True
                        )

                    if operation.hunks:
                        await utils.FILE_OPS.write_file(
                            move_target_path, updated_content, encoding="utf-8"
                        )
                        await utils.FILE_OPS.remove(target_path)
                        updates += 1
                    else:
                        await utils.FILE_OPS.rename(target_path, move_target_path)
                    moves += 1
                else:
                    await utils.FILE_OPS.write_file(
                        target_path, updated_content, encoding="utf-8"
                    )
                    updates += 1

                change: Dict[str, Any] = {
                    "type": "update",
                    "path": str(target_path),
                    "success": True,
                }
                if move_target_path is not None:
                    change["move_to"] = str(move_target_path)
                if backup_path:
                    change["backup_path"] = str(backup_path)
                changes.append(change)
            except Exception as e:
                changes.append(
                    {
                        "type": "update",
                        "path": str(target_path),
                        "success": False,
                        "error": f"Failed to write file: {str(e)}",
                    }
                )

    if dry_run:
        _patch_history[patch_hash] = True
    else:
        # Clean up after successful apply
        if patch_hash in _patch_history:
            del _patch_history[patch_hash]

    # Determine overall success
    all_successful = all(c.get("success", False) for c in changes)
    any_successful = any(c.get("success", False) for c in changes)

    return {
        "success": all_successful,
        "partial_success": any_successful and not all_successful,
        "operations_applied": len(changes),
        "adds": adds,
        "updates": updates,
        "deletes": deletes,
        "moves": moves,
        "changes": changes,
        "warnings": warnings,
        "dry_run": dry_run,
    }


async def preview_patch(patch: str) -> str:
    """
    Preview patch changes before applying.
    Shows a diff of what would change using diff-match-patch fuzzy matching.

    Works with all coding agents (Claude Code, Codex, OpenCode, etc.)
    Uses universal diff format that agents can display in their diff viewer.

    Args:
        patch: Patch content in Codex format

    Returns:
        Formatted diff preview compatible with all coding agents
    """
    try:
        result = await apply_patch(
            patch=patch,
            backup=True,
            dry_run=True,
            create_dirs=False,
            validate_first=True,
        )

        # Check for parsing errors
        if "error" in result and not result.get("success"):
            return f"❌ PATCH ERROR\n\n{result['error']}\n\nTry: patch_format_help()"

        # Format output - use universal diff format for all coding agents
        output = ""

        # Show warnings at the top if present
        if result.get("warnings"):
            output += "⚠️  WARNINGS:\n"
            for warning in result["warnings"]:
                output += f"  - {warning}\n"
            output += "\n" + "─" * 60 + "\n\n"

        # Generate unified diff format (works with all agents)
        has_changes = False
        file_diffs = []

        for change in result.get("changes", []):
            path = change.get("path", "unknown")
            filename = path.split("/")[-1] if "/" in path else path

            if not change.get("success"):
                output += f"❌ FAILED: {path}\n"
                output += f"   Error: {change.get('error')}\n\n"
                continue

            diff_content = ""

            if change.get("type") == "update" and change.get("diff"):
                has_changes = True
                diff_content = change["diff"]
            elif change.get("type") == "add":
                has_changes = True
                # Generate unified diff for new file
                lines = change.get("preview", "").split("\n")
                diff_content = f"--- /dev/null\n+++ b/{filename}\n"
                for i, line in enumerate(lines):
                    if line:
                        diff_content += f"@@ -0,0 +{i + 1},1 @@\n+{line}\n"
            elif change.get("type") == "delete":
                has_changes = True
                # Generate unified diff for deleted file
                size = change.get("size", 0)
                diff_content = f"--- a/{filename}\n+++ /dev/null\n@@ -1,0 +0,0 @@\n- (deleted, {size} bytes)\n"

            if diff_content:
                file_diffs.append(
                    {
                        "path": path,
                        "filename": filename,
                        "diff": diff_content,
                        "type": change.get("type"),
                    }
                )

        if not file_diffs and not any(
            not change.get("success") for change in result.get("changes", [])
        ):
            return "No changes to preview."

        # Output file-by-file diffs in universal format
        for fd in file_diffs:
            output += f"## {fd['path']}\n\n"

            if fd["type"] == "update":
                output += "```diff\n"
                output += fd["diff"]
                if not fd["diff"].endswith("\n"):
                    output += "\n"
                output += "```\n\n"
            elif fd["type"] == "add":
                output += "```diff\n"
                output += fd["diff"]
                output += "```\n\n"
            elif fd["type"] == "delete":
                output += "```diff\n"
                output += fd["diff"]
                output += "```\n\n"

        # Add summary footer
        output += "─" * 60 + "\n"
        output += "📊 Changes Summary:\n"
        output += f"  📝 Updates: {result.get('updates', 0)}\n"
        output += f"  ➕ Adds: {result.get('adds', 0)}\n"
        output += f"  🗑️ Deletes: {result.get('deletes', 0)}\n"

        if result.get("partial_success"):
            output += "\n⚠️  Some operations failed\n"
        elif result.get("success"):
            output += "\n✅ All changes validated\n"

        # Generate apply command for different agents
        output += "\n" + "─" * 60 + "\n"
        output += "💡 To apply these changes, use:\n\n"

        # Claude Code / OpenCode style
        output += "**Claude Code / OpenCode:**\n"
        output += "```python\n"
        output += 'apply_patch("""\\\n'
        escaped = patch.replace('"""', '\\"\\"\\"')
        output += escaped[:150] + ("..." if len(patch) > 150 else "")
        output += '\\n""", dry_run=False)\n'
        output += "```\n\n"

        # Codex style
        output += "**Codex CLI:**\n"
        output += "```bash\n"
        output += 'echo """\\\n'
        output += patch.replace("\\", "\\\\").replace('"', '\\"')[:200] + (
            "..." if len(patch) > 200 else ""
        )
        output += '\n""" | apply-patch\n'
        output += "```\n\n"

        return output

    except Exception as e:
        logger.exception("Error in preview_patch")
        return f"❌ Error: {str(e)}\n\nTry: patch_format_help()"


# async def preview_patch_with_vscode(patch: str) -> str:
#     """
#     Preview patch changes and provide instructions to open in VSCode diff view.

#     Returns diff content plus instructions for the agent to open in VSCode.
#     """
#     try:
#         result = await apply_patch(
#             patch=patch,
#             backup=True,
#             dry_run=True,
#             create_dirs=False,
#             validate_first=True,
#         )

#         if "error" in result and not result.get("success"):
#             return f"❌ PATCH ERROR\n\n{result['error']}\n\nTry: patch_format_help()"

#         if "warnings" in result and result["warnings"]:
#             output = "⚠️  WARNINGS:\n"
#             for warning in result["warnings"]:
#                 output += f"  - {warning}\n"
#             output += "\n" + "─" * 60 + "\n\n"
#         else:
#             output = ""

#         file_diffs = []

#         for change in result.get("changes", []):
#             path = change.get("path", "unknown")
#             filename = path.split("/")[-1] if "/" in path else path

#             if not change.get("success"):
#                 output += f"❌ FAILED: {path}\n"
#                 output += f"   Error: {change.get('error')}\n\n"
#                 continue

#             diff_content = ""
#             original_content = ""
#             new_content = ""

#             if change.get("type") == "update" and change.get("diff"):
#                 diff_content = change["diff"]
#             elif change.get("type") == "add":
#                 new_content = change.get("preview", "")
#             elif change.get("type") == "delete":
#                 pass

#             if diff_content or new_content:
#                 file_diffs.append(
#                     {
#                         "path": path,
#                         "filename": filename,
#                         "diff": diff_content,
#                         "new_content": new_content,
#                         "type": change.get("type"),
#                     }
#                 )

#         if not file_diffs:
#             return "No changes to preview."

#         # Generate output with diffs and VSCode instructions
#         output += "## Changes Preview\n\n"

#         import hashlib
#         import tempfile

#         temp_dir = tempfile.mkdtemp(prefix="mcp_diff_")

#         for i, fd in enumerate(file_diffs):
#             output += f"### {fd['path']}\n\n"

#             if fd["type"] == "update" and fd["diff"]:
#                 output += "```diff\n"
#                 output += fd["diff"]
#                 if not fd["diff"].endswith("\n"):
#                     output += "\n"
#                 output += "```\n\n"

#                 # Create temp files for VSCode diff
#                 orig_file = os.path.join(temp_dir, f"{fd['filename']}.orig")
#                 new_file = os.path.join(temp_dir, f"{fd['filename']}")

#                 # We need original content - read from file
#                 try:
#                     target_path = utils.resolve_path(fd["path"])
#                     if target_path.exists():
#                         with open(target_path) as f:
#                             original_content = f.read()
#                         with open(orig_file, "w") as f:
#                             f.write(original_content)
#                         with open(new_file, "w") as f:
#                             # Apply patch to get new content (simplified - just use preview)
#                             import difflib

#                             lines = fd["diff"].split("\n")
#                             new_lines = []
#                             for line in lines:
#                                 if line.startswith("+") and not line.startswith("+++"):
#                                     new_lines.append(line[1:])
#                                 elif line.startswith("@@"):
#                                     pass  # Skip hunk header
#                                 elif line.startswith("-") or line.startswith("---"):
#                                     pass  # Skip old content
#                                 elif line.startswith(" "):
#                                     new_lines.append(line[1:] if len(line) > 1 else "")
#                             with open(new_file, "w") as f:
#                                 f.write("\n".join(new_lines))
#                     else:
#                         continue
#                 except Exception as e:
#                     logger.warning(f"Could not create VSCode diff files: {e}")
#                     continue

#             elif fd["type"] == "add":
#                 output += f"(New file: {fd['new_content'][:200]}...)\n\n"
#                 new_file = os.path.join(temp_dir, f"NEW_{fd['filename']}")
#                 with open(new_file, "w") as f:
#                     f.write(fd["new_content"])

#         # Add summary and VSCode instructions
#         output += "─" * 60 + "\n"
#         output += "📊 Changes Summary:\n"
#         output += f"  📝 Updates: {result.get('updates', 0)}\n"
#         output += f"  ➕ Adds: {result.get('adds', 0)}\n"
#         output += f"  🗑️ Deletes: {result.get('deletes', 0)}\n\n"

#         output += "─" * 60 + "\n"
#         output += f"💡 To open diffs in VSCode:\n\n"
#         output += f"```bash\n"
#         output += f"# Open each diff in VSCode:\n"
#         for i, fd in enumerate(file_diffs):
#             filename = fd["filename"]
#             output += f"code --diff {temp_dir}/{filename}.orig {temp_dir}/{filename}\n"
#         output += "```\n\n"

#         output += f"Or manually review above, then apply with:\n"
#         output += f"`apply_patch(patch, dry_run=False)`"

#         return output

#     except Exception as e:
#         logger.exception("Error in preview_patch_with_vscode")
#         return f"❌ Error: {str(e)}"


async def preview_patch_with_vscode1(patch: str) -> str:
    """
    Preview patch with VSCode diff view - returns diff + instructions for agent.

    First runs dry-run to get diff content, then runs actual apply.
    Shows diff preview regardless of whether apply succeeds.
    """
    try:
        # Parse operations first to get file paths
        operations = ApplyPatchParser.parse(patch)

        # Read original content BEFORE applying patch
        original_contents = {}
        for op in operations:
            if op.kind == "update":
                try:
                    if utils.PROJECT_DIR:
                        filename = op.path.split("/")[-1] if "/" in op.path else op.path
                        full_path = utils.PROJECT_DIR / filename
                        if full_path.exists():
                            with open(full_path) as f:
                                original_contents[op.path] = f.read()
                                original_contents[filename] = f.read()
                except:
                    pass

        # First, run dry-run to get diff content for preview
        dry_result = await apply_patch(
            patch=patch,
            backup=True,
            dry_run=True,
            create_dirs=False,
            validate_first=True,
        )

        # Then run actual apply
        result = await apply_patch(
            patch=patch,
            backup=True,
            dry_run=False,
            create_dirs=False,
            validate_first=True,
        )

        # Show diff from dry-run result even if apply failed
        if not dry_result.get("changes"):
            return "No changes to preview."

        output_lines = []
        diff_files_info = []
        temp_dir = "/tmp/mcp_diff"

        # Process changes from dry-run (which has diff content)
        for change in dry_result.get("changes", []):
            path = change.get("path", "unknown")
            filename = path.split("/")[-1] if "/" in path else path
            change_type = change.get("type")

            if change_type == "update" and change.get("diff"):
                diff_content = change.get("diff", "")

                # Use original content we saved BEFORE applying the patch
                # Try both path and filename as keys
                original_content = original_contents.get(
                    path, ""
                ) or original_contents.get(filename, "")

                output_lines.append(f"\n## File: {path}\n")
                output_lines.append("```diff")
                output_lines.append(diff_content)
                output_lines.append("```\n")

                # Store with diff content for later reference
                diff_files_info.append(
                    {
                        "filename": filename,
                        "path": path,
                        "original": original_content,
                        "diff": diff_content,
                    }
                )

            elif change_type == "add":
                new_content = change.get("preview", "")
                output_lines.append(f"\n## NEW File: {path}\n")
                output_lines.append(f"```\n{new_content}\n```\n")
                diff_files_info.append(
                    {
                        "filename": filename,
                        "path": path,
                        "original": "",
                        "new": new_content,
                    }
                )

            elif change_type == "delete":
                output_lines.append(f"\n## DELETE File: {path}\n")

        # Show apply result
        if result.get("success"):
            output_lines.append(
                f"✅ Applied: {result.get('updates', 0)} updates, {result.get('adds', 0)} adds"
            )
        else:
            output_lines.append(
                f"❌ Apply failed: {result.get('changes', [{}])[0].get('error', 'Unknown error')}"
            )

        # Summary from dry-run
        output_lines.append("\n" + "─" * 60)
        output_lines.append(
            f"📊 Preview: {dry_result.get('updates', 0)} updates, {dry_result.get('adds', 0)} adds, {dry_result.get('deletes', 0)} deletes"
        )

        # VSCode diff view instructions for agent to execute locally
        if diff_files_info:
            output_lines.append("\n" + "─" * 60)
            output_lines.append("💡 OPEN IN VSCODE DIFF VIEW (agent executes locally):")
            output_lines.append("")
            output_lines.append(
                "Use your local tools to create diff files and open in VSCode:"
            )
            output_lines.append("")

            for df in diff_files_info:
                orig = df.get("original", "")
                has_original = orig is not None and len(orig) > 0
                logger.info(
                    f"VSCode section: filename={df['filename']}, original={repr(orig)[:30]}, has_original={has_original}"
                )

                if has_original:
                    diff = df.get("diff", "")
                    new_lines = []
                    in_hunk = False
                    for line in diff.split("\n"):
                        if line.startswith("@@"):
                            in_hunk = True
                            continue
                        if not in_hunk:
                            continue
                        if line.startswith("+") and not line.startswith("+++"):
                            new_lines.append(line[1:])
                        elif line.startswith("-"):
                            pass
                        elif line.startswith(" ") or line == "":
                            new_lines.append(line[1:] if len(line) > 1 else "")
                    new_content = "\n".join(new_lines).rstrip("\n")

                    output_lines.append(f"### File: {df['path']}")
                    output_lines.append("")
                    output_lines.append("**Original content:**")
                    output_lines.append("```")
                    output_lines.append(orig)
                    output_lines.append("```")
                    output_lines.append("")
                    output_lines.append("**New content:**")
                    output_lines.append("```")
                    output_lines.append(new_content)
                    output_lines.append("```")
                    output_lines.append("")
                    output_lines.append("**To open in VSCode diff view, run locally:**")
                    output_lines.append("```bash")
                    output_lines.append(f"mkdir -p {temp_dir}")
                    # Escape for shell
                    orig_escaped = (
                        orig.replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")
                    )
                    new_escaped = (
                        new_content.replace('"', '\\"')
                        .replace("$", "\\$")
                        .replace("`", "\\`")
                    )
                    output_lines.append(
                        f'echo -n "{orig_escaped}" > {temp_dir}/{df["filename"]}.orig'
                    )
                    output_lines.append(
                        f'echo -n "{new_escaped}" > {temp_dir}/{df["filename"]}'
                    )
                    output_lines.append(
                        f"code --diff {temp_dir}/{df['filename']}.orig {temp_dir}/{df['filename']}"
                    )
                    output_lines.append("```")
                    output_lines.append("")
                elif df.get("new"):
                    output_lines.append(f"### NEW File: {df['path']}")
                    output_lines.append("")
                    output_lines.append("**New file content:**")
                    output_lines.append("```")
                    output_lines.append(df.get("new", ""))
                    output_lines.append("```")
                    output_lines.append("")
                    output_lines.append("**To open in VSCode, run locally:**")
                    output_lines.append("```bash")
                    output_lines.append(f"mkdir -p {temp_dir}")
                    new_escaped = (
                        df.get("new", "")
                        .replace('"', '\\"')
                        .replace("$", "\\$")
                        .replace("`", "\\`")
                    )
                    output_lines.append(
                        f'echo -n "{new_escaped}" > {temp_dir}/NEW_{df["filename"]}'
                    )
                    output_lines.append(f"code {temp_dir}/NEW_{df['filename']}")
                    output_lines.append("```")
                    output_lines.append("")

        output_lines.append("\n" + "─" * 60)
        output_lines.append("After reviewing in VSCode, you can apply changes with:")
        output_lines.append("apply_patch(patch, dry_run=False)")

        return "\n".join(output_lines)

    except Exception as e:
        logger.exception("Error in preview_patch_with_vscode")
        return f"❌ Error: {str(e)}"

def _build_preview_diff_entries(
    dry_result: Dict[str, Any],
    original_contents: Optional[Dict[str, str]] = None,
    temp_dir: str = ".mcp-diff",
) -> List[Dict[str, Any]]:
    """Build normalized diff entries from an apply_patch dry-run result."""
    diff_entries: List[Dict[str, Any]] = []
    original_contents = original_contents or {}

    for change in dry_result.get("changes", []):
        if not change.get("success"):
            continue

        path = str(change.get("path", "unknown"))
        filename = Path(path).name or path
        change_type = change.get("type")
        original_content = original_contents.get(path, "")
        new_content = ""

        diff_text = ""
        if change_type == "update" and change.get("diff"):
            diff_text = change["diff"]
            new_content = _apply_diff_to_get_new_content(original_content, diff_text)
        elif change_type == "add":
            preview = change.get("preview", "")
            diff_lines = [f"--- /dev/null", f"+++ b/{filename}"]
            for i, line in enumerate(preview.splitlines(), start=1):
                diff_lines.append(f"@@ -0,0 +{i},1 @@")
                diff_lines.append(f"+{line}")
            diff_text = "\n".join(diff_lines).rstrip() + "\n"
            new_content = preview
        elif change_type == "delete":
            size = change.get("size", 0)
            diff_text = (
                f"--- a/{filename}\n"
                f"+++ /dev/null\n"
                f"@@ -1,0 +0,0 @@\n"
                f"- (deleted, {size} bytes)\n"
            )
            new_content = ""

        if diff_text:
            local_old_file = f"{temp_dir}/{filename}.orig"
            local_new_file = (
                f"{temp_dir}/{filename}.new"
                if change_type == "update"
                else f"{temp_dir}/{filename}"
            )
            diff_entries.append(
                {
                    "path": path,
                    "filename": filename,
                    "type": change_type,
                    "diff": diff_text,
                    "original_content": original_content,
                    "new_content": new_content,
                    "local_old_file": local_old_file,
                    "local_new_file": local_new_file,
                }
            )

    return diff_entries


def _format_patch_preview_text(
    dry_result: Dict[str, Any], diff_entries: List[Dict[str, Any]]
) -> str:
    """Render the human-readable patch preview."""
    if "error" in dry_result and not dry_result.get("success"):
        return f"❌ PATCH ERROR\n\n{dry_result['error']}\n\nTry: patch_format_help()"

    lines: List[str] = []
    failed_changes = [
        change for change in dry_result.get("changes", []) if not change.get("success")
    ]
    combined_diff = "\n".join(
        entry["diff"].rstrip() for entry in diff_entries if entry.get("diff")
    ).rstrip()
    changed_paths = [entry["path"] for entry in diff_entries]
    file_count = len(changed_paths)
    summary_bits = [
        f"{file_count} file{'s' if file_count != 1 else ''}",
        f"{dry_result.get('updates', 0)} update{'s' if dry_result.get('updates', 0) != 1 else ''}",
        f"{dry_result.get('adds', 0)} add{'s' if dry_result.get('adds', 0) != 1 else ''}",
        f"{dry_result.get('deletes', 0)} delete{'s' if dry_result.get('deletes', 0) != 1 else ''}",
    ]

    lines.append(f"Patch preview: {', '.join(summary_bits)}.")
    lines.append("")

    if dry_result.get("warnings"):
        lines.append("Warnings:")
        for warning in dry_result["warnings"]:
            lines.append(f"- {warning}")
        lines.append("")

    if changed_paths:
        lines.append("Files:")
        for path in changed_paths:
            lines.append(f"- {path}")
        lines.append("")

    if combined_diff:
        lines.append("```diff")
        lines.append(combined_diff)
        lines.append("```")
        lines.append("")

    if failed_changes:
        lines.append("Failed changes:")
        for change in failed_changes:
            path = change.get("path", "unknown")
            error = change.get("error", "Unknown preview failure")
            lines.append(f"❌ FAILED: {path}")
            lines.append(f"   Error: {error}")
        lines.append("")

    if not diff_entries and not failed_changes:
        return "No changes to preview."

    if dry_result.get("partial_success"):
        lines.append("Status: partial validation success.")
    elif dry_result.get("success"):
        lines.append("Status: ready for review.")
    else:
        lines.append("Status: validation failed.")

    lines.append("")
    if dry_result.get("success") and not dry_result.get("partial_success"):
        lines.append(
            "Confirm this reviewed preview before applying it with "
            "`apply_confirmed_patch(preview_id=...)`."
        )
    else:
        lines.append(
            "Fix the patch and run `apply_patch(..., dry_run=True)` again before "
            "trying to confirm or apply anything."
        )
    return "\n".join(lines)


def _preview_resource_uri(index: int, filename: str) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", filename) or f"file-{index}"
    return f"diff://patch-preview/{index}-{safe_name}.diff"


def _build_patch_preview_result(
    patch: str, dry_result: Dict[str, Any]
) -> ToolResult:
    """Return a structured MCP tool result for patch previews."""
    diff_entries = _build_preview_diff_entries(dry_result)
    text_preview = _format_patch_preview_text(dry_result, diff_entries)

    content: List[Any] = [types.TextContent(type="text", text=text_preview)]
    resources: List[Dict[str, Any]] = []
    combined_diff_parts: List[str] = []

    for index, entry in enumerate(diff_entries, start=1):
        uri = _preview_resource_uri(index, entry["filename"])
        diff_text = entry["diff"]
        combined_diff_parts.append(diff_text.rstrip())
        embedded_resource = _build_text_resource(uri, "text/x-diff", diff_text)
        if embedded_resource is not None:
            content.append(embedded_resource)
        resources.append(
            {
                "uri": uri,
                "mimeType": "text/x-diff",
                "path": entry["path"],
                "type": entry["type"],
            }
        )

    if combined_diff_parts:
        embedded_resource = _build_text_resource(
            "diff://patch-preview/all.diff",
            "text/x-diff",
            "\n".join(combined_diff_parts).rstrip() + "\n",
        )
        if embedded_resource is not None:
            content.append(embedded_resource)

    structured_content = {
        "kind": "patch_preview",
        "viewer_hint": "diff",
        "patch": patch,
        "all_diff": ("\n".join(combined_diff_parts).rstrip() + "\n") if combined_diff_parts else "",
        "summary": {
            "updates": dry_result.get("updates", 0),
            "adds": dry_result.get("adds", 0),
            "deletes": dry_result.get("deletes", 0),
            "warnings": dry_result.get("warnings", []),
            "success": dry_result.get("success", False),
            "partial_success": dry_result.get("partial_success", False),
        },
        "files": diff_entries,
        "resources": resources,
        "local_launch_plan": {
            "temp_dir": ".mcp-diff",
            "steps": [
                "Create the local temp directory on the agent machine.",
                "Write each old/new file pair locally using the provided file contents.",
                "Run the provided Bash command locally to open VS Code diff view.",
            ],
            "commands": [
                f"mkdir -p .mcp-diff",
                *[
                    (
                        f"code --diff {entry['local_old_file']} {entry['local_new_file']}"
                        if entry["type"] == "update"
                        else f"code {entry['local_new_file']}"
                    )
                    for entry in diff_entries
                ],
            ],
        },
    }

    return ToolResult(
        content=content,
        structured_content=structured_content,
    )


async def apply_preview_changes(
    structured_preview: Dict[str, Any],
    *,
    backup: bool = True,
    create_dirs: bool = False,
) -> Dict[str, Any]:
    """Apply reviewed preview file contents exactly as stored in the preview session."""
    files = structured_preview.get("files", [])
    changes: List[Dict[str, Any]] = []
    adds = updates = deletes = moves = 0

    for file_entry in files:
        path_value = str(file_entry.get("path", ""))
        if not path_value:
            changes.append(
                {
                    "type": "unknown",
                    "path": path_value,
                    "success": False,
                    "error": "Missing file path in preview session",
                }
            )
            continue

        target_path = Path(path_value)
        if not target_path.is_absolute():
            target_path = utils.resolve_path(path_value)

        if utils.CONNECTION_TYPE == "local" and not utils.is_safe_path(target_path):
            changes.append(
                {
                    "type": file_entry.get("type", "unknown"),
                    "path": str(target_path),
                    "success": False,
                    "error": f"Invalid path: {path_value}",
                }
            )
            continue

        entry_type = file_entry.get("type", "update")
        original_content = file_entry.get("original_content", "") or ""
        new_content = file_entry.get("new_content", "") or ""

        try:
            exists = await utils.FILE_OPS.exists(target_path)
        except Exception as e:
            changes.append(
                {
                    "type": entry_type,
                    "path": str(target_path),
                    "success": False,
                    "error": f"Failed to stat file: {e}",
                }
            )
            continue

        if entry_type == "delete" and new_content == "":
            if not exists:
                changes.append(
                    {
                        "type": "delete",
                        "path": str(target_path),
                        "success": False,
                        "error": "Cannot delete missing file",
                    }
                )
                continue

            current_content = await utils.FILE_OPS.read_file(target_path, encoding="utf-8")
            if current_content != original_content:
                changes.append(
                    {
                        "type": "delete",
                        "path": str(target_path),
                        "success": False,
                        "error": "Current file content no longer matches the reviewed preview",
                    }
                )
                continue

            if backup:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_path = target_path.parent / f"{target_path.name}.backup_{timestamp}"
                await utils.FILE_OPS.write_file(backup_path, current_content, encoding="utf-8")

            await utils.FILE_OPS.remove(target_path)
            deletes += 1
            changes.append({"type": "delete", "path": str(target_path), "success": True})
            continue

        if not exists:
            if create_dirs:
                await utils.FILE_OPS.makedirs(target_path.parent, exist_ok=True)
            await utils.FILE_OPS.write_file(target_path, new_content, encoding="utf-8")
            adds += 1
            changes.append({"type": "add", "path": str(target_path), "success": True})
            continue

        current_content = await utils.FILE_OPS.read_file(target_path, encoding="utf-8")
        if current_content != original_content:
            changes.append(
                {
                    "type": entry_type,
                    "path": str(target_path),
                    "success": False,
                    "error": "Current file content no longer matches the reviewed preview",
                }
            )
            continue

        if backup:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = target_path.parent / f"{target_path.name}.backup_{timestamp}"
            await utils.FILE_OPS.write_file(backup_path, current_content, encoding="utf-8")

        await utils.FILE_OPS.write_file(target_path, new_content, encoding="utf-8")
        updates += 1
        changes.append({"type": "update", "path": str(target_path), "success": True})

    all_successful = all(c.get("success", False) for c in changes) if changes else True
    any_successful = any(c.get("success", False) for c in changes)
    return {
        "success": all_successful,
        "partial_success": any_successful and not all_successful,
        "operations_applied": len(changes),
        "adds": adds,
        "updates": updates,
        "deletes": deletes,
        "moves": moves,
        "changes": changes,
        "warnings": structured_preview.get("summary", {}).get("warnings", []),
        "dry_run": False,
    }


def attach_patch_preview_session(
    tool_result: ToolResult,
    patch: str,
    *,
    base_url: str | None = None,
) -> ToolResult:
    structured = dict(tool_result.structured_content or {})
    summary = structured.get("summary", {})
    preview_is_actionable = bool(summary.get("success")) and not bool(
        summary.get("partial_success")
    )

    session = None
    preview_url = None
    confirm_url = None
    reject_url = None

    if preview_is_actionable:
        session = create_patch_preview_session(patch, structured)
        preview_url = (
            f"{base_url}/patch-preview/{session.preview_id}" if base_url else None
        )
        confirm_url = (
            f"{preview_url}/confirm?{urlencode({'token': session.confirm_token})}"
            if preview_url
            else None
        )
        reject_url = (
            f"{preview_url}/reject?{urlencode({'token': session.reject_token})}"
            if preview_url
            else None
        )

        structured["preview_session"] = {
            "preview_id": session.preview_id,
            "status": session.status,
            "expires_at": session.expires_at.isoformat(),
        }
        if preview_url:
            structured["preview_session"]["preview_url"] = preview_url
            structured["preview_session"]["confirm_url"] = confirm_url
            structured["preview_session"]["reject_url"] = reject_url

    content = list(tool_result.content)
    if content and getattr(content[0], "type", None) == "text":
        review_lines = [content[0].text]
        if preview_is_actionable and session is not None:
            review_lines.extend(
                [
                    "",
                    "Review workflow:",
                    f"- Preview ID: {session.preview_id}",
                    "- Confirm with `confirm_patch_preview(preview_id=...)` after review.",
                    "- Apply with `apply_confirmed_patch(preview_id=...)`.",
                    "- Reject with `reject_patch_preview(preview_id=...)` if needed.",
                ]
            )
            if preview_url:
                review_lines.extend(
                    [
                        f"- Browser Preview: {preview_url}",
                        f"- Browser Confirm: {confirm_url}",
                        f"- Browser Reject: {reject_url}",
                    ]
                )
        else:
            review_lines.extend(
                [
                    "",
                    "Preview workflow:",
                    "- This preview is not actionable because validation failed.",
                    "- Fix the patch, then run `apply_patch(..., dry_run=True)` again.",
                ]
            )
        content[0] = types.TextContent(
            type="text",
            text="\n".join(review_lines),
        )

    return ToolResult(content=content, structured_content=structured)


async def preview_patch_with_vscode(patch: str) -> ToolResult:
    """
    Preview a patch as structured diff content.

    The server cannot force Claude Code, Codex, or OpenCode to open a diff view.
    It can only return diff artifacts and metadata that compatible clients may
    render as a diff.
    """
    try:
        operations = ApplyPatchParser.parse(patch)
        original_contents: Dict[str, str] = {}
        for operation in operations:
            if operation.kind != "update":
                continue
            target_path = utils.resolve_path(operation.path)
            try:
                if await utils.FILE_OPS.exists(target_path):
                    original_contents[str(target_path)] = await utils.FILE_OPS.read_file(
                        target_path, encoding="utf-8"
                    )
            except Exception as exc:
                logger.warning(f"Could not read original content for {target_path}: {exc}")

        dry_result = await apply_patch(
            patch=patch,
            backup=True,
            dry_run=True,
            create_dirs=False,
            validate_first=True,
        )
        enriched_result = dict(dry_result)
        diff_entries = _build_preview_diff_entries(
            enriched_result,
            original_contents=original_contents,
            temp_dir=".mcp-diff",
        )
        text_preview = _format_patch_preview_text(enriched_result, diff_entries)
        output = _build_patch_preview_result(patch, enriched_result)
        output.content[0] = types.TextContent(
            type="text",
            text=text_preview,
        )
        output.structured_content["files"] = diff_entries
        output.structured_content["local_launch_plan"]["commands"] = [
            "mkdir -p .mcp-diff",
            *[
                (
                    f"code --diff {entry['local_old_file']} {entry['local_new_file']}"
                    if entry["type"] == "update"
                    else f"code {entry['local_new_file']}"
                )
                for entry in diff_entries
            ],
        ]
        return output

    except Exception as e:
        logger.exception("Error in preview_patch_with_vscode")
        return ToolResult(
            content=[
                types.TextContent(
                    type="text",
                    text=f"❌ Error: {str(e)}\n\nTry: patch_format_help()",
                )
            ],
            structured_content={"kind": "patch_preview", "error": str(e)},
        )


def _apply_diff_to_get_new_content(original: str, diff: str) -> str:
    """
    Apply a unified diff to original content to get new content.
    Used to extract the "after" state for VSCode diff view.
    """
    if not original and not diff:
        return ""
    
    new_lines = []
    original_lines = original.splitlines(keepends=False)
    
    in_hunk = False
    for line in diff.split("\n"):
        # Skip diff headers
        if line.startswith("---") or line.startswith("+++"):
            continue
        
        # Hunk header
        if line.startswith("@@"):
            in_hunk = True
            continue
        
        if not in_hunk:
            continue
        
        # Added line
        if line.startswith("+") and not line.startswith("+++"):
            new_lines.append(line[1:])
        # Context line (keep it)
        elif line.startswith(" "):
            new_lines.append(line[1:] if len(line) > 1 else "")
        # Removed line (skip it)
        elif line.startswith("-"):
            continue
        # Empty line
        elif line == "":
            new_lines.append("")
    
    return "\n".join(new_lines)

async def open_diff_in_vscode(patch: str) -> str:
    """
    Open patch diff in VSCode for visual review.
    Creates temp files and opens them with 'code --diff'.

    Args:
        patch: Patch content in Codex format

    Returns:
        Status message with instructions
    """
    try:
        result = await apply_patch(
            patch=patch,
            backup=False,
            dry_run=True,
            create_dirs=False,
            validate_first=True,
        )

        if "error" in result and not result.get("success"):
            return f"❌ PATCH ERROR\n\n{result['error']}\n\nTry: patch_format_help()"

        changes = result.get("changes", [])
        if not changes:
            return "No changes to preview."

        temp_dir = tempfile.mkdtemp(prefix="mcp_patch_diff_")
        diff_files = []

        for change in changes:
            if not change.get("success"):
                continue

            path = change.get("path", "unknown")
            change_type = change.get("type")

            if change_type == "update":
                diff_content = change.get("diff", "")
                if diff_content:
                    diff_file = os.path.join(temp_dir, f"{os.path.basename(path)}.diff")
                    with open(diff_file, "w") as f:
                        f.write(diff_content)
                    diff_files.append(diff_file)

            elif change_type == "add":
                preview = change.get("preview", "")
                if preview:
                    new_file = os.path.join(temp_dir, f"NEW_{os.path.basename(path)}")
                    with open(new_file, "w") as f:
                        f.write(preview)
                    diff_files.append(new_file)

        if not diff_files:
            return "No diff files generated."

        if len(diff_files) == 1:
            subprocess.Popen(["code", "--goto", diff_files[0]])
        else:
            subprocess.Popen(["code", "-n"])
            for df in diff_files[:5]:
                subprocess.Popen(["code", "--add", df])

        file_count = len(diff_files)
        return (
            f"✅ Opening {file_count} diff file(s) in VSCode\n\n"
            f"📁 Temp directory: {temp_dir}\n\n"
            f"VSCode should open with the diff view.\n"
            f"You can manually review changes before applying with apply_patch."
        )

    except FileNotFoundError:
        return "❌ VSCode not found. Make sure 'code' is in your PATH."
    except Exception as e:
        logger.exception("Error in open_diff_in_vscode")
        return f"❌ Error: {str(e)}"
