#!/usr/bin/env python3
"""
Test the linting and type checking functionality
"""

import asyncio
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


TEST_FILES = [
    "tests/test_lint_sample.py",
    "tests/test_format_sample.py",
    "tests/test_type_sample.py",
    "tests/test_lint_file_sample.py",
    "tests/test_type_file_sample.py",
]


async def cleanup_test_files():
    """Clean up test files after tests"""
    from mcp_file_edit.server import delete_file

    for test_file in TEST_FILES:
        try:
            await delete_file(path=test_file)
        except:
            pass


async def test_detect_linters():
    """Test detecting available linters"""
    from mcp_file_edit.server import set_project_directory
    from mcp_file_edit.linting_tools import detect_linters

    print("=== Testing detect_linters ===\n")

    await set_project_directory(".")

    result = await detect_linters(path=".")

    print(f"Available linters: {result.get('linters', [])}")
    print(f"Available type checkers: {result.get('type_checkers', [])}")
    print(f"Available formatters: {result.get('formatters', [])}")
    print(f"Detected config: {result.get('detected_config', {})}")
    print(f"Detected languages: {result.get('detected_languages', [])}")
    print()

    # Consider it a pass if we got any results
    return result


async def test_run_linter():
    """Test running linter"""
    from mcp_file_edit.server import set_project_directory, write_file
    from mcp_file_edit.linting_tools import run_linter

    print("=== Testing run_linter ===\n")

    await set_project_directory(".")

    test_file_content = '''"""Test file with lint issues"""
import os
import sys # unused import

def unused_function():
    """This function is never used"""
    x=1+2 # spaces around operator
    return x

class TestClass:
    pass
'''

    test_file_path = "tests/test_lint_sample.py"
    await write_file(path=test_file_path, content=test_file_content, create_dirs=True)

    # Run linter without fix
    result = await run_linter(path=test_file_path, tool="ruff", fix=False)

    print(f"Success: {result.get('success')}")
    print(f"Tool: {result.get('tool')}")
    print(f"Return code: {result.get('returncode')}")
    print(f"Issues count: {len(result.get('issues', []))}")
    print(f"Output: {result.get('output', '')[:500]}")
    print()

    # Run linter with fix
    result_fix = await run_linter(path=test_file_path, tool="ruff", fix=True)

    print(f"With fix - Success: {result_fix.get('success')}")
    print(f"With fix - Return code: {result_fix.get('returncode')}")
    print(f"With fix - Fix applied: {result_fix.get('fix_applied')}")
    print()

    return result


async def test_format_file():
    """Test formatting file"""
    from mcp_file_edit.server import set_project_directory, write_file
    from mcp_file_edit.linting_tools import format_file

    print("=== Testing format_file ===\n")

    await set_project_directory(".")

    test_file_content = """def   bad_format(  ):
    x=1+2
    return    x
"""

    test_file_path = "tests/test_format_sample.py"
    await write_file(path=test_file_path, content=test_file_content, create_dirs=True)

    # Check formatting
    result_check = await format_file(path=test_file_path, tool="ruff", check_only=True)

    print(f"Check only - Success: {result_check.get('success')}")
    print(f"Check only - Modified: {result_check.get('modified')}")
    print(f"Output: {result_check.get('output', '')}")
    print()

    # Apply formatting
    result_format = await format_file(
        path=test_file_path, tool="ruff", check_only=False
    )

    print(f"Format - Success: {result_format.get('success')}")
    print(f"Format - Modified: {result_format.get('modified')}")
    print()

    return result_format


