# State RAG MCP — grounded, verified, minimal

> **Two agents and an intelligent control system do more careful work than a swarm — and burn fewer tokens.**
> A state-grounded RAG that puts *verified current state in the agent's path*, so it reasons from ground
> truth instead of stale recall or costly re-derivation.

**Status:** early / exploratory. The thesis and the method are real (and battle-tested in daily use) —
the method itself is documented in **[METHODOLOGY.md](./METHODOLOGY.md)** (the two-agent pattern, with
the real four-round case study). The public tooling is being extracted and **the token-savings claim is
being measured, not proclaimed** — the number and its method will ship together (see *Measured, not
proclaimed*).

---

## The bet

The industry is racing toward multi-agent **swarms** on the premise that *more agents = better work*. We
take the opposite bet: a **minimal** setup — two agents plus a state-grounded control system — produces more
careful, more *verifiable* work at lower token cost.

- **A reasoning/architecture agent** (an advanced model) — designs, reviews, does root-cause analysis.
- **An execution agent** (a regular model) — builds, deploys, runs.
- **A human** — sets policy and holds the ceiling: irreversible / outward-facing changes need approval.

Swarms burn tokens re-deriving context, coordinating, and duplicating. The bottleneck was never *how many
agents* — it's **whether each decision is grounded and verified.** Fix that, and two agents go a long way.

## Why it works — the control system

1. **Grounded, not re-derived.** The current, reconciled state of the system is injected into the agent's
   path. It doesn't re-explore the world each session; it reads verified ground truth. *This is the anchor
   (below).*
2. **Verify at every boundary.** The reasoning agent never trusts the execution agent's *report* — it
   checks the live state directly ("is the service actually running?", not "did you say it is?").
3. **Right model for the right layer.** Expensive reasoning only where it pays; cheap execution everywhere
   else. A cost/latency lever the swarm can't pull.
4. **Compact, machine-primary artifacts.** State and handoffs are terse and structured, not prose.

## The anchor — a state-grounded RAG, as an MCP

Not a vector-RAG over documents. A **state RAG**: a canonical store written on every change, a **reconciler**
that keeps it ≡ reality (drift/orphan detection), and an *onboard* step that injects the current state into
the model's context. The discipline: **recall is not canon — verify against state.**

Exposed over the Model Context Protocol so *any* agent can plug in:

| tool | does |
|---|---|
| `state_onboard()` | the whole current picture in one call (services + status, open drift, rules, last decision) |
| `state_query(domain, filter)` | a narrow slice, on demand |
| `state_verify(claim)` | ★ *don't trust the report — check it against ground truth* → `{holds, actual, evidence}` |
| `state_reconcile(domain)` | model≡reality → the drift / orphan report |

Plus resources (`state://digest`, `state://rules`, `state://handoff`) for clients that inject context up front.

**It's domain-agnostic.** You register your own `StateProvider` (SQLite, JSON, an API — anything) and a
`Reconciler` (how to observe reality for each domain). See [`INTERFACE.md`](./INTERFACE.md).

**It composes.** State RAG is one instrument, not the whole rack: attach it over MCP side-by-side with
your content RAG, your memory server, your other tools. The discipline that keeps the ensemble honest
is **authority ordering** — for *current* truth, reconciled state outranks memory and documents
(details in [`INTERFACE.md`](./INTERFACE.md)).

## Measured, not proclaimed

We refuse to ship a token-savings number we haven't earned. [EXPERIMENT.md](./corpus/microstack/EXPERIMENT.md)
defines a reproducible experiment: the same tasks run **cold** (agent re-explores) vs **onboard** (state injected) vs
**MCP** (state queried), on a small controlled corpus ([`corpus/microstack/`](./corpus/microstack/)), same
model, ≥5 trials, **scored for correctness** (savings that produce a wrong answer are disqualified). The
honest finding is likely a *trade-off* — onboard wins broad tasks, lazy MCP wins narrow ones — and we'll
report it that way, including the case where the difference is small.

