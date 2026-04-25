#!/usr/bin/env python3
"""Focused regression tests for state, SSH behavior, and command safety."""

import sys
import os
import asyncio
import tempfile
import importlib
from pathlib import Path
from types import SimpleNamespace
import types

# Ensure local package imports work without installation.
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest

# Provide a lightweight asyncssh stub when dependency is unavailable in test env.
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

if "toml" not in sys.modules:
    toml_stub = types.ModuleType("toml")
    toml_stub.load = lambda *args, **kwargs: {}
    toml_stub.loads = lambda *args, **kwargs: {}
    sys.modules["toml"] = toml_stub

if "fastmcp" not in sys.modules:
    fastmcp_stub = types.ModuleType("fastmcp")

    class _FastMCP:
        def __init__(self, name):
            self.name = name

        def tool(self, *args, **kwargs):
            if args and callable(args[0]) and len(args) == 1 and not kwargs:
                fn = args[0]
                setattr(self, fn.__name__, fn)
                return fn

            def _decorator(fn):
                setattr(self, fn.__name__, fn)
                return fn

            return _decorator

        def add_middleware(self, middleware):
            return None

        def run(self, *args, **kwargs):
            return None

    class _Context:
        pass

    fastmcp_stub.FastMCP = _FastMCP
    fastmcp_stub.Context = _Context
    sys.modules["fastmcp"] = fastmcp_stub

if "fastmcp.server.tasks" not in sys.modules:
    tasks_stub = types.ModuleType("fastmcp.server.tasks")

    class _TaskConfig:
        def __init__(self, *args, **kwargs):
            pass

    tasks_stub.TaskConfig = _TaskConfig
    sys.modules["fastmcp.server.tasks"] = tasks_stub

if "fastmcp.server.middleware" not in sys.modules:
    middleware_stub = types.ModuleType("fastmcp.server.middleware")

    class _Middleware:
        pass

    class _MiddlewareContext:
        def __init__(self, message=None):
            self.message = message

    middleware_stub.Middleware = _Middleware
    middleware_stub.MiddlewareContext = _MiddlewareContext
    sys.modules["fastmcp.server.middleware"] = middleware_stub

if "fastmcp.server.dependencies" not in sys.modules:
    dependencies_stub = types.ModuleType("fastmcp.server.dependencies")
    dependencies_stub.get_http_headers = lambda: {}
    sys.modules["fastmcp.server.dependencies"] = dependencies_stub

if "fastmcp.exceptions" not in sys.modules:
    exceptions_stub = types.ModuleType("fastmcp.exceptions")

    class _ToolError(Exception):
        pass

    exceptions_stub.ToolError = _ToolError
    sys.modules["fastmcp.exceptions"] = exceptions_stub

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

if "mcp.server" not in sys.modules:
    sys.modules["mcp.server"] = types.ModuleType("mcp.server")

if "mcp.server.session" not in sys.modules:
    session_stub = types.ModuleType("mcp.server.session")

    class _ServerSession:
        async def _send_response(self, request_id, response):
            return None

    session_stub.ServerSession = _ServerSession
    sys.modules["mcp.server.session"] = session_stub

from mcp_file_edit import utils
from mcp_file_edit import config as app_config
from mcp_file_edit import file_tools
from mcp_file_edit import ssh_tools
from mcp_file_edit.file_patch_tools import (
    apply_patch as apply_codex_patch,
    _build_patch_preview_result,
    attach_patch_preview_session,
)
from mcp_file_edit.file_operations import SSHFileOperations
from mcp_file_edit.git_operations import SSHGitOperations
from mcp_file_edit.patch_preview_store import create_patch_preview_session, set_patch_preview_status
from mcp_file_edit.ssh_manager import SSHConnectionManager


class _StateGuard:
    def __init__(self):
        self.file_ops = utils.FILE_OPS
        self.connection_type = utils.CONNECTION_TYPE
        self.project_dir = utils.PROJECT_DIR
        self.base_dir = utils.BASE_DIR
        self.git_ops = utils.GIT_OPS
        self.settings = app_config.SETTINGS

    def restore(self):
        utils.FILE_OPS = self.file_ops
        utils.CONNECTION_TYPE = self.connection_type
        utils.PROJECT_DIR = self.project_dir
        utils.BASE_DIR = self.base_dir
        utils.GIT_OPS = self.git_ops
        app_config.SETTINGS = self.settings


