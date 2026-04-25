import pytest
import os
import tempfile
from pathlib import Path
from mcp_file_edit import utils, file_tools

def test_list_files_skips_symlink_outside_project():
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir) / "project"
        project_root.mkdir()
        outside = Path(tmpdir) / "outside.txt"
        outside.write_text("secret", encoding="utf-8")
        link_path = project_root / "outside-link.txt"

        try:
            os.symlink(outside, link_path)
        except (AttributeError, NotImplementedError, OSError):
            pytest.skip("symlinks unavailable on this platform")

        try:
            utils.CONNECTION_TYPE = "local"
            utils.PROJECT_DIR = project_root

            result = file_tools.list_files(".", pattern="*.txt")
            assert result == []
        finally:
            # Cleanup
            pass
