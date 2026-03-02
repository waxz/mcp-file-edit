#!/usr/bin/env python3
"""
Test the code analysis functionality
"""
import asyncio
import sys
import os
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def test_code_analysis():
    # Import the tools
    from mcp_file_edit.server import (
    set_project_directory, ssh_upload, ssh_download, ssh_sync,
    list_files, read_file, write_file, create_file
    )
    from mcp_file_edit.code_analyzer import (
    list_functions, get_function_at_line, 
    get_code_structure, search_functions
    )
    # Create test files
    print("=== Testing Code Analysis Features ===\n")
    
    # Set up test directory
    await set_project_directory(".")
    
    # Create a test Python file
    test_py_content = '''"""Test module for code analysis"""
import os
import sys
from typing import List, Optional

def simple_function():
    """A simple function"""
    return 42

async def async_function(name: str) -> str:
    """An async function with type hints
    
    Args:
        name: The name to greet
        
    Returns:
        A greeting string
    """
    return f"Hello, {name}!"

class TestClass:
    """A test class"""
    
    def __init__(self, value: int = 0):
        self.value = value
    
    def method(self) -> int:
        """A class method"""
        return self.value * 2
    
    @staticmethod
    def static_method():
        """A static method"""
        return "static"

def function_with_decorators():
    """Function with decorators"""
    @property
    def inner():
        return "inner"
    return inner
'''
    
    await create_file("test_analysis.py", test_py_content)
    
    # Test 1: List all functions
    print("1. List all functions in test_analysis.py:")
    functions = await list_functions("test_analysis.py")
    for func in functions:
        print(f"   - {func['signature']} at line {func['line_start']}")
        if func.get('is_method'):
            print(f"     (method of {func['class_name']})")
    print()
    
    # Test 2: Get function at specific line
    print("2. Get function at line 15:")
    func = await get_function_at_line("test_analysis.py", 15)
    if func:
        print(f"   Found: {func['name']} ({func['line_start']}-{func['line_end']})")
        if func.get('docstring'):
            print(f"   Docstring: {func['docstring'][:50]}...")
    print()
    
    # Test 3: Get code structure
    print("3. Get code structure:")
    structure = await get_code_structure("test_analysis.py")
    print(f"   Language: {structure['language']}")
    print(f"   Lines: {structure['lines']}")
    print(f"   Imports: {len(structure.get('imports', []))}")
    print(f"   Classes: {len(structure.get('classes', []))}")
    print(f"   Functions: {len(structure.get('functions', []))}")
    
    if structure.get('classes'):
        for cls in structure['classes']:
            print(f"   - Class {cls['name']} with {len(cls['methods'])} methods")
    print()
    
    # Create another test file
    test_js_content = '''// JavaScript test file
function regularFunction(a, b) {
    return a + b;
}

const arrowFunction = (x) => x * 2;

async function asyncFunction() {
    return await Promise.resolve(42);
}

class MyClass {
    constructor() {
        this.value = 0;
    }
    
    method() {
        return this.value;
    }
}
'''
    
    await create_file("test_analysis.js", test_js_content)
    
    # Test 4: List JavaScript functions
    print("4. List functions in JavaScript file:")
    js_functions = await list_functions("test_analysis.js", "javascript")
    for func in js_functions:
        print(f"   - {func['name']} at line {func['line_start']}")
    print()


    test_scl_content='''// SCL test file
PROGRAM Main
    VAR
        result : INT;
    END_VAR
    
    result := Add(5, 3);
    result := Multiply(6, 7);
END_PROGRAM

FUNCTION Add : INT
    VAR_INPUT
        a : INT;
        b : INT;
    END_VAR
    // Debug: log the addition
    Add := a + b;
END_FUNCTION

FUNCTION Multiply : INT
    VAR_INPUT
        a : INT;
        b : INT;
    END_VAR
    // Debug: log the multiplication
    Multiply := a * b;
END_FUNCTION
'''

    await create_file("test_analysis.scl", test_scl_content)

    # Test 5: List SCL functions
    print("5. List functions in SCL file:")
    scl_functions = await list_functions("test_analysis.scl", "scl")
    for func in scl_functions:
        print(f"   - {func['name']} at line {func['line_start']}")
    print()

    # Test 6: Rust
    test_rust_content='''// Rust test file
fn regular_function(a: i32, b: i32) -> i32 {
    return a + b;
}

const arrow_function = (x: i32) => x * 2;

async fn async_function() -> i32 {
    return await Promise.resolve(42);
}

class MyClass {
    constructor() {
        this.value = 0;
    }
    
    method() {
        return this.value;
    }
}
'''
    
    await create_file("test_analysis.rs", test_rust_content)
    
    # Test 6: List Rust functions
    print("6. List functions in Rust file:")
    rust_functions = await list_functions("test_analysis.rs", "rust")
    for func in rust_functions:
        print(f"   - {func['name']} at line {func['line_start']}")
    print()


    # Test C++
    test_c_content = '''// C++ test file
int regular_function(int a, int b) {
    return a + b;
}

const arrow_function = (x: int) => x * 2;

async fn async_function() -> int {
    return await Promise.resolve(42);
}

class MyClass {
    constructor() {
        this.value = 0;
    }
    
    method() {
        return this.value;
    }
}
'''
    
    await create_file("test_analysis.cpp", test_c_content)
    
    # Test 7: List C++ functions
    print("7. List functions in C++ file:")
    c_functions = await list_functions("test_analysis.cpp", "cpp")
    for func in c_functions:
        print(f"   - {func['name']} at line {func['line_start']}")
    print()


    # Test C
    test_c_content = '''// C test file
int regular_function(int a, int b) {
    return a + b;
}
int main(){
    printf("Hello, World!\n");
    return 0;  
}
'''
    
    await create_file("test_analysis.c", test_c_content)
    
    # Test 8: List C functions
    print("8. List functions in C file:")
    c_functions = await list_functions("test_analysis.c", "c")
    for func in c_functions:
        print(f"   - {func['name']} at line {func['line_start']}")
    print()
    
    # Test 9: Search for functions
    print("9. Search for functions matching 'function':")
    results = await search_functions("function", ".", "*.py", max_depth=2)
    print(f"   Found {results['total_functions']} matching functions in {results['files_searched']} files")
    for result in results['results']:
        print(f"   In {result['file']}:")
        for func in result['functions']:
            print(f"     - {func['name']}")
    print()
    
    # Test 10: Search with pattern
    print("10. Search for async functions:")
    results = await search_functions("async", ".", "*.py")
    for result in results['results']:
        for func in result['functions']:
            if func.get('is_async'):
                print(f"   - {func['name']} in {result['file']}")
    
    # Cleanup
    os.remove("test_analysis.py")
    os.remove("test_analysis.js")
    os.remove("test_analysis.scl")
    os.remove("test_analysis.rs")   
    os.remove("test_analysis.cpp")
    os.remove("test_analysis.c")    
    

    print("\n=== Code Analysis Tests Complete ===")
    print("Features tested:")
    print("- List all functions with signatures and line numbers")
    print("- Find function at specific line")
    print("- Extract complete code structure")
    print("- Support for Python and JavaScript")
    print("- Search functions by pattern")

if __name__ == "__main__":
    asyncio.run(test_code_analysis())