class FakeListOps:
    def __init__(self):
        self.listdir_calls = 0

    async def listdir(self, path):
        self.listdir_calls += 1
        return []

    async def is_dir(self, path):
        return False


class FakeDeleteOps:
    def __init__(self):
        self.rmtree_called = False
        self.remove_called = False

    async def exists(self, path):
        return True

    async def is_dir(self, path):
        return True

    async def listdir(self, path):
        return []

    async def rmtree(self, path):
        self.rmtree_called = True

    async def remove(self, path):
        self.remove_called = True


class FakeLocalOps:
    async def exists(self, path):
        return True

    async def is_file(self, path):
        return True

    async def is_dir(self, path):
        return False

    async def read_binary(self, path):
        return b"abc"

    async def write_file(self, path, content):
        return None


class FakeRemoteOps:
    def __init__(self):
        self.last_write = None

    async def exists(self, path):
        return False

    async def is_dir(self, path):
        return False

    async def write_file(self, path, content):
        self.last_write = (path, content)


class FakePatchOps:
    def __init__(self, files):
        self.files = dict(files)
        self.writes = []

    async def exists(self, path):
        return str(path) in self.files

    async def read_file(self, path, encoding="utf-8"):
        return self.files[str(path)]

    async def write_file(self, path, content, encoding="utf-8"):
        self.files[str(path)] = content
        self.writes.append((str(path), content))

    async def stat(self, path):
        return SimpleNamespace(st_size=len(self.files[str(path)]))

    async def remove(self, path):
        self.files.pop(str(path), None)


class FakeConn:
    def __init__(self):
        self.last_command = None

    def get_extra_info(self, key):
        if key == "peername":
            return ("127.0.0.1", 22)
        return None

    async def run(self, command, check=False):
        self.last_command = command
        return SimpleNamespace(stdout="", stderr="", returncode=0)


class NoRunConn(FakeConn):
    async def run(self, command, check=False):
        raise AssertionError("search_files should not call conn.run")


class FakeSFTP:
    async def listdir(self, path):
        return []


def _run(coro):
    return asyncio.run(coro)


def test_apply_patch_rejects_mismatched_removal_lines():
    guard = _StateGuard()
    try:
        project_dir = Path("/tmp/mcp-file-edit-regression")
        utils.PROJECT_DIR = project_dir
        utils.CONNECTION_TYPE = "local"
        target = project_dir / "demo.txt"
        utils.FILE_OPS = FakePatchOps({str(target): "hello mcp\n"})

        patch = """*** Begin Patch
*** Update File: demo.txt
@@
-Hello
+Hello world
*** End Patch"""

        result = _run(
            apply_codex_patch(
                patch,
                backup=False,
                dry_run=True,
                create_dirs=False,
                validate_first=True,
            )
        )

        assert result["success"] is False
        assert result["partial_success"] is False
        assert result["operations_applied"] == 1
        assert "Failed to locate patch context exactly" in result["changes"][0]["error"]
    finally:
        guard.restore()


def test_apply_patch_accepts_whitespace_normalized_hunk_match():
    guard = _StateGuard()
    try:
        project_dir = Path("/tmp/mcp-file-edit-regression")
        utils.PROJECT_DIR = project_dir
        utils.CONNECTION_TYPE = "local"
        target = project_dir / "demo.txt"
        utils.FILE_OPS = FakePatchOps({str(target): "def demo():\n\treturn 1\n"})

        patch = """*** Begin Patch
*** Update File: demo.txt
@@
-def demo():
-    return 1
+def demo():
+    return 2
*** End Patch"""

        result = _run(
            apply_codex_patch(
                patch,
                backup=False,
                dry_run=False,
                create_dirs=False,
                validate_first=True,
            )
        )

        assert result["success"] is True
        assert result["updates"] == 1
        assert any(
            "whitespace-normalized context" in warning
            for warning in result["warnings"]
        )
        assert utils.FILE_OPS.files[str(target)] == "def demo():\n    return 2\n"
    finally:
        guard.restore()


