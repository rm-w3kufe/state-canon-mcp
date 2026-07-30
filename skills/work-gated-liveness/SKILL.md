---
name: work-gated-liveness
description: Use when implementing or reviewing any liveness signal — a watchdog heartbeat, a health endpoint, a "still alive" log. The signal must be gated on real verified work, never emitted from a bare timer.
---

# Work-gated liveness

## The rule
A liveness signal emitted from a timer loop **independent of the work** is theater: it reports
healthy while the actual work is dead. The heartbeat must come from the work path, after a
verified successful operation.

Related but distinct from **loud-death**: this skill is about how a service *signals it's alive*
(gate the heartbeat on real work); loud-death is about how a service *dies* (exit loudly, and only
on real failure). The same "quiet zombie" scar shows up in both because they're two halves of one
failure mode — a process that's up but not working needs BOTH a heartbeat that stops (this skill)
and, if it can detect its own failure, a loud exit (loud-death) — neither alone is the full fix.

## How
- **Producers / tickers:** heartbeat *after* a successful work cycle (publish confirmed, batch
  committed). Work failed → no heartbeat.
- **Message-driven services** (sparse input, can't gate on arrival): gate on an **active health
  probe** — a bounded round-trip against the dependency (`connected + flush() within timeout`).
  Probe fails → withhold the heartbeat → the supervisor restarts.
- **Config coupling:** supervisor timeout ≥ 2–3× the heartbeat/probe interval, explicit in both
  places — otherwise a *healthy but quiet* service gets killed.
- **The decisive test** (non-negotiable): run under the real supervisor, kill the dependency,
  assert the supervisor **restarts the process**. A green unit suite is not this test.

## The scar
A watchdog heartbeat ran on its own 5-second timer, in a task separate from the work. The chaos
suite passed **11/11** — and the watchdog was still theater: with a silently dead subscription
(the exact incident it was built to prevent, a service frozen for 10 hours), the work would stop
but the timer would keep beating. The supervisor would never have fired. Caught in review by asking
one question: *"if the real work silently dies but the process keeps looping, does this heartbeat
stop?"* Second scar, same feature: the corrected probe used a no-op await that returned in
microseconds instead of waiting 30s — a busy-loop that, multiplied by the fleet, would have *caused*
the broker storm it guarded against. Empirical check of the wait, not the intention, caught it.

## Anti-patterns
- `while true: sleep(n); heartbeat()` anywhere near the word "watchdog".
- Health endpoints that return 200 because the *web server* is up, saying nothing about the work.
- Testing the helper in isolation and never the supervisor loop end-to-end.
