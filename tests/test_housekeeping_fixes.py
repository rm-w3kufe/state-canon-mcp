"""Regression tests for the 2026-07-30 housekeeping round (external review findings).

Each check below corresponds 1:1 to a finding in vsf/TASKS.vsm
(STATE-CANON-VERIFY-BYPASSES-RECONCILER-FINDING, STATE-CANON-EXTERNAL-REVIEW-FINDINGS):

  1. state_verify/state_query bypass the Reconciler -> mismatch warning
  2. reconcile.py silently drops duplicate declared()/observe() keys -> duplicate_key Drift
  3. focus.py mark() has a lost-update race under concurrent writers -> flock
  4. JsonStateProvider: unknown-filter behavior diverges from SqliteStateProvider; never reloads
  5. digest.py's silent "?" fallback for unconventional records
  6. journal.py no longer hardcodes a BBH-shaped findings/rag_feedback schema

Run:  python3 tests/test_housekeeping_fixes.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from state_canon.digest import _fmt_record  # noqa: E402
from state_canon.focus import FocusTracker  # noqa: E402
from state_canon.journal import StateJournal  # noqa: E402
from state_canon.provider import JsonStateProvider  # noqa: E402
from state_canon.reconcile import Reconciler  # noqa: E402
from state_canon.server import StateRagServer  # noqa: E402

PASSED = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASSED
    if not cond:
        print(f"✗ FAIL {name} {detail}")
        sys.exit(1)
    PASSED += 1
    print(f"✓ {name}")


# ══════════════════════════════════════════════════════════════════
# 1. state_verify / Reconciler mismatch warning
# ══════════════════════════════════════════════════════════════════

class _FixedReconciler(Reconciler):
    domain = "services"

    def __init__(self, observed):
        self._observed = observed

    def declared(self):
        return []

    def observe(self):
        return self._observed


class _FixedProvider:
    def __init__(self, records):
        self._records = records

    def list_domains(self):
        return ["services", "meta"]

    def query(self, domain, filter=None):
        if domain == "meta":
            return [{}]
        return self._records

    def schema(self, domain):
        return {}


# provider wired to DECLARED/config vocabulary ("active"), reconciler observes REALITY ("running")
mismatched = StateRagServer(
    _FixedProvider([{"name": "cache", "state": "active"}]),
    [_FixedReconciler([{"name": "cache", "state": "running"}])],
)
v = mismatched.state_verify("services", {"state": "running"}, {"name": "cache"})
check("verify.mismatch_warning_present", "warning" in v, str(v))
check("verify.mismatch_warning_names_domain", "services" in v.get("warning", ""), str(v))

# provider correctly represents the reconciled canon -> no warning
matched = StateRagServer(
    _FixedProvider([{"name": "cache", "state": "running"}]),
    [_FixedReconciler([{"name": "cache", "state": "running"}])],
)
v2 = matched.state_verify("services", {"state": "running"}, {"name": "cache"})
check("verify.no_warning_when_consistent", "warning" not in v2, str(v2))

# domain with no registered reconciler -> no warning (nothing to cross-check against)
no_rec = StateRagServer(_FixedProvider([{"name": "cache", "state": "active"}]), [])
v3 = no_rec.state_verify("services", {"state": "active"}, {"name": "cache"})
check("verify.no_warning_without_reconciler", "warning" not in v3, str(v3))


# ══════════════════════════════════════════════════════════════════
# 2. reconcile.py duplicate-key Drift
# ══════════════════════════════════════════════════════════════════

class _DupReconciler(Reconciler):
    domain = "services"

    def declared(self):
        return [{"name": "cache", "state": "active"}, {"name": "cache", "state": "active"}]

    def observe(self):
        return [{"name": "cache", "state": "running"}]


dup_drifts = _DupReconciler().diff()
dup_kinds = {(d.kind, d.subject) for d in dup_drifts}
check("reconcile.duplicate_key_flagged", ("duplicate_key", "cache") in dup_kinds, str(dup_kinds))


# ══════════════════════════════════════════════════════════════════
# 3. focus.py lost-update race (threaded stress test)
# ══════════════════════════════════════════════════════════════════

with tempfile.TemporaryDirectory() as tmp:
    focus_path = Path(tmp) / "current_focus.json"
    tracker = FocusTracker(focus_path)
    N = 40
    barrier = threading.Barrier(N)

    def _writer(i: int) -> None:
        barrier.wait()  # maximize concurrent overlap
        tracker.mark(f"REF-{i}", status="active", note=f"writer {i}")

    threads = [threading.Thread(target=_writer, args=(i,)) for i in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    entries = tracker.query()
    check("focus.no_lost_updates", len(entries) == N, f"expected {N}, got {len(entries)}")
    check("focus.all_refs_present",
          {e["ref"] for e in entries} == {f"REF-{i}" for i in range(N)},
          str(sorted(e["ref"] for e in entries)))


# ══════════════════════════════════════════════════════════════════
# 4. JsonStateProvider: unknown-filter raise + mtime reload
# ══════════════════════════════════════════════════════════════════

with tempfile.TemporaryDirectory() as tmp:
    state_path = Path(tmp) / "state.json"
    state_path.write_text(json.dumps({"services": [{"name": "cache", "state": "running"}]}))
    jp = JsonStateProvider(state_path)

    check("provider.query_known_filter_ok", len(jp.query("services", {"name": "cache"})) == 1)
    try:
        jp.query("services", {"nope": "x"})
        check("provider.unknown_filter_raises", False, "expected ValueError, none raised")
    except ValueError as e:
        check("provider.unknown_filter_raises", "nope" in str(e), str(e))

    check("provider.empty_domain_no_raise", jp.query("nonexistent_domain", {"anything": 1}) == [])

    # mtime reload: mutate the file on disk, bump mtime, requery
    time.sleep(0.01)
    state_path.write_text(json.dumps({"services": [{"name": "cache", "state": "stopped"},
                                                     {"name": "api", "state": "running"}]}))
    new_mtime = time.time() + 1
    import os
    os.utime(state_path, (new_mtime, new_mtime))
    reloaded = jp.query("services")
    check("provider.reloads_on_mtime_change", len(reloaded) == 2, str(reloaded))
    check("provider.reload_sees_new_data",
          any(r["name"] == "api" for r in reloaded), str(reloaded))

    # __new__-bypass pattern (tasks_provider.py style) must NOT crash and must
    # NOT attempt to re-json.loads() a non-JSON-shaped source.
    bypassed = JsonStateProvider.__new__(JsonStateProvider)
    bypassed.path = state_path
    bypassed._doc = {"services": [{"name": "manually-set", "state": "x"}]}
    check("provider.new_bypass_no_crash", bypassed.query("services") == [{"name": "manually-set", "state": "x"}])
    check("provider.new_bypass_no_reload", bypassed._mtime is None)


# ══════════════════════════════════════════════════════════════════
# 5. digest.py silent "?" fallback
# ══════════════════════════════════════════════════════════════════

check("digest.conventional_field_unchanged", _fmt_record({"name": "cache", "state": "running"}) == "cache [state=running]")
weird = _fmt_record({"foo": "bar", "baz": 3})
check("digest.no_bare_question_mark", weird != "?", weird)
check("digest.fallback_shows_first_field", weird.startswith("foo=bar"), weird)
check("digest.truly_empty_record_still_question_mark", _fmt_record({}) == "?")


# ══════════════════════════════════════════════════════════════════
# 6. journal.py stats_fn / rag_fn injection (no hardcoded BBH schema)
# ══════════════════════════════════════════════════════════════════

check("journal.no_bbh_constant_in_module", not hasattr(
    __import__("state_canon.journal", fromlist=["_BBH_TEST_TARGETS"]), "_BBH_TEST_TARGETS"))

with tempfile.TemporaryDirectory() as tmp:
    jdb = Path(tmp) / "journal.db"

    j_default = StateJournal(jdb)
    jid = j_default.mark(session_id="s1")
    row = j_default.history(limit=1)[0]
    check("journal.default_stats_zero", row["production_findings"] == 0, str(row))

    jdb2 = Path(tmp) / "journal2.db"
    j_injected = StateJournal(
        jdb2,
        stats_fn=lambda: {"production_findings": 7, "by_severity": {"high": 7}, "by_target": {}, "by_status": {}},
        rag_fn=lambda: {"accuracy": 0.9, "total": 10},
    )
    j_injected.mark(session_id="s1")
    row2 = j_injected.history(limit=1)[0]
    check("journal.injected_stats_populate", row2["production_findings"] == 7, str(row2))
    check("journal.injected_rag_populate", row2["rag_accuracy"] == 0.9, str(row2))


print(f"\nALL {PASSED} CHECKS PASSED")