def test_apply_patch_rejects_ambiguous_whitespace_normalized_match():
    guard = _StateGuard()
    try:
        project_dir = Path("/tmp/mcp-file-edit-regression")
        utils.PROJECT_DIR = project_dir
        utils.CONNECTION_TYPE = "local"
        target = project_dir / "demo.txt"
        utils.FILE_OPS = FakePatchOps(
            {str(target): "value  = 1\n\nvalue\t=\t1\n"}
        )

        patch = """*** Begin Patch
*** Update File: demo.txt
@@
-value = 1
+value = 2
*** End Patch"""

        result = _run(
            apply_codex_patch(
                patch,
                backup=False,
                dry_run=True,
                create_dirs=False,
                validate_first=True,
            )
        )

        assert result["success"] is False
        assert "ambiguous" in result["changes"][0]["error"]
    finally:
        guard.restore()


def _import_server_for_tests():
    # Isolate set_project_directory tests from unrelated import issues in code_analyzer.
    analyzer_stub = types.ModuleType("mcp_file_edit.code_analyzer")

    async def _noop(*args, **kwargs):
        return {}

    analyzer_stub.list_functions = _noop
    analyzer_stub.get_function_at_line = _noop
    analyzer_stub.get_code_structure = _noop
    analyzer_stub.search_functions = _noop
    sys.modules["mcp_file_edit.code_analyzer"] = analyzer_stub

    lint_stub = types.ModuleType("mcp_file_edit.linting_tools")
    lint_stub.detect_linters = _noop
    lint_stub.run_linter = _noop
    lint_stub.lint_file = _noop
    lint_stub.run_type_checker = _noop
    lint_stub.type_check_file = _noop
    lint_stub.format_file = _noop
    sys.modules["mcp_file_edit.linting_tools"] = lint_stub

    config_module = importlib.import_module("mcp_file_edit.config")
    cli_flags = {"-d", "--directories", "-t", "--transport", "-H", "--host", "-P", "--port", "-p", "--path", "-w", "--workdir", "-c", "--config"}
    old_argv = sys.argv[:]
    try:
        if not any(arg in cli_flags for arg in sys.argv[1:]):
            sys.argv = [sys.argv[0]]
        args = config_module.parse_args()
    finally:
        sys.argv = old_argv
    config_module.SETTINGS = config_module.Settings.from_runtime(args)

    tool_handlers = importlib.import_module("mcp_file_edit.tool_handlers")
    from fastmcp import FastMCP

    app = FastMCP("test-server")
    tool_handlers.register_tools(app)
    return app


def test_file_tools_uses_live_utils_state():
    state = _StateGuard()
    try:
        fake_ops = FakeListOps()
        utils.FILE_OPS = fake_ops

        async def _collect_items():
            return [item async for item in file_tools.walk_with_depth_async(Path("."), "*")]

        items = _run(_collect_items())

        assert items == []
        assert fake_ops.listdir_calls == 1
    finally:
        state.restore()


def test_apply_patch_tool_description_mentions_preview_workflow():
    app = _import_server_for_tests()
    description = app.apply_patch.__doc__ or ""

    assert "preview_id" in description
    assert "confirm_patch_preview" in description
    assert "apply_confirmed_patch" in description
    assert "both stdio and http" in description.lower()


def test_preview_patch_tool_description_mentions_read_only_workflow():
    app = _import_server_for_tests()
    description = app.preview_patch.__doc__ or ""

    assert "does not create a review session" in description
    assert "does not return a" in description
    assert "preview_id" in description
    assert "dry_run=True" in description


