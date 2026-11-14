# Derived from shell-mcp-server (Apache-2.0, https://github.com/waxz/shell-mcp-server);
# modified for unified-mcp-server. See NOTICE and LICENSE-APACHE.
"""Platform-specific command builders."""

from .posix import build_posix_shell_command
from .windows import build_windows_shell_command

__all__ = ["build_posix_shell_command", "build_windows_shell_command"]
