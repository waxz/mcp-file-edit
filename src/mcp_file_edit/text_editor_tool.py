"""
Anthropic-compatible text-editor tool.

Implements the ``str_replace_based_edit_tool`` protocol (the successor to
``text_editor_20241022`` / ``text_editor_20250124``) that Claude models are
trained to call for file editing: ``view``, ``create``, ``str_replace``,
``insert`` and ``undo_edit``.

Exposing this exact command surface as an MCP tool lets Claude drive file
edits the way it was trained to, instead of forcing it through the
Codex/OpenAI-style ``apply_patch`` unified-diff envelope (which OpenAI models
are trained on instead - see ``file_patch_tools.py``). Both protocols share
the same backend (``utils.FILE_OPS``, path safety, project directory), so
either model family gets a native-feeling, reliable editing tool.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import utils

logger = logging.getLogger(__name__)

# Number of context lines to show around an edit in the returned snippet.
SNIPPET_LINES = 4

# Bound per-file undo history so long-running sessions can't leak memory.
MAX_HISTORY_PER_FILE = 50

VALID_COMMANDS = {"view", "create", "str_replace", "insert", "undo_edit"}

# path (str) -> stack of (existed_before_edit, previous_content)
# `existed_before_edit is False` means the edit created a file that did not
# exist previously, so undo removes it instead of restoring old content.
_EDIT_HISTORY: Dict[str, List[Tuple[bool, str]]] = defaultdict(list)


def _push_history(path: Path, existed_before: bool, previous_content: str) -> None:
    stack = _EDIT_HISTORY[str(path)]
    stack.append((existed_before, previous_content))
    if len(stack) > MAX_HISTORY_PER_FILE:
        del stack[: len(stack) - MAX_HISTORY_PER_FILE]


async def _read_text(path: Path) -> str:
    return await utils.FILE_OPS.read_file(path, encoding="utf-8")


async def _write_text(path: Path, content: str) -> None:
    await utils.FILE_OPS.write_file(path, content, encoding="utf-8")


def _make_numbered_output(content: str, descriptor: str, init_line: int = 1) -> str:
    """Render content as `cat -n` style numbered lines, matching Anthropic's tool output."""
    expanded = content.expandtabs()
    numbered = "\n".join(
        f"{i + init_line:6}\t{line}" for i, line in enumerate(expanded.split("\n"))
    )
    return f"Here's the result of running `cat -n` on {descriptor}:\n{numbered}\n"


async def _list_dir_tree(base: Path, max_depth: int = 2) -> List[str]:
    """List entries up to `max_depth` levels deep, excluding hidden files/dirs."""
    from .file_tools import walk_with_depth_async

    items: List[str] = []
    async for item in walk_with_depth_async(base, "*", max_depth):
        try:
            rel_parts = item.relative_to(base).parts
        except ValueError:
            rel_parts = (item.name,)
        if any(part.startswith(".") for part in rel_parts):
            continue
        items.append(str(item))
    items.sort()
    return items


async def _view(path: Path, view_range: Optional[List[int]]) -> Dict[str, Any]:
    is_dir = await utils.FILE_OPS.is_dir(path)

    if is_dir:
        if view_range is not None:
            raise ValueError(
                "`view_range` is not allowed when `path` points to a directory"
            )
        entries = await _list_dir_tree(path, max_depth=2)
        listing = "\n".join(entries) if entries else "(empty)"
        output = (
            f"Here's the files and directories up to 2 levels deep in {path}, "
            f"excluding hidden items:\n{listing}\n"
        )
        return {"output": output, "path": str(path), "type": "directory", "entries": entries}

    if not await utils.FILE_OPS.exists(path):
        raise ValueError(f"File does not exist: {path}")

    content = await _read_text(path)
    init_line = 1
    displayed_content = content

    if view_range is not None:
        if len(view_range) != 2:
            raise ValueError("`view_range` must be a list of two integers [start, end]")
        start, end = view_range
        lines = content.split("\n")
        n_lines = len(lines)

        if start < 1 or start > n_lines:
            raise ValueError(
                f"`view_range` start line {start} is out of range for a file with "
                f"{n_lines} lines"
            )
        if end != -1 and (end < start or end > n_lines):
            raise ValueError(
                f"`view_range` end line {end} is out of range for a file with "
                f"{n_lines} lines (or -1 to read to the end)"
            )

        displayed_content = "\n".join(lines[start - 1 :] if end == -1 else lines[start - 1 : end])
        init_line = start

    output = _make_numbered_output(displayed_content, str(path), init_line)
    return {"output": output, "path": str(path), "type": "file", "content": displayed_content}


