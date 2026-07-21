---
name: logical-gates-not-time-estimates
description: Use when planning multi-step or multi-agent work and any step is about to be scheduled by a duration guess ("this should take ~2 hours"). Sequence by verifiable preconditions instead.
---

# Logical gates, not time estimates

## The rule
LLMs (and humans) are systematically bad at estimating durations — and a plan keyed on durations
fails silently when the estimate is wrong. Sequence work by **preconditions**: *"start Y after X
is verified"*, never *"start Y in about two hours"*. Gates are checkable; estimates are vibes.

## How
1. For every step, write its **entry gate** as an observable condition:
   - not "wait ~24h" → but "after the observation window closes at `<timestamp>` with zero
     supervisor restarts"
   - not "when the build is probably done" → but "when the artifact hash exists on the target"
2. Express plans as IF/THEN chains: `IF pilot passes (a)+(b) THEN widen to tier 2`.
3. Duration shows up only where an external anchor defines it (a fixed window end, a cron), and
   then as a **timestamp**, not an estimate.
4. When a gate can't be expressed as an observable, that's the signal the step is underspecified —
   fix the step, don't paper it with a guess.

## The scar
Repeated planning rounds keyed on "this will take N hours" collapsed the same way every time: the
estimate was wrong, dependent steps started against unfinished prerequisites, and nobody could say
*what state the plan was in* — because the plan's clock was imaginary. Rewritten as condition
gates ("after X passes", "once hash matches", "when the window closes"), handoffs became
deterministic: at any moment, each gate is simply open or closed, checkable by anyone.

## Anti-patterns
- Gantt-style agent plans ("hour 1: ..., hour 2: ...").
- "Should be done by now" as a trigger for the next step.
- Polling every few seconds because no completion condition was defined.
- Estimating in the plan what could be *observed* at run time.
