---
name: verify-live-not-report
description: Use when an agent (or a human) reports completed state-changing work — a deploy, a fix, a migration. Verify the claim against the live system before accepting it; never mark work done from the report alone.
---

# Verify live, not the report

## The rule
When anyone — an agent, a script, a person — reports that state-changing work is done, check the
**live system**, not the report. Reports describe intentions; systems describe reality.

## How
1. Identify the *claims* in the report: "deployed", "running", "fixed", "verified".
2. For each claim, find the live observable that would prove it:
   - deployed → the running binary's hash matches the built artifact
   - running → the process exists NOW (`is-active`, PID, recent log lines with fresh timestamps)
   - fixed → the failing symptom is absent in a fresh check, not in your transcript
3. Check them yourself, through a channel independent of whoever made the claim. With state-canon attached,
   `state_verify(domain, filter, expect)` is this step made mechanical.
4. Also check for **side effects**: did the change break something adjacent the report doesn't mention?
5. Only then mark it done — and record *what you verified*, not just "verified".

## The scar
An agent reported a fix "complete and verified." The target symptom was indeed gone — but the
live check showed the redeploy had resurrected a *different* failure class the report never
mentioned. Found only because the reviewer checked the system, not the transcript.

And the reverse scar, which keeps this honest: a reviewer declared a fix "algorithmically
incomplete" from analysis alone — the live check showed the fix was correct and had simply **never
been deployed** (a stale build). Verification runs in both directions; nobody's claims are exempt,
including the reviewer's.

## Anti-patterns
- "The test suite is green" as proof of *runtime* behavior (suites test what they test).
- Accepting "it says deployed" — check the binary hash on the target, not the deploy log.
- Verifying once and caching the belief forever — systems drift; re-verify at decision points.
