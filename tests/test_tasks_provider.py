"""Tests for the VSM task-file provider (instances/tasks_provider.py).

stdlib-only — no pytest dependency. Run:
    python3 tests/test_tasks_provider.py   (from state-canon-mcp/)
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "instances"))

PASSED = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASSED
    if not cond:
        print(f"✗ FAIL {name} {detail}")
        sys.exit(1)
    PASSED += 1
    print(f"✓ {name}")


# ── Fixture: a minimal realistic VSM file ──────────────────────────────

FIXTURE_VSM = """@vsm 1.0
// Test fixture — known open + resolved tasks

task("ALPHA-DONE", priority=P1, agent=ds, status=done) = {
  what: "was done, status is done",
  gate: "none",
}

task("BETA-OPEN", priority=P2, agent=ds, status=open) = {
  what: "still open, never resolved",
  gate: "must pass",
}

task("GAMMA-STALE", priority=P1, agent=[S], status=open) = {
  what: "status says open but session says resolved",
  gate: "something",
}

task("DELTA-DISPATCHED", priority=P3, agent=bbh, status=dispatched) = {
  what: "dispatched but session says resolved",
}

// Old-style task (legacy notation)
task(EPSILON-CLOSED): status=done what="old-style done"

// Open with old-style notation
task(ZETA-STALE): status=open what="old-style open but resolved in later session"

// Another open task not referenced anywhere
task(ETA-PENDING):
  status = open
  what = "pending, no session references"

task("THETA-SEEDED", priority=P2, agent=ds, status=seeded) = {
  what: "seeded task, should also be caught if resolved",
}

session("2026-07-20") = {
  summary: "first session — nothing resolved yet",
  result:  pass,
  resolved: [],
  commits: ["abc123 (first commit)"],
}

session("2026-07-21") = {
  summary: "second session — resolves GAMMA and DELTA",
  result:  pass,
  resolved: [
    "GAMMA-STALE — verified done and dusted",
    "DELTA-DISPATCHED — completed and tested",
  ],
  commits: ["def456 (gamma done)", "ghi789 (delta done)"],
}

session("2026-07-22") = {
  summary: "resolves ZETA-STALE",
  result:  pass,
  resolved: [
    "ZETA-STALE — old-style resolved in session",
  ],
}