async def _create(path: Path, file_text: Optional[str], create_dirs: bool) -> Dict[str, Any]:
    if file_text is None:
        raise ValueError("Parameter `file_text` is required for command `create`")

    existed = await utils.FILE_OPS.exists(path)
    if existed:
        if await utils.FILE_OPS.is_dir(path):
            raise ValueError(f"Path is a directory, not a file: {path}")
        previous_content = await _read_text(path)
        _push_history(path, True, previous_content)
    else:
        _push_history(path, False, "")

    if create_dirs:
        await utils.FILE_OPS.makedirs(path.parent, exist_ok=True)

    await _write_text(path, file_text)
    return {
        "output": f"File created successfully at: {path}",
        "path": str(path),
        "overwritten": existed,
    }


async def _str_replace(path: Path, old_str: Optional[str], new_str: Optional[str]) -> Dict[str, Any]:
    if old_str is None:
        raise ValueError("Parameter `old_str` is required for command `str_replace`")
    new_str = new_str or ""

    content = await _read_text(path)
    expanded_content = content.expandtabs()
    expanded_old = old_str.expandtabs()
    expanded_new = new_str.expandtabs()

    occurrences = expanded_content.count(expanded_old)
    if occurrences == 0:
        raise ValueError(
            f"No replacement was performed: `old_str` did not appear verbatim in {path}. "
            "Re-read the file and copy the exact text, including whitespace."
        )
    if occurrences > 1:
        matching_lines = [
            i + 1
            for i, line in enumerate(expanded_content.split("\n"))
            if expanded_old in line
        ]
        raise ValueError(
            f"No replacement was performed: `old_str` is not unique. It appears "
            f"{occurrences} times, on lines {matching_lines}. Add more surrounding "
            "context to `old_str` so it matches exactly once."
        )

    new_content = expanded_content.replace(expanded_old, expanded_new)
    _push_history(path, True, content)
    await _write_text(path, new_content)

    replacement_line = expanded_content.split(expanded_old)[0].count("\n")
    start_line = max(0, replacement_line - SNIPPET_LINES)
    end_line = replacement_line + SNIPPET_LINES + expanded_new.count("\n")
    snippet = "\n".join(new_content.split("\n")[start_line : end_line + 1])

    output = (
        f"The file {path} has been edited. "
        + _make_numbered_output(snippet, f"a snippet of {path}", start_line + 1)
        + "Review the changes and make sure they are as expected. Edit the file again "
        "if necessary."
    )
    return {"output": output, "path": str(path), "replaced": occurrences}


async def _insert(path: Path, insert_line: Optional[int], new_str: Optional[str]) -> Dict[str, Any]:
    if insert_line is None:
        raise ValueError("Parameter `insert_line` is required for command `insert`")
    if new_str is None:
        raise ValueError("Parameter `new_str` is required for command `insert`")

    content = await _read_text(path)
    expanded_content = content.expandtabs()
    expanded_new = new_str.expandtabs()
    lines = expanded_content.split("\n")
    n_lines = len(lines)

    if insert_line < 0 or insert_line > n_lines:
        raise ValueError(
            f"`insert_line` {insert_line} is out of range. Must be between 0 (start of "
            f"file) and {n_lines} (end of file)."
        )

    new_str_lines = expanded_new.split("\n")
    new_lines = lines[:insert_line] + new_str_lines + lines[insert_line:]
    new_content = "\n".join(new_lines)

    _push_history(path, True, content)
    await _write_text(path, new_content)

    start_line = max(0, insert_line - SNIPPET_LINES)
    end_line = insert_line + len(new_str_lines) + SNIPPET_LINES
    snippet = "\n".join(new_lines[start_line:end_line])

    output = (
        f"The file {path} has been edited. "
        + _make_numbered_output(snippet, "a snippet of the edited file", start_line + 1)
        + "Review the changes and make sure they are as expected (correct indentation, "
        "no duplicate lines, etc). Edit the file again if necessary."
    )
    return {"output": output, "path": str(path)}


