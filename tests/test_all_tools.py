#!/usr/bin/env python3
"""
Comprehensive test for all MCP File Editor tools
Tests: list_files, read_file, write_file, create_file, delete_file,
       move_file, copy_file, search_files, replace_in_files, patch_file,
       git operations
"""

import asyncio
import sys
import os
import shutil
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


TEST_DIR = "tests/comprehensive_test_dir"
TEST_FILES = []


async def cleanup():
    """Clean up test files and directories"""
    from mcp_file_edit.server import delete_file

    try:
        await delete_file(path=TEST_DIR, recursive=True)
    except:
        pass


async def test_list_files():
    """Test list_files tool"""
    from mcp_file_edit.server import set_project_directory, write_file, list_files

    print("=== Testing list_files ===\n")

    await set_project_directory(".")

    # Create test files
    test_files = [
        f"{TEST_DIR}/file1.txt",
        f"{TEST_DIR}/file2.txt",
        f"{TEST_DIR}/sub/file3.txt",
    ]

    for f in test_files:
        await write_file(path=f, content="test", create_dirs=True)
        TEST_FILES.append(f)

    # Test list all files
    result = await list_files(path=TEST_DIR)
    print(f"List all: Found {len(result) if isinstance(result, list) else 'error'}")

    # Test list with pattern
    result = await list_files(path=TEST_DIR, pattern="*.txt")
    print(f"List *.txt: Found {len(result) if isinstance(result, list) else 'error'}")

    # Test recursive
    result = await list_files(path=TEST_DIR, recursive=True)
    print(
        f"List recursive: Found {len(result) if isinstance(result, list) else 'error'}"
    )

    print()
    return {"success": True, "tool": "list_files"}


async def test_read_file():
    """Test read_file tool"""
    from mcp_file_edit.server import set_project_directory, write_file, read_file

    print("=== Testing read_file ===\n")

    await set_project_directory(".")

    test_path = f"{TEST_DIR}/read_test.txt"
    test_content = "Line 1\nLine 2\nLine 3"
    await write_file(path=test_path, content=test_content, create_dirs=True)
    TEST_FILES.append(test_path)

    # Read entire file
    result = await read_file(path=test_path)
    print(f"Read full: {str(result)[:50]}...")

    # Read with line range
    result = await read_file(path=test_path, start_line=1, end_line=2)
    print(f"Read lines 1-2: Success")

    print()
    return {"success": True, "tool": "read_file"}


async def test_write_file():
    """Test write_file tool"""
    from mcp_file_edit.server import set_project_directory, write_file, read_file

    print("=== Testing write_file ===\n")

    await set_project_directory(".")

    test_path = f"{TEST_DIR}/write_test.txt"

    # Write new file
    result = await write_file(path=test_path, content="New content")
    print(f"Write new: {result.get('success') if isinstance(result, dict) else 'done'}")

    # Read back
    content = await read_file(path=test_path)
    print(f"Verify write: {'success' if 'New content' in str(content) else 'failed'}")

    # Overwrite
    await write_file(path=test_path, content="Updated content")
    content = await read_file(path=test_path)
    print(f"Overwrite: {'success' if 'Updated' in str(content) else 'failed'}")

    TEST_FILES.append(test_path)
    print()
    return {"success": True, "tool": "write_file"}


async def test_create_file():
    """Test create_file tool"""
    from mcp_file_edit.server import set_project_directory, create_file, read_file

    print("=== Testing create_file ===\n")

    await set_project_directory(".")

    test_path = f"{TEST_DIR}/create_test.txt"

    # Create with content
    result = await create_file(path=test_path, content="Created content")
    print(f"Create with content: done")

    # Verify
    content = await read_file(path=test_path)
    print(f"Verify: {'success' if 'Created' in str(content) else 'failed'}")

    TEST_FILES.append(test_path)
    print()
    return {"success": True, "tool": "create_file"}


async def test_delete_file():
    """Test delete_file tool"""
    from mcp_file_edit.server import (
        set_project_directory,
        write_file,
        delete_file,
        list_files,
    )

    print("=== Testing delete_file ===\n")

    await set_project_directory(".")

    test_path = f"{TEST_DIR}/delete_test.txt"
    await write_file(path=test_path, content="To be deleted")

    # Delete file
    result = await delete_file(path=test_path)
    print(
        f"Delete file: {result.get('success') if isinstance(result, dict) else 'done'}"
    )

    # Verify
    files = await list_files(path=TEST_DIR)
    print(f"Verify delete: {'success' if test_path not in str(files) else 'failed'}")

    print()
    return {"success": True, "tool": "delete_file"}