async def test_type_checker():
    """Test running type checker"""
    from mcp_file_edit.server import set_project_directory, write_file
    from mcp_file_edit.linting_tools import run_type_checker

    print("=== Testing run_type_checker ===\n")

    await set_project_directory(".")

    test_file_content = '''"""Test file with type issues"""
def add(a: int, b: int) -> int:
    return a + b

def wrong_types(a: str, b: str) -> int:
    return a + b  # type error: can't add strings and return int
'''

    test_file_path = "tests/test_type_sample.py"
    await write_file(path=test_file_path, content=test_file_content, create_dirs=True)

    # Run type checker (mypy, not ruff)
    result = await run_type_checker(path=test_file_path, tool="mypy")

    print(f"Success: {result.get('success')}")
    print(f"Tool: {result.get('tool')}")
    print(f"Return code: {result.get('returncode')}")
    print(f"Issues count: {len(result.get('issues', []))}")
    print(f"Output: {result.get('output', '')}")
    print()

    return result


async def test_lint_file():
    """Test linting a specific file"""
    from mcp_file_edit.server import set_project_directory, write_file
    from mcp_file_edit.linting_tools import lint_file

    print("=== Testing lint_file ===\n")

    await set_project_directory(".")

    test_file_content = """x=1
y = 2
"""

    test_file_path = "tests/test_lint_file_sample.py"
    await write_file(path=test_file_path, content=test_file_content, create_dirs=True)

    result = await lint_file(path=test_file_path, tool="ruff")

    print(f"Success: {result.get('success')}")
    print(f"Tool: {result.get('tool')}")
    print()

    return result


async def test_type_check_file():
    """Test type checking a specific file"""
    from mcp_file_edit.server import set_project_directory, write_file
    from mcp_file_edit.linting_tools import type_check_file

    print("=== Testing type_check_file ===\n")

    await set_project_directory(".")

    test_file_content = """def foo(x: int) -> str:
    return x  # type error
"""

    test_file_path = "tests/test_type_file_sample.py"
    await write_file(path=test_file_path, content=test_file_content, create_dirs=True)

    result = await type_check_file(path=test_file_path, tool="mypy")

    print(f"Success: {result.get('success')}")
    print(f"Tool: {result.get('tool')}")
    print()

    return result


async def run_all_tests():
    """Run all linting tests"""
    print("\n" + "=" * 60)
    print("LINTING AND TYPE CHECKING TESTS")
    print("=" * 60 + "\n")

    results = {}

    try:
        results["detect_linters"] = await test_detect_linters()
    except Exception as e:
        print(f"Error in detect_linters: {e}")
        results["detect_linters"] = {"error": str(e)}

    try:
        results["run_linter"] = await test_run_linter()
    except Exception as e:
        print(f"Error in run_linter: {e}")
        results["run_linter"] = {"error": str(e)}

    try:
        results["format_file"] = await test_format_file()
    except Exception as e:
        print(f"Error in format_file: {e}")
        results["format_file"] = {"error": str(e)}

    try:
        results["type_checker"] = await test_type_checker()
    except Exception as e:
        print(f"Error in type_checker: {e}")
        results["type_checker"] = {"error": str(e)}

    try:
        results["lint_file"] = await test_lint_file()
    except Exception as e:
        print(f"Error in lint_file: {e}")
        results["lint_file"] = {"error": str(e)}

    try:
        results["type_check_file"] = await test_type_check_file()
    except Exception as e:
        print(f"Error in type_check_file: {e}")
        results["type_check_file"] = {"error": str(e)}

    # Additional tests
    try:
        results["auto_detect_linter"] = await test_auto_detect_linter()
    except Exception as e:
        print(f"Error in auto_detect_linter: {e}")
        results["auto_detect_linter"] = {"error": str(e)}

    try:
        results["pyright"] = await test_pyright()
    except Exception as e:
        print(f"Error in pyright: {e}")
        results["pyright"] = {"error": str(e)}

    try:
        results["lint_directory"] = await test_lint_directory()
    except Exception as e:
        print(f"Error in lint_directory: {e}")
        results["lint_directory"] = {"error": str(e)}

    try:
        results["format_check_only"] = await test_format_check_only()
    except Exception as e:
        print(f"Error in format_check_only: {e}")
        results["format_check_only"] = {"error": str(e)}

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    for test_name, result in results.items():
        if "error" in result:
            status = "❌ ERROR"
        elif result.get("success") or result.get("tool") is not None:
            # Tool ran successfully (even if issues were found)
            status = "✅ PASS"
        elif (
            result.get("linters")
            or result.get("type_checkers")
            or result.get("formatters")
        ):
            # detect_linters returned results
            status = "✅ PASS"
        else:
            status = "⚠️  FAIL"
        print(f"{test_name}: {status}")

    # Clean up test files
    print("Cleaning up test files...")
    await cleanup_test_files()
    print("Done!\n")


