#!/usr/bin/env python3
"""
Linting and type checking tools for MCP File Editor
Supports multiple languages and tools.
"""

import asyncio
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Any, Optional

from .utils import resolve_path, is_safe_path, get_file_type


LINTER_CONFIG_FILES = {
    "ruff": ["ruff.toml", "pyproject.toml", ".ruff.toml"],
    "pylint": [".pylintrc", "pyproject.toml", "setup.cfg"],
    "flake8": [".flake8", "pyproject.toml", "setup.cfg"],
    "mypy": ["mypy.ini", "pyproject.toml", ".mypy.ini"],
    "pyright": ["pyrightconfig.json", "tsconfig.json"],
    "eslint": [".eslintrc.json", ".eslintrc.js", "eslint.config.js", "package.json"],
    "tslint": ["tslint.json"],
    "golangci-lint": [".golangci.yml", ".golangci.yaml"],
    "clippy": ["rust-toolchain.toml"],
    "rustfmt": ["rustfmt.toml"],
}


SUPPORTED_LINTERS = {
    "python": ["ruff", "pylint", "flake8"],
    "javascript": ["eslint"],
    "typescript": ["eslint", "tslint"],
    "rust": ["clippy", "rustfmt"],
    "go": ["golangci-lint"],
}

SUPPORTED_TYPE_CHECKERS = {
    "python": ["mypy", "pyright"],
    "typescript": ["tsc"],
    "go": ["go vet"],
}

SUPPORTED_FORMATTERS = {
    "python": ["ruff"],
    "javascript": ["prettier"],
    "typescript": ["prettier"],
    "rust": ["rustfmt"],
    "go": ["gofmt"],
}


def get_language_from_file(path: str) -> Optional[str]:
    """Detect language from file extension."""
    suffix = Path(path).suffix.lower()
    mapping = {
        ".py": "python",
        ".pyw": "python",
        ".pyi": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".rs": "rust",
        ".go": "go",
        ".java": "java",
        ".cs": "csharp",
    }
    return mapping.get(suffix)


def is_tool_available(tool: str) -> bool:
    """Check if a tool is available in the system."""
    return shutil.which(tool) is not None


async def run_command(
    cmd: List[str], cwd: Optional[str] = None, timeout: int = 60
) -> Dict[str, Any]:
    """Run a command and return the result."""
    try:
        result = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "combined": result.stdout + result.stderr,
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "returncode": -1,
            "stdout": "",
            "stderr": f"Command timed out after {timeout} seconds",
            "combined": f"Command timed out after {timeout} seconds",
        }
    except Exception as e:
        return {
            "success": False,
            "returncode": -1,
            "stdout": "",
            "stderr": str(e),
            "combined": str(e),
        }


def parse_ruff_output(output: str) -> List[Dict[str, Any]]:
    """Parse ruff linter output."""
    issues = []
    lines = output.strip().split("\n")

    for i, line in enumerate(lines):
        line = line.strip()

        if " --> " in line:
            parts = line.split(" --> ")
            if len(parts) == 2:
                file_part = parts[0]
                location_part = parts[1]

                file_match = file_part.strip()
                loc_match = location_part.split(":")

                if len(loc_match) >= 2:
                    try:
                        line_num = int(loc_match[0])
                        col = int(loc_match[1]) if len(loc_match) > 1 else 0

                        message = ""
                        if i + 1 < len(lines):
                            next_line = lines[i + 1].strip()
                            if next_line and not next_line.startswith("-->"):
                                message = next_line

                        code = file_match.split()[0] if file_match else ""
                        severity = "error" if code and code[0] in "EF" else "warning"

                        issues.append(
                            {
                                "file": file_match,
                                "line": line_num,
                                "column": col,
                                "code": code,
                                "message": message,
                                "severity": severity,
                            }
                        )
                    except (ValueError, IndexError):
                        pass
        elif line and not line.startswith("Found ") and not line.startswith("help:"):
            if any(c.isalnum() for c in line):
                issues.append({"raw": line})

    return issues


