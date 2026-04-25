"""
Fuzzy Patch Wrapper - Uses official OpenAI codex-apply-patch library.

Features:
- Parse Codex-style patch format (via library)
- Convert to unified diff format for diff-match-patch
- Smart search and match for replace operations
"""

import logging
from typing import Dict, Any, Tuple
from dataclasses import dataclass, field
from dataclasses import field as _field

logger = logging.getLogger(__name__)

# Import official OpenAI library
try:
    import codex_apply_patch as cap

    LIBRARY_AVAILABLE = True
except ImportError:
    LIBRARY_AVAILABLE = False
    logger.warning("codex-apply-patch library not installed")


@dataclass
class PatchResult:
    """Result of patch operation"""

    success: bool = False
    files: Dict[str, str] = field(default_factory=dict)
    added: int = 0
    modified: int = 0
    deleted: int = 0
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


class CodexPatchParser:
    """Parse Codex-style patch format using official library"""

    @staticmethod
    def parse(patch_text: str) -> Any:
        """Parse patch using official library"""
        if not LIBRARY_AVAILABLE:
            raise ImportError("codex-apply-patch library not available")
        return cap.parse_patch(patch_text)


class FuzzyPatchConverter:
    """Convert Codex patches to unified diff format"""

    def __init__(self, enable_fuzzy: bool = True, enable_autofix: bool = True):
        self.enable_fuzzy = enable_fuzzy
        self.enable_autofix = enable_autofix
        self._lib = cap if LIBRARY_AVAILABLE else None

    def convert(self, patch_text: str, original_content: str = "") -> Dict[str, Any]:
        """Convert Codex patch to unified diff format"""
        result = {
            "success": False,
            "unified_diff": "",
            "operations": [],
            "errors": [],
            "warnings": [],
        }

        if not self._lib:
            result["errors"].append("Library not available")
            return result

        try:
            parsed = self._lib.parse_patch(patch_text)
            result["success"] = True
            result["operations"] = [{"parsed": str(parsed)}]
        except Exception as e:
            result["errors"].append(str(e))

        return result

    def apply_in_memory(self, patch: str, files: Dict[str, str]) -> PatchResult:
        """Apply patch to files in memory"""
        if not self._lib:
            return PatchResult(errors=["Library not available"])

        try:
            result = self._lib.apply_patch_in_memory(patch, files)
            return PatchResult(
                success=True,
                files=result.files if hasattr(result, "files") else {},
                added=getattr(result, "added", 0),
                modified=getattr(result, "modified", 0),
                deleted=getattr(result, "deleted", 0),
            )
        except Exception as e:
            return PatchResult(errors=[str(e)])


