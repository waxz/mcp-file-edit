"""End-to-end tests for the unified server (in-memory and over HTTP)."""

from __future__ import annotations

import socket
from pathlib import Path

import anyio
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from unified_mcp_server.config import load_settings
from unified_mcp_server.server import ApiKeyAuth, _extract_api_key, build_unified_server


def _write_config(tmp_path: Path, body: str) -> str:
    cfg = tmp_path / "config.toml"
    cfg.write_text(body)
    return str(cfg)


BASE_CONFIG = """
PATH = "/mcp"
[TRUSTED_COMMANDS.t_cat]
command = "cat hello.txt"
shell = "bash"
cwd = "."
description = "print hello.txt from the project dir"

[TRUSTED_COMMANDS.t_pwd]
command = "pwd"
shell = "bash"
cwd = "."
description = "print working dir"
"""


def _text(result) -> str:
    return "".join(getattr(c, "text", "") for c in result.content)


async def _build(tmp_path: Path, extra: str = "", *argv: str, top: str = ""):
    """``top`` holds top-level keys (must precede any [table]); ``extra`` tables."""
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    cfg = _write_config(tmp_path, top + BASE_CONFIG + extra)
    settings = load_settings(["-c", cfg, "-w", str(project), *argv])
    return await build_unified_server(settings), project


async def test_exposes_both_tool_sets(tmp_path):
    app, _ = await _build(tmp_path)
    async with Client(app) as client:
        names = {t.name for t in await client.list_tools()}
    assert {"read_file", "write_file", "apply_patch", "git_status"} <= names
    assert {"execute_command", "tmux_execute", "list_processes"} <= names


async def test_namespaced_tool_names(tmp_path):
    app, _ = await _build(tmp_path, "", "--namespaced")
    async with Client(app) as client:
        names = {t.name for t in await client.list_tools()}
    assert "fs_read_file" in names and "shell_execute_command" in names
    assert "read_file" not in names


async def test_disable_shell(tmp_path):
    app, _ = await _build(tmp_path, "", "--no-shell")
    async with Client(app) as client:
        names = {t.name for t in await client.list_tools()}
    assert "read_file" in names and "execute_command" not in names


async def test_file_and_shell_share_project_dir(tmp_path):
    app, project = await _build(tmp_path)
    async with Client(app) as client:
        await client.call_tool("write_file", {"path": "hello.txt", "content": "hi from fs\n"})
        assert (project / "hello.txt").read_text() == "hi from fs\n"
        out = await client.call_tool("execute_command", {"command": "t_cat", "cwd": "."})
    assert "hi from fs" in _text(out)


async def test_shell_follows_set_project_directory(tmp_path):
    app, project = await _build(tmp_path)
    sub = project / "sub"
    sub.mkdir()
    async with Client(app) as client:
        await client.call_tool("set_project_directory", {"path": str(sub)})
        out = await client.call_tool("execute_command", {"command": "t_pwd", "cwd": "."})
    assert str(sub.resolve()) in _text(out)


async def test_explicit_shell_host_root_is_not_overridden(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    extra = f'\n[DOCKER_CONFIG.linux]\nhost_root = "{other}"\nallow_directories_host = ["{other}"]\n'
    app, project = await _build(tmp_path, extra)
    from shell_mcp_server import config as sh_config

    assert sh_config.SETTINGS.DOCKER_SANDBOX_HOST_ROOT == str(other.resolve())
    async with Client(app) as client:
        await client.call_tool("set_project_directory", {"path": str(project)})
    assert sh_config.SETTINGS.DOCKER_SANDBOX_HOST_ROOT == str(other.resolve())


async def test_config_rejects_unknown_transport(tmp_path):
    cfg = _write_config(tmp_path, 'TRANSPORT = "carrier-pigeon"\n')
    with pytest.raises(ValueError):
        load_settings(["-c", cfg])


def test_extract_api_key_variants():
    assert _extract_api_key({"Authorization": "Bearer abc"}) == "abc"
    assert _extract_api_key({"authorization": "abc"}) == "abc"
    assert _extract_api_key({"X-API-Key": " abc "}) == "abc"
    assert _extract_api_key({}) is None


def test_api_key_validation_multiple_keys():
    auth = ApiKeyAuth(frozenset({"k1", "k2"}))
    assert auth.is_valid("k1") and auth.is_valid("k2")
    assert not auth.is_valid("k3") and not auth.is_valid(None) and not auth.is_valid("")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def test_http_api_key_auth(tmp_path):
    port = _free_port()
    app, _ = await _build(
        tmp_path, "", "-t", "http", "-P", str(port), "-H", "127.0.0.1",
        top='API_KEYS = "secret-1,secret-2"\n',
    )
    url = f"http://127.0.0.1:{port}/mcp"

    async with anyio.create_task_group() as tg:
        tg.start_soon(lambda: app.run_http_async(host="127.0.0.1", port=port, path="/mcp", show_banner=False))
        for _ in range(100):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except OSError:
                await anyio.sleep(0.05)

        good = StreamableHttpTransport(url, headers={"Authorization": "Bearer secret-2"})
        async with Client(good) as client:
            res = await client.call_tool("list_trusted_commands", {})
            assert "t_cat" in _text(res)

        alt = StreamableHttpTransport(url, headers={"x-api-key": "secret-1"})
        async with Client(alt) as client:
            await client.call_tool("list_trusted_commands", {})

        bad = StreamableHttpTransport(url, headers={"Authorization": "Bearer nope"})
        async with Client(bad) as client:
            with pytest.raises(Exception) as excinfo:
                await client.call_tool("list_trusted_commands", {})
            assert "nope" not in str(excinfo.value)  # never echo the presented key

        tg.cancel_scope.cancel()