async def _undo_edit(path: Path) -> Dict[str, Any]:
    key = str(path)
    history = _EDIT_HISTORY.get(key)
    if not history:
        raise ValueError(f"No edit history found for {path}; nothing to undo.")

    existed_before, previous_content = history.pop()
    if not history:
        del _EDIT_HISTORY[key]

    if existed_before:
        await _write_text(path, previous_content)
        output = f"Last edit to {path} undone successfully."
    else:
        if await utils.FILE_OPS.exists(path):
            await utils.FILE_OPS.remove(path)
        output = (
            f"Last edit to {path} undone successfully "
            "(the file did not exist before that edit, so it was removed)."
        )

    return {"output": output, "path": str(path)}


async def str_replace_based_edit_tool(
    command: str,
    path: str,
    file_text: Optional[str] = None,
    old_str: Optional[str] = None,
    new_str: Optional[str] = None,
    insert_line: Optional[int] = None,
    view_range: Optional[List[int]] = None,
    create_dirs: bool = False,
) -> Dict[str, Any]:
    """
    Anthropic ``str_replace_based_edit_tool`` protocol implementation.

    Commands:
        view: Show a file (numbered like `cat -n`, optionally restricted to
            `view_range`) or list a directory's contents up to 2 levels deep.
        create: Create (or overwrite) a file with `file_text`.
        str_replace: Replace the single, unique occurrence of `old_str` with
            `new_str` in an existing file. Fails if `old_str` is missing or
            appears more than once - add more context to make it unique.
        insert: Insert `new_str` after line `insert_line` (0 inserts at the
            start of the file) in an existing file.
        undo_edit: Revert the most recent create/str_replace/insert made to
            `path` through this tool, restoring the prior content (or
            removing the file if this tool created it).

    Args:
        command: One of "view", "create", "str_replace", "insert", "undo_edit".
        path: File or directory path, relative to the active project
            directory (see `set_project_directory`).
        file_text: Full file content, required for `create`.
        old_str: Exact text to replace, required for `str_replace`.
        new_str: Replacement text for `str_replace`; text to insert for `insert`.
        insert_line: Line number after which to insert, required for `insert`.
        view_range: Optional [start, end] 1-based inclusive line range for
            `view` on a file; `end=-1` reads to the end of the file.
        create_dirs: Create missing parent directories for `create`.

    Returns:
        Dict with an `output` field containing human-readable confirmation
        text (matching what the Anthropic text-editor tool returns), plus
        structured fields for the given command.

    Raises:
        ValueError: For invalid commands, missing required parameters, path
            safety violations, or when `str_replace`/`insert` preconditions
            are not met (e.g. `old_str` not found or not unique).
    """
    if command not in VALID_COMMANDS:
        raise ValueError(
            f"Unknown command `{command}`. Allowed commands: {sorted(VALID_COMMANDS)}"
        )
    if not path:
        raise ValueError("Parameter `path` is required")

    target_path = utils.resolve_path(path)
    if utils.CONNECTION_TYPE == "local" and not utils.is_safe_path(target_path):
        raise ValueError(f"Invalid path: directory traversal detected: {path}")

    if command == "view":
        return await _view(target_path, view_range)

    if command == "create":
        return await _create(target_path, file_text, create_dirs)

    # str_replace / insert / undo_edit all require an existing, non-directory file.
    if not await utils.FILE_OPS.exists(target_path):
        raise ValueError(
            f'File does not exist: {path}. Use command="create" to create it first.'
        )
    if await utils.FILE_OPS.is_dir(target_path):
        raise ValueError(f"Path is a directory, not a file: {path}")

    if command == "str_replace":
        return await _str_replace(target_path, old_str, new_str)
    if command == "insert":
        return await _insert(target_path, insert_line, new_str)
    return await _undo_edit(target_path)
