# EXPERIMENT — measuring the token cost of grounding

*Public arm of the internal experiment spec. Rule: **measure, don't proclaim** — a fair baseline,
correctness-gated, honestly caveated.*

## Hypothesis

A state-grounded context layer (onboard digest and/or MCP query) reduces input tokens for
state-dependent tasks vs a cold baseline, **without loss of correctness**. (Null hypothesis must be
rejectable: no significant difference, or savings at the cost of correctness.)

## Conditions — same model, same tasks, same initial state

| | Condition | The agent gets |
|---|---|---|
| **C0** | cold baseline | only `raw/` (manifest, processes, rules, handoff) — must explore + synthesize |
| **C1** | onboard | a compact digest of the reconciled state, injected up front — zero exploration |
| **C2** | MCP lazy | the MCP tools — queries only what it needs, on demand |

Two fixed tasks, because the interesting result is a **trade-off**, not a winner:
- **T_broad** — "report the full state + drift + last decision" (should favor C1's front-load)
- **T_narrow** — "is `cache` consistent? what's the drift?" (should favor C2's targeted query)

## Controls

1. Same model across all conditions (model tiering is a *different* experiment).
2. Fixed corpus (`corpus/microstack/` — 3 seeded drifts of different kinds).
3. N≥5 trials per cell; report mean ± spread (LLMs are stochastic; a single number lies).
4. **Fair baseline**: C0 is a competent agent with good read tools — never handicapped to inflate savings.
5. **Correctness gate**: answers scored against `GROUND_TRUTH.md`; token savings with a wrong or
   incomplete answer are **disqualified**.

## Results

See [RESULTS.md](./RESULTS.md) — including the honest caveats (proxy tokenizer, projected-vs-observed
labels, and the behavioral finding that agents default to the broadest tool). Publication-grade
counters (real MCP attachment + billed usage) are the pending step; relative numbers are credible,
absolute numbers approximate.
