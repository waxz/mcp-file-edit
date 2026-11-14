"""Tests for the unified server's runtime fixes of upstream bugs."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from unified_mcp_server import patches


# ---------------------------------------------------------------- rmtree
def test_shutil_compat_rmtree_accepts_onexc(tmp_path):
    target = tmp_path / "tree" / "sub"
    target.mkdir(parents=True)
    (target / "f.txt").write_text("x")
    calls = []
    patches._ShutilCompat().rmtree(tmp_path / "tree", onexc=lambda *a: calls.append(a))
    assert not (tmp_path / "tree").exists() and calls == []


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="needs POSIX non-root")
def test_shutil_compat_routes_errors_to_onexc(tmp_path):
    """A read-only dir makes unlink fail; the handler must get (func, path, exc)."""
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "f.txt").write_text("x")
    tree.chmod(stat.S_IRUSR | stat.S_IXUSR)
    seen = []

    def handler(func, path, exc):
        seen.append(exc)
        os.chmod(tree, stat.S_IRWXU)
        func(path)

    try:
        patches._ShutilCompat().rmtree(tree, onexc=handler)
    finally:
        if tree.exists():
            tree.chmod(stat.S_IRWXU)
    assert seen and isinstance(seen[0], PermissionError)


def test_shutil_compat_delegates_other_attributes():
    assert patches._ShutilCompat().copy2 is shutil.copy2


def test_rmtree_fix_installed_only_on_old_python(tmp_path):
    from unified_mcp_server.config import load_settings
    from unified_mcp_server.server import build_unified_server
    import anyio

    project = tmp_path / "p"
    project.mkdir()
    anyio.run(build_unified_server, load_settings(["-c", "none.toml", "-w", str(project)]))
    from mcp_file_edit import file_operations

    assert isinstance(file_operations.shutil, patches._ShutilCompat) == (sys.version_info < (3, 12))


# ------------------------------------------------------------------ tmux
def test_reset_pane_never_sends_ctrl_c():
    cmds = patches.build_tmux_reset_pane_command("native_mcp_x")
    assert not any("C-c" in c for c in cmds)
    assert any("clear-history" in c for c in cmds)


def test_builders_validate_session_name():
    with pytest.raises(ValueError):
        patches.build_tmux_bootstrap_command("bad;name")
    with pytest.raises(ValueError):
        patches.build_tmux_reset_pane_command("bad name")


def test_tmux_fix_is_installed_into_tool_handlers(tmp_path):
    from unified_mcp_server.config import load_settings
    from unified_mcp_server.server import build_unified_server
    import anyio

    project = tmp_path / "p"
    project.mkdir()
    anyio.run(build_unified_server, load_settings(["-c", "none.toml", "-w", str(project)]))
    from shell_mcp_server import tool_handlers

    assert tool_handlers.build_tmux_reset_pane_command is patches.build_tmux_reset_pane_command
    assert tool_handlers.build_tmux_bootstrap_command is patches.build_tmux_bootstrap_command


@pytest.mark.skipif(shutil.which("tmux") is None or sys.platform == "win32", reason="needs tmux")
def test_bootstrap_waits_for_slow_shell(tmp_path):
    """Reproduce the runner failure: a pane shell that takes 0.5s to start.

    With upstream's immediate C-c the pane died. With the fix the bootstrap
    returns only once the prompt is up, and a following C-c is harmless.
    """
    slow = tmp_path / "slowsh"
    slow.write_text("#!/bin/sh\nsleep 0.5\nexec /bin/sh -i\n")
    slow.chmod(0o755)
    env = {**os.environ, "SHELL": str(slow), "TMUX_TMPDIR": str(tmp_path)}
    env.pop("TMUX", None)
    name = "native_mcp_slowtest"
    try:
        subprocess.run(
            ["sh", "-c", patches.build_tmux_bootstrap_command(name)], env=env, check=True, timeout=30
        )
        # The prompt is up, so even upstream's C-c no longer kills the shell.
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


# ------------------------------------------------------ async functions
PARITY_SOURCE = '''
import functools

@functools.lru_cache(maxsize=None)
def top(a: int, *args, b=2, **kw) -> int:
    """Doc."""
    def inner(x):
        return x
    return inner(a)

class K(object):
    @staticmethod
    def method(self, y: str):
        pass
'''


def test_async_extractor_matches_upstream_on_sync_code():
    """For code without async defs the replacement must return exactly what upstream did."""
    from conftest import UPSTREAM_EXTRACT_FUNCTIONS

    assert UPSTREAM_EXTRACT_FUNCTIONS is not patches._python_functions_with_async
    result = patches._python_functions_with_async(PARITY_SOURCE)
    assert {f["name"] for f in result} == {"top", "inner", "method"}
    assert result == UPSTREAM_EXTRACT_FUNCTIONS(PARITY_SOURCE)


def test_async_extractor_finds_async_defs():
    src = "class A:\n    async def m(self):\n        pass\n\nasync def f():\n    pass\n"
    funcs = {f["name"]: f for f in patches._python_functions_with_async(src)}
    assert funcs["m"]["is_async"] and funcs["m"]["class_name"] == "A"
    assert funcs["f"]["is_async"] and not funcs["f"]["is_method"]


# ------------------------------------------------------- tmux sessions
async def test_tmux_list_session_replaced_in_namespaced_mode(tmp_path, monkeypatch):
    from fastmcp import Client

    from unified_mcp_server.config import load_settings
    from unified_mcp_server.server import build_unified_server

    monkeypatch.setenv("TMUX_TMPDIR", str(tmp_path))  # no tmux server here
    project = tmp_path / "p"
    project.mkdir()
    app = await build_unified_server(
        load_settings(["-c", "none.toml", "-w", str(project), "--namespaced"])
    )
    async with Client(app) as client:
        res = await client.call_tool("shell_tmux_list_session", {})
    assert res.data == []