class SmartMatchReplacer:
    """Smart search and replace with fuzzy matching"""

    def __init__(self, fuzzy_threshold: float = 0.8):
        self.fuzzy_threshold = fuzzy_threshold
        try:
            from diff_match_patch import diff_match_patch

            self.dmp = diff_match_patch()
        except ImportError:
            logger.warning("diff_match_patch not available, using basic matching")
            self.dmp = None

    def find_and_replace(
        self, original: str, old_string: str, new_string: str, replace_all: bool = False
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Find old_string in original and replace with new_string.
        Uses fuzzy matching if exact match fails.
        """
        result = {"success": False, "replacements": 0, "method": "none", "warnings": []}

        if not old_string:
            result["warnings"].append("Empty old_string")
            return original, result

        # Try exact match first
        if old_string in original:
            if replace_all:
                count = original.count(old_string)
                result["replacements"] = count
                original = original.replace(old_string, new_string)
            else:
                original = original.replace(old_string, new_string, 1)
                result["replacements"] = 1
            result["success"] = True
            result["method"] = "exact"
            return original, result

        # Try fuzzy matching if enabled
        if self.dmp and self.enable_fuzzy:
            return self._fuzzy_replace(
                original, old_string, new_string, replace_all, result
            )

        # Try smart search
        return self._smart_replace(
            original, old_string, new_string, replace_all, result
        )

    def _fuzzy_replace(
        self,
        original: str,
        old_string: str,
        new_string: str,
        replace_all: bool,
        result: Dict[str, Any],
    ) -> Tuple[str, Any]:
        """Fuzzy replace using diff-match-patch"""
        old_clean = self._semantic_cleanup(old_string)

        patches = self.dmp.patch_make(old_clean, new_string)
        patched_text, results = self.dmp.patch_apply(patches, original)

        if results and any(results):
            result["success"] = True
            result["method"] = "fuzzy"
            result["replacements"] = sum(1 for r in results if r)
            return patched_text, result

        result["warnings"].append("Fuzzy match not found")
        return original, result

    def _smart_replace(
        self,
        original: str,
        old_string: str,
        new_string: str,
        replace_all: bool,
        result: Dict[str, Any],
    ) -> Tuple[str, Any]:
        """Smart replace with various heuristics"""

        # Heuristic 1: Case-insensitive match
        import re

        pattern = re.escape(old_string)
        match = re.search(pattern, original, re.IGNORECASE)
        if match:
            original = original[: match.start()] + new_string + original[match.end() :]
            result["success"] = True
            result["method"] = "case_insensitive"
            result["replacements"] = 1
            return original, result

        # Heuristic 2: Whitespace-normalized match
        old_normalized = re.sub(r"\s+", " ", old_string).strip()
        original_normalized = re.sub(r"\s+", " ", original)

        if old_normalized in original_normalized:
            pos = original_normalized.find(old_normalized)
            if pos >= 0:
                original = (
                    original[:pos] + new_string + original[pos + len(old_string) :]
                )
                result["success"] = True
                result["method"] = "whitespace_normalized"
                result["replacements"] = 1
                return original, result

        result["warnings"].append("No match found with any method")
        return original, result

    def _semantic_cleanup(self, text: str) -> str:
        """Clean up text for better fuzzy matching"""
        import re

        text = re.sub(r"[ \t]+", " ", text)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        return text.strip()

    @property
    def enable_fuzzy(self) -> bool:
        return self.dmp is not None


class FuzzyPatchEngine:
    """Main engine for fuzzy patch processing using official library"""

    def __init__(self):
        self._lib = cap if LIBRARY_AVAILABLE else None
        self.converter = FuzzyPatchConverter()
        self.replacer = SmartMatchReplacer()

    def process(
        self, patch: str, original_content: str = "", apply_fuzzy: bool = True
    ) -> Dict[str, Any]:
        """Process a patch with fuzzy conversion"""
        result = {
            "success": False,
            "unified_diff": "",
            "operations": [],
            "errors": [],
            "warnings": [],
        }

        if not self._lib:
            result["errors"].append("codex-apply-patch library not available")
            return result

        try:
            parsed = self._lib.parse_patch(patch)
            result["success"] = True
            result["operations"] = [{"parsed": str(parsed)}]
        except Exception as e:
            result["errors"].append(str(e))

        return result

    def apply_in_memory(self, patch: str, files: Dict[str, str]) -> PatchResult:
        """Apply patch to in-memory files"""
        return self.converter.apply_in_memory(patch, files)


def convert_codex_to_google(patch: str, original: str = "") -> str:
    """Convenience function to convert Codex patch to unified diff"""
    if not LIBRARY_AVAILABLE:
        return ""
    return cap.generate_patch("unknown", original, "")


def smart_replace(
    original: str, old_string: str, new_string: str, replace_all: bool = False
) -> Tuple[str, bool]:
    """Convenience function for smart replace"""
    replacer = SmartMatchReplacer()
    result_str, info = replacer.find_and_replace(
        original, old_string, new_string, replace_all
    )
    return result_str, info["success"]


# Convenience functions using official library
def apply_patch(patch: str) -> Any:
    """Apply patch to files on disk"""
    if not LIBRARY_AVAILABLE:
        raise ImportError("codex-apply-patch library not available")
    return cap.apply_patch(patch)


def apply_patch_in_memory(patch: str, files: Dict[str, str]) -> PatchResult:
    """Apply patch to in-memory files"""
    if not LIBRARY_AVAILABLE:
        return PatchResult(errors=["Library not available"])

    result = cap.apply_patch_in_memory(patch, files)
    return PatchResult(
        success=True,
        files=result.files if hasattr(result, "files") else {},
        added=getattr(result, "added", 0),
        modified=getattr(result, "modified", 0),
        deleted=getattr(result, "deleted", 0),
    )


def parse_patch(patch: str) -> Any:
    """Parse patch and return structure info"""
    if not LIBRARY_AVAILABLE:
        raise ImportError("codex-apply-patch library not available")
    return cap.parse_patch(patch)


def generate_patch(path: str, original_content: str, new_content: str) -> str:
    """Generate patch for a single file"""
    if not LIBRARY_AVAILABLE:
        raise ImportError("codex-apply-patch library not available")
    return cap.generate_patch(path, original_content, new_content)


def generate_patch_from_files(files: Dict[str, Tuple[str, str]]) -> str:
    """Generate patch for multiple files"""
    if not LIBRARY_AVAILABLE:
        raise ImportError("codex-apply-patch library not available")
    return cap.generate_patch_from_files(files)
