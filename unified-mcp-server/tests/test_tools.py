"""Tool-level tests: call every tool family through a real MCP client.

Each test builds a fresh unified server rooted at a temporary project dir and
talks to it over the in-memory MCP transport, so arguments and results go
through the same serialisation as a real client.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import anyio
import pytest
from fastmcp import Client

from unified_mcp_server.config import load_settings
from unified_mcp_server.server import build_unified_server

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="shell/tmux fixtures assume a POSIX shell"
)

CONFIG = """
COMMAND_TIMEOUT = 20

[TRUSTED_COMMANDS.t_echo]
command = "echo hello-from-shell"
shell = "bash"
cwd = "."
description = "echo"

[TRUSTED_COMMANDS.t_cat]
command = "cat notes.txt"
shell = "bash"
cwd = "."
description = "cat a project file"

[TRUSTED_COMMANDS.t_fail]
command = "exit 3"
shell = "bash"
cwd = "."
description = "non-zero exit"

[TRUSTED_COMMANDS.t_sleep]
command = "sleep 30"
shell = "bash"
cwd = "."
description = "long-running"
"""

EXPECTED_TOOLS = {
    # mcp-file-edit
    "list_files", "read_file", "write_file", "create_directory", "remove_directory",
    "create_file", "delete_file", "move_file", "copy_file", "search_files",
    "replace_in_files", "patch_file", "patch_format_help", "validate_patch_syntax",
    "preview_patch", "apply_patch", "get_patch_preview_status", "confirm_patch_preview",
    "reject_patch_preview", "apply_confirmed_patch", "get_file_info",
    "git_status", "git_init", "git_clone", "git_add", "git_commit", "git_push",
    "git_pull", "git_log", "git_branch", "git_checkout", "git_diff", "git_remote",
    "ssh_upload", "ssh_download", "ssh_sync",
    "list_functions", "get_function_at_line", "get_code_structure", "search_functions",
    "set_project_directory", "get_project_directory",
    "detect_linters", "run_linter", "lint_file", "run_type_checker",
    "type_check_file", "format_file",
    # shell-mcp-server
    "list_trusted_commands", "execute_command", "list_processes", "terminate_process",
    "terminate_all_processes", "tmux_execute", "tmux_get_output", "tmux_list_session",
    "tmux_send_keys", "tmux_kill_session",
}


@pytest.fixture
def project(tmp_path: Path) -> Path:
    p = tmp_path / "project"
    p.mkdir()
    return p


@pytest.fixture
async def client(tmp_path: Path, project: Path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(CONFIG)
    app = await build_unified_server(load_settings(["-c", str(cfg), "-w", str(project)]))
    async with Client(app) as c:
        yield c


async def call(client: Client, name: str, args: dict | None = None):
    """Call a tool and return parsed JSON (or text when not JSON)."""
    res = await client.call_tool(name, args or {})
    text = "".join(getattr(c, "text", "") for c in res.content)
    try:
        return json.loads(text)
    except ValueError:
        return text


async def call_error(client: Client, name: str, args: dict | None = None) -> str:
    res = await client.call_tool(name, args or {}, raise_on_error=False)
    assert res.is_error, f"{name} unexpectedly succeeded"
    return "".join(getattr(c, "text", "") for c in res.content)


# --------------------------------------------------------------------- registry
async def test_all_tools_registered_with_schemas(client):
    tools = await client.list_tools()
    names = {t.name for t in tools}
    assert names == EXPECTED_TOOLS, (
        f"missing={sorted(EXPECTED_TOOLS - names)} extra={sorted(names - EXPECTED_TOOLS)}"
    )
    for tool in tools:
        assert tool.description, f"{tool.name} has no description"
        assert tool.inputSchema.get("type") == "object", tool.name


# ------------------------------------------------------------------ file tools
class TestFileTools:
    async def test_write_read_info(self, client, project):
        await call(client, "write_file", {"path": "a.txt", "content": "one\ntwo\n"})
        data = await call(client, "read_file", {"path": "a.txt"})
        assert data["content"] == "one\ntwo\n"
        info = await call(client, "get_file_info", {"path": "a.txt"})
        assert info["type"] == "file" and info["size"] == 8

    async def test_create_list_copy_move_delete(self, client, project):
        await call(client, "create_file", {"path": "d/b.txt", "content": "x", "create_dirs": True})
        listing = await call(client, "list_files", {"path": ".", "recursive": True})
        assert any(e["name"] == "b.txt" for e in listing)
        await call(client, "copy_file", {"source": "d/b.txt", "destination": "c.txt"})
        await call(client, "move_file", {"source": "c.txt", "destination": "e.txt"})
        assert (project / "e.txt").read_text() == "x" and not (project / "c.txt").exists()
        await call(client, "delete_file", {"path": "e.txt"})
        assert not (project / "e.txt").exists()

    async def test_create_and_remove_directory(self, client, project):
        # remove_directory crashed on Python < 3.12 upstream (rmtree onexc=).
        await call(client, "create_directory", {"path": "newdir"})
        assert (project / "newdir").is_dir()
        assert await call(client, "remove_directory", {"path": "newdir"}) is True
        assert not (project / "newdir").exists()

    async def test_create_file_refuses_overwrite(self, client, project):
        (project / "exists.txt").write_text("keep")
        await call_error(client, "create_file", {"path": "exists.txt", "content": "new"})
        assert (project / "exists.txt").read_text() == "keep"

    async def test_search_and_replace(self, client, project):
        (project / "s.txt").write_text("hello world\n")
        found = await call(client, "search_files", {"pattern": "wor.d"})
        assert found["results"][0]["matches"][0]["line_number"] == 1
        await call(client, "replace_in_files", {"search": "world", "replace": "there", "file_pattern": "*.txt"})
        assert (project / "s.txt").read_text() == "hello there\n"

    @pytest.mark.parametrize("bad", ["../outside.txt", "a/../../x", "a.txt; rm -rf /", "a\x00b"])
    async def test_rejects_unsafe_paths(self, client, bad):
        msg = await call_error(client, "read_file", {"path": bad})
        assert "Invalid path" in msg

    async def test_rejects_absolute_path_outside_project(self, client, tmp_path):
        outside = tmp_path / "outside.txt"
        outside.write_text("secret")
        await call_error(client, "read_file", {"path": str(outside)})


# ----------------------------------------------------------------- patch tools
PATCH = """*** Begin Patch
*** Update File: cfg.py
@@
 # settings
