# tasks_provider — VSM Task/Session Canonical Instance

Parses VSM-notation `.vsm` files containing `task()` and `session()`
blocks into structured JSON records. Exposes three domains:

| Domain | Records | Source |
|--------|---------|--------|
| `tasks` | One per `task(...)` block | Parsed from the VSM file |
| `sessions` | One per `session(...)` block | Parsed from the VSM file |
| `focus` | Per-agent focus items | Co-located `current_focus.json` (optional) |
| `meta` | File metadata (path, sha256, counts) | Synthesised |

## Usage

```bash
# Load from a .vsm file
python3 mcp_server.py --instance instances/tasks_provider.py:/path/to/TASKS.vsm

# Load from a directory (auto-discovers TASKS.vsm + current_focus.json)
python3 mcp_server.py --instance instances/tasks_provider.py:/path/to/project/dir
```

## Task Record Shape

```json
{
  "id": "TASK-ID",
  "priority": "P1",
  "agent": "ds | [S] | [S, bbh]",
  "status": "open | dispatched | done | seeded | investigated",
  "what": "description of the work",
  "gate": "precondition",
  "done_when": "observable outcome",
  "title": "legacy title field (also mapped to what)"
}
```

Task blocks support three syntax styles:

1. **New-style** — `task("ID", ...) = { key: value, ... }`
2. **Old-style single-line** — `task(ID): key=value key=value ...`
3. **Old-style indented** — `task(ID):\n  key = value\n  key = value\n`

## Session Record Shape

```json
{
  "id": "2026-07-27",
  "summary": "what was done",
  "result": "pass | partial | fail",
  "resolved": ["TASK-ID — evidence", ...],
  "commits": ["sha (message)", ...],
  "verify": ["command output", ...],
  "next": "next action",
  "note": "anything non-obvious"
}
```

## Focus Record Shape (from current_focus.json)

```json
{
  "ref": "TASK-ID",
  "status": "active | paused | done",
  "note": "what's happening with this item",
  "started_at": "2026-07-27T18:00:00Z",
  "updated_at": "2026-07-27T18:30:00Z"
}
```

The `focus` domain is only present when a `current_focus.json` file
exists alongside the VSM file, containing an array of focus records.

## TaskSessionReconciler

Flags **declared-vs-observed drift** between task status and session
resolution records. Checks: if a task's `id` appears textually in any
later session's `resolved: []` list but the task's status still says
`open`, `dispatched`, `seeded`, or `investigated` (any status containing
those keywords), it produces a `declared_but_resolved` drift.

Schema of the drift evidence:

```json
{
  "kind": "declared_but_resolved",
  "subject": "TASK-ID",
  "detail": "Task 'TASK-ID' has status='open' but is referenced as resolved in session(s): 2026-07-27",
  "evidence": {
    "task": {"id": "TASK-ID", "status": "open", "what": "..."},
    "resolved_in": ["2026-07-27"],
    "status_field": "open"
  }
}
```

## VSM Parser Implementation Notes

- The parser is line-based, not AST-based — it handles the subset of VSM
  notation used in project task files.
- Supports `@vsm` header lines (skipped), `//` comments (skipped),
  nested bracket blocks (`key: [ ... ]`), and quoted strings with
  continuation lines.
- Two-pass over bracket blocks: collected separately from regular KV
  pairs to handle multi-line `resolved: [...]` and `commits: [...]`.