## Status (honest)

| piece | state |
|---|---|
| Thesis + method | ✅ in daily use |
| Interface design (v0) | ✅ `INTERFACE.md` |
| Controlled measurement corpus | ✅ `corpus/microstack/` |
| Cold vs onboard measurement (C0/C1) | ✅ direction confirmed (~43% input savings, correctness intact) — token counts estimated, not yet publication-grade |
| MCP server (stdlib-only, enables the query path / C2) | ✅ prototyped — 22/22 checks + end-to-end stdio smoke |
| MCP measurement (C2) | ✅ trade-off characterized (onboard wins broad, lazy query wins narrow, cold always loses; correctness intact) — publication-grade counters still pending (real MCP attach + billed usage) |
| Behavioral finding → interface feedback | ✅ agents default to the broadest tool → cost hints now steer tool choice |
| Second living instance (generic SQLite provider over a real production canon) | ✅ 14/14 structural checks; digest policy born from a real 44k→12k lesson |
| Remote mode (remote state, local server) | ✅ by design at the provider layer — the `ApiStateProvider` example is remote mode; pattern + considerations in `INTERFACE.md`. Remote MCP *transport* = open integration point, not shipped |
| Git/VCS instance | ✅ `GitStateProvider` + reconciler (`--git` flag) — the three drift kinds fall out of `git status`; read-only by subcommand allow-list; 17/17 self-contained checks |
| The two roles as adoptable agent specs | ✅ `agents/reasoner.md` + `agents/executor.md` — the method made installable |
| Realistic corpus + published numbers | ⬜ after validation |

*Legend of honesty: ✅ built and tested · ⬜ declared/roadmap. `METHODOLOGY.md` is practice
documentation (the pattern we run daily), not orchestration code — nothing in this repo pretends to
be what it isn't.*

## Lineage & philosophy

Built on Stafford Beer's **Viable System Model** and the **Cybersyn** project (Chile, 1971) — a system is
viable when it can be *described*, *governed*, and *audited*. "Don't trust, verify" isn't a slogan here;
it's the reconciler and the verify-at-every-boundary discipline made mechanical. Community-first, and
deliberately **from the Global South** — the heir to Cybersyn's bet that good cybernetics serves people.

## Repository layout

```
state-rag-mcp/
├── README.md            ← this file
├── INSTALL.md           ← per-client setup (Claude Code/Desktop, OpenCode, Cursor, Cline, Windsurf)
├── USAGE.md             ← 60-second demo · onboarding your system · provider examples · use cases
├── METHODOLOGY.md       ← the two-agent pattern (the method behind the tool)
├── skills/              ← the disciplines as portable skills (9 · installable in Claude Code)
├── agents/              ← the two roles as adoptable agent specs (reasoner · executor)
├── INTERFACE.md         ← the MCP surface + the provider abstraction
├── mcp_server.py        ← one-file launcher for any MCP client
├── state_rag/           ← the library (stdlib-only): provider · sqlite_provider · git_provider · reconcile · digest · server
├── instances/           ← reference instances (microstack demo · a real SQLite production canon)
└── corpus/microstack/   ← controlled measurement corpus
    ├── raw/             ← what a COLD agent faces (must synthesize)
    ├── synthesized/     ← the reconciled state (the RAG's product)
    ├── EXPERIMENT.md    ← the measurement design (public arm)
    ├── GROUND_TRUTH.md  ← scoring key
    └── TASKS.md         ← the 2 fixed tasks + conditions
```

## License

Code: **Apache-2.0** ([LICENSE](./LICENSE)) · Docs: **CC-BY-4.0**.

This module is deliberately more permissive than the AGPL core it was extracted from — it is meant
to be adopted, embedded, and improved by the community. Improvements can flow back; the module stays
clean of AGPL code by construction.
