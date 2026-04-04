"""Integration test runner for shell-mcp-server tools.

Usage:
  python ./test.py
  python ./test.py --transport http --url http://localhost:8000/mcp
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import sys
import shutil
import subprocess
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastmcp import Client

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


# @dataclass
# class Scenario:
#     tool: str
#     args: dict[str, Any]
#     expect_error: bool = False
#     must_contain: str | None = None

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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Shell MCP Server integration tester")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Client transport target",
    )
    parser.add_argument(
        "--url",
        default="http://localhost:8000/mcp",
        help="HTTP MCP endpoint when --transport=http",
    )
    # parser.add_argument("-w"
    #     "--workdir",
    #     default=".",
    #     help="Working directory for execute_command scenarios",
    # )
    parser.add_argument("-w", "--workdir", type=str, default=None)

    parser.add_argument(
        "--shell",
        default="bash",
        help="Shell name for execute_command scenarios",
    )
    parser.add_argument(
        "--report",
        default="report.txt",
        help="Output report path",
    )
    return parser.parse_args()


def build_client(args) -> Client:

    transport = args.transport
    url = args.url

    if transport == "http":
        return Client(url)

    from mcp_file_edit.server import build_server
    from mcp_file_edit.config import  parse_args
    from mcp_file_edit import config

    workdir = Path(args.workdir).resolve() if args.workdir else PROJECT_ROOT.resolve()

    old_argv = sys.argv[:]
    try:
        sys.argv = [
            sys.argv[0],
            "--workdir",
            str(workdir),
            "--directories",
            str(workdir),
        ]
        args = parse_args()

        config.SETTINGS = config.Settings.from_runtime(args)

        server = build_server(config.SETTINGS)

    finally:
        sys.argv = old_argv
    return Client(server)


def extract_text(result: Any) -> str:
    parts: list[str] = []
    for content in getattr(result, "content", []):
        text = getattr(content, "text", "")
        if text:
            parts.append(text)
    return "\n".join(parts).strip()


def _one_line(value: str) -> str:
    return " ".join(value.split())


def _truncate(value: str, limit: int = 72) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _scenario_label(scenario: Scenario) -> str:
    command = scenario.args.get("command")
    if isinstance(command, str) and command:
        return _truncate(_one_line(command))
    return "-"


def _looks_like_error_output(output: str) -> bool:
    text = output.strip()
    if text.startswith("Execution failed:"):
        return True
    if "[timed out after " in text:
        return True
    if "[client disconnected]" in text:
        return True
    if "[exit code:" in text:
        tail = text.rsplit("[exit code:", maxsplit=1)[-1]
        code_text = tail.split("]", maxsplit=1)[0].strip()
        try:
            return int(code_text) != 0
        except ValueError:
            return False
    return False


def _row(columns: list[tuple[str, int]]) -> str:
    parts: list[str] = []
    for text, width in columns:
        parts.append(text.ljust(width)[:width])
    return " | ".join(parts)


async def call_tool(client: Client, scenario: Scenario) -> ScenarioResult:
    label = f"{scenario.tool}({json.dumps(scenario.args, ensure_ascii=False)})"
    print(f"\n=== {label}")

    try:
        result = await client.call_tool(scenario.tool, scenario.args)
        output = extract_text(result)
        if scenario.expect_error:
            if _looks_like_error_output(output):
                print(f"EXPECTED ERROR: {output}")
                return ScenarioResult(
                    scenario=scenario,
                    passed=True,
                    output=output,
                    detail="expected error matched tool error output",
                )
            print("FAILED: expected an error but call succeeded")
            print("OUTPUT> ",output)
            return ScenarioResult(
                scenario=scenario,
                passed=False,
                output=output,
                detail="expected error but call succeeded",
            )

        if scenario.must_contain and scenario.must_contain not in output:
            print(f"FAILED: expected output to contain: {scenario.must_contain!r}")
            print("OUTPUT> ",output or "<empty>")
            return ScenarioResult(
                scenario=scenario,
                passed=False,
                output=output,
                detail=f"missing expected substring: {scenario.must_contain!r}",
            )

        if output.startswith("Error calling tool") and "No such file or directory" in output:
            print("FAILED: unexpected path resolution error")
            print("OUTPUT> ",output)
            return ScenarioResult(
                scenario=scenario,
                passed=False,
                output=output,
                detail="unexpected path resolution error",
            )

        print("OUTPUT> ",output or "<empty>")
        return ScenarioResult(scenario=scenario, passed=True, output=output)
    except Exception as exc:  # noqa: BLE001
        if scenario.expect_error:
            print(f"EXPECTED ERROR: {exc}")
            return ScenarioResult(
                scenario=scenario,
                passed=True,
                error=str(exc),
                detail="expected exception raised",
            )
        print(f"FAILED: {exc}")
        return ScenarioResult(
            scenario=scenario,
            passed=False,
            error=str(exc),
            detail="unexpected exception",
        )


def write_report(
    report_path: Path,
    args: argparse.Namespace,
    results: list[ScenarioResult],
) -> None:
    passed = sum(1 for item in results if item.passed)
    total = len(results)
    failed = [item for item in results if not item.passed]

    lines: list[str] = []
    lines.append("Shell MCP Server Test Report")
    lines.append(f"Generated: {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"Host OS: {platform.platform()}")
    lines.append(f"Host System: {platform.system()} {platform.release()}")
    lines.append(f"Host Machine: {platform.machine()}")
    lines.append(f"Host CPU: {platform.processor() or 'unknown'}")
    lines.append(f"CPU Cores (logical): {os.cpu_count()}")
    lines.append(f"Memory Total: {_get_memory_total_human()}")
    lines.append(f"Python: {platform.python_version()}")
    lines.append(f"Transport: {args.transport}")
    lines.append(f"CWD arg: {args.workdir}")
    lines.append(f"Shell arg: {args.shell}")
    lines.append(f"Summary: {passed}/{total} scenarios passed")
    lines.append("")

    lines.append("Result Table")
    lines.append("=" * 78)
    lines.append(
        _row(
            [
                ("#", 3),
                ("Status", 6),
                ("Tool", 18),
                ("Check", 24),
                ("Case", 22),
            ]
        )
    )
    lines.append("-" * 78)
    for idx, item in enumerate(results, start=1):
        scenario = item.scenario
        if scenario.expect_error:
            check = "expect error"
        elif scenario.must_contain:
            check = _truncate(f"contains: {scenario.must_contain}", 24)
        else:
            check = "normal"
        lines.append(
            _row(
                [
                    (str(idx), 3),
                    ("PASS" if item.passed else "FAIL", 6),
                    (scenario.tool, 18),
                    (check, 24),
                    (_scenario_label(scenario), 22),
                ]
            )
        )
    lines.append("=" * 78)
    lines.append("")

    lines.append(f"Failed Scenarios: {len(failed)}")
    if failed:
        lines.append("-" * 78)
        for item in failed:
            scenario = item.scenario
            lines.append(f"Tool: {scenario.tool}")
            lines.append(f"Args: {json.dumps(scenario.args, ensure_ascii=False)}")
            if scenario.must_contain:
                lines.append(f"Expected contain: {scenario.must_contain}")
            if scenario.expect_error:
                lines.append("Expected error: True")
            if item.detail:
                lines.append(f"Detail: {item.detail}")
            if item.error:
                lines.append(f"Error: {item.error}")
            if item.output:
                lines.append("Actual output:")
                lines.append(item.output)
            lines.append("-" * 78)
    lines.append("")

    lines.append("Detailed Results")
    lines.append("=" * 78)

    for idx, item in enumerate(results, start=1):
        scenario = item.scenario
        status = "PASS" if item.passed else "FAIL"
        lines.append(f"[{idx}] {status} {scenario.tool}")
        lines.append(f"Args: {json.dumps(scenario.args, ensure_ascii=False)}")
        lines.append(f"Expect error: {scenario.expect_error}")
        if scenario.must_contain:
            lines.append(f"Must contain: {scenario.must_contain}")
        if item.detail:
            lines.append(f"Detail: {item.detail}")
        if item.error:
            lines.append(f"Error: {item.error}")
        if item.output:
            lines.append("Output:")
            lines.append(item.output)
        lines.append("-" * 78)

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _get_memory_total_human() -> str:
    """Best-effort total memory detection with stdlib fallbacks."""
    # Linux / WSL
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        try:
            for line in meminfo.read_text(encoding="utf-8").splitlines():
                if line.startswith("MemTotal:"):
                    # Format: MemTotal:  32895332 kB
                    kb = int(line.split()[1])
                    return _format_bytes(kb * 1024)
        except Exception:  # noqa: BLE001
            pass

    # Optional psutil fallback if available in environment.
    try:
        import psutil  # type: ignore

        return _format_bytes(int(psutil.virtual_memory().total))
    except Exception:  # noqa: BLE001
        return "unknown"


def _format_bytes(value: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(value)
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{value} B"


def _is_wsl_runtime() -> bool:
    if platform.system().lower() != "linux":
        return False
    release = platform.release().lower()
    version = platform.version().lower()
    return "microsoft" in release or "microsoft" in version


def is_wsl() -> bool:
    return _is_wsl_runtime()


def _expected_sandbox_base() -> str:
    if platform.system().lower().startswith("win"):
        return "/app"
    if _is_wsl_runtime():
        return str(PROJECT_ROOT)
    return "/workspace"


# Keep this as a raw multiline bash script, then normalize to LF for Windows drun.
human_like_python_project_cmd = r"""
set -e
proj=".mcp_human_py"

