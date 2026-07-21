# Install

**Requirements:** Python **3.10+**. Nothing else — the server is stdlib-only, there is no `pip install`.

```bash
git clone <this-repo> state-rag-mcp
python3 state-rag-mcp/tests/test_state_rag.py   # optional: 22 checks, ~1s
```

The server is one command (stdio; your MCP client spawns it):

```bash
python3 /abs/path/state-rag-mcp/mcp_server.py --state      /abs/path/your-state.json
python3 /abs/path/state-rag-mcp/mcp_server.py --sqlite     /abs/path/your-state.db     # SQLite
python3 /abs/path/state-rag-mcp/mcp_server.py --microstack /abs/path/state-rag-mcp/corpus/microstack  # demo
```

> **Architecture note:** the server runs **locally, beside your agent** (stdio). Your state lives where
> your agent lives. It is not a network service and does not phone anywhere.

## Per-client configuration

All stdio MCP clients need the same three facts: `command: python3`, `args: [launcher, --flag, path]`.
Use **absolute paths** everywhere.

### Claude Code (CLI)

```bash
claude mcp add state-rag -- python3 /abs/path/state-rag-mcp/mcp_server.py --state /abs/path/state.json
```

or per-project in `.mcp.json`:

```json
{ "mcpServers": { "state-rag": {
    "command": "python3",
    "args": ["/abs/path/state-rag-mcp/mcp_server.py", "--state", "/abs/path/state.json"] } } }
```

### Claude Desktop

`claude_desktop_config.json` (Settings → Developer → Edit Config):

```json
{ "mcpServers": { "state-rag": {
    "command": "python3",
    "args": ["/abs/path/state-rag-mcp/mcp_server.py", "--state", "/abs/path/state.json"] } } }
```

### OpenCode

`opencode.json` (schema varies by version — this is the 0.x shape):

```json
{ "mcp": { "state-rag": {
    "type": "local",
    "command": ["python3", "/abs/path/state-rag-mcp/mcp_server.py", "--state", "/abs/path/state.json"] } } }
```

### Cursor

`.cursor/mcp.json` (project) or `~/.cursor/mcp.json` (global) — same `mcpServers` shape as Claude Desktop.

### Cline (VS Code)

`cline_mcp_settings.json` (Cline → MCP Servers → Configure) — same `mcpServers` shape.

### Windsurf

`~/.codeium/windsurf/mcp_config.json` — same `mcpServers` shape.

## Verify the install (no client needed)

```bash
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  | python3 /abs/path/state-rag-mcp/mcp_server.py --microstack /abs/path/state-rag-mcp/corpus/microstack
```

You should see one JSON line with `"serverInfo": {"name": "state-rag-mcp"}`. Then see
[USAGE.md](./USAGE.md) for the 60-second demo and how to point it at **your** system.