-DEBUG = False
+DEBUG = True
 PORT = 1
*** End Patch"""


class TestPatchTools:
    @pytest.fixture(autouse=True)
    def _file(self, project):
        (project / "cfg.py").write_text("# settings\nDEBUG = False\nPORT = 1\n")

    async def test_format_help_and_validation(self, client):
        assert "Begin Patch" in await call(client, "patch_format_help")
        assert (await call(client, "validate_patch_syntax", {"patch": PATCH}))["valid"] is True
        bad = await call(client, "validate_patch_syntax", {"patch": "not a patch"})
        assert bad["valid"] is False

    async def test_dry_run_does_not_write(self, client, project):
        await call(client, "apply_patch", {"patch": PATCH, "dry_run": True})
        assert "DEBUG = False" in (project / "cfg.py").read_text()

    async def test_preview_confirm_apply_workflow(self, client, project):
        res = await client.call_tool("apply_patch", {"patch": PATCH, "dry_run": True})
        preview_id = res.structured_content["preview_session"]["preview_id"]
        status = await call(client, "get_patch_preview_status", {"preview_id": preview_id})
        assert status["status"] == "pending"
        # Applying before confirmation must be refused.
        await call_error(client, "apply_confirmed_patch", {"preview_id": preview_id})
        await call(client, "confirm_patch_preview", {"preview_id": preview_id})
        applied = await call(client, "apply_confirmed_patch", {"preview_id": preview_id})
        assert applied["success"] is True
        assert "DEBUG = True" in (project / "cfg.py").read_text()

    async def test_rejected_preview_cannot_be_applied(self, client, project):
        res = await client.call_tool("apply_patch", {"patch": PATCH, "dry_run": True})
        preview_id = res.structured_content["preview_session"]["preview_id"]
        await call(client, "reject_patch_preview", {"preview_id": preview_id})
        await call_error(client, "apply_confirmed_patch", {"preview_id": preview_id})
        assert "DEBUG = False" in (project / "cfg.py").read_text()

    async def test_patch_file_search_replace(self, client, project):
        await call(
            client,
            "patch_file",
            {"path": "cfg.py", "patches": [{"find": "PORT = 1", "replace": "PORT = 2"}], "backup": False},
        )
        assert "PORT = 2" in (project / "cfg.py").read_text()


# ------------------------------------------------------------------- git tools
@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
class TestGitTools:
    async def test_init_add_commit_log_branch_diff(self, client, project, monkeypatch):
        for var, val in {
            "GIT_AUTHOR_NAME": "ci", "GIT_AUTHOR_EMAIL": "ci@example.invalid",
            "GIT_COMMITTER_NAME": "ci", "GIT_COMMITTER_EMAIL": "ci@example.invalid",
        }.items():
            monkeypatch.setenv(var, val)
        assert (await call(client, "git_init"))["success"] is True
        (project / "f.txt").write_text("v1\n")
        status = await call(client, "git_status")
        assert "f.txt" in status["untracked"]
        await call(client, "git_add", {"files": ["f.txt"]})
        commit = await call(client, "git_commit", {"message": "first"})
        assert commit["success"] is True, commit
        assert "first" in json.dumps(await call(client, "git_log"))
        (project / "f.txt").write_text("v2\n")
        assert "+v2" in json.dumps(await call(client, "git_diff"))
        await call(client, "git_checkout", {"branch": "feature", "create": True})
        assert "feature" in json.dumps(await call(client, "git_branch"))


# --------------------------------------------------------- code analysis tools
SOURCE = '''import os


class Greeter:
    def greet(self, name):
        return f"hi {name}"


async def main():
    return Greeter().greet("x")
'''


class TestCodeAnalysis:
    @pytest.fixture(autouse=True)
    def _file(self, project):
        (project / "mod.py").write_text(SOURCE)

    async def test_list_functions(self, client):
        names = {f["name"] for f in await call(client, "list_functions", {"path": "mod.py"})}
        assert "greet" in names

    @pytest.mark.xfail(
        strict=True,
        reason="upstream bug: code_analyzer has no visit_AsyncFunctionDef, so async defs are skipped",
    )
    async def test_list_functions_includes_async(self, client):
        names = {f["name"] for f in await call(client, "list_functions", {"path": "mod.py"})}
        assert "main" in names

    async def test_structure(self, client):
        data = await call(client, "get_code_structure", {"path": "mod.py"})
        assert data["language"] == "python"
        assert [c["name"] for c in data["classes"]] == ["Greeter"]

    async def test_function_at_line_and_search(self, client):
        fn = await call(client, "get_function_at_line", {"path": "mod.py", "line_number": 6})
        assert "greet" in json.dumps(fn)
        found = await call(client, "search_functions", {"pattern": "gre"})
        assert "greet" in json.dumps(found)


# ------------------------------------------------------------- lint tools
@pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff not installed")
class TestLintTools:
    async def test_detect_lint_and_format(self, client, project):
        (project / "bad.py").write_text("import os\nx=1\n")
        detected = await call(client, "detect_linters", {"path": "."})
        assert "python" in detected["detected_languages"]
        lint = await call(client, "lint_file", {"path": "bad.py", "tool": "ruff"})
        assert "F401" in json.dumps(lint)  # unused import
        await call(client, "format_file", {"path": "bad.py", "tool": "ruff"})
        assert "x = 1" in (project / "bad.py").read_text()


# ------------------------------------------------------ project directory tools
class TestProjectDirectory:
    async def test_get_and_set(self, client, project):
        cur = await call(client, "get_project_directory")
        assert Path(cur["absolute_path"]) == project.resolve()
        sub = project / "sub"
        sub.mkdir()
        await call(client, "set_project_directory", {"path": str(sub)})
        (sub / "notes.txt").write_text("in sub")
        # File and shell tools both follow the new project directory.
        assert (await call(client, "read_file", {"path": "notes.txt"}))["content"] == "in sub"
        assert "in sub" in await call(client, "execute_command", {"command": "t_cat", "cwd": "."})

    async def test_set_outside_allowed_roots_is_refused(self, client, tmp_path):
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        await call_error(client, "set_project_directory", {"path": str(outside)})


# ----------------------------------------------------------------- shell tools
class TestShellTools:
    async def test_list_trusted_commands(self, client):
        cmds = await call(client, "list_trusted_commands")
        assert {"t_echo", "t_cat", "t_fail", "t_sleep"} <= set(cmds)

    async def test_execute_trusted_command(self, client):
        out = await call(client, "execute_command", {"command": "t_echo", "cwd": "."})
        assert "hello-from-shell" in out and "[exit code: 0]" in out

    async def test_shell_sees_files_written_by_file_tools(self, client):
        await call(client, "write_file", {"path": "notes.txt", "content": "shared!"})
        assert "shared!" in await call(client, "execute_command", {"command": "t_cat", "cwd": "."})

    async def test_nonzero_exit_is_an_error(self, client):
        assert "exit code: 3" in await call_error(client, "execute_command", {"command": "t_fail", "cwd": "."})

    @pytest.mark.parametrize("field", ["command", "cwd"])
    async def test_rejects_null_bytes(self, client, field):
        args = {"command": "t_echo", "cwd": "."}
        args[field] += "\x00"
        assert "null byte" in await call_error(client, "execute_command", args)

    async def test_untrusted_command_outside_sandbox_is_refused(self, client):
        # Without the drun sandbox configured, arbitrary commands must not run on the host.
        await call_error(client, "execute_command", {"command": "echo pwned", "cwd": "."})

    async def test_list_and_terminate_processes(self, client):
        assert await call(client, "list_processes") in ("", None, {"result": None})
        async with anyio.create_task_group() as tg:
            async def run_sleep():
                await client.call_tool("execute_command", {"command": "t_sleep", "cwd": "."}, raise_on_error=False)

            tg.start_soon(run_sleep)
            procs = []
            for _ in range(50):
                procs = await call(client, "list_processes")
                if procs:
                    break
                await anyio.sleep(0.1)
            assert procs and procs[0]["command"] == "sleep 30"
            msg = await call(client, "terminate_process", {"pid": procs[0]["PID"]})
            assert "terminated" in msg
        assert "not found" in await call(client, "terminate_process", {"pid": 999999})
        assert "Terminated 0" in await call(client, "terminate_all_processes")


def _tmux(*args: str) -> str:
    import subprocess

    return subprocess.run(["tmux", *args], capture_output=True, text=True, check=False).stdout


@pytest.fixture
async def ready_tmux_session():
    """A tmux session created outside the tools, returned once its shell prompt is up.

    Created directly so these tests don't depend on tmux_execute.
    The ``native_mcp_`` prefix makes the shell tools treat it as trusted/host.
    """
    import uuid

    name = f"native_mcp_ci_{uuid.uuid4().hex[:8]}"
    _tmux("new-session", "-d", "-s", name)
    for _ in range(100):
        if _tmux("capture-pane", "-t", name, "-p").strip():
            break
        await anyio.sleep(0.1)
    else:
        pytest.fail("tmux pane shell never showed a prompt")
    yield name
    _tmux("kill-session", "-t", name)


async def _wait_for_output(client, session: str, predicate) -> str:
    output = ""
    for _ in range(100):
        output = await call(client, "tmux_get_output", {"session_name": session})
        if predicate(output):
            break
        await anyio.sleep(0.1)
    return output


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux not installed")
class TestTmuxTools:
    async def test_send_keys_and_get_output(self, client, ready_tmux_session):
        session = ready_tmux_session
        await call(client, "tmux_send_keys", {"session_name": session, "keys": "echo $((40 + 2))"})
        output = await _wait_for_output(client, session, lambda o: "\n42" in o)
        assert "\n42" in output  # the command ran, not just echoed

    async def test_get_output_clear_after(self, client, ready_tmux_session):
        session = ready_tmux_session
        await call(client, "tmux_send_keys", {"session_name": session, "keys": "echo marker-$((1 + 1))"})
        await _wait_for_output(client, session, lambda o: "marker-2" in o)
        await call(client, "tmux_get_output", {"session_name": session, "clear_after": True})
        output = await _wait_for_output(client, session, lambda o: "marker-2" not in o)
        assert "marker-2" not in output

    async def test_kill_session(self, client, ready_tmux_session):
        session = ready_tmux_session
        await call(client, "tmux_kill_session", {"session_name": session})
        assert session not in _tmux("ls")

    async def test_rejects_invalid_session_name(self, client):
        await call_error(client, "tmux_kill_session", {"session_name": "bad;name"})
        await call_error(client, "tmux_send_keys", {"session_name": "bad name", "keys": "x"})

    async def test_execute(self, client):
        # Upstream failed this on every GitHub runner (C-c reached the pane
        # before its shell started); fixed in unified_mcp_server.patches.
        session = "native_mcp_ci_exec"
        try:
            await client.call_tool("tmux_execute", {"command": "t_echo", "session_name": "ci_exec"})
            output = await _wait_for_output(
                client, session, lambda o: "hello-from-shell" in o.replace("echo hello-from-shell", "")
            )
            assert "hello-from-shell" in output.replace("echo hello-from-shell", "")
        finally:
            _tmux("kill-session", "-t", session)

    @pytest.mark.xfail(
        strict=True,
        reason="upstream bug: tmux_list_session passes cwd=None when no sandbox work_dir is set",
    )
    async def test_list_sessions(self, client):
        await call(client, "tmux_list_session")
