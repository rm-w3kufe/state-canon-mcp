# Changelog

All notable changes to state-canon-mcp are documented here. Loosely follows
[Keep a Changelog](https://keepachangelog.com/). Versions match the `serverInfo.version`
string the server reports on `initialize` — see "Verify the install" in the README to
check yours.

## [0.8.1] — 2026-07-30

### Fixed
- **`instances/tasks_provider.py` served stale data for the entire lifetime of
  a long-running MCP server session** — found live, while closing out this
  same day's housekeeping round: `state_focus_mark` then `state_reconcile`
  in the *same* server session returned zero drift, because
  `FocusTaskReconciler`'s `declared()` returned a `focus_items` list frozen
  at `load()` time, never re-read. A direct edit to `TASKS.vsm` (the normal
  way agents change it — not through this server) was invisible for the
  same reason: the provider's `_doc` was built once via a
  `JsonStateProvider.__new__` bypass (needed because its data comes from
  parsing a `.vsm` file, not `json.loads`) and never reloaded, and both
  `TaskSessionReconciler` and `FocusTaskReconciler` cached their own parsed
  copy of the VSM file forever too. Given MCP servers aren't hot-reloaded
  (0.6.1) and sessions run for hours with heavy file editing, this meant
  `state_query`/`state_verify`/`state_reconcile` against `tasks`/`sessions`/
  `focus` were serving whatever was true at server startup, indefinitely.
  Fixed: a new `VsmStateProvider(JsonStateProvider)` reloads on mtime change
  (same mechanism as the base class, `parse_vsm_file` instead of
  `json.loads`); both reconcilers now check mtime before trusting their
  cache; `FocusTaskReconciler` gained `bind_focus_tracker()` — the server
  auto-wires the *same* `FocusTracker` instance `state_focus_mark` writes
  through into any reconciler that exposes the hook, so `declared()` can
  never silently diverge from what was actually written (closes the
  `--focus PATH` vs. co-located-path footgun from 2026-07-27 as a side
  effect, not just the staleness). 8 new regression checks in
  `tests/test_tasks_provider.py` (60/60), reproduced and confirmed fixed
  against the real MCP server subprocess, not just unit-level.

## [0.8.0] — 2026-07-30

Housekeeping round from an external code review (6 findings) plus the most severe
finding of the review, found via a live demo rather than code reading. All fixes have
regression tests in `tests/test_housekeeping_fixes.py` (22/22 checks).

### Fixed
- **`state_verify` silently bypassing the Reconciler (most severe finding)** —
  `state_verify`/`state_query` call `self.provider` directly and never consulted a
  registered `Reconciler`. If a provider was wired to declared/config state instead of
  the reconciled canon, `state_verify` would silently check claims against aspiration,
  not reality, with no error signal. Fixed with a structural safeguard: when a
  `Reconciler` is registered for the queried domain, `state_verify` now cross-checks
  the provider's data against `reconciler.observe()` and adds a `"warning"` field to
  the response on disagreement. See INTERFACE.md's new "Provider contract" section for
  the underlying rule this can't fully substitute for.
- `reconcile.py`'s base `Reconciler.diff()` silently dropped duplicate keys in
  `declared()`/`observe()` (last-wins, no signal) — now emits a `duplicate_key` Drift.
- `focus.py`'s `FocusTracker.mark()` had a lost-update race: two near-simultaneous
  callers could both read-modify-write and the second would silently clobber the
  first's update (atomic temp+rename protects against corruption, not against this).
  Fixed with an `flock()`-guarded critical section around the whole read-modify-write
  cycle. `journal.py` was reviewed for the same pattern and found NOT vulnerable —
  `mark()` is a pure append (autoincrement PK), not a read-modify-write.
- `JsonStateProvider.query()` silently no-matched on an unknown filter field while
  `SqliteStateProvider.query()` raised `ValueError` for the same case — inconsistent
  behavior depending on backend. Unified: `JsonStateProvider` now raises `ValueError`
  when a filter key isn't present in any record of a non-empty domain.
- `JsonStateProvider` loaded its JSON document once in `__init__` and never reloaded —
  a long-lived stdio server session would serve a stale snapshot forever. Now reloads
  on mtime change (checked once per query, not unconditionally). Instances that
  construct a `JsonStateProvider` via `__new__` and populate `_doc` themselves (e.g.
  `tasks_provider.py`, whose data comes from a VSM-file parse, not `json.loads`) are
  unaffected — reload-on-change only activates for the standard `__init__` path.
- `digest.py`'s `_fmt_record` fell back to a bare, uninformative `"?"` label when a
  record had none of the conventional identifier fields (`name`/`id`/`rule`/`value`).
  Now falls back to the record's first available `key=value` pair instead.

### Changed — may require action if you use `--journal`
- `journal.py` no longer hardcodes a BBH-shaped `findings`/`rag_feedback` schema in the
  shared core (`_BBH_TEST_TARGETS`, `_gather_stats`, `_rag_stats` are gone). Domain-
  specific schema assumptions don't belong in the public tool's core — same principle
  as `DIGEST_POLICY` staying instance-side. `StateJournal` now accepts optional
  `stats_fn`/`rag_fn` callables; an `--instance` module can supply them via module-level
  `JOURNAL_STATS_FN`/`JOURNAL_RAG_FN` (fetched the same way as `DIGEST_POLICY`). Left
  unset, the instance-specific journal columns just stay zeroed — drift tracking still
  works fully. **If your instance was relying on the old auto-detected BBH stats**, add
  `JOURNAL_STATS_FN`/`JOURNAL_RAG_FN` to your module (see INTERFACE.md's "Opt-in side
  systems" section for the pattern; `instances/` in your own private fork is the
  intended home for this, not the shared repo).

## [0.7.0] — 2026-07-27

### Added
- `FreshnessReconciler` (`state_canon/freshness.py`) — generic core reconciler
  that flags a file as stale if its mtime is older than *N* seconds. Two drift
  kinds: `missing` (path does not exist) and `stale` (exists but too old —
  detailed message with age in days vs max). Domain defaults to `"freshness"`,
  overridable. Configured in code — instantiate in your instance module:
  `FreshnessReconciler(path="/var/lib/state.db", max_age_seconds=86400)`.
  Stdlib-only, 24/24 checks.

## [0.6.1] — 2026-07-27

### Fixed
- `_load_instance_file()` crash when `--instance` module uses `@dataclass`
  or other Python internals that require `cls.__module__` to be findable
  in `sys.modules` at class-definition time. The fix registers the module
  in `sys.modules` **before** `exec_module()` — one line: `sys.modules[spec.name] = mod`.

### Added
- End-to-end smoke test (`tests/test_e2e_smoke.py`): spawns the actual MCP
  server as a subprocess with `--instance tasks_provider.py + --focus + --journal`,
  sends real JSON-RPC messages over stdio (initialize, tools/list,
  state_reconcile, state_query, state_focus_mark/close, state_journal_mark,
  state_onboard), asserts 27 checks on the live output.
- Combined `--instance + --journal + --focus` example in README quickstart.

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
