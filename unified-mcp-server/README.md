# unified-mcp-server

A self-contained MCP server with file editing and shell execution in one
process, one endpoint and one config file. It has 58 tools:

| Family | Tools |
|---|---|
| Files | read/write/create/copy/move/delete, search & replace, `patch_file`, `apply_patch` with preview → confirm → apply (plus a browser review page over HTTP), `get_file_info` |
| Git | status, init, clone, add, commit, push, pull, log, branch, checkout, diff, remote |
| Code analysis | tree-sitter `list_functions`, `get_function_at_line`, `get_code_structure`, `search_functions` |
| Linting | `detect_linters`, `run_linter`, `lint_file`, `run_type_checker`, `type_check_file`, `format_file` |
| Remote | `ssh_upload`, `ssh_download`, `ssh_sync`, SSH project directories |
| Project | `set_project_directory`, `get_project_directory` |
| Shell | `execute_command` (streamed output), `list_trusted_commands`, process list/terminate, tmux sessions |

The code started as two separate servers,
[mcp-file-edit](https://github.com/waxz/mcp-file-edit) and
[shell-mcp-server](https://github.com/waxz/shell-mcp-server). It is copied
into this package and maintained here; neither project is a dependency.

## Install & run

```bash
uv venv && uv pip install -e .
```

stdio (Claude Desktop, Claude Code):

```bash
unified-mcp-server -w /path/to/project
```

```bash
claude mcp add unified -- unified-mcp-server -w /path/to/project
```

HTTP:

```bash
unified-mcp-server -c config.toml -t http -H 127.0.0.1 -P 8000 -p /mcp
```

### CLI

| Flag | Meaning |
|---|---|
| `-c/--config` | TOML config (default `config.toml`; see `config.example.toml`) |
| `-t/--transport` | `stdio` or `http` |
| `-H/--host`, `-P/--port`, `-p/--path` | HTTP bind settings |
| `-w/--workdir` | project directory |
| `-d/--directories` | allowed root directories |
| `--shell NAME PATH` | shell mapping for shell tools (repeatable) |
| `--namespaced` | prefix tools with `fs_` / `shell_` |
| `--no-files` / `--no-shell` | disable one family |

Precedence: built-in defaults → config file → CLI flags. Environment variables
are not read.

## Configuration

`config.example.toml` lists every option. Config files written for either
original project use the same format and load as they are, as long as the
directories they name exist on this machine. Keys this server doesn't know
are logged and ignored.

- **Project directory.** `[CONFIG.<os>] work_dir` / `-w` sets the root for
  file tools. Unless `[DOCKER_CONFIG.<os>] host_root` is set, shell commands
  with `cwd="."` run there too, and follow `set_project_directory`. Allowed
  roots are shared the same way.
- **Auth.** `API_KEYS = "k1,k2"` protects every tool call over HTTP. Send
  `Authorization: Bearer <key>` or `x-api-key: <key>`. Keys are compared in
  constant time and never echoed back. stdio has no headers, so keys are
  ignored there.

### Shell execution model

- `TRUSTED_COMMANDS` run directly on the host, by name:
  `execute_command(command="t_test", cwd=".")`.
- Any other command on a Linux host is wrapped in the external `drun` sandbox
  helper (expected in `~/.bashrc`). Without `drun`, only trusted commands run.
- Set `IS_IN_DOCKER = true` when the server itself runs inside a container:
  every command then runs directly in it.
- `SAFETY_MODE = "strict"` forces `bash` for untrusted commands.

## Changes from the original projects

**Structure**

- `files/` holds the file tools and `shell/` the shell tools. Code both
  projects duplicated lives once in `common/`.
- Both tool families share one `Settings` model, one loader and one FastMCP
  app. Tools are registered directly; there is no proxying or mounting.
- Settings is a plain pydantic model, not `BaseSettings`, so the system
  `PATH`/`HOST` environment variables can't leak into the server's
  `PATH`/`HOST` fields.
- The unused `fuzzy_patch.py` (it needed an uninstalled library) and a
  debugging tmux helper that printed to stdout were not copied.

**Bugs fixed**

- `tmux_execute` sent `C-c` to a new pane before its shell had started,
  killing the shell and the tmux server. This failed every time on GitHub
  runners. The bootstrap now waits for the pane's prompt and the reset no
  longer sends `C-c`. *(shell/tmux_commands.py)*
- `tmux_list_session` crashed with `cwd=None` when no sandbox work dir was
  configured, and raised when no tmux server was running. It now checks the
  sandbox only when one exists, returns `[]` with no server, and drops blank
  names. *(shell/tool_handlers.py)*
- `remove_directory` and recursive `delete_file` used
  `shutil.rmtree(onexc=...)`, which needs Python 3.12. They now work on 3.11.
  *(files/file_operations.py)*
- Code analysis skipped every `async def` (no `visit_AsyncFunctionDef`).
  *(files/code_analyzer.py)*
- A timed-out command crashed while formatting its result (`config` was never
  imported). *(common/mcp_types_utils.py)*
- Auth: Bearer tokens never worked, because the `Authorization` header was
  stripped. A failed check also echoed the key and all request headers back to
  the caller. *(server.py)*
- fastmcp 4.x removed `fastmcp.server.tasks`; the dependency is pinned `<4`.

## Tests & CI

```bash
uv pip install -e ".[dev]"
pytest -q
```

- `tests/test_tools.py` calls every tool family through a real MCP client. It
  also checks the exact set of 58 registered tools.
- `tests/test_unified.py` covers config, namespacing, the shared project
  directory, the installed console script over stdio, and API-key auth over
  real HTTP.
- `tests/test_fixes.py` holds a regression test for each fixed bug, including
  a reproduction of the tmux race using a shell that is slow to start.

CI (`.github/workflows/unified-mcp-tools.yml`) runs the suite on Ubuntu with
Python 3.11, 3.12 and 3.13.

## License

The code comes from an MIT-licensed project (mcp-file-edit) and an
Apache-2.0-licensed project (shell-mcp-server), so the package is
`MIT AND Apache-2.0`. See `NOTICE`, `LICENSE-MIT` and `LICENSE-APACHE`. Each
copied file says which project it came from.
