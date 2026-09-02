"""Tests for the Anthropic-compatible str_replace_based_edit_tool."""

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
from mcp_file_edit.text_editor_tool import _EDIT_HISTORY, str_replace_based_edit_tool


def _run(awaitable):
    return asyncio.run(awaitable)


@pytest.fixture
def local_edit_env(tmp_path):
    original_file_ops = utils.FILE_OPS
    original_connection_type = utils.CONNECTION_TYPE
    original_project_dir = utils.PROJECT_DIR

    utils.FILE_OPS = LocalFileOperations()
    utils.CONNECTION_TYPE = "local"
    utils.PROJECT_DIR = tmp_path

    _EDIT_HISTORY.clear()

    try:
        yield tmp_path
    finally:
        utils.FILE_OPS = original_file_ops
        utils.CONNECTION_TYPE = original_connection_type
        utils.PROJECT_DIR = original_project_dir
        _EDIT_HISTORY.clear()


def test_view_file_numbers_lines(local_edit_env):
    (local_edit_env / "hello.py").write_text("a = 1\nb = 2\n", encoding="utf-8")

    result = _run(str_replace_based_edit_tool(command="view", path="hello.py"))

    assert "1\ta = 1" in result["output"]
    assert "2\tb = 2" in result["output"]
    assert result["type"] == "file"


def test_view_file_with_range(local_edit_env):
    (local_edit_env / "hello.py").write_text("l1\nl2\nl3\nl4\n", encoding="utf-8")

    result = _run(
        str_replace_based_edit_tool(command="view", path="hello.py", view_range=[2, 3])
    )

    assert result["content"] == "l2\nl3"
    assert "l1" not in result["output"]


def test_view_directory_lists_entries(local_edit_env):
    (local_edit_env / "sub").mkdir()
    (local_edit_env / "sub" / "nested.txt").write_text("x", encoding="utf-8")
    (local_edit_env / "top.txt").write_text("y", encoding="utf-8")

    result = _run(str_replace_based_edit_tool(command="view", path="."))

    assert result["type"] == "directory"
    names = {Path(e).name for e in result["entries"]}
    assert "top.txt" in names
    assert "nested.txt" in names


def test_create_writes_new_file(local_edit_env):
    result = _run(
        str_replace_based_edit_tool(
            command="create", path="new_module.py", file_text="print('hi')\n"
        )
    )

    assert "created successfully" in result["output"]
    assert (local_edit_env / "new_module.py").read_text(encoding="utf-8") == "print('hi')\n"


def test_create_requires_file_text(local_edit_env):
    with pytest.raises(ValueError, match="file_text"):
        _run(str_replace_based_edit_tool(command="create", path="new_module.py"))


def test_str_replace_updates_unique_match(local_edit_env):
    target = local_edit_env / "config.py"
    target.write_text("DEBUG = False\nOTHER = 1\n", encoding="utf-8")

    result = _run(
        str_replace_based_edit_tool(
            command="str_replace",
            path="config.py",
            old_str="DEBUG = False",
            new_str="DEBUG = True",
        )
    )

    assert target.read_text(encoding="utf-8") == "DEBUG = True\nOTHER = 1\n"
    assert result["replaced"] == 1


def test_str_replace_fails_when_not_found(local_edit_env):
    target = local_edit_env / "config.py"
    target.write_text("DEBUG = False\n", encoding="utf-8")

    with pytest.raises(ValueError, match="did not appear verbatim"):
        _run(
            str_replace_based_edit_tool(
                command="str_replace",
                path="config.py",
                old_str="DOES_NOT_EXIST",
                new_str="x",
            )
        )


def test_str_replace_fails_when_ambiguous(local_edit_env):
    target = local_edit_env / "config.py"
    target.write_text("x = 1\nx = 1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="not unique"):
        _run(
            str_replace_based_edit_tool(
                command="str_replace", path="config.py", old_str="x = 1", new_str="x = 2"
            )
        )


def test_insert_adds_line_at_position(local_edit_env):
    target = local_edit_env / "file.txt"
    target.write_text("line1\nline2\n", encoding="utf-8")

    _run(
        str_replace_based_edit_tool(
            command="insert", path="file.txt", insert_line=1, new_str="inserted"
        )
    )

    assert target.read_text(encoding="utf-8") == "line1\ninserted\nline2\n"


def test_insert_at_start_of_file(local_edit_env):
    target = local_edit_env / "file.txt"
    target.write_text("line1\n", encoding="utf-8")

    _run(
        str_replace_based_edit_tool(
            command="insert", path="file.txt", insert_line=0, new_str="line0"
        )
    )

    assert target.read_text(encoding="utf-8") == "line0\nline1\n"


def test_insert_out_of_range_rejected(local_edit_env):
    target = local_edit_env / "file.txt"
    target.write_text("line1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="out of range"):
        _run(
            str_replace_based_edit_tool(
                command="insert", path="file.txt", insert_line=99, new_str="x"
            )
        )


def test_undo_edit_reverts_str_replace(local_edit_env):
    target = local_edit_env / "config.py"
    target.write_text("DEBUG = False\n", encoding="utf-8")

    _run(
        str_replace_based_edit_tool(
            command="str_replace",
            path="config.py",
            old_str="DEBUG = False",
            new_str="DEBUG = True",
        )
    )
    assert target.read_text(encoding="utf-8") == "DEBUG = True\n"

    _run(str_replace_based_edit_tool(command="undo_edit", path="config.py"))
    assert target.read_text(encoding="utf-8") == "DEBUG = False\n"


def test_undo_edit_removes_created_file(local_edit_env):
    target = local_edit_env / "brand_new.txt"

    _run(
        str_replace_based_edit_tool(
            command="create", path="brand_new.txt", file_text="hello\n"
        )
    )
    assert target.exists()

    _run(str_replace_based_edit_tool(command="undo_edit", path="brand_new.txt"))
    assert not target.exists()


def test_undo_edit_without_history_raises(local_edit_env):
    (local_edit_env / "file.txt").write_text("content\n", encoding="utf-8")

    with pytest.raises(ValueError, match="No edit history"):
        _run(str_replace_based_edit_tool(command="undo_edit", path="file.txt"))


def test_str_replace_requires_existing_file(local_edit_env):
    with pytest.raises(ValueError, match="does not exist"):
        _run(
            str_replace_based_edit_tool(
                command="str_replace", path="missing.txt", old_str="a", new_str="b"
            )
        )


def test_path_traversal_rejected(local_edit_env):
    with pytest.raises(ValueError, match="Invalid path"):
        _run(
            str_replace_based_edit_tool(
                command="view", path="../outside.txt"
            )
        )


def test_unknown_command_rejected(local_edit_env):
    (local_edit_env / "file.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="Unknown command"):
        _run(str_replace_based_edit_tool(command="delete", path="file.txt"))
