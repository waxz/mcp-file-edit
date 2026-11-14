"""Capture upstream originals before any test applies the unified fixes."""

from mcp_file_edit.code_analyzer import CodeAnalyzer

UPSTREAM_EXTRACT_FUNCTIONS = CodeAnalyzer.__dict__["extract_functions_from_python"].__func__