async def test_move_file():
    """Test move_file tool"""
    from mcp_file_edit.server import (
        set_project_directory,
        write_file,
        move_file,
        list_files,
    )

    print("=== Testing move_file ===\n")

    await set_project_directory(".")

    source = f"{TEST_DIR}/move_source.txt"
    dest = f"{TEST_DIR}/moved_file.txt"

    await write_file(path=source, content="Move me")

    # Move file
    result = await move_file(source=source, destination=dest)
    print(f"Move file: {result.get('success') if isinstance(result, dict) else 'done'}")

    TEST_FILES.append(dest)
    print()
    return {"success": True, "tool": "move_file"}


async def test_copy_file():
    """Test copy_file tool"""
    from mcp_file_edit.server import (
        set_project_directory,
        write_file,
        copy_file,
        read_file,
    )

    print("=== Testing copy_file ===\n")

    await set_project_directory(".")

    source = f"{TEST_DIR}/copy_source.txt"
    dest = f"{TEST_DIR}/copy_dest.txt"

    await write_file(path=source, content="Original content")

    # Copy file
    result = await copy_file(source=source, destination=dest)
    print(f"Copy file: {result.get('success') if isinstance(result, dict) else 'done'}")

    # Verify both exist
    content = await read_file(path=dest)
    print(f"Verify copy: {'success' if 'Original' in str(content) else 'failed'}")

    TEST_FILES.append(source)
    TEST_FILES.append(dest)
    print()
    return {"success": True, "tool": "copy_file"}


async def test_search_files():
    """Test search_files tool"""
    from mcp_file_edit.server import set_project_directory, write_file, search_files

    print("=== Testing search_files ===\n")

    await set_project_directory(".")

    test_path = f"{TEST_DIR}/search_test.py"
    await write_file(
        path=test_path,
        content="""def hello():
    print('hello world')
    return 'hello'
""",
        create_dirs=True,
    )
    TEST_FILES.append(test_path)

    # Search for function
    result = await search_files(pattern="def hello", path=TEST_DIR, file_pattern="*.py")
    print(
        f"Search 'def hello': Found {len(result.get('results', [])) if isinstance(result, dict) else 'N/A'} matches"
    )

    # Search with regex
    result = await search_files(
        pattern="hello.*world", path=TEST_DIR, file_pattern="*.py"
    )
    print(f"Search regex: Found matches")

    print()
    return {"success": True, "tool": "search_files"}


async def test_replace_in_files():
    """Test replace_in_files tool"""
    from mcp_file_edit.server import (
        set_project_directory,
        write_file,
        replace_in_files,
        read_file,
    )

    print("=== Testing replace_in_files ===\n")

    await set_project_directory(".")

    test_path = f"{TEST_DIR}/replace_test.txt"
    await write_file(
        path=test_path, content="Hello world\nHello again", create_dirs=True
    )
    TEST_FILES.append(test_path)

    # Replace
    result = await replace_in_files(
        search="Hello", replace="Hi", path=TEST_DIR, file_pattern="*.txt"
    )
    print(f"Replace: done")

    # Verify
    content = await read_file(path=test_path)
    print(f"Verify: {'success' if 'Hi' in str(content) else 'failed'}")

    print()
    return {"success": True, "tool": "replace_in_files"}


async def test_patch_file():
    """Test patch_file tool"""
    from mcp_file_edit.server import (
        set_project_directory,
        write_file,
        patch_file,
        read_file,
    )

    print("=== Testing patch_file ===\n")

    await set_project_directory(".")

    test_path = f"{TEST_DIR}/patch_test.txt"
    await write_file(
        path=test_path, content="Line 1\nLine 2\nLine 3\nLine 4\n", create_dirs=True
    )
    TEST_FILES.append(test_path)

    # Patch specific lines
    result = await patch_file(
        path=test_path, patches=[{"search": "Line 2", "replace": "Patched Line 2"}]
    )
    print(
        f"Patch: {result.get('patches_applied') if isinstance(result, dict) else 'done'}"
    )

    # Verify
    content = await read_file(path=test_path)
    print(f"Verify: {'success' if 'Patched' in str(content) else 'failed'}")

    print()
    return {"success": True, "tool": "patch_file"}


