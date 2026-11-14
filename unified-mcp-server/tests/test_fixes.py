"""Regression tests for bugs fixed relative to the original projects."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import anyio
import pytest
from fastmcp import Client

from unified_mcp_server.config import load_settings
from unified_mcp_server.server import build_server


def _server(tmp_path: Path, *argv: str):
    project = tmp_path / "p"
    project.mkdir(exist_ok=True)
    return build_server(load_settings(["-c", str(tmp_path / "none.toml"), "-w", str(project), *argv]))


# ---------------------------------------------------------- rmtree (py<3.12)
async def test_local_rmtree_works_on_this_python(tmp_path):
    """mcp-file-edit called rmtree(onexc=...), a TypeError before Python 3.12."""
    from unified_mcp_server.files.file_operations import LocalFileOperations

    tree = tmp_path / "tree" / "sub"
    tree.mkdir(parents=True)
    (tree / "f.txt").write_text("x")
    await LocalFileOperations().rmtree(tmp_path / "tree")
    assert not (tmp_path / "tree").exists()


async def test_local_rmtree_calls_error_handler(tmp_path, monkeypatch):
    """The error handler must be wired up on every Python version.

    A failing unlink must reach handle_remove_readonly (via onexc on 3.12+,
    onerror before); the handler then retries the removal.
    """
    from unified_mcp_server.files import file_operations

    calls = []
    real_unlink = os.unlink
    failed_once = set()

    def flaky_unlink(path, *args, **kwargs):
        if str(path).endswith("f.txt") and "f" not in failed_once:
            failed_once.add("f")
            raise PermissionError(13, "simulated read-only file", str(path))
        return real_unlink(path, *args, **kwargs)

    def handler(func, path, exc):
        calls.append((func, path))
        func(path)  # retry, as handle_remove_readonly does after chmod

    monkeypatch.setattr(os, "unlink", flaky_unlink)
    monkeypatch.setattr(file_operations, "handle_remove_readonly", handler)
    tree = tmp_path / "tree" / "sub"
    tree.mkdir(parents=True)
    (tree / "f.txt").write_text("x")
    await file_operations.LocalFileOperations().rmtree(tmp_path / "tree")
    assert calls, "rmtree never called the error handler"
    assert not (tmp_path / "tree").exists()


# ---------------------------------------------------------- async functions
def test_python_analyzer_lists_async_defs():
    from unified_mcp_server.files.code_analyzer import CodeAnalyzer

    src = (
        "import x\n\n"
        "def sync(a: int) -> int:\n    return a\n\n"
        "class A:\n    async def m(self):\n        pass\n\n"
        "async def f():\n    async def inner():\n        pass\n"
    )
    funcs = {f["name"]: f for f in CodeAnalyzer.extract_functions_from_python(src)}
    assert set(funcs) == {"sync", "m", "f", "inner"}
    assert funcs["m"]["is_async"] and funcs["m"]["class_name"] == "A" and funcs["m"]["is_method"]
    assert funcs["f"]["is_async"] and not funcs["f"]["is_method"]
    assert funcs["sync"]["is_async"] is False
    assert funcs["sync"]["return_type"] == "int" and funcs["sync"]["param_types"] == {"a": "int"}


# ------------------------------------------------------------- tmux startup
def test_reset_pane_never_sends_ctrl_c():
    from unified_mcp_server.shell.tmux_commands import build_tmux_reset_pane_command

    cmds = build_tmux_reset_pane_command("native_mcp_x")
    assert not any("C-c" in c for c in cmds)
    assert any("clear-history" in c for c in cmds)


def test_tmux_builders_validate_session_name():
    from unified_mcp_server.shell.tmux_commands import (
        build_tmux_bootstrap_command,
        build_tmux_reset_pane_command,
    )

    with pytest.raises(ValueError):
        build_tmux_bootstrap_command("bad;name")
    with pytest.raises(ValueError):
        build_tmux_reset_pane_command("bad name")
    assert "while" not in build_tmux_bootstrap_command("ok", wait_for_prompt=False)


@pytest.mark.skipif(shutil.which("tmux") is None or sys.platform == "win32", reason="needs tmux")
def test_bootstrap_waits_for_slow_shell(tmp_path):
    """Reproduces the GitHub-runner failure: a pane shell that takes 0.5s to start.

    The original sent C-c right after new-session and killed the starting
    shell. The bootstrap now returns only once the prompt is up, after which a
    C-c is harmless.
    """
    from unified_mcp_server.shell.tmux_commands import build_tmux_bootstrap_command

    slow = tmp_path / "slowsh"
    slow.write_text("#!/bin/sh\nsleep 0.5\nexec /bin/sh -i\n")
    slow.chmod(0o755)
    env = {**os.environ, "SHELL": str(slow), "TMUX_TMPDIR": str(tmp_path)}
    env.pop("TMUX", None)
    name = "native_mcp_slowtest"
    try:
        subprocess.run(["sh", "-c", build_tmux_bootstrap_command(name)], env=env, check=True, timeout=30)
        subprocess.run(["tmux", "send-keys", "-t", name, "C-c", "Enter"], env=env, check=True)
        subprocess.run(["tmux", "send-keys", "-t", name, "echo alive-$((1+1))", "Enter"], env=env, check=True)
        out = ""
        for _ in range(50):
            out = subprocess.run(
                ["tmux", "capture-pane", "-t", name, "-p"], env=env, capture_output=True, text=True
            ).stdout
            if "alive-2" in out:
                break
            subprocess.run(["sleep", "0.1"])
        assert "alive-2" in out
    finally:
        subprocess.run(["tmux", "kill-server"], env=env, capture_output=True)


# ---------------------------------------------------------- tmux_list_session
async def test_tmux_list_session_without_server_namespaced(tmp_path, monkeypatch):
    monkeypatch.setenv("TMUX_TMPDIR", str(tmp_path))  # no tmux server here
    app = _server(tmp_path, "--namespaced")
    async with Client(app) as client:
        res = await client.call_tool("shell_tmux_list_session", {})
    assert res.data == []


# ------------------------------------------------- latent bugs found in copy
def test_timeout_result_message_does_not_crash():
    """create_shell_result referenced `config` without importing it."""
    from unified_mcp_server.common.mcp_types_utils import create_shell_result
    from unified_mcp_server.common.models import ExecutionResult

    load_settings(["-c", "none.toml"])
    res = create_shell_result(
        ExecutionResult(stdout="ok", exit_code=0, command="x", shell="bash", cwd=".", timed_out=True)
    )
    assert "timed out after" in res.text


def test_env_vars_do_not_leak_into_settings(monkeypatch):
    """BaseSettings used to read PATH/HOST from the environment."""
    monkeypatch.setenv("PORT", "1234")
    monkeypatch.setenv("HOST", "evil.example")
    s = load_settings(["-c", "none.toml"])
    assert s.PORT == 8000 and s.HOST == "127.0.0.1" and s.PATH == "/mcp"