def test_attach_patch_preview_session_only_exposes_confirm_flow_for_valid_preview():
    tool_result = _build_patch_preview_result(
        "*** Begin Patch\n*** Add File: demo.txt\n+hello\n*** End Patch",
        {
            "success": True,
            "partial_success": False,
            "updates": 0,
            "adds": 1,
            "deletes": 0,
            "warnings": [],
            "changes": [
                {
                    "type": "add",
                    "path": "/tmp/demo.txt",
                    "success": True,
                    "new_content": "hello\n",
                }
            ],
        },
    )

    attached = attach_patch_preview_session(tool_result, "patch")
    text = attached.content[0].text

    assert "preview_session" in attached.structured_content
    assert "Review workflow:" in text
    assert "confirm_patch_preview(preview_id=...)" in text
    assert "apply_confirmed_patch(preview_id=...)" in text
    assert "dry_run=False" not in text


def test_attach_patch_preview_session_hides_confirm_flow_for_failed_preview():
    tool_result = _build_patch_preview_result(
        "*** Begin Patch\n*** Update File: README.md\n@@\n-old\n+new\n*** End Patch",
        {
            "success": False,
            "partial_success": False,
            "updates": 0,
            "adds": 0,
            "deletes": 0,
            "warnings": ["README.md: Patch validation error"],
            "changes": [
                {
                    "type": "update",
                    "path": "/tmp/README.md",
                    "success": False,
                    "error": "Failed to locate patch context exactly: 'old'",
                }
            ],
        },
    )

    attached = attach_patch_preview_session(tool_result, "patch")
    text = attached.content[0].text

    assert "preview_session" not in attached.structured_content
    assert "Preview workflow:" in text
    assert "not actionable because validation failed" in text
    assert "confirm_patch_preview(preview_id=...)" not in text
    assert "apply_confirmed_patch(preview_id=...)" not in text
    assert "dry_run=False" not in text


def test_apply_confirmed_patch_uses_reviewed_preview_contents():
    state = _StateGuard()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "demo.txt"
            target.write_text("before\n", encoding="utf-8")

            utils.FILE_OPS = utils.LocalFileOperations()
            utils.CONNECTION_TYPE = "local"
            utils.PROJECT_DIR = root

            app = _import_server_for_tests()
            utils.PROJECT_DIR = root
            session = create_patch_preview_session(
                "*** Begin Patch\n*** Update File: demo.txt\n@@\n-before\n+after\n*** End Patch",
                {
                    "summary": {"updates": 1, "adds": 0, "deletes": 0, "warnings": []},
                    "files": [
                        {
                            "path": str(target),
                            "filename": "demo.txt",
                            "type": "update",
                            "diff": "--- a/demo.txt\n+++ b/demo.txt\n@@ -1 +1 @@\n-before\n+after\n",
                            "original_content": "before\n",
                            "new_content": "after reviewed by human\n",
                        }
                    ],
                },
            )
            set_patch_preview_status(
                session.preview_id,
                token=session.confirm_token,
                status="confirmed",
            )

            result = _run(
                app.apply_confirmed_patch(
                    preview_id=session.preview_id,
                    backup=False,
                    create_dirs=False,
                    validate_first=True,
                )
            )

            assert result["success"] is True
            assert target.read_text(encoding="utf-8") == "after reviewed by human\n"
    finally:
        state.restore()


def test_delete_file_empty_directory_uses_rmtree():
    state = _StateGuard()
    try:
        fake_ops = FakeDeleteOps()
        utils.FILE_OPS = fake_ops
        utils.CONNECTION_TYPE = "ssh"
        utils.PROJECT_DIR = Path("/")

        _run(file_tools.delete_file("empty_dir", recursive=False))

        assert fake_ops.rmtree_called is True
        assert fake_ops.remove_called is False
    finally:
        state.restore()


def test_ssh_upload_uses_binary_read_and_write_file(monkeypatch):
    state = _StateGuard()
    try:
        fake_remote = FakeRemoteOps()
        utils.FILE_OPS = fake_remote
        utils.CONNECTION_TYPE = "ssh"
        utils.PROJECT_DIR = Path("/remote")

        monkeypatch.setattr(ssh_tools, "LocalFileOperations", FakeLocalOps)

        result = _run(ssh_tools.ssh_upload("dummy.txt", "dest.bin"))

        assert result["uploaded"] == 1
        assert fake_remote.last_write is not None
        assert fake_remote.last_write[1] == b"abc"
    finally:
        state.restore()


