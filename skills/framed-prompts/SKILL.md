---
name: framed-prompts
description: Use when a reasoning agent (or human lead) hands a task to an execution agent. Package the handoff as a delimited, self-contained contract with scope, steps, exclusions, and an explicit stop-point.
---

# Framed prompts

## The rule
The handoff between agents is a **contract, not a conversation**. Every task crosses the boundary
as a delimited, self-contained block: context, exact scope, ordered steps, what NOT to touch, and
an explicit stop-point. No ambient context, no "you know what I mean."

## How
A framed prompt has, every time:
1. **A visible frame** — a delimiter the recipient can copy verbatim, so the instruction is
   unmistakably separate from surrounding chatter. Nothing outside the frame is instruction.
2. **Context** — the minimum the recipient needs and no session-private assumptions.
3. **Ordered steps** — numbered; if order matters, say "MANDATORY order".
4. **Exclusions** — "do NOT touch X", "do NOT deploy", named explicitly. The exclusions prevent
   more incidents than the steps do.
5. **A stop-point** — "report findings and STOP", or the acceptance criteria that end the task.
6. **A single source of truth reference** — point to the canonical spec, don't inline a copy that
   can drift.

## The scar
The discipline was earned in the small print: an agent deployed to production reading state from
a *report* instead of the *canon*, because the handoff hadn't named the canonical source; a fleet
touched wider than intended because the "do NOT widen yet" wasn't in the frame. Every missing
element above is a specific incident that happened once. The frame is the accumulated scar tissue.

## Anti-patterns
- Instructions dribbled across several chat messages the agent must reassemble.
- "Fix the thing we discussed" — no self-contained scope.
- Omitting the stop-point, so the agent keeps going past the checkpoint.
- Inlining a spec that then drifts from the canonical one (two truths).
