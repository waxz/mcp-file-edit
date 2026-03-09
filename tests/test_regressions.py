#!/usr/bin/env python3
"""Focused regression tests for state, SSH behavior, and command safety."""

import sys
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

if "fastmcp" not in sys.modules:
    fastmcp_stub = types.ModuleType("fastmcp")

    class _FastMCP:
        def __init__(self, name):
            self.name = name

        def tool(self):
            def _decorator(fn):
                return fn

            return _decorator

        def run(self, *args, **kwargs):
            return None

    fastmcp_stub.FastMCP = _FastMCP
    sys.modules["fastmcp"] = fastmcp_stub

from mcp_file_edit import utils
from mcp_file_edit import config as app_config
from mcp_file_edit import file_tools
from mcp_file_edit import ssh_tools
from mcp_file_edit.file_operations import SSHFileOperations
from mcp_file_edit.git_operations import SSHGitOperations
from mcp_file_edit.ssh_manager import SSHConnectionManager


class _StateGuard:
    def __init__(self):
        self.file_ops = utils.FILE_OPS
        self.connection_type = utils.CONNECTION_TYPE
        self.project_dir = utils.PROJECT_DIR

    def restore(self):
        utils.FILE_OPS = self.file_ops
        utils.CONNECTION_TYPE = self.connection_type
        utils.PROJECT_DIR = self.project_dir


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

    if "mcp_file_edit.server" in sys.modules:
        return importlib.reload(sys.modules["mcp_file_edit.server"])
    return importlib.import_module("mcp_file_edit.server")


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


def test_set_project_directory_respects_allow_directories_allow_case(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        allowed_root = Path(tmpdir) / "allowed"
        project_dir = allowed_root / "project"
        project_dir.mkdir(parents=True)

        monkeypatch.setattr(sys, "argv", ["server.py", "--allow-directories", str(allowed_root)])

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

        monkeypatch.setattr(sys, "argv", ["server.py", "--allow-directories", str(allowed_root)])

        server = _import_server_for_tests()

        with pytest.raises(ValueError, match="not allowed"):
            _run(server.set_project_directory(str(blocked_root)))


def test_cli_allow_directories_overrides_runtime_config(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["server.py", "--allow-directories", "/tmp/a:/tmp/b"])

    _import_server_for_tests()
    roots = utils.get_allow_directories()
    assert len(roots) == 2
    assert str(roots[0]).endswith("/tmp/a")
    assert str(roots[1]).endswith("/tmp/b")


def test_get_allow_directories_linux_style_separator(monkeypatch):
    monkeypatch.setattr(app_config.os, "pathsep", ":")
    app_config.configure_runtime(allow_directories_raw="/tmp/a:/tmp/b")

    roots = utils.get_allow_directories()

    assert len(roots) == 2
    assert str(roots[0]).endswith("/tmp/a")
    assert str(roots[1]).endswith("/tmp/b")


def test_get_allow_directories_windows_style_separator(monkeypatch):
    monkeypatch.setattr(app_config.os, "pathsep", ";")
    app_config.configure_runtime(allow_directories_raw="/tmp/a;/tmp/b")

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
