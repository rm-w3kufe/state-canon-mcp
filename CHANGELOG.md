# Changelog

All notable changes to state-canon-mcp are documented here. Loosely follows
[Keep a Changelog](https://keepachangelog.com/). Versions match the `serverInfo.version`
string the server reports on `initialize` — see "Verify the install" in the README to
check yours.

## [0.6.0] — 2026-07-27

### Added
- `FocusTaskReconciler` — flags focus entries whose status says active/paused
  but whose referenced task is done or resolved. Two drift kinds:
  `stale_focus_task_done` (task's own status is closed-like) and
  `stale_focus_session_resolved` (task ref appears in session's `resolved:[]`
  list). Domain `focus`, coexists with `TaskSessionReconciler` (domain `tasks`).
- Wired into `instances/tasks_provider.py`'s `load()` — both reconcilers are
  returned automatically.

## [0.5.0] — 2026-07-27

### Added
- `state_focus_mark` / `state_focus_close` — opt-in per-agent focus tracking
  (`--focus PATH`). `FocusTracker` class with atomic write (temp+rename),
  upsert-by-ref `mark()`, `close()` for status=done. `state_query('focus')`
  reads entries back. Returns error if `--focus` not set.
- 42 tests for the focus tracker (unit + MCP dispatch), all pass.

## [0.4.0] — 2026-07-27

### Added
- `instances/tasks_provider.py` — generic VSM task-file provider. Parses
  `task()` / `session()` blocks from `.vsm` files into domains `tasks`,
  `sessions`, `meta`. Supports new-style (`{...}`), old-style single-line,
  and old-style indented notation. Includes `TaskSessionReconciler` that
  flags tasks whose status says `open`/`dispatched`/`seeded` but whose id
  appears in a later session's `resolved: []` list (declared-vs-observed
  drift for task tracking).
- Co-located `current_focus.json` support — if a `current_focus.json` file
  exists next to the VSM file, its records are exposed as the `focus`
  domain (per-agent work-tracking items with `ref`, `status`, `note`,
  `started_at`, `updated_at`).
- 13 tests for the parser, reconciler, and focus loading
  (`tests/test_tasks_provider.py`).
- Reference documentation for the tasks provider instance
  (`instances/reference-tasks.md`).

## [0.3.0] — 2026-07-27

### Added
- `state_journal_mark` / `state_journal_diff` / `state_journal_history` — opt-in
  session-snapshot tracking (`--journal PATH`): "what changed since last session?",
  simple trend tracking. Off by default; existing setups are unaffected.

## [0.2.0] — 2026-07-24

### Changed
- Renamed **State RAG MCP → state-canon**. The canon layer (authoritative, reconciled,
  verifiable) is the point — RAG retrieval was ~20% of the design, not the headline.
- Collapsed the reference agent pattern from two agents (reasoner + executor) to one
  canon-grounded agent (`agents/agent.md`).
- README/docs polish: concrete clone URL, diagram fixes, dropped defensive framing.

## [0.1.0] — 2026-07-20

### Added
- Initial public release. MCP server (stdio, JSON-RPC 2.0, stdlib-only) exposing
  `state_onboard` / `state_query` / `state_verify` / `state_reconcile`.
- `JsonStateProvider`, `SqliteStateProvider`, `GitStateProvider` + the generic
  `Reconciler` (declared-vs-observed drift).
- `microstack` demo corpus + controlled token-cost experiment.
- Single-agent spec + 9 portable skills.