def test_ssh_manager_properties_expose_connection_params():
    manager = SSHConnectionManager()
    manager._connection_params = {
        "host": "example.com",
        "username": "alice",
        "port": 2222,
        "client_keys": ["/tmp/id_rsa"],
    }

    assert manager.host == "example.com"
    assert manager.username == "alice"
    assert manager.port == 2222
    assert manager.key_filename == "/tmp/id_rsa"


def test_apply_patch_updates_file_with_context_hunks():
    state = _StateGuard()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "sample.py"
            target.write_text("def old_name():\n    return 1\n", encoding="utf-8")

            utils.FILE_OPS = utils.LocalFileOperations()
            utils.CONNECTION_TYPE = "local"
            utils.PROJECT_DIR = root

            result = _run(
                file_tools.apply_patch(
                    "\n".join(
                        [
                            "*** Begin Patch",
                            "*** Update File: sample.py",
                            "@@",
                            "-def old_name():",
                            "-    return 1",
                            "+def new_name():",
                            "+    return 2",
                            "*** End Patch",
                        ]
                    )
                )
            )

            assert result["success"] is True
            assert target.read_text(encoding="utf-8") == "def new_name():\n    return 2\n"
    finally:
        state.restore()


def test_apply_patch_adds_and_deletes_files():
    state = _StateGuard()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            existing = root / "obsolete.txt"
            existing.write_text("remove me\n", encoding="utf-8")

            utils.FILE_OPS = utils.LocalFileOperations()
            utils.CONNECTION_TYPE = "local"
            utils.PROJECT_DIR = root

            patch = "\n".join(
                [
                    "*** Begin Patch",
                    "*** Add File: created.txt",
                    "+hello",
                    "+world",
                    "*** Delete File: obsolete.txt",
                    "*** End Patch",
                ]
            )

            result = _run(file_tools.apply_patch(patch))

            assert result["success"] is True
            assert (root / "created.txt").read_text(encoding="utf-8") == "hello\nworld\n"
            assert existing.exists() is False
    finally:
        state.restore()


def test_apply_patch_moves_file_when_move_to_is_present():
    state = _StateGuard()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "before.txt"
            source.write_text("old line\n", encoding="utf-8")

            utils.FILE_OPS = utils.LocalFileOperations()
            utils.CONNECTION_TYPE = "local"
            utils.PROJECT_DIR = root

            patch = "\n".join(
                [
                    "*** Begin Patch",
                    "*** Update File: before.txt",
                    "*** Move to: after.txt",
                    "@@",
                    "-old line",
                    "+new line",
                    "*** End Patch",
                ]
            )

            result = _run(file_tools.apply_patch(patch))

            assert result["success"] is True
            assert source.exists() is False
            assert (root / "after.txt").read_text(encoding="utf-8") == "new line\n"
    finally:
        state.restore()


def test_apply_patch_move_only_preserves_file_content():
    state = _StateGuard()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "from.txt"
            source.write_text("keep this\n", encoding="utf-8")

            utils.FILE_OPS = utils.LocalFileOperations()
            utils.CONNECTION_TYPE = "local"
            utils.PROJECT_DIR = root

            patch = "\n".join(
                [
                    "*** Begin Patch",
                    "*** Update File: from.txt",
                    "*** Move to: to.txt",
                    "*** End Patch",
                ]
            )

            result = _run(file_tools.apply_patch(patch))

            assert result["success"] is True
            assert result["moves"] == 1
            assert source.exists() is False
            assert (root / "to.txt").read_text(encoding="utf-8") == "keep this\n"
    finally:
        state.restore()


def test_apply_patch_honors_end_of_file_marker():
    state = _StateGuard()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            utils.FILE_OPS = utils.LocalFileOperations()
            utils.CONNECTION_TYPE = "local"
            utils.PROJECT_DIR = root

            patch = "\n".join(
                [
                    "*** Begin Patch",
                    "*** Add File: nonewline.txt",
                    "+no trailing newline",
                    "*** End of File",
                    "*** End Patch",
                ]
            )

            result = _run(file_tools.apply_patch(patch))

            assert result["success"] is True
            assert (root / "nonewline.txt").read_text(encoding="utf-8") == "no trailing newline"
    finally:
        state.restore()


