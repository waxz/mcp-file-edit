import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "src", "mcp_file_edit")
)

# Use official OpenAI codex-apply-patch library
import codex_apply_patch as cap

from mcp_file_edit.fuzzy_patch import (
    SmartMatchReplacer,
    FuzzyPatchEngine,
    smart_replace,
)


class TestCodexApplyPatchLibrary(unittest.TestCase):
    """Tests for official codex-apply-patch library"""

    def test_basic_apply_patch(self):
        """Test basic patch application"""
        patch = """*** Begin Patch
*** Add File: test.txt
+Hello World
*** End Patch"""

        result = cap.apply_patch(patch)
        # Result has attributes like added, modified, deleted counts
        self.assertIsNotNone(result)

    def test_parse_patch(self):
        """Test patch parsing"""
        patch = """*** Begin Patch
*** Update File: test.py
@@ -1,2 +1,2 @@
-old
+new
*** End Patch"""

        parsed = cap.parse_patch(patch)
        self.assertIsNotNone(parsed)

    def test_generate_patch(self):
        """Test patch generation"""
        original = "def hello():\n    print('old')"
        new = "def hello():\n    print('new')"

        patch = cap.generate_patch("hello.py", original, new)
        self.assertIn("*** Begin Patch", patch)
        self.assertIn("*** End Patch", patch)

    def test_apply_patch_in_memory(self):
        """Test in-memory patch application"""
        files = {"main.py": "def main():\n    print('old version')\n"}

        patch = """*** Begin Patch
*** Update File: main.py
@@
 def main():
-    print('old version')
+    print('new version')
*** End Patch"""

        result = cap.apply_patch_in_memory(patch, files)
        self.assertIn("main.py", result.files)
        self.assertIn("new version", result.files["main.py"])

    def test_multi_file_patch(self):
        """Test multi-file patch generation"""
        file_changes = {
            "new.py": (None, "print('new file')"),  # Add
            "old.py": ("old content", None),  # Delete
            "mod.py": ("old", "new"),  # Update
        }

        patch = cap.generate_patch_from_files(file_changes)
        self.assertIn("*** Add File: new.py", patch)
        self.assertIn("*** Delete File: old.py", patch)
        self.assertIn("*** Update File: mod.py", patch)


class TestSmartMatchReplacer(unittest.TestCase):
    """Tests for smart match replacer (custom implementation)"""

    def test_exact_replace(self):
        """Test exact string replacement"""
        replacer = SmartMatchReplacer()
        original = "hello world"
        result, info = replacer.find_and_replace(original, "world", "universe")
        self.assertEqual(result, "hello universe")
        self.assertTrue(info["success"])
        self.assertEqual(info["method"], "exact")

    def test_replace_all(self):
        """Test replace all occurrences"""
        replacer = SmartMatchReplacer()
        original = "hello world world"
        result, info = replacer.find_and_replace(
            original, "world", "universe", replace_all=True
        )
        self.assertEqual(result, "hello universe universe")
        self.assertEqual(info["replacements"], 2)

    def test_no_match(self):
        """Test when no match is found"""
        replacer = SmartMatchReplacer()
        original = "hello world"
        result, info = replacer.find_and_replace(original, "missing", "nothing")
        self.assertEqual(result, "hello world")
        self.assertFalse(info["success"])


class TestConvenienceFunctions(unittest.TestCase):
    """Tests for convenience functions"""

    def test_smart_replace(self):
        """Test smart replace convenience function"""
        result, success = smart_replace("hello world", "world", "universe")
        self.assertEqual(result, "hello universe")
        self.assertTrue(success)


class TestFuzzyPatchEngine(unittest.TestCase):
    """Tests for the fuzzy patch engine"""

    def test_process_uses_library(self):
        """Test that engine uses codex-apply-patch library"""
        engine = FuzzyPatchEngine()

        # Generate a patch using the library
        patch = cap.generate_patch("test.py", "old", "new")

        result = engine.process(patch)
        self.assertTrue(result["success"])
        self.assertIn("unified_diff", result)


class TestIntegration(unittest.TestCase):
    """Integration tests combining library and custom features"""

    def test_full_workflow(self):
        """Test complete workflow: generate, parse, apply"""
        # Generate patch
        original = "def main():\n    print('start')\n"
        new = "def main():\n    print('end')\n"

        patch = cap.generate_patch("app.py", original, new)

        # Parse patch
        parsed = cap.parse_patch(patch)
        self.assertIsNotNone(parsed)

        # Apply in memory
        files = {"app.py": original}
        result = cap.apply_patch_in_memory(patch, files)

        self.assertIn("app.py", result.files)
        self.assertIn("print('end')", result.files["app.py"])

    def test_multiple_operations(self):
        """Test patch with multiple file operations"""
        file_changes = {
            "a.txt": (None, "content A"),
            "b.txt": ("old B", None),
            "c.txt": ("old C", "new C"),
        }

        patch = cap.generate_patch_from_files(file_changes)
        self.assertIn("*** Add File: a.txt", patch)
        self.assertIn("*** Delete File: b.txt", patch)
        self.assertIn("*** Update File: c.txt", patch)


class TestEdgeCases(unittest.TestCase):
    """Edge case tests"""

    def test_empty_patch(self):
        """Test with empty patch - should raise error"""
        patch = ""
        with self.assertRaises(Exception):
            cap.apply_patch(patch)

    def test_unicode_content(self):
        """Test with unicode content"""
        original = "def hello():\n    print('世界')\n"
        new = "def hello():\n    print('🌍')\n"

        patch = cap.generate_patch("unicode.py", original, new)
        self.assertIn("🌍", patch)

    def test_large_file(self):
        """Test with large file content"""
        large_content = "line\n" * 10000
        patch = cap.generate_patch("large.py", large_content, large_content + "new\n")
        self.assertIsNotNone(patch)


if __name__ == "__main__":
    unittest.main()
