# unified-mcp-server

One MCP server that exposes **both** tool sets:

| Sub-server | Tools (58 total) |
|---|---|
| [mcp-file-edit](..) | files (read/write/move/search/replace), patches (`apply_patch` with preview → confirm → apply), git, SSH transfer, tree-sitter code analysis, linters, `set_project_directory` |
| [shell-mcp-server](https://github.com/waxz/shell-mcp-server) | `execute_command` (streamed), trusted commands, process list/terminate, tmux sessions |

It does not copy either codebase. It **mounts** the two existing FastMCP servers
into a parent server that owns transport, auth and configuration, so fixes
upstream flow straight through.

## What the unification adds

- **One process, one endpoint, one config file.** The config format is a
  superset of both originals (their keys don't overlap), so an existing
  `config.toml` from either project still works.
- **Shared working directory.** Unless `[DOCKER_CONFIG.<os>] host_root` is set
  explicitly, shell commands with `cwd="."` run in the file tools' project
  directory, and follow it when `set_project_directory` changes it. Allowed
  roots are shared the same way.
- **Fixed auth.** Upstream checks `get_http_headers()` without
  `include_all=True`, which strips `Authorization`, so Bearer tokens never
  work there, and on failure it sends the presented key and all request headers
  back to the caller. Here:
  `Authorization: Bearer <key>` and `x-api-key: <key>` both work, several
  keys are allowed (`API_KEYS = "k1,k2"`), the check takes the same time
  whichever key is sent, and nothing is echoed back. Auth applies to HTTP only
  (stdio has no headers).
- **Optional namespacing.** `--namespaced` exposes `fs_*` and `shell_*` names.
  Without it, startup fails fast if the two tool sets ever collide.
- **Upstream bundled config files are not read.** Both upstream wheels bundle a
  `config.toml` with the author's own paths (and a sample API key); the unified
  server reads only its own defaults and your file.

## Install & run

```bash
cd unified-mcp-server
uv venv && uv pip install -e .
```

```bash
# stdio (Claude Desktop / Claude Code)
unified-mcp-server -w /path/to/project
```

```bash
# HTTP
unified-mcp-server -c config.toml -t http -H 127.0.0.1 -P 8000 -p /mcp
```

Claude Code:

```bash
claude mcp add unified -- unified-mcp-server -w /path/to/project
```

### CLI

| Flag | Meaning |
|---|---|
| `-c/--config` | TOML config (default `config.toml`; see `config.example.toml`) |
| `-t/--transport` | `stdio` or `http` |
| `-H/--host`, `-P/--port`, `-p/--path` | HTTP bind settings |
| `-w/--workdir` | project directory for file tools (and shell, if not configured) |
| `-d/--directories` | allowed root directories |
| `--shell NAME PATH` | shell mapping for shell tools (repeatable) |
| `--namespaced` | prefix tools with `fs_` / `shell_` |
| `--no-files` / `--no-shell` | disable one half |

Precedence: built-in defaults → config file → CLI flags.

## Shell execution model (inherited from shell-mcp-server)

- `TRUSTED_COMMANDS` run directly on the host, by name.
- Other commands on a Linux host are wrapped in the external `drun` sandbox
  helper (expected in `~/.bashrc`). Without `drun`, only trusted commands work.
- Set `IS_IN_DOCKER = true` when the server itself runs in a container: all
  commands then run directly inside it.

## Tests

```bash
uv pip install -e ".[dev]"
pytest -q
```

The tests cover the combined tool list, namespacing, a file written by
`write_file` being read by a shell command, the shell following
`set_project_directory`, and API-key auth over real HTTP.

## Dependency note

Both sub-servers import `fastmcp.server.tasks`, which fastmcp 4.x removed, and
both declared `fastmcp>=3.0.0` with no upper bound, so a fresh install broke.
This package pins `fastmcp[tasks]>=3.0.0,<4`.