def test_apply_patch_dry_run_does_not_modify_files():
    state = _StateGuard()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "sample.txt"
            target.write_text("before\n", encoding="utf-8")

            utils.FILE_OPS = utils.LocalFileOperations()
            utils.CONNECTION_TYPE = "local"
            utils.PROJECT_DIR = root

            patch = "\n".join(
                [
                    "*** Begin Patch",
                    "*** Update File: sample.txt",
                    "@@",
                    "-before",
                    "+after",
                    "*** End Patch",
                ]
            )

            result = _run(apply_codex_patch(patch, dry_run=True))

            assert result["success"] is True
            assert target.read_text(encoding="utf-8") == "before\n"
    finally:
        state.restore()


def test_apply_patch_appends_after_context_line():
    state = _StateGuard()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "README.md"
            target.write_text(
                "## License\nThis project is licensed under the MIT License. See [LICENSE](LICENSE) for details.\n",
                encoding="utf-8",
            )

            utils.FILE_OPS = utils.LocalFileOperations()
            utils.CONNECTION_TYPE = "local"
            utils.PROJECT_DIR = root

            patch = "\n".join(
                [
                    "*** Begin Patch",
                    "*** Update File: README.md",
                    "@@",
                    "This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.",
                    "+",
                    "+## Fun Fact",
                    "+Why did the AI program go on a diet? It wanted to lose some bytes!",
                    "*** End Patch",
                ]
            )

            result = _run(apply_codex_patch(patch, dry_run=True))

            assert result["success"] is True
            assert result["updates"] == 1
            assert "## Fun Fact" in result["changes"][0]["diff"]
    finally:
        state.restore()


def test_patch_file_unified_diff_uses_shared_hunk_logic():
    state = _StateGuard()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "u.txt"
            target.write_text("alpha\nbeta\n", encoding="utf-8")

            utils.FILE_OPS = utils.LocalFileOperations()
            utils.CONNECTION_TYPE = "local"
            utils.PROJECT_DIR = root

            result = _run(
                file_tools.patch_file(
                    "u.txt",
                    patches=[
                        {
                            "unified_diff": "\n".join(
                                [
                                    "--- a/u.txt",
                                    "+++ b/u.txt",
                                    "@@",
                                    "-alpha",
                                    "+ALPHA",
                                    " beta",
                                ]
                            )
                        }
                    ],
                )
            )

            assert result["success"] is True
            assert target.read_text(encoding="utf-8") == "ALPHA\nbeta\n"
    finally:
        state.restore()


def test_patch_file_literal_match_falls_back_to_whitespace_normalized_search():
    state = _StateGuard()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "pattern.txt"
            target.write_text("def demo():\n\treturn 1\n", encoding="utf-8")

            utils.FILE_OPS = utils.LocalFileOperations()
            utils.CONNECTION_TYPE = "local"
            utils.PROJECT_DIR = root

            result = _run(
                file_tools.patch_file(
                    "pattern.txt",
                    patches=[
                        {
                            "find": "def demo():\n    return 1\n",
                            "replace": "def demo():\n    return 2\n",
                        }
                    ],
                    backup=False,
                )
            )

            assert result["success"] is True
            assert result["patches_applied"] == 1
            assert result["changes"][0]["match_method"] == "whitespace_normalized"
            assert target.read_text(encoding="utf-8") == "def demo():\n    return 2\n"
    finally:
        state.restore()


def test_ssh_git_command_quotes_arguments_and_cwd():
    conn = FakeConn()
    ops = SSHGitOperations(conn, object())

    _run(ops.run_git_command(["status; echo hacked", "--porcelain"], cwd=Path("/tmp/space dir")))

    assert conn.last_command is not None
    assert "cd '/tmp/space dir' && git" in conn.last_command
    assert "'status; echo hacked'" in conn.last_command


