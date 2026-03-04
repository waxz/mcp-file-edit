# MCP File Edit

A Model Context Protocol (MCP) server for comprehensive file system operations with SSH and Git support. Built on FastMCP.

## Features

| Category | Capabilities |
|----------|-------------|
| **File Operations** | Read, write, create, delete, move, copy files |
| **Directory Management** | List files, create directories, recursive operations |
| **Search & Replace** | Regex search across files, multi-file find/replace |
| **Patching** | Line-based, pattern-based, and context-based modifications |
| **Code Analysis** | Extract functions, classes, and code structure |
| **SSH Support** | Remote file operations, upload/download, rsync sync |
| **Git Operations** | Full git support for local and remote repositories |
| **HTTP Transport** | Run as web service via Streamable HTTP |

## Installation

```bash
git clone https://github.com/patrickomatik/mcp-file-edit.git
cd mcp-file-edit
uv pip install -e .[all]
```

Or with pip:
```bash
pip install -e .
```

## Quick Start

### HTTP Server Mode

```bash
mcp-file-edit -t http -P 8000 -H 0.0.0.0 -p /mcp
```

### Claude Desktop Configuration

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "file-edit": {
      "command": "uv",
      "args": ["run", "mcp", "run", "/path/to/mcp-file-edit/server.py"]
    }
  }
}
```

Restart Claude Desktop after configuration.

## Usage

### Set Project Directory

```python
set_project_directory("/path/to/your/project")
```

Now use simple relative paths:
```python
read_file("src/main.py")
write_file("docs/README.md", content)
list_files("tests")
```

### SSH Connections

```python
set_project_directory(
    path="/home/user/project",
    connection_type="ssh",
    ssh_host="example.com",
    ssh_username="user",
    ssh_port=22,
    ssh_key_filename="~/.ssh/id_rsa"
)
```

Or use SSH URL format:
```python
set_project_directory("ssh://user@example.com:22/home/user/project")
```

### SSH File Transfer

```python
ssh_upload(local_path="/local/file.txt", remote_path="remote/file.txt", recursive=True)
ssh_download(remote_path="/remote/file.txt", local_path="/local/file.txt")
ssh_sync(local_path="/local/source", remote_path="/remote/mirror", direction="upload")
```

### Search and Replace

```python
results = search_files(pattern="TODO|FIXME", path="src", recursive=True)
replace_in_files(search="old_function", replace="new_function", file_pattern="*.py")
```

### Advanced Patching

```python
patch_file("config.json", patches=[{"line": 5, "content": '    "debug": true,'}])
patch_file("main.py", patches=[{"find": "import old", "replace": "import new"}])
patch_file("app.py", patches=[{"context": ["def process():", "    return None"], "replace": ["def process():", "    return result"]}])
```

### Code Analysis

```python
functions = list_functions("mycode.py")
func = get_function_at_line("mycode.py", 42)
structure = get_code_structure("mycode.py")
search_results = search_functions("test_.*", "tests/", "*.py")
```

### Git Operations

```python
status = git_status()
git_init()
git_clone("https://github.com/user/repo.git", branch="main")
git_add("file.txt")
git_commit("feat: Add new feature")
git_push("origin", "main", set_upstream=True)
git_pull("origin", "main")
git_branch(create="feature/new-feature")
git_checkout("feature/new-feature")
diff = git_diff()
```

## Available Tools

### File Operations
- `read_file` - Read file contents with optional line range
- `write_file` - Write content to a file
- `create_file` - Create a new file
- `delete_file` - Delete a file or directory
- `move_file` - Move or rename files
- `copy_file` - Copy files or directories
- `get_file_info` - Get detailed file metadata

### Directory Operations
- `list_files` - List files with glob patterns and depth control

### Search and Modification
- `search_files` - Search for patterns with regex support
- `replace_in_files` - Find and replace across multiple files
- `patch_file` - Apply precise modifications to files

### Project Management
- `set_project_directory` - Set working directory (local or SSH)
- `get_project_directory` - Get current project directory

### Code Analysis
- `list_functions` - List functions with signatures and line numbers
- `get_function_at_line` - Find function containing a specific line
- `get_code_structure` - Extract complete code structure
- `search_functions` - Search for functions by pattern

### SSH Operations
- `ssh_upload` - Upload files to remote server
- `ssh_download` - Download files from remote server
- `ssh_sync` - Rsync-based directory synchronization

### Git Operations
- `git_status`, `git_init`, `git_clone`, `git_add`, `git_commit`
- `git_push`, `git_pull`, `git_log`, `git_branch`, `git_checkout`
- `git_diff`, `git_remote`

## Safety Features

- **Path Traversal Protection**: Validated paths prevent directory traversal attacks
- **Project Boundary Enforcement**: Operations restricted to base directory
- **Backup Creation**: Automatic backups before modifications
- **Dry Run Mode**: Preview changes before applying
- **Atomic Operations**: All-or-nothing patch applications

## Configuration Options

| Option | Description |
|--------|-------------|
| `-t, --transport` | Transport type: `stdio` (default) or `http` |
| `-P, --port` | HTTP server port (default: 8000) |
| `-H, --host` | HTTP server host (default: 127.0.0.1) |
| `-p, --path` | HTTP path prefix (default: /mcp) |

## Examples

See the `examples/` directory for detailed examples:
- `example_usage.py` - Basic file operations
- `patch_examples.py` - Various patching techniques
- `ssh_transfer_examples.py` - SSH operations

## Development

```bash
python -m pytest tests/
```

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Acknowledgments

- Built with [FastMCP](https://github.com/jlowin/fastmcp)
- Implements [Model Context Protocol](https://modelcontextprotocol.io)
