# Ground truth — scoring key (NOT provided to any agent)

## T_broad — "current state + drift + last decision"
- **Services**: 9 total. Declared active: 8 (api, proxy, metrics, worker, db, cache, scheduler, logger).
  Declared inactive: 1 (backup, correctly stopped).
- **Drift (3)**:
  - **DRIFT-1**: `cache` declared active v7 on node-b but NOT running (stopped). Impacts `api` (depends on cache).
  - **DRIFT-2**: **R1 violation** — `api` v1.2.0 ≠ `worker` v1.1.0.
  - **DRIFT-3**: **orphan** — `debug-shell` (PID 303, node-c) running but not a declared service (violates R3).
- **Last decision**: D-42 — approved `cache` upgrade to v8, maintenance 2026-07-25.

Scoring (7 pts): services-count correct (1) · DRIFT-1 (2) · DRIFT-2 (2) · DRIFT-3 (2) · last-decision (bonus).
A drift is "identified" only if kind + service/process are both correct.

## T_narrow — "is cache consistent? what's the drift?"
- Answer: **NO**. `cache` is declared active (v7) on node-b, but the process snapshot shows no cache
  process → **DRIFT-1** (declared-active-but-stopped). It impacts `api` (depends on cache).
  (Bonus: relates to pending D-42 cache upgrade.)

Scoring (3 pts): correct "NO" (1) · DRIFT-1 named (1) · impact on api (1).

## Notes for the grader
- A COLD (C0) agent must cross-reference `raw/manifest.txt` × `raw/processes.txt` × `raw/RULES.md` to
  derive all 3 drifts. An onboard/MCP condition gets `drift` pre-computed in `synthesized/state.json`.
- Token savings that produce an INCORRECT or INCOMPLETE answer are DISQUALIFIED (report correctness alongside tokens).
