"""Tests for the VSM task-file provider (instances/tasks_provider.py).

Follows same pattern as test_state_canon.py and test_git_provider.py:
real parse+reconcile over known VSM fixtures.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

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


# ── Tests ──────────────────────────────────────────────────────────────

class TestVsmParser:
    """Core parser correctness — tokenisation, block detection, field extraction."""

    def test_parse_task_counts(self, tmp_path):
        f = tmp_path / "TASKS.vsm"
        f.write_text(FIXTURE_VSM)
        from instances.tasks_provider import parse_vsm_file
        data = parse_vsm_file(f)
        assert data["meta"]["tasks_count"] == 8
        assert data["meta"]["sessions_count"] == 4
        assert data["meta"]["lines"] == len(FIXTURE_VSM.splitlines())

    def test_parse_task_fields_new_style(self, tmp_path):
        f = tmp_path / "TASKS.vsm"
        f.write_text(FIXTURE_VSM)
        from instances.tasks_provider import parse_vsm_file
        data = parse_vsm_file(f)
        tasks = {t["id"]: t for t in data["tasks"]}

        t = tasks["BETA-OPEN"]
        assert t["priority"] == "P2"
        assert t["agent"] == "ds"
        assert t["status"] == "open"
        assert "still open" in t.get("what", "")

    def test_parse_task_fields_old_style(self, tmp_path):
        f = tmp_path / "TASKS.vsm"
        f.write_text(FIXTURE_VSM)
        from instances.tasks_provider import parse_vsm_file
        data = parse_vsm_file(f)
        tasks = {t["id"]: t for t in data["tasks"]}

        t = tasks["EPSILON-CLOSED"]
        assert t["status"] == "done"
        assert "old-style done" in t.get("what", "")

    def test_parse_task_indented_old_style(self, tmp_path):
        f = tmp_path / "TASKS.vsm"
        f.write_text(FIXTURE_VSM)
        from instances.tasks_provider import parse_vsm_file
        data = parse_vsm_file(f)
        tasks = {t["id"]: t for t in data["tasks"]}

        t = tasks["ETA-PENDING"]
        assert t["status"] == "open"
        assert "pending" in t.get("what", "")

    def test_parse_agent_list(self, tmp_path):
        f = tmp_path / "TASKS.vsm"
        f.write_text(FIXTURE_VSM)
        from instances.tasks_provider import parse_vsm_file
        data = parse_vsm_file(f)
        tasks = {t["id"]: t for t in data["tasks"]}

        # [S] single element list
        t = tasks["GAMMA-STALE"]
        assert t["agent"] == ["S"]

        # agent=ds (without brackets) is a plain string
        t = tasks["ALPHA-DONE"]
        assert t["agent"] == "ds"

    def test_parse_session_resolved_list(self, tmp_path):
        f = tmp_path / "TASKS.vsm"
        f.write_text(FIXTURE_VSM)
        from instances.tasks_provider import parse_vsm_file
        data = parse_vsm_file(f)

        ses = {s["id"]: s for s in data["sessions"]}

        # Empty resolved list
        s1 = ses["2026-07-20"]
        assert s1["resolved"] == []

        # Populated resolved list (2 items)
        s2 = ses["2026-07-21"]
        assert len(s2["resolved"]) == 2, f"expected 2, got {s2['resolved']}"
        assert "GAMMA-STALE — verified done and dusted" in s2["resolved"]

        # Commits list (2 items)
        assert len(s2["commits"]) == 2, f"expected 2 commits, got {s2['commits']}"
        assert "def456 (gamma done)" in s2["commits"][0]


class TestTaskSessionReconciler:
    """Reconciler catches open/dispatched/seeded tasks referenced in session resolved:[]."""

    def test_known_stale_detected(self, tmp_path):
        f = tmp_path / "TASKS.vsm"
        f.write_text(FIXTURE_VSM)
        from instances.tasks_provider import TaskSessionReconciler
        rec = TaskSessionReconciler(f)
        drifts = rec.diff()

        drift_by_subject = {d.subject: d for d in drifts}

        # GAMMA-STALE: status=open, resolved in 2026-07-21
        assert "GAMMA-STALE" in drift_by_subject
        assert drift_by_subject["GAMMA-STALE"].kind == "declared_but_resolved"

        # DELTA-DISPATCHED: status=dispatched, resolved in 2026-07-21
        assert "DELTA-DISPATCHED" in drift_by_subject

        # ZETA-STALE: old-style, status=open, resolved in 2026-07-22
        assert "ZETA-STALE" in drift_by_subject

        # THETA-SEEDED: status=seeded, resolved in 2026-07-23
        assert "THETA-SEEDED" in drift_by_subject

        # Total: 4 stale tasks
        assert len(drifts) == 4

    def test_done_tasks_not_flagged(self, tmp_path):
        f = tmp_path / "TASKS.vsm"
        f.write_text(FIXTURE_VSM)
        from instances.tasks_provider import TaskSessionReconciler
        rec = TaskSessionReconciler(f)
        drifts = rec.diff()

        drift_subjects = {d.subject for d in drifts}
        assert "ALPHA-DONE" not in drift_subjects
        assert "EPSILON-CLOSED" not in drift_subjects

    def test_unreferenced_open_left_alone(self, tmp_path):
        f = tmp_path / "TASKS.vsm"
        f.write_text(FIXTURE_VSM)
        from instances.tasks_provider import TaskSessionReconciler
        rec = TaskSessionReconciler(f)
        drifts = rec.diff()

        drift_subjects = {d.subject for d in drifts}
        # BETA-OPEN is open but never referenced in session resolved → should not be flagged
        assert "BETA-OPEN" not in drift_subjects
        # ETA-PENDING is open and never referenced → should not be flagged
        assert "ETA-PENDING" not in drift_subjects


class TestLoadFocus:
    """Co-located focus file loading."""

    def test_focus_loaded_automatically(self, tmp_path):
        f = tmp_path / "TASKS.vsm"
        f.write_text(FIXTURE_VSM)
        focus_f = tmp_path / "current_focus.json"
        focus_f.write_text(FIXTURE_FOCUS)

        from instances.tasks_provider import load
        provider, reconcilers = load(tmp_path)

        domains = provider.list_domains()
        assert "focus" in domains
        assert "tasks" in domains
        assert "sessions" in domains

        focus_items = provider.query("focus")
        assert len(focus_items) == 3
        assert focus_items[0]["ref"] == "ALPHA-DONE"

    def test_no_focus_file_graceful(self, tmp_path):
        f = tmp_path / "TASKS.vsm"
        f.write_text(FIXTURE_VSM)

        from instances.tasks_provider import load
        provider, reconcilers = load(tmp_path)

        domains = provider.list_domains()
        assert "focus" not in domains
        assert "tasks" in domains

    def test_load_by_vsm_file_path(self, tmp_path):
        f = tmp_path / "tasks.vsm"
        f.write_text(FIXTURE_VSM)

        from instances.tasks_provider import load
        provider, reconcilers = load(f)

        assert "tasks" in provider.list_domains()


class TestDriftEvidenceRichness:
    """Drift records carry enough context for diagnosis."""

    def test_drift_has_task_context(self, tmp_path):
        f = tmp_path / "TASKS.vsm"
        f.write_text(FIXTURE_VSM)
        from instances.tasks_provider import TaskSessionReconciler
        rec = TaskSessionReconciler(f)
        drifts = rec.diff()

        gs = [d for d in drifts if d.subject == "GAMMA-STALE"][0]
        # Evidence contains task details
        ev = gs.evidence
        assert "task" in ev
        assert ev["task"]["status"] == "open"
        assert "resolved_in" in ev
        assert "2026-07-21" in ev["resolved_in"]
        # Detail string is descriptive
        assert "GAMMA-STALE" in gs.detail
        assert "open" in gs.detail
