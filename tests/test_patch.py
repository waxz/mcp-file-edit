"""Regression tests for Codex-style patch application."""

import asyncio
import sys
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


if "fastmcp" not in sys.modules:
    fastmcp_stub = types.ModuleType("fastmcp")
    sys.modules["fastmcp"] = fastmcp_stub

if "asyncssh" not in sys.modules:
    asyncssh_stub = types.ModuleType("asyncssh")
    asyncssh_stub.FILEXFER_TYPE_REGULAR = 1
    asyncssh_stub.FILEXFER_TYPE_DIRECTORY = 2

    class _NoSuchFile(Exception):
        pass

    class _Failure(Exception):
        pass

    class _SSHClientConnection:
        pass

    class _SFTPClient:
        pass

    asyncssh_stub.SFTPNoSuchFile = _NoSuchFile
    asyncssh_stub.SFTPFailure = _Failure
    asyncssh_stub.SSHClientConnection = _SSHClientConnection
    asyncssh_stub.SFTPClient = _SFTPClient
    asyncssh_stub.connect = None
    sys.modules["asyncssh"] = asyncssh_stub

if "fastmcp.tools" not in sys.modules:
    sys.modules["fastmcp.tools"] = types.ModuleType("fastmcp.tools")

if "fastmcp.tools.base" not in sys.modules:
    tools_base_stub = types.ModuleType("fastmcp.tools.base")

    class _ToolResult:
        def __init__(self, content=None, structured_content=None):
            self.content = content or []
            self.structured_content = structured_content or {}

    tools_base_stub.ToolResult = _ToolResult
    sys.modules["fastmcp.tools.base"] = tools_base_stub

if "mcp" not in sys.modules:
    sys.modules["mcp"] = types.ModuleType("mcp")

if "mcp.types" not in sys.modules:
    mcp_types_stub = types.ModuleType("mcp.types")

    class _TextContent:
        def __init__(self, type="text", text=""):
            self.type = type
            self.text = text

    mcp_types_stub.TextContent = _TextContent
    sys.modules["mcp.types"] = mcp_types_stub

if "toml" not in sys.modules:
    toml_stub = types.ModuleType("toml")
    toml_stub.load = lambda *args, **kwargs: {}
    toml_stub.loads = lambda *args, **kwargs: {}
    sys.modules["toml"] = toml_stub


from mcp_file_edit import utils
from mcp_file_edit.file_operations import LocalFileOperations
from mcp_file_edit.file_patch_tools import apply_patch


def _run(awaitable):
    return asyncio.run(awaitable)


@pytest.fixture
def local_patch_env(tmp_path):
    original_file_ops = utils.FILE_OPS
    original_connection_type = utils.CONNECTION_TYPE
    original_project_dir = utils.PROJECT_DIR

    utils.FILE_OPS = LocalFileOperations()
    utils.CONNECTION_TYPE = "local"
    utils.PROJECT_DIR = tmp_path

    try:
        yield tmp_path
    finally:
        utils.FILE_OPS = original_file_ops
        utils.CONNECTION_TYPE = original_connection_type
        utils.PROJECT_DIR = original_project_dir


def test_apply_patch_updates_file_with_exact_hunk_match(local_patch_env):
    target = local_patch_env / "module.py"
    target.write_text("line 1\nold value\nline 3\n", encoding="utf-8")

    patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Update File: module.py",
            "@@",
            " line 1",
            "-old value",
            "+new value",
            " line 3",
            "*** End Patch",
        ]
    )

    result = _run(apply_patch(patch))

    assert result["success"] is True
    assert result["updates"] == 1
    assert target.read_text(encoding="utf-8") == "line 1\nnew value\nline 3\n"


def test_apply_patch_add_file_honors_end_of_file_marker(local_patch_env):
    patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Add File: nonewline.txt",
            "+no trailing newline",
            "*** End of File",
            "*** End Patch",
        ]
    )

    result = _run(apply_patch(patch))

    assert result["success"] is True
    assert result["adds"] == 1
    assert (local_patch_env / "nonewline.txt").read_text(encoding="utf-8") == "no trailing newline"


def test_apply_patch_dry_run_reports_change_without_writing(local_patch_env):
    target = local_patch_env / "dry_run.txt"
    target.write_text("before\n", encoding="utf-8")

    patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Update File: dry_run.txt",
            "@@",
            "-before",
            "+after",
            "*** End Patch",
        ]
    )

    result = _run(apply_patch(patch, dry_run=True))

    assert result["success"] is True
    assert result["dry_run"] is True
    assert result["updates"] == 1
    assert target.read_text(encoding="utf-8") == "before\n"


def test_apply_patch_preserves_numeric_leading_diff_content(local_patch_env):
    target = local_patch_env / "numbers.md"
    target.write_text("header\n123abc\nfooter\n", encoding="utf-8")

    patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Update File: numbers.md",
            "@@",
            " header",
            "-123abc",
            "+2025 report",
            " footer",
            "*** End Patch",
        ]
    )

    result = _run(apply_patch(patch))

    assert result["success"] is True
    assert result["updates"] == 1
    assert target.read_text(encoding="utf-8") == "header\n2025 report\nfooter\n"


def test_apply_patch_move_only_renames_file(local_patch_env):
    source = local_patch_env / "from.md"
    destination = local_patch_env / "to.md"
    source.write_text("keep this\n", encoding="utf-8")

    patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Update File: from.md",
            "*** Move to: to.md",
            "*** End Patch",
        ]
    )

    result = _run(apply_patch(patch))

    assert result["success"] is True
    assert result["moves"] == 1
    assert result["updates"] == 0
    assert source.exists() is False
    assert destination.read_text(encoding="utf-8") == "keep this\n"


def test_apply_patch_accepts_whitespace_normalized_context(local_patch_env):
    target = local_patch_env / "whitespace.py"
    target.write_text("def demo():\n\treturn 1\n", encoding="utf-8")

    patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Update File: whitespace.py",
            "@@",
            "-def demo():",
            "-    return 1",
            "+def demo():",
            "+    return 2",
            "*** End Patch",
        ]
    )

    result = _run(apply_patch(patch, backup=False))

    assert result["success"] is True
    assert result["updates"] == 1
    assert any("whitespace-normalized context" in warning for warning in result["warnings"])
    assert target.read_text(encoding="utf-8") == "def demo():\n    return 2\n"
