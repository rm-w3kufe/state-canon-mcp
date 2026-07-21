---
name: confirm-first
description: Use when handing a defect or incident to an executor, or when tempted to patch on hypothesis. Structure the work as diagnosis-first with an explicit STOP before any fix is implemented.
---

# Confirm first

## The rule
Diagnose before patching. The task structure is always: **(0) reproduce and narrow → report and
STOP → (1) design reviewed → (2) implement**. Never ship a fix for a mechanism you haven't
confirmed is the one that fired.

## How
1. Phase 0 is **read-only**: reproduce the failure, narrow to the exact mechanism, gather evidence
   (logs, kernel state, a failing input). No code changes in this phase.
2. The executor reports findings and **stops**. The instruction literally ends with "report and
   STOP — do not patch yet."
3. The reviewer confirms the mechanism (or sends phase 0 back), then the fix is designed against
   the *confirmed* mechanism only.
4. Multiple plausible mechanisms? Confirm which one actually fired before touching any of them.

## The scar
A fleet-wide hang was diagnosed from code reading: **three** plausible failure mechanisms in the
client library, all real defects. The kernel-level evidence (what the frozen process was actually
blocked on, same PID, no restart logs) showed only *one* had fired. Patching all three blind would
have shipped twice the untested complexity to ~98 processes — and the extra "fixes" would have
masked whether the real one worked.

## Anti-patterns
- "While I'm in there" fixes bundled into a diagnosis.
- Patching the first plausible cause found ("plausible" is not "confirmed").
- Skipping phase 0 because the fix "is obvious" — the obvious fix for the wrong mechanism is how
  regressions are born.
