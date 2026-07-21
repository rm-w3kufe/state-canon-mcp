---
name: blast-radius-gating
description: Use when a change is about to widen its reach — from one service to a fleet, from a sandbox to production, from reversible to hard-to-reverse. Gate every widening on verified evidence from the smaller stage.
---

# Blast-radius gating

## The rule
Never widen the blast radius on an unverified claim. One pilot before the fleet; an observation
window before "done"; each widening gated on evidence from the stage before — not on confidence.

## How
1. Order the rollout by blast radius: sandbox → one pilot (least critical instance) → small tier →
   fleet. Write the order down *before* starting.
2. Define the **acceptance criteria of each stage in observables** (e.g. "no supervisor restarts
   over the window, memory flat, dependency blip survived") — not in vibes.
3. Hold an **observation window** at the pilot stage sized to the failure modes you fear (a
   slow leak needs hours, not minutes).
4. Only the reviewer widens the gate, and only against verified stage evidence.
5. Rolling out to N instances at once? Stagger it — N simultaneous reconnections/restarts can
   *become* the incident.

## The scar
A resilience fix, chaos-tested and review-corrected twice, went to a single pilot service instead
of the ~98-process fleet. The pilot promptly stuck in `activating` forever — a config+library-version
bug none of the tests had surfaced. Cost: one non-critical service, one evening. Fleet-wide it would
have frozen every node *simultaneously* — a second outage, self-inflicted by the fix for the first
one. The pilot then ran a 24-hour window before any widening; that window is what "done" meant.

## Anti-patterns
- "The tests pass, roll it everywhere."
- Pilots on the most critical instance ("to really test it") — the pilot's job is to fail cheaply.
- Declaring success at deploy time instead of after the window.
- Big-bang restarts of a whole fleet (thundering herd is a failure mode of its own).