def test_ssh_git_command_quotes_cwd_injection_string():
    conn = FakeConn()
    ops = SSHGitOperations(conn, object())

    _run(
        ops.run_git_command(
            ["status"],
            cwd=Path("/tmp/repo; echo injected"),
        )
    )

    assert conn.last_command is not None
    assert "cd '/tmp/repo; echo injected' && git status" in conn.last_command


def test_path_protection_blocks_parent_traversal():
    state = _StateGuard()
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        escape_path = project_root.parent / "escape.txt"
        escape_path.write_text("data", encoding="utf-8")

        try:
            utils.CONNECTION_TYPE = "local"
            utils.PROJECT_DIR = project_root

            with pytest.raises(ValueError, match="directory traversal"):
                _run(file_tools.read_file("../escape.txt"))
        finally:
            state.restore()


def test_path_protection_blocks_absolute_path_outside_project():
    state = _StateGuard()
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        outside = project_root.parent / "outside.txt"
        outside.write_text("data", encoding="utf-8")

        try:
            utils.CONNECTION_TYPE = "local"
            utils.PROJECT_DIR = project_root

            with pytest.raises(ValueError, match="directory traversal"):
                _run(file_tools.read_file(str(outside)))
        finally:
            state.restore()


def test_list_files_skips_symlink_escaping_project_root():
    state = _StateGuard()
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir) / "project"
        project_root.mkdir()
        outside = Path(tmpdir) / "outside.txt"
        outside.write_text("secret", encoding="utf-8")
        link_path = project_root / "outside-link.txt"

        try:
            os.symlink(outside, link_path)
        except (AttributeError, NotImplementedError, OSError):
            pytest.skip("symlinks unavailable on this platform")

        try:
            utils.CONNECTION_TYPE = "local"
            utils.PROJECT_DIR = project_root

            result = _run(file_tools.list_files(".", pattern="*.txt"))
            assert result == []
        finally:
            state.restore()


def test_search_files_skips_symlink_escaping_project_root():
    state = _StateGuard()
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir) / "project"
        project_root.mkdir()
        outside = Path(tmpdir) / "outside.txt"
        outside.write_text("needle\n", encoding="utf-8")
        link_path = project_root / "outside-link.txt"

        try:
            os.symlink(outside, link_path)
        except (AttributeError, NotImplementedError, OSError):
            pytest.skip("symlinks unavailable on this platform")

        try:
            utils.CONNECTION_TYPE = "local"
            utils.PROJECT_DIR = project_root

            result = _run(file_tools.search_files("needle", ".", file_pattern="*.txt"))
            assert result["results"] == []
            assert result["completed"] is True
        finally:
            state.restore()


def test_replace_in_files_skips_symlink_escaping_project_root():
    state = _StateGuard()
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir) / "project"
        project_root.mkdir()
        outside = Path(tmpdir) / "outside.txt"
        outside.write_text("needle\n", encoding="utf-8")
        link_path = project_root / "outside-link.txt"

        try:
            os.symlink(outside, link_path)
        except (AttributeError, NotImplementedError, OSError):
            pytest.skip("symlinks unavailable on this platform")

        try:
            utils.CONNECTION_TYPE = "local"
            utils.PROJECT_DIR = project_root

            result = _run(file_tools.replace_in_files("needle", "patched", ".", file_pattern="*.txt"))
            assert result["results"] == []
            assert outside.read_text(encoding="utf-8") == "needle\n"
        finally:
            state.restore()