async def test_auto_detect_linter():
    """Test auto-detection of linter"""
    from mcp_file_edit.server import set_project_directory, write_file
    from mcp_file_edit.linting_tools import run_linter

    print("=== Testing auto-detect linter ===\n")

    await set_project_directory(".")

    test_file_content = """x=1
"""

    test_file_path = "tests/test_auto_detect.py"
    await write_file(path=test_file_path, content=test_file_content, create_dirs=True)

    # Run linter without specifying tool
    result = await run_linter(path=test_file_path)

    print(f"Success: {result.get('success')}")
    print(f"Tool (auto-detected): {result.get('tool')}")
    print()

    return result


async def test_pyright():
    """Test pyright type checker"""
    from mcp_file_edit.server import set_project_directory, write_file
    from mcp_file_edit.linting_tools import run_type_checker

    print("=== Testing pyright ===\n")

    await set_project_directory(".")

    test_file_content = """def foo(x: int) -> str:
    return x
"""

    test_file_path = "tests/test_pyright_sample.py"
    await write_file(path=test_file_path, content=test_file_content, create_dirs=True)

    result = await run_type_checker(path=test_file_path, tool="pyright")

    print(f"Success: {result.get('success')}")
    print(f"Tool: {result.get('tool')}")
    print(f"Return code: {result.get('returncode')}")
    print()

    return result


async def test_lint_directory():
    """Test linting a directory"""
    from mcp_file_edit.server import set_project_directory, write_file
    from mcp_file_edit.linting_tools import run_linter

    print("=== Testing lint directory ===\n")

    await set_project_directory(".")

    # Create multiple test files
    test_files = [
        ("tests/dir_test/file1.py", "x=1\ny=2\n"),
        ("tests/dir_test/file2.py", "import os\n"),
    ]

    for path, content in test_files:
        await write_file(path=path, content=content, create_dirs=True)

    result = await run_linter(path="tests/dir_test/", tool="ruff")

    print(f"Success: {result.get('success')}")
    print(f"Tool: {result.get('tool')}")
    print(f"Issues count: {len(result.get('issues', []))}")
    print()

    # Cleanup
    from mcp_file_edit.server import delete_file

    await delete_file(path="tests/dir_test/", recursive=True)

    return result


async def test_format_check_only():
    """Test format check only mode"""
    from mcp_file_edit.server import set_project_directory, write_file
    from mcp_file_edit.linting_tools import format_file

    print("=== Testing format check only ===\n")

    await set_project_directory(".")

    test_file_content = """def   bad():
        return    1
"""

    test_file_path = "tests/test_check_only.py"
    await write_file(path=test_file_path, content=test_file_content, create_dirs=True)

    result = await format_file(path=test_file_path, tool="ruff", check_only=True)

    print(f"Success: {result.get('success')}")
    print(f"Modified: {result.get('modified')}")
    print(f"Check only: {result.get('check_only')}")
    print()

    # Read file to verify it wasn't modified
    from mcp_file_edit.server import read_file

    content = await read_file(path=test_file_path)
    print(
        f"File still has bad formatting: {'yes' if 'def   bad' in str(content) else 'no'}"
    )
    print()

    return result


if __name__ == "__main__":
    asyncio.run(run_all_tests())
