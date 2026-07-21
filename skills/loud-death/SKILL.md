---
name: loud-death
description: Use when designing service failure behavior or reviewing an incident where something died quietly. Services must die noisily or not at all — and alarms must never fire on clean shutdowns.
---

# Loud death

## The rule
Silence is never health. A service that cannot continue must **exit loudly** (so the supervisor
restarts it and the death is recorded) — never linger as a zombie that looks alive. And the
complement: a death-alarm that fires on *clean* shutdowns trains everyone to ignore it.

## How
- On unrecoverable state: log CRITICAL with the reason, then exit nonzero. Let the supervisor
  restart. Never swallow the fatal and keep looping idle.
- Wire a **death notification** (an on-failure hook, a "wail") so an unexpected death reaches a
  human channel, not just the journal.
- **Gate the wail on unexpected death only**: a clean stop (deploy, operator restart) must be
  silent. Check the exit condition (`SERVICE_RESULT`/equivalent) before crying.
- Intentional-shutdown paths (drain/close) must be distinguishable from failure paths in code —
  a shared close-handler that always fires the loud path will kill you on every deploy.
- Watch for the **quiet-idle zombie**: a process "active" for weeks doing nothing is a death
  nobody declared. Liveness = recent *work*, not process existence (see work-gated-liveness).

## The scar
A message-board service ran for **two months** polling an empty channel — process up, zero work,
zero complaints. Nobody noticed it was dead because it never said so; the system had organically
migrated elsewhere. And the mirror scar: a death-wail that fired on every *clean* restart — within
days it was mental noise, and a real crash would have worn the same face. The fix was one guard:
`if clean-shutdown → silent`.

## Anti-patterns
- `except: pass` around the main loop (the immortal zombie).
- Alerts wired to process-exists instead of work-happens.
- One close-handler for both graceful and fatal paths.
- Treating a full journal of CRITICALs nobody reads as "we have logging".
