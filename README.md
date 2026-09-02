# MCP File Edit

A Model Context Protocol (MCP) server for comprehensive file system operations with SSH and Git support. Built on FastMCP.

## Features

| Category | Capabilities |
|----------|-------------|
| **File Operations** | Read, write, create, delete, move, copy files |
| **Directory Management** | List files, create directories, recursive operations |
| **Search & Replace** | Regex search across files, multi-file find/replace |
| **Patching** | Line-based, pattern-based, context-based, Codex/OpenAI-style `apply_patch`, and Anthropic-style `str_replace_based_edit_tool` modifications |
| **Code Analysis** | Extract functions, classes, and code structure |
| **SSH Support** | Remote file operations, upload/download, rsync sync |
| **Git Operations** | Full git support for local and remote repositories |
| **HTTP Transport** | Run as web service via Streamable HTTP |

## Installation

```bash
git clone https://github.com/patrickomatik/mcp-file-edit.git
cd mcp-file-edit
uv pip install  .[all]

uv build --wheel

uv pip uninstall mcp-file-edit

uv pip install dist/mcp_file_edit-2.0-py3-none-any.whl
uv pip install "dist/mcp_file_edit-2.0-py3-none-any.whl[all]"
```

Or with pip:
```bash
pip install -e .
```

## Quick Start

### HTTP Server Mode

```bash
# windows
$ENV:API_KEYS = "sk_qqqq"
#linux
API_KEYS = "sk_qqqq"
mcp-file-edit -t http -P 8000 -H 0.0.0.0 -p /fs
```

### Claude Code
```bash
claude mcp add --transport http filesystem  http://localhost:8001/fs --header "x-api-key:sk-123456"

claude config set permissions.deny "['Edit', 'Write']"

```


Restart Claude Desktop after configuration.

### Two File-Editing Protocols: Claude and OpenAI

This server exposes two purpose-built editing tools, one per model family's native
tool-calling conventions, both operating on the same project directory and files:

| Tool | Protocol | Best for |
|------|----------|----------|
| `str_replace_based_edit_tool` | Anthropic's `str_replace_based_edit_tool` commands (`view`, `create`, `str_replace`, `insert`, `undo_edit`) | Claude models, which are trained to call this exact tool shape |
| `apply_patch` | OpenAI/Codex-style `*** Begin Patch` / `*** Update File` unified-diff envelope | GPT/Codex/OpenAI models, which are trained on this exact envelope |

Pick whichever tool matches the calling model; both are safe to use interchangeably
against the same files, and other agents (OpenCode, etc.) can use either.

### Claude Code Guidance

When Claude Code uses this MCP server, prefer tools in this order:

1. `str_replace_based_edit_tool` (`str_replace`/`insert`) or `apply_patch` for targeted edits to existing files
2. `create_file` (or `str_replace_based_edit_tool` with `command="create"`) for new files
3. `write_file` only for full rewrites when patching is unnecessary

Avoid the brittle pattern of `read_file` followed by `write_file` for a small change. That loses context, makes anchors weaker, and is more likely to corrupt unrelated content when the model diagnosis is wrong.

Example agent instruction templates are included in:
- `CLAUDE.md.example`
- `AGENTS.md.example`

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

For code-editing agents, prefer `apply_patch` over `read_file` + `write_file` when making targeted changes:

```text
*** Begin Patch
*** Update File: src/example.py
@@
-old_value = 1
+old_value = 2
*** End Patch
```

Use `write_file` only when one of these is true:
- the file is brand new
- the entire file content is being replaced intentionally
- patch context cannot be expressed cleanly

For a normal code fix, the guidance should be:
- inspect with `read_file`
- modify with `apply_patch`
- avoid whole-file rewrites unless necessary

For Claude specifically, prefer `str_replace_based_edit_tool` over `apply_patch`
when available - it matches the exact tool schema Claude is trained to call:

```text
# 1. Inspect
str_replace_based_edit_tool(command="view", path="src/example.py")

# 2. Edit - old_str must match exactly once in the file
str_replace_based_edit_tool(
    command="str_replace",
    path="src/example.py",
    old_str="old_value = 1",
    new_str="old_value = 2",
)

# 3. Undo if the edit was wrong
str_replace_based_edit_tool(command="undo_edit", path="src/example.py")
```

`str_replace_based_edit_tool` commands:
- `view` - show a file (numbered like `cat -n`, optionally via `view_range`) or list a directory up to 2 levels deep
- `create` - create (or overwrite) a file with `file_text`
- `str_replace` - replace the single, unique occurrence of `old_str` with `new_str`
- `insert` - insert `new_str` after line `insert_line` (`0` = start of file)
- `undo_edit` - revert the last edit made to a file through this tool

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
- `apply_patch` - Apply robust multi-file patches using Codex/OpenAI-style patch envelopes
- `str_replace_based_edit_tool` - Anthropic-compatible text editor tool for Claude (`view`/`create`/`str_replace`/`insert`/`undo_edit`)

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
- **Agent-Friendly Editing**: `apply_patch` avoids brittle whole-file rewrite flows for small edits

## Recommended Agent Workflow

For Claude Code and similar agents:

```text
1. Use list_files/search_files/read_file to gather context.
2. Use apply_patch for edits to existing files.
3. Use create_file for new files.
4. Use write_file only for intentional full-file replacement.
```

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