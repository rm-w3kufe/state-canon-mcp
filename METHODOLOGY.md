# The Two-Agent Pattern

> The industry bet: more agents = better work. Our bet: **two agents + verified state + disciplined
> boundaries** produce more careful work than a swarm — at a fraction of the token cost. This document
> is the pattern we actually run every day, including the failures that shaped it.

## The roles

| Role | Runs on | Does | Never does |
|---|---|---|---|
| **Reasoner** | an advanced model | architecture, design, review, root-cause analysis, verification | routine execution (waste of an expensive model) |
| **Executor** | a cost-efficient model | builds, deploys, runs tests, reports | design decisions, irreversible actions without a checkpoint |
| **Human** | — | policy, priorities, approval of irreversible / outward-facing changes | micromanaging either agent |

In VSM terms (the lineage behind this): the executor is **S1** (operations), the reasoner is **S3/S4**
(control + intelligence), the human is **S5** (policy). The point is not the labels — it's that the
three never collapse into one undifferentiated "agent doing everything," and *neither role trusts the
other's claims without verification*.

## Where quality is actually made: the boundaries

The swarm assumption is that quality comes from adding workers. In practice, quality is made (or
lost) at four boundaries:

**1. Framed handoffs.** Every task crosses the reasoner→executor boundary as a *framed prompt*: a
delimited, self-contained block with context, exact scope, ordered steps, what NOT to touch, and an
explicit stop-point. No ambient context, no "you know what I mean."

**2. Verify live, never trust the report.** When the executor reports "deployed and verified," the
reasoner checks the *live system* — the running process, the actual binary hash, the real log — not
the report. This is not distrust of the executor; it is the design assumption that **any** single
observer (human or model) can be wrong about its own work.

**3. Confirm-first checkpoints.** Diagnosis before patching ("PASO 0"), pilot before fleet, one
service before 98. The executor's instructions end with *"report and STOP"* at every point where the
blast radius is about to grow.

**4. Verification runs in both directions.** The reasoner reviews the executor — and the executor
corrects the reasoner. In our logs: the reasoner once diagnosed a fix as "algorithmically incomplete";
the executor proved the fix was correct all along — it had simply never been deployed (a stale build).
The reasoner also once prescribed a library parameter that didn't exist in the deployed version; the
executor caught it and designed a version-safe equivalent. A pattern where correction only flows one
way is theater.

## Who holds the pen: write-coherence

There is a fifth boundary, easy to miss because it isn't between the agents — it's between the
humans and the system.

The only way the system stays coherent across read and write runs is that **the system's managed
surfaces are written by the system**. The agent executes the changes and maintains the order; the
reconciler keeps the record ≡ reality. A human hand-edit to a managed surface — a state row, a
generated index, a tracked manifest — is **drift by definition**: a write the reconciler didn't see,
that the next read will faithfully repeat as truth.

This does *not* remove the human. It splits two things that are usually conflated:

- **Decisions flow through the human** — policy, priorities, approval of anything irreversible.
- **Writes flow through the system** — the human contributes *inputs* through declared channels
  (an agreed inbox directory, a task queue, a review verdict), and the agent turns them into
  reconciled state.

And yes — this includes **information architecture itself**. Folder taxonomies, documentation
indexes, "where things go": these are not a separate layer, they are just another domain under the
same primitive — a *declared* order (the index, the taxonomy) vs an *observed* reality (the actual
tree), with drift computed between them. In our own system the documentation index is
reconciler-controlled: editing it by hand is forbidden, not by etiquette but because a hand-edited
index is a lie the next agent will trust. If you can declare it and observe it, you can reconcile
it — files and folders included.

## The loop

```mermaid
flowchart LR
    D[Reasoner:\ndesign + spec] --> F[Framed prompt\nwith stop-points]
    F --> E[Executor:\nbuild / deploy / test]
    E --> R[Report]
    R --> V{Reasoner:\nverify LIVE\nnot the report}
    V -- defect found --> C[Review finding\nwritten to canon] --> F
    V -- verified --> G{Blast radius\ngate}
    G -- pilot passes --> N[Next stage\nwider rollout]
    G -- human approval\nneeded --> H[Human decides]
```

