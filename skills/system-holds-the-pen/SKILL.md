---
name: system-holds-the-pen
description: Use when deciding who writes a managed surface — a state store, a generated index, a tracked manifest, a folder taxonomy. The system writes it via reconciled process; humans contribute through declared input channels, never by hand-editing.
---

# The system holds the pen

## The rule
Managed surfaces are written **by the system**, never hand-edited. A human edit to a managed
surface — a state row, a generated index, a tracked manifest — is **drift by definition**: a write
the reconciler didn't see, that the next read will faithfully repeat as truth. Decisions flow
through the human; *writes* flow through the system.

## How
1. Name your **managed surfaces**: what is authoritative and machine-maintained (the state store,
   the doc index, the topology, the taxonomy).
2. For each, the only writer is a reconciled process (a generator, a populate step, an agent action
   the reconciler observes). Hand-editing them is forbidden — mechanically if possible (a check that
   fails on manual diffs), by rule otherwise.
3. Humans contribute through **declared input channels**: an agreed inbox directory, a task queue,
   a review verdict, a request the agent turns into reconciled state. The human's leverage is
   *decisions and inputs*, not the pen.
4. This includes **information architecture itself** — folder taxonomies and doc indexes are just
   another domain: a *declared* order vs an *observed* tree, with drift between them. If you can
   declare it and observe it, you can reconcile it — files and folders included.

## The scar
A documentation index was hand-edited "just this once" to add an entry — and the next agent trusted
the index over the tree, propagating a taxonomy that no longer matched reality. The lie wasn't
malicious; it was a write the reconciler never saw. Making the index reconciler-controlled (edits
rejected, regenerated from the observed tree) removed the whole class: the index cannot disagree
with reality because reality writes it.

## Anti-patterns
- "I'll just fix that state row by hand real quick."
- A generated file with manual edits on top (the next regen either destroys them or inherits the drift).
- Treating folder structure as beneath governance — it's the map everyone navigates by.
- A human and the system both writing the same surface through different doors.
