#!/usr/bin/env python3
"""
Function-based code analysis capabilities for MCP File Editor
Supports multiple languages via tree-sitter and regex parsers.
"""

import ast
import re
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path

# Import local modules
from .utils import resolve_path, is_safe_path
from .file_tools import walk_with_depth,get_file_type

# Language extension mapping
LANGUAGE_EXTENSIONS = {
    # Python
    '.py': 'python', '.pyw': 'python', '.pyi': 'python',
    # JavaScript/TypeScript
    '.js': 'javascript', '.jsx': 'javascript',
    '.ts': 'typescript', '.tsx': 'typescript',
    # C/C++
    '.c': 'c', '.h': 'c',
    '.cpp': 'cpp', '.cc': 'cpp', '.cxx': 'cpp', '.hpp': 'cpp', '.c++': 'cpp',
    # Rust
    '.rs': 'rust',
    # C#
    '.cs': 'csharp',
    # Java
    '.java': 'java',
    # SCL / Structured Text (Siemens PLC)
    '.scl': 'scl', '.st': 'scl',
    # Go
    '.go': 'go',
    # C++/ObjC
    '.m': 'objc', '.mm': 'objc',
}


# Try to import tree-sitter and language grammars
TREE_SITTER_AVAILABLE = False
try:
    from tree_sitter import Parser, Language
    TREE_SITTER_AVAILABLE = True
    
    # Language grammar imports (these will fail gracefully if not installed)
    try:
        import tree_sitter_c
        LANGUAGE_C_AVAILABLE = True
    except ImportError:
        LANGUAGE_C_AVAILABLE = False
    
    try:
        import tree_sitter_cpp
        LANGUAGE_CPP_AVAILABLE = True
    except ImportError:
        LANGUAGE_CPP_AVAILABLE = False
    
    try:
        import tree_sitter_rust
        LANGUAGE_RUST_AVAILABLE = True
    except ImportError:
        LANGUAGE_RUST_AVAILABLE = False
    
    try:
        import tree_sitter_c_sharp
        LANGUAGE_CSHARP_AVAILABLE = True
    except ImportError:
        LANGUAGE_CSHARP_AVAILABLE = False
    
    try:
        import tree_sitter_java
        LANGUAGE_JAVA_AVAILABLE = True
    except ImportError:
        LANGUAGE_JAVA_AVAILABLE = False
    
    try:
        import tree_sitter_javascript
        LANGUAGE_JAVASCRIPT_AVAILABLE = True
    except ImportError:
        LANGUAGE_JAVASCRIPT_AVAILABLE = False
    
    try:
        import tree_sitter_structured_text
        LANGUAGE_SCL_AVAILABLE = True
    except ImportError:
        LANGUAGE_SCL_AVAILABLE = False
        
except ImportError:
    TREE_SITTER_AVAILABLE = False
    LANGUAGE_C_AVAILABLE = False
    LANGUAGE_CPP_AVAILABLE = False
    LANGUAGE_RUST_AVAILABLE = False
    LANGUAGE_CSHARP_AVAILABLE = False
    LANGUAGE_JAVA_AVAILABLE = False
    LANGUAGE_JAVASCRIPT_AVAILABLE = False
    LANGUAGE_SCL_AVAILABLE = False


def get_tree_sitter_parser(language: str) -> Optional[Any]:
    if not TREE_SITTER_AVAILABLE:
        return None
    
    lang_map = {
        'c': 'tree_sitter_c', 'cpp': 'tree_sitter_cpp',
        'rust': 'tree_sitter_rust', 'csharp': 'tree_sitter_c_sharp',
        'java': 'tree_sitter_java', 'javascript': 'tree_sitter_javascript',
        'typescript': 'tree_sitter_javascript',
        'scl': 'tree_sitter_structured_text',
    }
    
    if language not in lang_map:
        return None
    
    try:
        module_name = lang_map[language]
        module = __import__(module_name)
        
        # Get language object - wrap with Language() constructor
        from tree_sitter import Language
        lang_ptr = module.language()  # Returns pointer/capsule
        lang = Language(lang_ptr)     # Wrap in Language object
        
        # Create parser with language
        parser = Parser(lang)
        return parser
        
    except Exception as e:
        print(f"[CodeAnalyzer] Error loading {language} parser: {e}")
        return None