rm -rf "$proj" && mkdir -p "$proj"

# Avoid single quotes in payload to keep PowerShell -> drun -> bash quoting stable.
echo "import toml,time" > "$proj/main.py"

echo "data={\"status\": \"success\", \"msg\": \"hello from app\"}" >> "$proj/main.py"
echo "print(f'data: {data}')" >> "$proj/main.py"
echo "print(toml.dumps(data))" >> "$proj/main.py"

echo "print('sleep 2')" >> "$proj/main.py"

echo "time.sleep(2)" >> "$proj/main.py"


echo "print('sleep 3')" >> "$proj/main.py"

echo "time.sleep(3)" >> "$proj/main.py"


echo "print('sleep 1')" >> "$proj/main.py"

echo "time.sleep(1)" >> "$proj/main.py"


echo "print('sleep 2')" >> "$proj/main.py"

echo "time.sleep(2)" >> "$proj/main.py"

echo "toml" > "$proj/requirements.txt"

uv pip install -r "$proj/requirements.txt"
python3 "$proj/main.py"
""".replace("\r\n", "\n").strip()


import os, shutil, stat

def remove_readonly(func, path, _):
    os.chmod(path, stat.S_IWRITE)
    func(path)

def clean_workspace():
    ws = PROJECT_ROOT / ".workspace"
    if ws.exists():
        shutil.rmtree(ws, onerror=remove_readonly)

def prepare_workspace() -> dict[str, Path]:
    ws = PROJECT_ROOT / ".workspace/mcp_test_workspace"
    if ws.exists():
        shutil.rmtree(ws, onerror=remove_readonly)
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
    if clone_target.exists():
        shutil.rmtree(clone_target, onerror=remove_readonly)
    # clone_target.mkdir(parents=True, exist_ok=True)

    return {"ws": ws, "files": files, "gitrepo": gitrepo, "clone_target": clone_target}


def build_scenarios() -> list[Scenario]:
    


    test_dir = ".tests"
    git_rel = f"git_project"
    clone_rel = f"git_clone_project"
    scenarios = [
        # project tools
        Scenario("remove directory valid", "remove_directory", {"path": f"../"}, expect_error=True),

        # Scenario("remove directory valid", "remove_directory", {"path": f"{test_dir}"}),

        Scenario("create directory valid", "create_directory", {"path": f"{test_dir}", "create_dirs": True}),
       
        Scenario("set project valid", "set_project_directory", {"path": f"{test_dir}", "connection_type": "local"}, require_keys=["project_directory", "connection_type"]),
        Scenario("get project", "get_project_directory", {}, require_keys=["project_directory", "connection_type"]),
        Scenario("set project invalid", "set_project_directory", {"path": "/", "connection_type": "local"}, expect_error=True),
        Scenario("set project invalid", "set_project_directory", {"path": "../", "connection_type": "local"}, expect_error=True),
        Scenario("set project invalid", "set_project_directory", {"path": "..//", "connection_type": "local"}, expect_error=True),
        Scenario("set project invalid", "set_project_directory", {"path": "..\\..//", "connection_type": "local"}, expect_error=True),
        
        Scenario("get project", "get_project_directory", {}, require_keys=["project_directory", "connection_type"]),

        # file tools valid
        Scenario("write file valid", "write_file", {"path": f"./README.md", "content": "hello MCP"}, require_keys=["path", "size"]),
        Scenario("list files valid", "list_files", {"path": ".", "pattern": "*.md"}),
        Scenario("read file valid", "read_file", {"path": "README.md"}, must_contain="MCP"),
        Scenario("write file valid", "write_file", {"path": f"./write_target.txt", "content": "hello"}, require_keys=["path", "size"]),
        Scenario("create file valid", "create_file", {"path": f"./new.txt", "content": "new"}),
        Scenario("copy file valid", "copy_file", {"source": f"./new.txt", "destination": f"./a_copy.txt"}),
        Scenario("move file valid", "move_file", {"source": f"./a_copy.txt", "destination": f"./a_moved.txt"}),
        Scenario("search files valid", "search_files", {"pattern": "foo", "path": "./"}),
        Scenario("replace files valid", "replace_in_files", {"search": "alpha", "replace": "ALPHA", "path": "."}),
        Scenario("create py file", "write_file",{"path":"./b.py", "content":"def foo():\n    return 1\n\ndef bar(x):\n    return x\n" }),
        Scenario("patch file valid", "patch_file", {"path": f"./b.py", "patches": [{"search": "return 1", "replace": "return 2"}], "backup": False}),
        Scenario("get file info valid", "get_file_info", {"path": f"./b.py"}, require_keys=["name", "size"]),
        Scenario("delete file valid", "delete_file", {"path": f"./new.txt"}),

        # file tools invalid
        Scenario("list files invalid", "list_files", {"path": "README.md"}, expect_error=True),
        Scenario("read file invalid", "read_file", {"path": "../README.md"}, expect_error=True),
        Scenario("write file invalid", "write_file", {"path": "../x.txt", "content": "x"}, expect_error=True),
        Scenario("create file invalid", "create_file", {"path": f"./b.py", "content": "dup"}, expect_error=True),
        Scenario("copy file invalid", "copy_file", {"source": f"./missing.txt", "destination": f"./x.txt"}, expect_error=True),
        Scenario("move file invalid", "move_file", {"source": f"./missing.txt", "destination": f"./x.txt"}, expect_error=True),
        Scenario("search files invalid", "search_files", {"pattern": "(*", "path": "."}, expect_error=True),
        Scenario("replace files invalid", "replace_in_files", {"search": "(*", "replace": "x", "path": "."}, expect_error=True),
        Scenario("patch file invalid", "patch_file", {"path": f"./b.py", "patches": [{"bad": "shape"}]}, expect_error=True),
        Scenario("get file info invalid", "get_file_info", {"path": f"./missing.py"}, expect_error=True),
        Scenario("delete file invalid", "delete_file", {"path": f"./missing.txt"}, expect_error=True),

        # code analysis valid
        Scenario("list functions valid", "list_functions", {"path": f"./b.py"}),
        Scenario("function at line valid", "get_function_at_line", {"path": f"./b.py", "line_number": 1}),
        Scenario("code structure valid", "get_code_structure", {"path": f"./b.py"}, require_keys=["language"]),
        Scenario("search functions valid", "search_functions", {"pattern": "foo", "path": "."}),

        # code analysis invalid
        Scenario("list functions invalid", "list_functions", {"path": f"./missing.py"}, expect_error=True),
        Scenario("function at line invalid", "get_function_at_line", {"path": f"./missing.py", "line_number": 1}, expect_error=True),
        Scenario("code structure invalid", "get_code_structure", {"path": f"./missing.py"}, expect_error=True),
        Scenario("search functions invalid", "search_functions", {"pattern": "foo", "path": "../"}, expect_error=True),

        # lint/type/format valid (correct params; may return success false depending env)
        Scenario("detect linters valid", "detect_linters", {"path": "."}, require_keys=["linters", "type_checkers", "formatters"], timeout_s=5.0),
        Scenario("run linter valid", "run_linter", {"path": ".", "timeout": 1}, allow_error_output=True, timeout_s=5.0),
        Scenario("lint file valid", "lint_file", {"path": f"./b.py", "timeout": 1}, allow_error_output=True, timeout_s=5.0),
        Scenario("run type checker valid", "run_type_checker", {"path": ".", "timeout": 1}, allow_error_output=True, timeout_s=5.0),
        Scenario("type check file valid", "type_check_file", {"path": f"./b.py", "timeout": 1}, allow_error_output=True, timeout_s=5.0),
        Scenario("format file valid", "format_file", {"path": f"./b.py", "check_only": True, "timeout": 1}, allow_error_output=True, timeout_s=5.0),

        # lint/type/format invalid
        Scenario("detect linters invalid", "detect_linters", {"path": "../"}, expect_error=True),
        Scenario("run linter invalid", "run_linter", {"path": "../"}, expect_error=True),
        Scenario("lint file invalid", "lint_file", {"path": "../x.py"}, expect_error=True),
        Scenario("run type checker invalid", "run_type_checker", {"path": "../"}, expect_error=True),
        Scenario("type check file invalid", "type_check_file", {"path": "../x.py"}, expect_error=True),
        Scenario("format file invalid", "format_file", {"path": "../x.py"}, expect_error=True),

        # git valid flow
        Scenario("create directory valid", "create_directory", {"path": git_rel, "create_dirs": True}),

        Scenario("set project git", "set_project_directory", {"path": f"{test_dir}/{git_rel}", "connection_type": "local"}),
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
        
        # Scenario("git clone valid", "git_clone", {"url": "https://github.com/marlocarlo/psmux", "path": clone_rel, "depth": 1}, allow_error_output=True, timeout_s=8.0),
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
        windows_files_rel = ".".replace("/", "\\")
        scenarios.extend(
            [
           Scenario("set project valid", "set_project_directory", {"path": f"{test_dir}", "connection_type": "local"}, require_keys=["project_directory", "connection_type"]),

                # Windows accepts relative POSIX paths but rejects POSIX absolute paths.
                Scenario("windows relative posix path valid", "read_file", {"path": f"./b.py"}, must_contain="def foo"),
                Scenario("windows posix absolute path invalid", "read_file", {"path": "/etc/passwd"}, expect_error=True),
                Scenario("windows backslash read valid", "read_file", {"path": f"{windows_files_rel}\\b.py"}, must_contain="def foo"),
                Scenario("windows traversal invalid", "read_file", {"path": "..\\README.md"}, expect_error=True),
                Scenario("windows root outside allowlist", "set_project_directory", {"path": "C:\\Windows", "connection_type": "local"}, expect_error=True),
            ]
        )
    else:
        scenarios.extend(
            [

           Scenario("set project valid", "set_project_directory", {"path": f"{test_dir}", "connection_type": "local"}, require_keys=["project_directory", "connection_type"]),
            Scenario(
                "linux relative posix path valid",
                "read_file",
                {"path": f"./b.py"},
                must_contain="def foo",
            ),
                        Scenario(
                "linux windows style path invalid",
                "read_file",
                {"path": r"C:\\Windows\\System32\\drivers\\etc\\hosts"},
                expect_error=True,
            ),

Scenario("posix traversal invalid", "read_file", {"path": "../README.md"}, expect_error=True)
            ]
        )
        if is_wsl():
            scenarios.append(
                Scenario("wsl windows-mount outside allowlist", "set_project_directory", {"path": "/mnt/c/Windows", "connection_type": "local"}, expect_error=True)
            )

    return scenarios


def reset_test_workspace(root: Path) -> None:
    test_dir = root / ".tests"
    if test_dir.exists():
        shutil.rmtree(test_dir, ignore_errors=True)


async def run_scenarios(args: argparse.Namespace) -> int:
    workdir = Path(args.workdir).resolve() if args.workdir else PROJECT_ROOT.resolve()
    reset_test_workspace(workdir)
    client = build_client(args)
 
    # path = prepare_workspace()
    scenarios =build_scenarios()
 
    results: list[ScenarioResult] = []
    async with client:
        tmux_available = True
        # try:
        #     probe = await client.call_tool(
        #         "execute_command",
        #         {"command": "tmux -V >/dev/null 2>&1; echo $?", "cwd": args.cwd, "shell": args.shell},
        #     )
        #     probe_text = extract_text(probe)
        #     tmux_available = "\n0\n" in f"\n{probe_text}\n"
        # except Exception:
        #     tmux_available = False

        for scenario in scenarios:
            results.append(await call_tool(client, scenario))

    passed = sum(1 for item in results if item.passed)
    total = len(results)
    print(f"\nSummary: {passed}/{total} scenarios passed")
    report_path = Path(args.report)
    if not report_path.is_absolute():
        report_path = PROJECT_ROOT / report_path
    report_path = report_path.resolve()
    write_report(report_path=report_path, args=args, results=results)
    print(f"Report written: {report_path}")
    # clean_workspace()
    return 0 if passed == total else 1


def main() -> None:
    args = parse_args()
    exit_code = asyncio.run(run_scenarios(args))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