def test_set_project_directory_respects_allow_directories_allow_case(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        allowed_root = base / "allowed"
        project_dir = allowed_root / "project"
        project_dir.mkdir(parents=True)

        monkeypatch.setattr(
            sys, "argv", ["server.py", "--workdir", str(base), "--directories", str(allowed_root)]
        )

        server = _import_server_for_tests()

        result = _run(server.set_project_directory(str(project_dir)))

        assert result["connection_type"] == "local"
        assert Path(result["absolute_path"]).resolve() == project_dir.resolve()


def test_set_project_directory_respects_allow_directories_block_case(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        allowed_root = base / "allowed"
        blocked_root = base / "blocked"
        allowed_root.mkdir(parents=True)
        blocked_root.mkdir(parents=True)

        monkeypatch.setattr(
            sys, "argv", ["server.py", "--workdir", str(base), "--directories", str(allowed_root)]
        )

        server = _import_server_for_tests()

        with pytest.raises(ValueError, match="not allowed"):
            _run(server.set_project_directory(str(blocked_root)))


def test_cli_allow_directories_overrides_runtime_config(monkeypatch):
    monkeypatch.setattr(
        sys, "argv", ["server.py", "--workdir", "/tmp", "--directories", "/tmp/a", "/tmp/b"]
    )

    _import_server_for_tests()
    roots = utils.get_allow_directories()
    assert len(roots) == 2
    assert str(roots[0]).endswith("/tmp/a")
    assert str(roots[1]).endswith("/tmp/b")


def test_settings_default_allowed_directories_to_work_dir():
    settings = app_config.Settings(
        PLATFORM="linux",
        WORK_DIR="/tmp/project",
        ALLOWED_DIRECTORIES=[],
    )

    assert settings.WORK_DIR == "/tmp/project"
    assert settings.ALLOWED_DIRECTORIES == ["/tmp/project"]
    assert utils.PROJECT_DIR == Path("/tmp/project")


def test_settings_defaults_project_dir_to_first_allowed_root_when_work_dir_is_outside():
    settings = app_config.Settings(
        PLATFORM="linux",
        WORK_DIR="/tmp/project",
        ALLOWED_DIRECTORIES=["/tmp/elsewhere", "/tmp/other"],
    )

    assert settings.ALLOWED_DIRECTORIES == ["/tmp/elsewhere", "/tmp/other"]
    assert utils.PROJECT_DIR == Path("/tmp/elsewhere")


def test_get_allow_directories_linux_style_separator(monkeypatch):
    settings = app_config.Settings(
        PLATFORM="linux",
        WORK_DIR="/tmp",
        ALLOWED_DIRECTORIES=["/tmp/a", "/tmp/b"],
    )
    app_config.SETTINGS = settings

    roots = utils.get_allow_directories()

    assert len(roots) == 2
    assert str(roots[0]).endswith("/tmp/a")
    assert str(roots[1]).endswith("/tmp/b")


def test_get_allow_directories_windows_style_separator(monkeypatch):
    settings = app_config.Settings(
        PLATFORM="linux",
        WORK_DIR="/tmp",
        ALLOWED_DIRECTORIES=["/tmp/a", "/tmp/b"],
    )
    app_config.SETTINGS = settings

    roots = utils.get_allow_directories()

    assert len(roots) == 2
    assert str(roots[0]).endswith("/tmp/a")
    assert str(roots[1]).endswith("/tmp/b")


def test_ssh_search_files_does_not_use_remote_shell_command():
    ops = SSHFileOperations(NoRunConn(), FakeSFTP())

    results = _run(ops.search_files(Path("/tmp"), "anything"))

    assert results == []


def test_validate_path_input_allows_relative_posix_path():
    utils.validate_path_input("a/b/c.txt")


@pytest.mark.parametrize(
    "bad_path",
    [
        "../README.md;echo pwn",
        r"..\README.md&whoami",
        "../x.txt|cat /etc/passwd",
        r"..\x.txt`calc`",
        ".\nmalicious",
        ".\x00malicious",
    ],
)
def test_validate_path_input_rejects_injection_metacharacters(bad_path):
    with pytest.raises(ValueError, match="unsafe characters"):
        utils.validate_path_input(bad_path)


def test_validate_path_input_rejects_windows_style_path_on_non_windows(monkeypatch):
    monkeypatch.setattr(utils.os, "name", "posix")
    with pytest.raises(ValueError, match="Windows-style"):
        utils.validate_path_input(r"C:\Users\alice\file.txt")


def test_validate_path_input_rejects_posix_absolute_path_on_windows(monkeypatch):
    monkeypatch.setattr(utils.os, "name", "nt")
    with pytest.raises(ValueError, match="POSIX absolute"):
        utils.validate_path_input("/etc/passwd")