class CStyleAnalyzer:
    """Regex-based analyzer for C/C++."""
    FUNCTION_PATTERN = r'(?:^|;|\n)\s*([a-zA-Z_][a-zA-Z0-9_*\s]*?)\s+(\w+)\s*\(([^)]*)\)\s*\{'
    
    @staticmethod
    def extract_functions(content: str, language: str) -> List[Dict[str, Any]]:
        functions = []
        for match in re.finditer(CStyleAnalyzer.FUNCTION_PATTERN, content, re.MULTILINE):
            return_type = match.group(1).strip()
            func_name = match.group(2)
            params = match.group(3)
            start_line = content[:match.start()].count('\n') + 1
            end_line = content[:match.end()].count('\n') + 1
            functions.append({
                "name": func_name, "return_type": return_type,
                "params": params.strip(), "line_start": start_line,
                "line_end": end_line, "signature": f"{return_type} {func_name}({params})",
                "source": "regex"
            })
        return functions


class SCLAnalyzer:
    """Regex-based analyzer for Siemens SCL (Structured Control Language)."""
    
    FUNCTION_PATTERN = r'(?i)^\s*FUNCTION\s+(\w+)\s*:\s*(\w+)\s*$'
    PROGRAM_PATTERN = r'(?i)^\s*PROGRAM\s+(\w+)\s*$'
    FUNCTION_BLOCK_PATTERN = r'(?i)^\s*FUNCTION_BLOCK\s+(\w+)\s*$'
    ACTION_PATTERN = r'(?i)^\s*ACTION\s+(\w+)\s*$'
    
    @staticmethod
    def extract_functions(content: str, language: str) -> List[Dict[str, Any]]:
        functions = []
        lines = content.split('\n')
        
        for i, line in enumerate(lines):
            match = re.match(SCLAnalyzer.FUNCTION_PATTERN, line)
            if match:
                func_name = match.group(1)
                return_type = match.group(2)
                start_line = i + 1
                end_line = SCLAnalyzer._find_end_line(lines, i, 'END_FUNCTION')
                functions.append({
                    "name": func_name,
                    "return_type": return_type,
                    "params": "",
                    "line_start": start_line,
                    "line_end": end_line,
                    "signature": f"FUNCTION {func_name} : {return_type}",
                    "source": "regex"
                })
                continue
            
            match = re.match(SCLAnalyzer.PROGRAM_PATTERN, line)
            if match:
                prog_name = match.group(1)
                start_line = i + 1
                end_line = SCLAnalyzer._find_end_line(lines, i, 'END_PROGRAM')
                functions.append({
                    "name": prog_name,
                    "type": "PROGRAM",
                    "line_start": start_line,
                    "line_end": end_line,
                    "signature": f"PROGRAM {prog_name}",
                    "source": "regex"
                })
                continue
            
            match = re.match(SCLAnalyzer.FUNCTION_BLOCK_PATTERN, line)
            if match:
                fb_name = match.group(1)
                start_line = i + 1
                end_line = SCLAnalyzer._find_end_line(lines, i, 'END_FUNCTION_BLOCK')
                functions.append({
                    "name": fb_name,
                    "type": "FUNCTION_BLOCK",
                    "line_start": start_line,
                    "line_end": end_line,
                    "signature": f"FUNCTION_BLOCK {fb_name}",
                    "source": "regex"
                })
                continue
            
            match = re.match(SCLAnalyzer.ACTION_PATTERN, line)
            if match:
                action_name = match.group(1)
                start_line = i + 1
                end_line = SCLAnalyzer._find_end_line(lines, i, 'END_ACTION')
                functions.append({
                    "name": action_name,
                    "type": "ACTION",
                    "line_start": start_line,
                    "line_end": end_line,
                    "signature": f"ACTION {action_name}",
                    "source": "regex"
                })
        
        return functions
    
    @staticmethod
    def _find_end_line(lines: List[str], start_idx: int, end_keyword: str) -> int:
        for i in range(start_idx + 1, len(lines)):
            if re.match(r'(?i)\s*' + end_keyword + r'\b', lines[i]):
                return i + 1
        return len(lines)