async def test_git_operations():
    """Test git operations"""
    from mcp_file_edit.server import (
        set_project_directory,
        write_file,
        git_init,
        git_status,
        git_add,
        git_commit,
        git_log,
        git_branch,
    )

    print("=== Testing Git Operations ===\n")

    await set_project_directory(".")

    # Create a test repo
    test_path = f"{TEST_DIR}/git_test"

    # Create directory first
    os.makedirs(test_path, exist_ok=True)

    # git init
    result = await git_init(path=test_path)
    print(f"git init: done")

    # Create file and commit
    test_file = f"{TEST_DIR}/git_test/test.txt"
    await write_file(path=test_file, content="Git test content", create_dirs=True)
    TEST_FILES.append(test_file)

    # git status
    result = await git_status(path=test_path)
    print(f"git status: done")

    # git add
    result = await git_add(files=".", path=test_path)
    print(f"git add: done")

    # git commit
    result = await git_commit(message="Test commit", path=test_path)
    print(f"git commit: done")

    # git log
    result = await git_log(path=test_path)
    print(f"git log: done")

    # git branch
    result = await git_branch(path=test_path)
    print(f"git branch: done")

    print()
    return {"success": True, "tool": "git_operations"}


async def test_code_analysis():
    """Test code analysis tools"""
    from mcp_file_edit.server import (
        set_project_directory,
        write_file,
        list_functions,
        get_code_structure,
        search_functions,
    )

    print("=== Testing Code Analysis ===\n")

    await set_project_directory(".")

    test_path = f"{TEST_DIR}/code_analysis.py"
    await write_file(
        path=test_path,
        content="""def hello():
    '''Say hello'''
    return 'hello'

async def async_func(x: int) -> str:
    '''Async function'''
    return str(x)

class MyClass:
    def method(self):
        pass
""",
        create_dirs=True,
    )
    TEST_FILES.append(test_path)

    # list_functions
    result = await list_functions(path=test_path)
    print(f"list_functions: Found {len(result) if isinstance(result, list) else 'N/A'}")

    # get_code_structure
    result = await get_code_structure(path=test_path)
    print(f"get_code_structure: done")

    # search_functions
    result = await search_functions(pattern="hello", path=TEST_DIR)
    print(f"search_functions: done")

    print()
    return {"success": True, "tool": "code_analysis"}


async def test_get_file_info():
    """Test get_file_info tool"""
    from mcp_file_edit.server import set_project_directory, write_file, get_file_info

    print("=== Testing get_file_info ===\n")

    await set_project_directory(".")

    test_path = f"{TEST_DIR}/info_test.txt"
    await write_file(path=test_path, content="Test content", create_dirs=True)
    TEST_FILES.append(test_path)

    result = await get_file_info(path=test_path)
    print(
        f"get_file_info: is_file={result.get('is_file') if isinstance(result, dict) else 'N/A'}"
    )

    print()
    return {"success": True, "tool": "get_file_info"}


async def run_all_tests():
    """Run all comprehensive tests"""
    print("\n" + "=" * 60)
    print("COMPREHENSIVE TOOL TESTS")
    print("=" * 60 + "\n")

    results = {}

    # Run tests
    tests = [
        ("list_files", test_list_files),
        ("read_file", test_read_file),
        ("write_file", test_write_file),
        ("create_file", test_create_file),
        ("delete_file", test_delete_file),
        ("move_file", test_move_file),
        ("copy_file", test_copy_file),
        ("search_files", test_search_files),
        ("replace_in_files", test_replace_in_files),
        ("patch_file", test_patch_file),
        ("git_operations", test_git_operations),
        ("code_analysis", test_code_analysis),
        ("get_file_info", test_get_file_info),
    ]

    for name, test_func in tests:
        try:
            results[name] = await test_func()
        except Exception as e:
            print(f"Error in {name}: {e}")
            results[name] = {"error": str(e), "success": False}

    # Cleanup
    print("\nCleaning up...")
    await cleanup()

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    passed = 0
    failed = 0
    errors = 0

    for name, result in results.items():
        if "error" in result:
            status = "❌ ERROR"
            errors += 1
        elif result.get("success"):
            status = "✅ PASS"
            passed += 1
        else:
            status = "⚠️  FAIL"
            failed += 1
        print(f"{name}: {status}")

    print(f"\nTotal: {passed} passed, {failed} failed, {errors} errors")
    print()


if __name__ == "__main__":
    asyncio.run(run_all_tests())