session("2026-07-23") = {
  summary: "resolves THETA-SEEDED",
  result:  pass,
  resolved: [
    "THETA-SEEDED — seeded no more",
  ],
}
"""

FIXTURE_FOCUS = """[
  {"ref": "ALPHA-DONE", "status": "done", "note": "completed in july", "started_at": "2026-07-01", "updated_at": "2026-07-20"},
  {"ref": "BETA-OPEN", "status": "active", "note": "working on it", "started_at": "2026-07-15", "updated_at": "2026-07-27"},
  {"ref": "GAMMA-STALE", "status": "done", "note": "was stale, now closed", "started_at": "2026-07-10", "updated_at": "2026-07-21"}
]
"""

# ── Helpers ────────────────────────────────────────────────────────────

_tmpdirs: list[Path] = []


def _tmp() -> Path:
    d = Path(tempfile.mkdtemp())
    _tmpdirs.append(d)
    return d


def _write_vsm(tmp: Path, name: str = "TASKS.vsm",
               content: str = FIXTURE_VSM) -> Path:
    f = tmp / name
    f.write_text(content)
    return f


# ── Parser: basic counts ──────────────────────────────────────────────

tmp1 = _tmp()
f1 = _write_vsm(tmp1)

from instances.tasks_provider import parse_vsm_file
data = parse_vsm_file(f1)

check("parse.task_counts",
      data["meta"]["tasks_count"] == 8,
      f"got {data['meta']['tasks_count']}")
check("parse.session_counts",
      data["meta"]["sessions_count"] == 4,
      f"got {data['meta']['sessions_count']}")
check("parse.meta_lines",
      data["meta"]["lines"] == len(FIXTURE_VSM.splitlines()),
      f"got {data['meta']['lines']}")

tasks = {t["id"]: t for t in data["tasks"]}
sessions = {s["id"]: s for s in data["sessions"]}

# ── Parser: field extraction (new-style) ──────────────────────────────

t = tasks["BETA-OPEN"]
check("parse.fields.new.priority", t["priority"] == "P2", str(t.get("priority")))
check("parse.fields.new.agent", t["agent"] == "ds", str(t.get("agent")))
check("parse.fields.new.status", t["status"] == "open", str(t.get("status")))
check("parse.fields.new.what", "still open" in t.get("what", ""), t.get("what", ""))

# ── Parser: field extraction (old-style) ──────────────────────────────

t = tasks["EPSILON-CLOSED"]
check("parse.fields.old.status", t["status"] == "done", str(t.get("status")))
check("parse.fields.old.what", "old-style done" in t.get("what", ""), t.get("what", ""))

# ── Parser: indented old-style ────────────────────────────────────────

t = tasks["ETA-PENDING"]
check("parse.fields.indented.status", t["status"] == "open", str(t.get("status")))
check("parse.fields.indented.what", "pending" in t.get("what", ""), t.get("what", ""))

# ── Parser: agent list ────────────────────────────────────────────────

t = tasks["GAMMA-STALE"]
check("parse.agent.list_single", t["agent"] == ["S"], str(t.get("agent")))

t = tasks["ALPHA-DONE"]
check("parse.agent.plain_str", t["agent"] == "ds", str(t.get("agent")))

# ── Parser: session resolved/commits lists ────────────────────────────

s1 = sessions["2026-07-20"]
check("parse.session.empty_resolved", s1["resolved"] == [], str(s1.get("resolved")))

s2 = sessions["2026-07-21"]
check("parse.session.resolved_count", len(s2["resolved"]) == 2,
      f"got {len(s2['resolved'])}: {s2['resolved']}")
check("parse.session.resolved_content",
      "GAMMA-STALE — verified done and dusted" in s2["resolved"],
      str(s2["resolved"]))
check("parse.session.commits_count", len(s2["commits"]) == 2,
      f"got {len(s2['commits'])}: {s2['commits']}")
check("parse.session.commits_content",
      "def456 (gamma done)" in s2["commits"][0],
      str(s2["commits"]))

del tasks, sessions, t, data

# ── Reconciler: stale tasks caught ────────────────────────────────────

tmp2 = _tmp()
f2 = _write_vsm(tmp2)

from instances.tasks_provider import TaskSessionReconciler
rec = TaskSessionReconciler(f2)
drifts = rec.diff()
drift_by_subject = {d.subject: d for d in drifts}

check("reconciler.gamma_stale_present",
      "GAMMA-STALE" in drift_by_subject,
      f"drift subjects: {list(drift_by_subject.keys())}")
gs = drift_by_subject["GAMMA-STALE"]
check("reconciler.gamma_stale_kind",
      gs.kind == "declared_but_resolved",
      f"kind: {gs.kind}")

check("reconciler.delta_present",
      "DELTA-DISPATCHED" in drift_by_subject,
      f"drift subjects: {list(drift_by_subject.keys())}")
check("reconciler.zeta_present",
      "ZETA-STALE" in drift_by_subject,
      f"drift subjects: {list(drift_by_subject.keys())}")
check("reconciler.theta_present",
      "THETA-SEEDED" in drift_by_subject,
      f"drift subjects: {list(drift_by_subject.keys())}")
check("reconciler.total_4", len(drifts) == 4, f"got {len(drifts)} drifts")

# ── Reconciler: done tasks not flagged ────────────────────────────────

check("reconciler.alpha_done_not_flagged",
      "ALPHA-DONE" not in drift_by_subject,
      f"drift subjects: {list(drift_by_subject.keys())}")
check("reconciler.epsilon_done_not_flagged",
      "EPSILON-CLOSED" not in drift_by_subject,
      f"drift subjects: {list(drift_by_subject.keys())}")

# ── Reconciler: open but unreferenced left alone ──────────────────────

check("reconciler.beta_open_not_flagged",
      "BETA-OPEN" not in drift_by_subject,
      f"drift subjects: {list(drift_by_subject.keys())}")
check("reconciler.eta_pending_not_flagged",
      "ETA-PENDING" not in drift_by_subject,
      f"drift subjects: {list(drift_by_subject.keys())}")

# ── Reconciler: drift evidence richness ───────────────────────────────

ev = gs.evidence
check("reconciler.evidence.task_status",
      ev["task"]["status"] == "open",
      str(ev.get("task")))
check("reconciler.evidence.resolved_in",
      "2026-07-21" in ev["resolved_in"],
      str(ev.get("resolved_in")))
check("reconciler.evidence.detail",
      "GAMMA-STALE" in gs.detail and "open" in gs.detail,
      gs.detail)

del drifts, rec, drift_by_subject, gs

# ── Focus: co-located auto-load ───────────────────────────────────────

tmp3 = _tmp()
_write_vsm(tmp3)
(tmp3 / "current_focus.json").write_text(FIXTURE_FOCUS)

from instances.tasks_provider import load
provider, reconcilers = load(tmp3)

domains = provider.list_domains()
check("focus.domains.has_focus", "focus" in domains, str(domains))
check("focus.domains.has_tasks", "tasks" in domains, str(domains))
check("focus.domains.has_sessions", "sessions" in domains, str(domains))

focus_items = provider.query("focus")
check("focus.items_count", len(focus_items) == 3, f"got {len(focus_items)}")
check("focus.item0_ref", focus_items[0]["ref"] == "ALPHA-DONE",
      str(focus_items[0].get("ref")))

del provider, reconcilers, focus_items

# ── Focus: no focus file graceful ─────────────────────────────────────

tmp4 = _tmp()
_write_vsm(tmp4)

provider, reconcilers = load(tmp4)
domains = provider.list_domains()
check("focus.no_file.focus_absent", "focus" not in domains, str(domains))
check("focus.no_file.tasks_present", "tasks" in domains, str(domains))

del provider, reconcilers

# ── Focus: load by file path (not directory) ──────────────────────────

tmp5 = _tmp()
f5 = _write_vsm(tmp5, name="tasks.vsm")
provider, reconcilers = load(f5)
check("focus.load_by_vsm_path", "tasks" in provider.list_domains(),
      str(provider.list_domains()))

del provider, reconcilers

# ── Cleanup ───────────────────────────────────────────────────────────

for d in _tmpdirs:
    shutil.rmtree(str(d), ignore_errors=True)

print(f"\nALL {PASSED} CHECKS PASSED")