class TreeSitterAnalyzer:
    @staticmethod
    def extract_functions(content: str, language: str) -> List[Dict[str, Any]]:
        parser = get_tree_sitter_parser(language)
        if parser is not None:
            try:
                tree = parser.parse(bytes(content, 'utf8'))
                functions = []
                TreeSitterAnalyzer._find_functions(tree.root_node, content, language, functions)
                if functions:
                    return functions
            except Exception as e:
                print(f"[TreeSitterAnalyzer] tree-sitter failed: {e}")
        
        # Fallback to regex for C/C++
        if language in ['c', 'cpp']:
            return CStyleAnalyzer.extract_functions(content, language)
        
        # Fallback to SCL analyzer for Siemens SCL
        if language == 'scl':
            return SCLAnalyzer.extract_functions(content, language)
        
        return []
        try:
            tree = parser.parse(bytes(content, 'utf8'))
            functions = []
            TreeSitterAnalyzer._find_functions(tree.root_node, content, language, functions)
            return functions
        except Exception:
            return []
    
    @staticmethod
    def _find_functions(node, content: str, language: str, functions: List[Dict]):
        node_types = {
            'c': ['function_definition', 'function_declaration', 'declaration'],
            'cpp': ['function_definition', 'function_declaration', 'declaration'],
            'rust': ['function_item', 'function_declaration'],
            'csharp': ['method_declaration', 'local_function_statement', 'function_declaration'],
            'java': ['method_declaration', 'function_declaration'],
            'javascript': ['function_declaration', 'function_expression', 'arrow_function', 'method_definition'],
            'typescript': ['function_declaration', 'method_definition', 'arrow_function'],
            'scl': ['program_definition', 'action_definition', 'call_expression'],
        }.get(language, [])
        
        if node.type in node_types:
            # Try to extract function name
            name = None
            for child in node.children:
                if child.type == 'identifier':
                    name = content[child.start_byte:child.end_byte]
                    if isinstance(name, bytes):
                        name = name.decode('utf8')
                    break
            if not name:
                # Try to get from function declarator
                for child in node.children:
                    if child.type == 'function_declarator':
                        for subchild in child.children:
                            if subchild.type == 'identifier':
                                name = content[subchild.start_byte:subchild.end_byte]
                                if isinstance(name, bytes):
                                    name = name.decode('utf8')
                                break
                        break
            if not name:
                name = f"func_{node.start_point[0]}"
            
            functions.append({
                "name": name,
                "line_start": node.start_point[0] + 1,
                "line_end": node.end_point[0] + 1,
                "node_type": node.type
            })
        
        for child in node.children:
            TreeSitterAnalyzer._find_functions(child, content, language, functions)


class SCLAnalyzer:
    BLOCK_PATTERNS = {
        'function': r'(?m)^FUNCTION\s+(\w+)\s*:\s*(\w+)',
        'function_block': r'(?m)^FUNCTION_BLOCK\s+(\w+)',
        'program': r'(?m)^PROGRAM\s+(\w+)',
    }
    
    @staticmethod
    def extract_blocks(content: str) -> List[Dict[str, Any]]:
        blocks = []
        for block_type, pattern in SCLAnalyzer.BLOCK_PATTERNS.items():
            for match in re.finditer(pattern, content):
                blocks.append({
                    "type": block_type,
                    "name": match.group(1),
                    "return_type": match.group(2) if match.lastindex >= 2 else None,
                    "line_start": content[:match.start()].count('\n') + 1,
                    "line_end": content.count('\n') + 1,
                })
        return blocks


