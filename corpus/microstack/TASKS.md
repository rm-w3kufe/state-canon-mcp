# EXP-TOKEN-GROUNDING — the 2 fixed tasks (spec: docs/spec/EXP-TOKEN-GROUNDING.spec.vsm)

## T_broad  (hypothesis: favors C1 onboard — needs almost all the state)
> "Report the current state of the `microstack` system: list all services with their declared status,
> flag any drift between the declared manifest and the actual reality (declared-active-but-stopped,
> rule violations, orphan processes), and state the last recorded decision."

## T_narrow  (hypothesis: favors C2 MCP — needs one slice)
> "Is the `cache` service consistent with the declared state? If not, describe the specific drift and
> what it impacts."

---

## Conditions (same model, N≥5 trials each, fixed corpus)
- **C0 — baseline/cold**: agent gets ONLY `raw/` (manifest, processes, RULES, HANDOFF). Must explore + synthesize.
- **C1 — onboard**: agent gets a compact digest of `synthesized/state.json` injected into context up front.
- **C2 — MCP**: agent gets state MCP tools to query `synthesized/state.json` on demand (lazy).

## Measure per trial
input_tokens · output_tokens · total · tool_calls · wall-clock · **correctness** (score vs GROUND_TRUTH.md).
Report mean ± spread. Savings with wrong/incomplete answers = disqualified.

## Harness
Run on an isolated sandbox host (never the dev workstation). Read the harness's usage report. Same model across C0/C1/C2.
