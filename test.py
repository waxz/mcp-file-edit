#!/usr/bin/env python3
"""Comprehensive MCP tool test runner (valid + invalid params) with report output."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from fastmcp import Client

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


@dataclass
class Scenario:
    name: str
    tool: str
    args: dict[str, Any]
    expect_error: bool = False
    allow_error_output: bool = False
    must_contain: str | None = None
    require_keys: list[str] | None = None
    timeout_s: float | None = None


@dataclass
class ScenarioResult:
    scenario: Scenario
    passed: bool
    output: str = ""
    error: str = ""
    detail: str = ""


def is_wsl() -> bool:
    if platform.system() != "Linux":
        return False
    release = platform.release().lower()
    if "microsoft" in release:
        return True
    proc_version = Path("/proc/version")
    if proc_version.exists():
        text = proc_version.read_text(encoding="utf-8", errors="ignore").lower()
        return "microsoft" in text or "wsl" in text
    return False


class HttpServerRunner:
    def __init__(self, host: str, port: int, mcp_path: str, allow_directories: str | None, config_path: str | None):
        self.host = host
        self.port = port
        self.mcp_path = mcp_path
        self.allow_directories = allow_directories
        self.config_path = config_path
        self.proc: subprocess.Popen[str] | None = None

    def start(self) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SRC_DIR) + os.pathsep + env.get("PYTHONPATH", "")

        cmd = [
            sys.executable,
            "-m",
            "mcp_file_edit.server",
            "-t",
            "http",
            "-H",
            self.host,
            "-P",
            str(self.port),
            "-p",
            self.mcp_path,
            "--name",
            "file-editor-test",
        ]
        if self.config_path:
            cmd.extend(["--config", self.config_path])
        if self.allow_directories is not None:
            cmd.extend(["--allow-directories", self.allow_directories])
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True, env=env)

    async def wait_ready(self, timeout_sec: float = 15.0) -> bool:
        deadline = asyncio.get_event_loop().time() + timeout_sec
        while asyncio.get_event_loop().time() < deadline:
            if self.proc and self.proc.poll() is not None:
                return False
            try:
                reader, writer = await asyncio.open_connection(self.host, self.port)
                writer.close()
                await writer.wait_closed()
                return True
            except Exception:
                await asyncio.sleep(0.2)
        return False

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=2)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run full MCP tool tests and generate report")
    parser.add_argument("--mode", choices=["direct", "http"], default="direct")
    parser.add_argument("--url", default="http://127.0.0.1:8000/mcp")
    parser.add_argument("--output", default="report.txt")
    parser.add_argument("--allow-directories", default=None)
    parser.add_argument("--config", default="config.toml")
    parser.add_argument("--http-autostart", action="store_true")
    parser.add_argument("--http-host", default="127.0.0.1")
    parser.add_argument("--http-port", type=int, default=8000)
    parser.add_argument("--http-path", default="/mcp")
    parser.add_argument("--call-timeout", type=float, default=2.0)
    parser.add_argument("--max-duration", type=float, default=180.0)
    return parser.parse_args()


def build_client(mode: str, url: str, allow_directories: str | None, config_path: str | None) -> Client:
    if mode == "http":
        return Client(url)

    old_argv = sys.argv[:]
    try:
        argv = [sys.argv[0]]
        if config_path:
            argv.extend(["--config", config_path])
        if allow_directories is not None:
            argv.extend(["--allow-directories", allow_directories])
        sys.argv = argv
        from mcp_file_edit import server as server_module
    finally:
        sys.argv = old_argv
    return Client(server_module.mcp)


def extract_text(result: Any) -> str:
    parts: list[str] = []
    for content in getattr(result, "content", []):
        text = getattr(content, "text", "")
        if text:
            parts.append(text)
    if parts:
        return "\n".join(parts).strip()
    return str(result).strip()


def parse_json_maybe(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return None


def has_error_result(obj: Any, output: str) -> bool:
    if isinstance(obj, dict):
        if obj.get("success") is False:
            return True
        if obj.get("error"):
            return True
    lower = output.lower()
    patterns = ["traceback", "exception", "valueerror", "typeerror", "runtimeerror", "invalid path", "not allowed"]
    return any(p in lower for p in patterns)


async def call_tool(client: Client, scenario: Scenario, timeout_s: float) -> ScenarioResult:
    print(f"\n=== {scenario.tool}({json.dumps(scenario.args, ensure_ascii=False)})")
    try:
        effective_timeout = scenario.timeout_s if scenario.timeout_s is not None else timeout_s
        result = await asyncio.wait_for(client.call_tool(scenario.tool, scenario.args), timeout=effective_timeout)
        output = extract_text(result)
        obj = parse_json_maybe(output)
        is_error = has_error_result(obj, output)

        if scenario.expect_error:
            if is_error:
                return ScenarioResult(scenario, True, output=output, detail="expected error observed")
            return ScenarioResult(scenario, False, output=output, detail="expected error but call looked successful")

        if (not scenario.allow_error_output) and is_error:
            return ScenarioResult(scenario, False, output=output, detail="unexpected error output")

        if scenario.must_contain and scenario.must_contain not in output:
            return ScenarioResult(scenario, False, output=output, detail=f"missing substring: {scenario.must_contain!r}")

        if scenario.require_keys and isinstance(obj, dict):
            missing = [k for k in scenario.require_keys if k not in obj]
            if missing:
                return ScenarioResult(scenario, False, output=output, detail=f"missing keys: {missing}")

        return ScenarioResult(scenario, True, output=output)
    except Exception as exc:  # noqa: BLE001
        if scenario.expect_error:
            return ScenarioResult(scenario, True, error=str(exc), detail="expected exception")
        return ScenarioResult(scenario, False, error=str(exc), detail="unexpected exception")


def prepare_workspace() -> dict[str, Path]:
    ws = PROJECT_ROOT / ".workspace/mcp_test_workspace"
    if ws.exists():
        shutil.rmtree(ws,ignore_errors=True)
    ws.mkdir(parents=True, exist_ok=True)

    files = ws / "files"
    files.mkdir(parents=True, exist_ok=True)
    (files / "a.txt").write_text("alpha\nbeta\n", encoding="utf-8")
    (files / "b.py").write_text("def foo():\n    return 1\n\ndef bar(x):\n    return x\n", encoding="utf-8")
    (files / "notes.md").write_text("# Notes\nhello\n", encoding="utf-8")

    gitrepo = ws / "gitrepo"
    gitrepo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=gitrepo, check=False, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "mcp@test.local"], cwd=gitrepo, check=False, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "MCP Test"], cwd=gitrepo, check=False, capture_output=True, text=True)
    (gitrepo / "gitfile.txt").write_text("v1\n", encoding="utf-8")

    clone_target = ws / "clone_target"
    clone_target.mkdir(parents=True, exist_ok=True)

    return {"ws": ws, "files": files, "gitrepo": gitrepo, "clone_target": clone_target}


def build_scenarios(paths: dict[str, Path]) -> list[Scenario]:
    files_rel = str(paths["files"].relative_to(PROJECT_ROOT))
    git_rel = str(paths["gitrepo"].relative_to(PROJECT_ROOT))
    clone_rel = str(paths["clone_target"].relative_to(PROJECT_ROOT))
    scenarios = [
        # project tools
        Scenario("set project valid", "set_project_directory", {"path": "./tests", "connection_type": "local"}, require_keys=["project_directory", "connection_type"]),
        Scenario("get project", "get_project_directory", {}, require_keys=["project_directory", "connection_type"]),
        Scenario("set project valid", "set_project_directory", {"path": ".", "connection_type": "local"}, require_keys=["project_directory", "connection_type"]),
        Scenario("set project invalid", "set_project_directory", {"path": "/", "connection_type": "local"}, expect_error=True),
        Scenario("set project invalid", "set_project_directory", {"path": "../", "connection_type": "local"}, expect_error=True),
        Scenario("set project invalid", "set_project_directory", {"path": "..//", "connection_type": "local"}, expect_error=True),
        Scenario("set project invalid", "set_project_directory", {"path": "..\\..//", "connection_type": "local"}, expect_error=True),
        
        Scenario("get project", "get_project_directory", {}, require_keys=["project_directory", "connection_type"]),

        # file tools valid
        Scenario("list files valid", "list_files", {"path": ".", "pattern": "*.md"}),
        Scenario("read file valid", "read_file", {"path": "README.md"}, must_contain="MCP"),
        Scenario("write file valid", "write_file", {"path": f"{files_rel}/write_target.txt", "content": "hello"}, require_keys=["path", "size"]),
        Scenario("create file valid", "create_file", {"path": f"{files_rel}/new.txt", "content": "new"}),
        Scenario("copy file valid", "copy_file", {"source": f"{files_rel}/a.txt", "destination": f"{files_rel}/a_copy.txt"}),
        Scenario("move file valid", "move_file", {"source": f"{files_rel}/a_copy.txt", "destination": f"{files_rel}/a_moved.txt"}),
        Scenario("search files valid", "search_files", {"pattern": "foo", "path": files_rel}),
        Scenario("replace files valid", "replace_in_files", {"search": "alpha", "replace": "ALPHA", "path": files_rel}),
        Scenario("patch file valid", "patch_file", {"path": f"{files_rel}/b.py", "patches": [{"search": "return 1", "replace": "return 2"}], "backup": False}),
        Scenario("get file info valid", "get_file_info", {"path": f"{files_rel}/b.py"}, require_keys=["name", "size"]),
        Scenario("delete file valid", "delete_file", {"path": f"{files_rel}/new.txt"}),

        # file tools invalid
        Scenario("list files invalid", "list_files", {"path": "README.md"}, expect_error=True),
        Scenario("read file invalid", "read_file", {"path": "../README.md"}, expect_error=True),
        Scenario("write file invalid", "write_file", {"path": "../x.txt", "content": "x"}, expect_error=True),
        Scenario("create file invalid", "create_file", {"path": f"{files_rel}/b.py", "content": "dup"}, expect_error=True),
        Scenario("copy file invalid", "copy_file", {"source": f"{files_rel}/missing.txt", "destination": f"{files_rel}/x.txt"}, expect_error=True),
        Scenario("move file invalid", "move_file", {"source": f"{files_rel}/missing.txt", "destination": f"{files_rel}/x.txt"}, expect_error=True),
        Scenario("search files invalid", "search_files", {"pattern": "(*", "path": files_rel}, expect_error=True),
        Scenario("replace files invalid", "replace_in_files", {"search": "(*", "replace": "x", "path": files_rel}, expect_error=True),
        Scenario("patch file invalid", "patch_file", {"path": f"{files_rel}/b.py", "patches": [{"bad": "shape"}]}, expect_error=True),
        Scenario("get file info invalid", "get_file_info", {"path": f"{files_rel}/missing.py"}, expect_error=True),
        Scenario("delete file invalid", "delete_file", {"path": f"{files_rel}/missing.txt"}, expect_error=True),

        # code analysis valid
        Scenario("list functions valid", "list_functions", {"path": f"{files_rel}/b.py"}),
        Scenario("function at line valid", "get_function_at_line", {"path": f"{files_rel}/b.py", "line_number": 1}),
        Scenario("code structure valid", "get_code_structure", {"path": f"{files_rel}/b.py"}, require_keys=["language"]),
        Scenario("search functions valid", "search_functions", {"pattern": "foo", "path": files_rel}),

        # code analysis invalid
        Scenario("list functions invalid", "list_functions", {"path": f"{files_rel}/missing.py"}, expect_error=True),
        Scenario("function at line invalid", "get_function_at_line", {"path": f"{files_rel}/missing.py", "line_number": 1}, expect_error=True),
        Scenario("code structure invalid", "get_code_structure", {"path": f"{files_rel}/missing.py"}, expect_error=True),
        Scenario("search functions invalid", "search_functions", {"pattern": "foo", "path": "../"}, expect_error=True),

        # lint/type/format valid (correct params; may return success false depending env)
        Scenario("detect linters valid", "detect_linters", {"path": files_rel}, require_keys=["linters", "type_checkers", "formatters"], timeout_s=5.0),
        Scenario("run linter valid", "run_linter", {"path": files_rel, "timeout": 1}, allow_error_output=True, timeout_s=5.0),
        Scenario("lint file valid", "lint_file", {"path": f"{files_rel}/b.py", "timeout": 1}, allow_error_output=True, timeout_s=5.0),
        Scenario("run type checker valid", "run_type_checker", {"path": files_rel, "timeout": 1}, allow_error_output=True, timeout_s=5.0),
        Scenario("type check file valid", "type_check_file", {"path": f"{files_rel}/b.py", "timeout": 1}, allow_error_output=True, timeout_s=5.0),
        Scenario("format file valid", "format_file", {"path": f"{files_rel}/b.py", "check_only": True, "timeout": 1}, allow_error_output=True, timeout_s=5.0),

        # lint/type/format invalid
        Scenario("detect linters invalid", "detect_linters", {"path": "../"}, expect_error=True),
        Scenario("run linter invalid", "run_linter", {"path": "../"}, expect_error=True),
        Scenario("lint file invalid", "lint_file", {"path": "../x.py"}, expect_error=True),
        Scenario("run type checker invalid", "run_type_checker", {"path": "../"}, expect_error=True),
        Scenario("type check file invalid", "type_check_file", {"path": "../x.py"}, expect_error=True),
        Scenario("format file invalid", "format_file", {"path": "../x.py"}, expect_error=True),

        # git valid flow
        Scenario("set project git", "set_project_directory", {"path": git_rel, "connection_type": "local"}),
        Scenario("git init valid", "git_init", {}),
        Scenario("git status valid", "git_status", {}, require_keys=["is_repository"]),
        Scenario("git add valid", "git_add", {"files": "gitfile.txt"}),
        Scenario("git commit valid", "git_commit", {"message": "test commit"}, allow_error_output=True),
        Scenario("git log valid", "git_log", {"limit": 5}),
        Scenario("git branch valid", "git_branch", {}),
        Scenario("git checkout valid", "git_checkout", {"branch": "test-branch", "create": True}, allow_error_output=True),
        Scenario("git diff valid", "git_diff", {}),
        Scenario("git remote valid", "git_remote", {"action": "list"}),

        # git invalid params/state
        Scenario("git checkout invalid", "git_checkout", {"branch": "no-such-branch"}, expect_error=True),
        Scenario("git push invalid state", "git_push", {"remote": "origin"}, expect_error=True),
        Scenario("git pull invalid state", "git_pull", {"remote": "origin"}, expect_error=True),
        Scenario("git remote invalid action", "git_remote", {"action": "bad-action"}, expect_error=True),

        # git clone valid/invalid
        Scenario("set project root for clone", "set_project_directory", {"path": ".", "connection_type": "local"}),
        Scenario("git clone valid", "git_clone", {"url": str(paths["gitrepo"]), "path": clone_rel}, allow_error_output=True, timeout_s=8.0),
        Scenario("git clone invalid", "git_clone", {"url": "not-a-valid-url", "path": f"{clone_rel}_bad"}, expect_error=True),

        # ssh tools (no ssh session expected)
        Scenario("ssh upload valid-shape", "ssh_upload", {"local_path": "README.md", "remote_path": "x"}, expect_error=True),
        Scenario("ssh upload invalid", "ssh_upload", {"local_path": "", "remote_path": ""}, expect_error=True),
        Scenario("ssh download valid-shape", "ssh_download", {"remote_path": "x", "local_path": "x"}, expect_error=True),
        Scenario("ssh download invalid", "ssh_download", {"remote_path": "", "local_path": ""}, expect_error=True),
        Scenario("ssh sync valid-shape", "ssh_sync", {"local_path": ".", "remote_path": "/tmp", "direction": "upload"}, expect_error=True),

        # path-string injection protection (portable checks)
        Scenario("posix path injection read invalid", "read_file", {"path": "../README.md;echo owned"}, expect_error=True),
        Scenario("posix path injection write invalid", "write_file", {"path": "../x.txt|cat", "content": "x"}, expect_error=True),
        Scenario("windows path injection read invalid", "read_file", {"path": "..\\README.md&echo owned"}, expect_error=True),
        Scenario("windows path injection write invalid", "write_file", {"path": "..\\x.txt|type nul", "content": "x"}, expect_error=True),
        Scenario("set project injection invalid posix", "set_project_directory", {"path": "./;pwd", "connection_type": "local"}, expect_error=True),
        Scenario("set project injection invalid windows", "set_project_directory", {"path": ".\\&whoami", "connection_type": "local"}, expect_error=True),
    ]

    # Platform-specific path handling checks
    if sys.platform == "win32":
        windows_files_rel = files_rel.replace("/", "\\")
        scenarios.extend(
            [
                # Windows accepts relative POSIX paths but rejects POSIX absolute paths.
                Scenario("windows relative posix path valid", "read_file", {"path": f"{files_rel}/b.py"}, must_contain="def foo"),
                Scenario("windows posix absolute path invalid", "read_file", {"path": "/etc/passwd"}, expect_error=True),
                Scenario("windows backslash read valid", "read_file", {"path": f"{windows_files_rel}\\b.py"}, must_contain="def foo"),
                Scenario("windows traversal invalid", "read_file", {"path": "..\\README.md"}, expect_error=True),
                Scenario("windows root outside allowlist", "set_project_directory", {"path": "C:\\Windows", "connection_type": "local"}, expect_error=True),
            ]
        )
    else:
        scenarios.append(
            Scenario(
                "linux relative posix path valid",
                "read_file",
                {"path": f"{files_rel}/b.py"},
                must_contain="def foo",
            )
        )
        scenarios.append(
            Scenario(
                "linux windows style path invalid",
                "read_file",
                {"path": r"C:\\Windows\\System32\\drivers\\etc\\hosts"},
                expect_error=True,
            )
        )
        scenarios.append(Scenario("posix traversal invalid", "read_file", {"path": "../README.md"}, expect_error=True))
        if is_wsl():
            scenarios.append(
                Scenario("wsl windows-mount outside allowlist", "set_project_directory", {"path": "/mnt/c/Windows", "connection_type": "local"}, expect_error=True)
            )

    return scenarios


def _format_bytes(value: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(value)
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{value} B"


def _get_memory_total_human() -> str:
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        for line in meminfo.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("MemTotal:"):
                kb = int(line.split()[1])
                return _format_bytes(kb * 1024)
    return "unknown"


def write_report(report_path: Path, args: argparse.Namespace, results: list[ScenarioResult]) -> None:
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = [r for r in results if not r.passed]

    lines: list[str] = []
    lines.append("# MCP Comprehensive Test Report")
    lines.append("")
    lines.append("## Run Config")
    lines.append(f"- generated: {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"- mode: {args.mode}")
    lines.append(f"- target: {args.url if args.mode == 'http' else args.mode}")
    lines.append(f"- allow_directories: {args.allow_directories or '(default)'}")
    lines.append(f"- call_timeout: {args.call_timeout}s")
    lines.append("")

    lines.append("## Hardware Info")
    lines.append(f"- hostname: {socket.gethostname()}")
    lines.append(f"- os: {platform.system()} {platform.release()}")
    lines.append(f"- platform: {platform.platform()}")
    lines.append(f"- machine: {platform.machine()}")
    lines.append(f"- processor: {platform.processor() or 'unknown'}")
    lines.append(f"- cpu_count: {os.cpu_count()}")
    lines.append(f"- memory_total: {_get_memory_total_human()}")
    lines.append(f"- python: {platform.python_version()}")
    lines.append("")

    lines.append("## Test Result")
    lines.append("| # | Status | Tool | Case |")
    lines.append("|---:|:---:|---|---|")
    for i, item in enumerate(results, start=1):
        lines.append(f"| {i} | {'PASS' if item.passed else 'FAIL'} | {item.scenario.tool} | {item.scenario.name} |")
    lines.append("")

    lines.append("## Summary")
    lines.append(f"- total: {total}")
    lines.append(f"- passed: {passed}")
    lines.append(f"- failed: {total - passed}")
    lines.append(f"- status: {'PASS' if passed == total else 'FAIL'}")
    lines.append("")

    lines.append("## Fastcheck Table")
    lines.append("| Metric | Value |")
    lines.append("|---|---:|")
    lines.append(f"| Total | {total} |")
    lines.append(f"| Passed | {passed} |")
    lines.append(f"| Failed | {total - passed} |")
    lines.append(f"| Pass Rate | {(passed / total * 100 if total else 0):.1f}% |")
    lines.append("")

    lines.append("## Failed Details")
    if not failed:
        lines.append("- none")
    else:
        for item in failed:
            s = item.scenario
            lines.append(f"- tool: {s.tool}")
            lines.append(f"  case: {s.name}")
            lines.append(f"  args: {json.dumps(s.args, ensure_ascii=False)}")
            lines.append(f"  expect_error: {s.expect_error}")
            if item.detail:
                lines.append(f"  detail: {item.detail}")
            if item.error:
                lines.append(f"  error: {item.error}")
            if item.output:
                lines.append(f"  output: {item.output[:220].replace(chr(10), ' ')}")
            lines.append("")

    report_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


async def run(args: argparse.Namespace) -> int:
    paths = prepare_workspace()

    http_runner: HttpServerRunner | None = None
    client: Client | None = None
    client_entered = False
    if args.mode == "http" and args.http_autostart:
        http_runner = HttpServerRunner(args.http_host, args.http_port, args.http_path, args.allow_directories, args.config)
        http_runner.start()
        if not await http_runner.wait_ready():
            http_runner.stop()
            raise RuntimeError("HTTP MCP server did not become ready in time")
        args.url = f"http://{args.http_host}:{args.http_port}{args.http_path}"

    results: list[ScenarioResult] = []
    try:
        client = build_client(args.mode, args.url, args.allow_directories, args.config)
        scenarios = build_scenarios(paths)
        await asyncio.wait_for(client.__aenter__(), timeout=10.0)
        client_entered = True
        started = time.monotonic()
        for sc in scenarios:
            if (time.monotonic() - started) > args.max_duration:
                results.append(
                    ScenarioResult(
                        scenario=Scenario("Global Timeout", "runner", {}),
                        passed=False,
                        detail=f"max duration exceeded ({args.max_duration:.1f}s), stopped early",
                    )
                )
                break
            try:
                scenario_total_timeout = (sc.timeout_s if sc.timeout_s is not None else args.call_timeout) + 1.5
                res = await asyncio.wait_for(call_tool(client, sc, args.call_timeout), timeout=scenario_total_timeout)
            except asyncio.TimeoutError:
                res = ScenarioResult(
                    scenario=sc,
                    passed=False,
                    detail=f"scenario timed out after {scenario_total_timeout:.1f}s",
                )
            results.append(res)
    except Exception as exc:  # noqa: BLE001
        results.append(
            ScenarioResult(
                scenario=Scenario("Connection", "client", {}),
                passed=False,
                error=str(exc),
                detail="failed to initialize/connect client",
            )
        )
    finally:
        # FastMCP HTTP teardown can block indefinitely in this stress runner.
        # For HTTP mode we rely on process termination after report write.
        if client is not None and client_entered and args.mode == "direct":
            try:
                await asyncio.wait_for(client.__aexit__(None, None, None), timeout=3.0)
            except Exception:
                pass
        if http_runner is not None:
            http_runner.stop()

    report_path = Path(args.output)
    if not report_path.is_absolute():
        report_path = (PROJECT_ROOT / report_path).resolve()
    write_report(report_path, args, results)
    print(f"Report written: {report_path}")

    passed = sum(1 for r in results if r.passed)
    return 0 if passed == len(results) else 1


def main() -> None:
    args = parse_args()
    hard_timeout = max(30.0, args.max_duration + 30.0)
    watchdog = threading.Timer(hard_timeout, lambda: os._exit(124))
    watchdog.daemon = True
    watchdog.start()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        exit_code = loop.run_until_complete(run(args))
    finally:
        watchdog.cancel()
        try:
            loop.stop()
            loop.close()
        except Exception:
            pass
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(exit_code)


if __name__ == "__main__":
    main()