class CodeAnalyzer:
    """Analyzes code files to extract function and structure information"""
    
    @staticmethod
    def parse_python_file(content: str) -> ast.AST:
        """Parse Python code and return AST"""
        try:
            return ast.parse(content)
        except SyntaxError as e:
            raise ValueError(f"Python syntax error: {e}")
    
    @staticmethod
    def get_docstring(node: ast.AST) -> Optional[str]:
        """Extract docstring from an AST node"""
        docstring = ast.get_docstring(node)
        return docstring.strip() if docstring else None
    
    @staticmethod
    def get_function_signature(node: ast.FunctionDef) -> str:
        """Get function signature as a string"""
        args = []
        for arg in node.args.args:
            args.append(arg.arg)
        
        # Add defaults
        defaults_start = len(args) - len(node.args.defaults)
        for i, default in enumerate(node.args.defaults):
            args[defaults_start + i] += "=..."
            
        # Add *args and **kwargs
        if node.args.vararg:
            args.append(f"*{node.args.vararg.arg}")
        if node.args.kwarg:
            args.append(f"**{node.args.kwarg.arg}")
            
        return f"{node.name}({', '.join(args)})"
    
    @staticmethod
    def extract_functions_from_python(content: str) -> List[Dict[str, Any]]:
        """Extract all functions from Python code"""
        tree = CodeAnalyzer.parse_python_file(content)
        functions = []
        
        class FunctionVisitor(ast.NodeVisitor):
            def __init__(self, source_lines):
                self.functions = []
                self.source_lines = source_lines
                self.current_class = None
                
            def visit_ClassDef(self, node):
                old_class = self.current_class
                self.current_class = node.name
                self.generic_visit(node)
                self.current_class = old_class
                
            def visit_FunctionDef(self, node):
                func_info = {
                    "name": node.name,
                    "line_start": node.lineno,
                    "line_end": node.end_lineno,
                    "signature": CodeAnalyzer.get_function_signature(node),
                    "docstring": CodeAnalyzer.get_docstring(node),
                    "decorators": [d.id if isinstance(d, ast.Name) else ast.unparse(d) 
                                  for d in node.decorator_list],
                    "is_method": self.current_class is not None,
                    "class_name": self.current_class,
                    "is_async": isinstance(node, ast.AsyncFunctionDef)
                }
                
                # Get return type if annotated
                if node.returns:
                    func_info["return_type"] = ast.unparse(node.returns)
                    
                # Get parameter types if annotated
                param_types = {}
                for arg in node.args.args:
                    if arg.annotation:
                        param_types[arg.arg] = ast.unparse(arg.annotation)
                if param_types:
                    func_info["param_types"] = param_types
                    
                self.functions.append(func_info)
                self.generic_visit(node)
        
        visitor = FunctionVisitor(content.splitlines())
        visitor.visit(tree)
        return visitor.functions
    
    @staticmethod
    def extract_functions_from_javascript(content: str) -> List[Dict[str, Any]]:
        """Extract functions from JavaScript/TypeScript code using regex"""
        functions = []
        
        # Regex patterns for different function styles
        patterns = [
            # Regular function declaration
            r'(?:async\s+)?function\s+(\w+)\s*\([^)]*\)\s*(?::\s*[^{]+)?\s*\{',
            # Arrow function assigned to const/let/var
            r'(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\([^)]*\)\s*(?::\s*[^=]+)?\s*=>',
            # Method in class
            r'(?:async\s+)?(\w+)\s*\([^)]*\)\s*(?::\s*[^{]+)?\s*\{',
        ]
        
        lines = content.splitlines()
        for i, line in enumerate(lines):
            for pattern in patterns:
                match = re.search(pattern, line)
                if match:
                    func_name = match.group(1)
                    # Simple heuristic to find end of function
                    brace_count = 0
                    start_line = i + 1
                    end_line = start_line
                    
                    for j in range(i, len(lines)):
                        brace_count += lines[j].count('{') - lines[j].count('}')
                        if brace_count == 0 and j > i:
                            end_line = j + 1
                            break
                    
                    functions.append({
                        "name": func_name,
                        "line_start": start_line,
                        "line_end": end_line,
                        "signature": line.strip(),
                        "is_async": 'async' in line
                    })
                    break
        
        return functions
    
    @staticmethod
    def find_function_at_line(functions: List[Dict[str, Any]], line_number: int) -> Optional[Dict[str, Any]]:
        """Find which function contains a given line number"""
        for func in functions:
            if func["line_start"] <= line_number <= func["line_end"]:
                return func
        return None
    
    @staticmethod
    def extract_imports_from_python(content: str) -> List[Dict[str, Any]]:
        """Extract import statements from Python code"""
        tree = CodeAnalyzer.parse_python_file(content)
        imports = []
        
        class ImportVisitor(ast.NodeVisitor):
            def __init__(self):
                self.imports = []
                
            def visit_Import(self, node):
                for alias in node.names:
                    self.imports.append({
                        "type": "import",
                        "module": alias.name,
                        "alias": alias.asname,
                        "line": node.lineno
                    })
                    
            def visit_ImportFrom(self, node):
                module = node.module or ""
                for alias in node.names:
                    self.imports.append({
                        "type": "from",
                        "module": module,
                        "name": alias.name,
                        "alias": alias.asname,
                        "line": node.lineno
                    })
        
        visitor = ImportVisitor()
        visitor.visit(tree)
        return visitor.imports
    
    @staticmethod
    def extract_classes_from_python(content: str) -> List[Dict[str, Any]]:
        """Extract class definitions from Python code"""
        tree = CodeAnalyzer.parse_python_file(content)
        classes = []
        
        class ClassVisitor(ast.NodeVisitor):
            def __init__(self):
                self.classes = []
                
            def visit_ClassDef(self, node):
                class_info = {
                    "name": node.name,
                    "line_start": node.lineno,
                    "line_end": node.end_lineno,
                    "docstring": CodeAnalyzer.get_docstring(node),
                    "bases": [ast.unparse(base) for base in node.bases],
                    "decorators": [d.id if isinstance(d, ast.Name) else ast.unparse(d) 
                                  for d in node.decorator_list],
                    "methods": []
                }
                
                # Get methods
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        class_info["methods"].append({
                            "name": item.name,
                            "line": item.lineno,
                            "is_async": isinstance(item, ast.AsyncFunctionDef)
                        })
                
                self.classes.append(class_info)
                self.generic_visit(node)
        
        visitor = ClassVisitor()
        visitor.visit(tree)
        return visitor.classes