def parse_eslint_output(output: str) -> List[Dict[str, Any]]:
    """Parse eslint output."""
    issues = []
    try:
        data = json.loads(output)
        if isinstance(data, list):
            for item in data:
                issues.append(
                    {
                        "file": item.get("filePath", ""),
                        "line": item.get("line", 0),
                        "column": item.get("column", 0),
                        "message": item.get("message", ""),
                        "rule": item.get("ruleId", ""),
                        "severity": "error"
                        if item.get("severity", 0) >= 2
                        else "warning",
                    }
                )
    except json.JSONDecodeError:
        for line in output.strip().split("\n"):
            if line:
                issues.append({"raw": line})
    return issues


def parse_mypy_output(output: str, cwd: str) -> List[Dict[str, Any]]:
    """Parse mypy output."""
    issues = []
    for line in output.strip().split("\n"):
        if not line or line.startswith("<"):
            continue
        match = re.match(r"(.+?):(\d+):\s+(\w+):\s+(.+)", line)
        if match:
            issues.append(
                {
                    "file": match.group(1),
                    "line": int(match.group(2)),
                    "severity": match.group(3),
                    "message": match.group(4),
                }
            )
    return issues


def parse_tsc_output(output: str) -> List[Dict[str, Any]]:
    """Parse TypeScript compiler output."""
    issues = []
    try:
        data = json.loads(output)
        if "errors" in data:
            for err in data["errors"]:
                issues.append(
                    {
                        "file": err.get("file", ""),
                        "line": err.get("line", 0),
                        "column": err.get("start", {}).get("column", 0),
                        "message": err.get("text", ""),
                        "code": err.get("code", ""),
                        "severity": "error",
                    }
                )
    except json.JSONDecodeError:
        for line in output.strip().split("\n"):
            if "error" in line.lower():
                match = re.match(r"(.+?)\((\d+),(\d+)\): (.+)", line)
                if match:
                    issues.append(
                        {
                            "file": match.group(1),
                            "line": int(match.group(2)),
                            "column": int(match.group(3)),
                            "message": match.group(4),
                            "severity": "error",
                        }
                    )
    return issues


async def detect_linters(path: str = ".") -> Dict[str, Any]:
    """
    Detect available linters and type checkers in a project.

    Args:
        path: Path to the project directory.

    Returns:
        Dictionary with available tools and detected config files.
    """
    resolved = resolve_path(path)
    if not is_safe_path(resolved):
        raise ValueError(f"Path not allowed: {path}")

    project_path = Path(resolved)
    if not project_path.exists():
        raise ValueError(f"Path does not exist: {path}")

    if not project_path.is_dir():
        project_path = project_path.parent

    available = {
        "linters": [],
        "type_checkers": [],
        "formatters": [],
        "detected_config": {},
    }

    for tool in [
        "ruff",
        "pylint",
        "flake8",
        "eslint",
        "prettier",
        "mypy",
        "pyright",
        "tsc",
        "clippy",
        "rustfmt",
        "golangci-lint",
        "gofmt",
        "go vet",
    ]:
        if is_tool_available(tool):
            if tool in SUPPORTED_LINTERS.get("python", []) or tool in [
                "eslint",
                "clippy",
                "golangci-lint",
            ]:
                available["linters"].append(tool)
            if tool in ["mypy", "pyright", "tsc", "go vet"]:
                available["type_checkers"].append(tool)
            if tool in ["ruff", "prettier", "rustfmt", "gofmt"]:
                available["formatters"].append(tool)

    for tool, config_files in LINTER_CONFIG_FILES.items():
        for config_file in config_files:
            config_path = project_path / config_file
            if config_path.exists():
                available["detected_config"][tool] = str(config_path)
                break

    detected_langs = set()
    for ext in [".py", ".js", ".jsx", ".ts", ".tsx", ".rs", ".go", ".java", ".cs"]:
        if list(project_path.rglob(f"*{ext}")):
            detected_langs.add(get_language_from_file(f"file{ext}"))

    available["detected_languages"] = list(detected_langs)

    return available