Two properties matter. The loop **converges** — each round either verifies or produces a written
finding that narrows the next round. And it **fails small** — defects are caught at the pilot stage,
where the cost of being wrong is one service, not the fleet.

## Case study: four rounds to a fleet-safe fix

Real sequence, condensed from our logs. Context: a fleet of ~98 telemetry processes shared a defect
(clients hanging silently on broker disruption — a real 54-minute outage). The fix had to be right
before touching the fleet.

| Round | Executor delivered | Independent verification found | Outcome |
|---|---|---|---|
| 1 | 3-layer resilience fix, chaos suite 11/11 green | the watchdog heartbeat ran on a timer *independent of the work* — a dead subscription would never trip it. **A green suite ≠ a working watchdog** | heartbeat re-gated on real work; decisive test added |
| 2 | work-gated watchdog, systemd test passes | the new health probe was a **busy-loop** (a no-op await returning in µs, not 30s) — confirmed empirically; ×98 it would have *caused* the very broker storm it guarded against | real interruptible wait; probe/watchdog ratio made explicit |
| 3 | pilot deployed | service stuck in `activating` forever: initial-connect retry looped without ever signaling readiness | two-phase connect (time-bounded attempts, then READY + background retry) |
| 4 | — | **reversal:** the reasoner's prescribed fix used a parameter absent from the deployed library version; the executor caught it and shipped a version-safe design | version-independent fix, verified live |

Four defects, all real, all caught **before** the fleet — each one found not by adding more agents,
but by refusing to accept an unverified claim. The pilot then ran a 24-hour observation window before
any wider rollout.

## Why this also saves tokens

The swarm burns tokens on re-derivation and coordination. This pattern attacks both:

- **Grounded state, not re-exploration** — the [State RAG](./README.md) puts reconciled ground truth
  in the agent's path (measured on a controlled corpus: a cold agent re-deriving state is always the
  most expensive condition; see [RESULTS](./corpus/microstack/RESULTS.md), including honest caveats).
- **Model tiering** — the expensive model only reasons; the cheap model only executes.
- **Compact machine-primary artifacts** — state, specs and handoffs are terse structured text, not prose.
- **Verification by query, not by re-reading** — "is this still true?" is one `state_verify` call.

## The disciplines (each one paid for by a real scar)

*Each is packaged as a portable, installable skill in [`skills/`](./skills/) — the rule, the scar,
and the anti-patterns, ready to drop into an agent's context.*

- **Verify live, not the report** — reports describe intentions; systems describe reality.
- **Confirm-first** — diagnose before patching; narrow before fixing.
- **Work-gated liveness** — a heartbeat decoupled from real work is theater (round 1 above).
- **Blast-radius gating** — one pilot before 98; a window of observation before "done."
- **Loud death** — services die noisily or not at all; silence is never health.
- **Fix the source, keep the detector** — never widen a threshold to quiet an alarm.
- **Logical gates, not time estimates** — "after X passes" beats "in about two hours." LLMs are
  reliably bad at duration; they are good at preconditions.
- **Framed prompts** — the handoff is a contract, not a conversation.
- **The system holds the pen** — managed surfaces (state, indexes, taxonomies) are written by the
  system, never hand-edited; humans contribute through declared input channels.

## Where this pattern does NOT fit (honest limits)

- **Massively parallel, independent subtasks** (crawl 500 pages, translate 200 files): a worker pool
  is simply right. The pattern governs *coupled, stateful, high-consequence* work.
- **No verifiable ground truth**: the pattern leans on a canonical state to verify against. Pure
  creative work has no `state_verify`.
- **Hard real-time**: verification adds latency by design. Reflex paths belong in deterministic code,
  not in any LLM loop (our rule D6/R10 — the LLM never sits on the safety-critical path).
- The token numbers we publish are **relative and corpus-bound** so far; treat them as direction, not
  gospel, until the publication-grade run ships.

## Lineage

This is Stafford Beer's Viable System Model made operational for agent teams — Cybersyn's bet
(Chile, 1971) that a *system with the right feedback structure* beats a bigger system without one.
Requisite variety is engineered into the boundaries (framing, verification, gating), not bought with
more agents.