# Tool implementations for MCP

async def list_functions(
    path: str,
    language: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    List all functions in a code file.
    
    Args:
        path: File path
        language: Programming language (auto-detected if not specified)
        
    Returns:
        List of function information including name, line numbers, signature, etc.
    """
    
    file_path = resolve_path(path)
    if not is_safe_path(file_path):
        raise ValueError("Invalid path: directory traversal detected")
    
    if not file_path.exists():
        raise ValueError(f"File does not exist: {path}")
    
    # Read file content
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Auto-detect language if not specified
    if not language:
        suffix = file_path.suffix.lower()
        language = LANGUAGE_EXTENSIONS.get(suffix, '')
        if not language:
            raise ValueError(f"Unsupported file type: {suffix}")
    
    # Extract functions based on language
    if language == 'python':
        return CodeAnalyzer.extract_functions_from_python(content)
    elif language in ['javascript', 'typescript']:
        return CodeAnalyzer.extract_functions_from_javascript(content)
    elif language in ['c', 'cpp', 'rust', 'csharp', 'java']:
        return TreeSitterAnalyzer.extract_functions(content, language)
    elif language == 'scl':
        return SCLAnalyzer.extract_blocks(content)
    else:
        raise ValueError(f"Unsupported language: {language}")


async def get_function_at_line(
    path: str,
    line_number: int,
    language: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Get the function that contains a specific line number.
    
    Args:
        path: File path
        line_number: Line number to search for
        language: Programming language (auto-detected if not specified)
        
    Returns:
        Function information if found, None otherwise
    """
    functions = await list_functions(path, language)
    return CodeAnalyzer.find_function_at_line(functions, line_number)


async def get_code_structure(
    path: str,
    language: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get the overall code structure of a file.
    
    Args:
        path: File path
        language: Programming language (auto-detected if not specified)
        
    Returns:
        Dictionary containing imports, classes, functions, and other structural elements
    """
    
    file_path = resolve_path(path)
    if not is_safe_path(file_path):
        raise ValueError("Invalid path: directory traversal detected")
    
    if not file_path.exists():
        raise ValueError(f"File does not exist: {path}")
    
    # Read file content
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Auto-detect language if not specified
    if not language:
        suffix = file_path.suffix.lower()
        language = LANGUAGE_EXTENSIONS.get(suffix, '')
        if not language:
            raise ValueError(f"Unsupported file type: {suffix}")
    
    structure = {
        "language": language,
        "file": str(file_path.name),
        "lines": len(content.splitlines()),
        "tree_sitter_available": TREE_SITTER_AVAILABLE
    }
    
    if language == 'python':
        structure["imports"] = CodeAnalyzer.extract_imports_from_python(content)
        structure["classes"] = CodeAnalyzer.extract_classes_from_python(content)
        structure["functions"] = CodeAnalyzer.extract_functions_from_python(content)
    elif language in ['javascript', 'typescript']:
        structure["functions"] = CodeAnalyzer.extract_functions_from_javascript(content)
    elif language in ['c', 'cpp', 'rust', 'csharp', 'java']:
        structure["functions"] = TreeSitterAnalyzer.extract_functions(content, language)
    elif language == 'scl':
        structure["blocks"] = SCLAnalyzer.extract_blocks(content)
    
    return structure


async def search_functions(
    pattern: str,
    path: str = ".",
    file_pattern: str = "*.py",
    recursive: bool = True,
    max_depth: Optional[int] = None
) -> Dict[str, Any]:
    """
    Search for functions by name pattern across files.
    
    Args:
        pattern: Function name pattern (regex)
        path: Directory to search in
        file_pattern: File name pattern
        recursive: Search recursively
        max_depth: Maximum depth for recursive search
        
    Returns:
        Dictionary with search results
    """

    
    search_path = resolve_path(path)
    if not is_safe_path(search_path):
        raise ValueError("Invalid path: directory traversal detected")
    
    regex = re.compile(pattern)
    results = []
    files_searched = 0
    
    # Get files to search
    if search_path.is_file():
        files_to_search = [search_path]
    else:
        if recursive:
            if max_depth is not None:
                files_to_search = list(walk_with_depth(search_path, file_pattern, max_depth))
            else:
                files_to_search = list(search_path.rglob(file_pattern))
        else:
            files_to_search = list(search_path.glob(file_pattern))
    
    for file_path in files_to_search:
        if not file_path.is_file():
            continue
        
        try:
            # Get language from file extension
            suffix = file_path.suffix.lower()
            language = LANGUAGE_EXTENSIONS.get(suffix)
            if not language:
                continue
            
            # Get functions from file
            functions = await list_functions(str(file_path.relative_to(search_path)), language)
            files_searched += 1
            
            # Search function names
            matching_functions = []
            for func in functions:
                if regex.search(func["name"]):
                    matching_functions.append(func)
            
            if matching_functions:
                results.append({
                    "file": str(file_path.relative_to(search_path)),
                    "functions": matching_functions
                })
                
        except Exception:
            continue
    
    return {
        "results": results,
        "files_searched": files_searched,
        "total_functions": sum(len(r["functions"]) for r in results)
    }