async def run_linter(
    path: str = ".", tool: Optional[str] = None, fix: bool = False, timeout: int = 60
) -> Dict[str, Any]:
    """
    Run a linter on a project or file.

    Args:
        path: Path to lint (file or directory).
        tool: Specific linter to use. If None, auto-detect.
        fix: If True, attempt to fix issues automatically.
        timeout: Maximum time in seconds.

    Returns:
        Dictionary with lint results.
    """
    resolved = resolve_path(path)
    if not is_safe_path(resolved):
        raise ValueError(f"Path not allowed: {path}")

    project_path = Path(resolved)
    if not project_path.exists():
        raise ValueError(f"Path does not exist: {path}")

    work_dir = str(project_path.parent) if project_path.is_file() else str(project_path)

    if tool is None:
        available = await detect_linters(work_dir)
        if available["linters"]:
            tool = available["linters"][0]
        else:
            return {"success": False, "error": "No linters found", "issues": []}

    if tool is not None and not is_tool_available(tool):
        return {"success": False, "error": f"Tool {tool} not found", "issues": []}

    cmd = []
    issues = []
    fix_applied = False

    if tool == "ruff":
        cmd = ["ruff", "check"]
        if fix:
            cmd.append("--fix")
            fix_applied = True
        cmd.append(str(project_path))
        result = await run_command(cmd, work_dir, timeout)

        if fix:
            format_result = await run_command(
                ["ruff", "format", str(project_path)], work_dir, timeout
            )
            if format_result.get("returncode", 0) == 0:
                fix_applied = True

        issues = parse_ruff_output(result.get("combined", ""))

    elif tool == "pylint":
        cmd = ["pylint"]
        if fix:
            cmd.append("--fix")
            fix_applied = True
        cmd.append(str(project_path))
        result = await run_command(cmd, work_dir, timeout)

    elif tool == "flake8":
        cmd = ["flake8", str(project_path)]
        result = await run_command(cmd, work_dir, timeout)

    elif tool == "eslint":
        cmd = ["eslint", "--format", "json"]
        if fix:
            cmd.append("--fix")
            fix_applied = True
        cmd.append(str(project_path))
        result = await run_command(cmd, work_dir, timeout)
        issues = parse_eslint_output(result.get("stdout", ""))

    elif tool == "clippy":
        cmd = ["cargo", "clippy", "--", "-D", "warnings"]
        result = await run_command(cmd, work_dir, timeout)

    elif tool == "golangci-lint":
        cmd = ["golangci-lint", "run"]
        if fix:
            cmd.append("--fix")
            fix_applied = True
        result = await run_command(cmd, work_dir, timeout)

    else:
        return {"success": False, "error": f"Unsupported linter: {tool}", "issues": []}

    returncode = result.get("returncode", 0)
    success = returncode == 0

    return {
        "success": success,
        "tool": tool,
        "path": path,
        "returncode": returncode,
        "fix_applied": fix_applied if fix else False,
        "fix_requested": fix,
        "issues": issues,
        "output": result.get("combined", "")[:5000],
    }


async def lint_file(
    path: str, tool: Optional[str] = None, fix: bool = False, timeout: int = 30
) -> Dict[str, Any]:
    """
    Lint a specific file.

    Args:
        path: Path to the file to lint.
        tool: Specific linter to use. If None, auto-detect.
        fix: If True, attempt to fix issues.
        timeout: Maximum time in seconds.

    Returns:
        Dictionary with lint results.
    """
    return await run_linter(path=path, tool=tool, fix=fix, timeout=timeout)


