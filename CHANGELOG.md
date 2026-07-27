# Changelog

All notable changes to state-canon-mcp are documented here. Loosely follows
[Keep a Changelog](https://keepachangelog.com/). Versions match the `serverInfo.version`
string the server reports on `initialize` — see "Verify the install" in the README to
check yours.

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
