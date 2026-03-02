#!/usr/bin/env python3
"""Test tree-sitter parsing functionality"""
import sys
sys.path.insert(0, 'src')

from mcp_file_edit.code_analyzer import (
    TREE_SITTER_AVAILABLE,
    LANGUAGE_C_AVAILABLE,
    LANGUAGE_CPP_AVAILABLE,
    LANGUAGE_RUST_AVAILABLE,
    LANGUAGE_CSHARP_AVAILABLE,
    LANGUAGE_JAVA_AVAILABLE,
    LANGUAGE_JAVASCRIPT_AVAILABLE,
    LANGUAGE_SCL_AVAILABLE,
    get_tree_sitter_parser,
    TreeSitterAnalyzer
)

print("=== Tree-sitter Availability ===")
print(f"tree-sitter core: {TREE_SITTER_AVAILABLE}")
print(f"  C:       {LANGUAGE_C_AVAILABLE}")
print(f"  C++:     {LANGUAGE_CPP_AVAILABLE}")
print(f"  Rust:    {LANGUAGE_RUST_AVAILABLE}")
print(f"  C#:      {LANGUAGE_CSHARP_AVAILABLE}")
print(f"  Java:    {LANGUAGE_JAVA_AVAILABLE}")
print(f"  JS/TS:   {LANGUAGE_JAVASCRIPT_AVAILABLE}")
print(f"  SCL/ST:  {LANGUAGE_SCL_AVAILABLE}")

if TREE_SITTER_AVAILABLE:
    print("\n=== Testing Parser Creation ===")
    for lang in ['c', 'cpp', 'rust', 'csharp', 'java', 'javascript', 'scl']:
        parser = get_tree_sitter_parser(lang)
        status = "OK" if parser else "FAILED"
        print(f"  {lang}: {status}")
    
    print("\n=== Testing Function Extraction ===")
    test_c = """
int add(int a, int b) {
    return a + b;
}

void main() {
    int result = add(1, 2);
}
"""
    funcs = TreeSitterAnalyzer.extract_functions(test_c, 'c')
    print(f"  C functions found: {len(funcs)}")
    for f in funcs:
        print(f"    - {f.get('name', 'unknown')} at line {f.get('line_start')}")
    
    test_js = """
function hello(name) {
    return "Hello " + name;
}

const arrow = (x) => x * 2;
"""
    funcs = TreeSitterAnalyzer.extract_functions(test_js, 'javascript')
    print(f"  JS functions found: {len(funcs)}")
    for f in funcs:
        print(f"    - {f.get('name', 'unknown')} at line {f.get('line_start')}")
    
    # Test SCL
    test_scl = """
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
    Add := a + b;
END_FUNCTION

FUNCTION Multiply : INT
    VAR_INPUT
        a : INT;
        b : INT;
    END_VAR
    Multiply := a * b;
END_FUNCTION
"""
    funcs = TreeSitterAnalyzer.extract_functions(test_scl, 'scl')
    print(f"  SCL functions found: {len(funcs)}")
    for f in funcs:
        print(f"    - {f.get('name', 'unknown')} at line {f.get('line_start')}")
else:
    print("\nTree-sitter is not available. Install with:")
    print("  pip install tree-sitter tree-sitter-c tree-sitter-cpp ...")