async def run_type_checker(
    path: str = ".", tool: Optional[str] = None, timeout: int = 60
) -> Dict[str, Any]:
    """
    Run a type checker on a project or file.

    Args:
        path: Path to check (file or directory).
        tool: Specific type checker to use. If None, auto-detect.
        timeout: Maximum time in seconds.

    Returns:
        Dictionary with type check results.
    """
    resolved = resolve_path(path)
    if not is_safe_path(resolved):
        raise ValueError(f"Path not allowed: {path}")

    project_path = Path(resolved)
    if not project_path.exists():
        raise ValueError(f"Path does not exist: {path}")

    work_dir = str(project_path.parent) if project_path.is_file() else str(project_path)

    if tool is None:
        available = await detect_linters(work_dir)
        if available["type_checkers"]:
            tool = available["type_checkers"][0]
        else:
            return {"success": False, "error": "No type checkers found", "issues": []}

    if tool is not None and not is_tool_available(tool):
        return {"success": False, "error": f"Tool {tool} not found", "issues": []}

    cmd = []
    issues = []

    if tool == "mypy":
        cmd = ["mypy", str(project_path)]
        result = await run_command(cmd, work_dir, timeout)
        issues = parse_mypy_output(result.get("combined", ""), work_dir)

    elif tool == "pyright":
        cmd = ["pyright", str(project_path)]
        result = await run_command(cmd, work_dir, timeout)

    elif tool == "tsc":
        cmd = ["tsc", "--noEmit", "--pretty", "false"]
        result = await run_command(cmd, work_dir, timeout)
        issues = parse_tsc_output(result.get("stdout", ""))

    elif tool == "go vet":
        cmd = ["go", "vet", "./..."]
        result = await run_command(cmd, work_dir, timeout)

    else:
        return {
            "success": False,
            "error": f"Unsupported type checker: {tool}",
            "issues": [],
        }

    return {
        "success": result.get("success", False),
        "tool": tool,
        "path": path,
        "returncode": result.get("returncode"),
        "issues": issues,
        "output": result.get("combined", "")[:5000],
    }


async def type_check_file(
    path: str, tool: Optional[str] = None, timeout: int = 30
) -> Dict[str, Any]:
    """
    Type check a specific file.

    Args:
        path: Path to the file to type check.
        tool: Specific type checker to use. If None, auto-detect.
        timeout: Maximum time in seconds.

    Returns:
        Dictionary with type check results.
    """
    return await run_type_checker(path=path, tool=tool, timeout=timeout)


async def format_file(
    path: str, tool: Optional[str] = None, check_only: bool = False, timeout: int = 30
) -> Dict[str, Any]:
    """
    Format a file using the appropriate formatter.

    Args:
        path: Path to the file to format.
        tool: Specific formatter to use. If None, auto-detect.
        check_only: If True, only check if file needs formatting (don't modify).
        timeout: Maximum time in seconds.

    Returns:
        Dictionary with format results.
    """
    resolved = resolve_path(path)
    if not is_safe_path(resolved):
        raise ValueError(f"Path not allowed: {path}")

    file_path = Path(resolved)
    if not file_path.exists():
        raise ValueError(f"File does not exist: {path}")

    work_dir = str(file_path.parent)

    if tool is None:
        ext = file_path.suffix.lower()
        lang = get_language_from_file(path)
        if lang in SUPPORTED_FORMATTERS:
            tool = SUPPORTED_FORMATTERS[lang][0]
        else:
            return {
                "success": False,
                "error": f"Cannot auto-detect formatter for {path}",
                "modified": False,
            }

    if tool is not None and not is_tool_available(tool):
        return {"success": False, "error": f"Tool {tool} not found", "modified": False}

    cmd = []

    if tool == "ruff":
        cmd = ["ruff", "format"]
        if check_only:
            cmd.append("--check")
        cmd.append(str(file_path))

    elif tool == "prettier":
        cmd = ["prettier"]
        if check_only:
            cmd.append("--check")
        else:
            cmd.append("--write")
        cmd.append(str(file_path))

    elif tool == "rustfmt":
        cmd = ["rustfmt"]
        if check_only:
            cmd.append("--check")
        cmd.append(str(file_path))

    elif tool == "gofmt":
        cmd = ["gofmt"]
        if not check_only:
            cmd.append("-w")
        cmd.append(str(file_path))

    else:
        return {
            "success": False,
            "error": f"Unsupported formatter: {tool}",
            "modified": False,
        }

    result = await run_command(cmd, work_dir, timeout)

    return {
        "success": result.get("success", False),
        "tool": tool,
        "path": path,
        "returncode": result.get("returncode"),
        "modified": not check_only and result.get("returncode") == 0,
        "check_only": check_only,
        "output": result.get("combined", "")[:2000],
    }
