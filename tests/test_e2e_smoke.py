"""End-to-end smoke test — spawns the actual MCP server as a subprocess
with --instance instances/tasks_provider.py and --focus, sends real JSON-RPC
over stdio, asserts sane output without crashes.

This is the test class that would have caught the _load_instance_file()
sys.modules bug (pre-0.6.1: @dataclass crash on import via --instance).

Run:  python3 tests/test_e2e_smoke.py   (from state-canon-mcp/)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PASSED = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASSED
    if not cond:
        print(f"✗ FAIL {name} {detail}")
        sys.exit(1)
    PASSED += 1
    print(f"✓ {name}")


# ── Fixture ──────────────────────────────────────────────────────────

FIXTURE_VSM = """@vsm 1.0
// E2E smoke test fixture

task("DONE-TASK", priority=P1, agent=ds, status=done) = {
  what: "already done",
}

task("OPEN-TASK", priority=P2, agent=ds, status=open) = {
  what: "still in progress",
}

task("RESOLVED-TASK", priority=P1, agent=ds, status=open) = {
  what: "open but resolved in session",
}

session("2026-07-27") = {
  summary: "test session",
  result:  pass,
  resolved: [
    "RESOLVED-TASK — resolved via e2e",
  ],
  commits: ["abc123 (e2e test)"],
}
"""

FIXTURE_FOCUS = """[
  {"ref": "DONE-TASK", "status": "active", "note": "stale — task is done"},
  {"ref": "RESOLVED-TASK", "status": "active", "note": "stale — resolved in session"},
  {"ref": "OPEN-TASK", "status": "active", "note": "current — correct"}
]
"""


def _call(proc: subprocess.Popen, req: dict) -> dict:
    """Send a JSON-RPC request to the subprocess, read one response line."""
    line = json.dumps(req) + "\n"
    proc.stdin.write(line.encode())
    proc.stdin.flush()
    raw = proc.stdout.readline()
    if not raw:
        raise RuntimeError("subprocess died — no response")
    resp = json.loads(raw.decode())
    assert "error" not in resp, f"RPC error: {resp['error']}"
    return resp["result"]


# ── Setup: temp dir with fixture files ───────────────────────────────

tmpdir = Path(tempfile.mkdtemp(prefix="e2e-"))
vsm = tmpdir / "TASKS.vsm"
vsm.write_text(FIXTURE_VSM)
focus = tmpdir / "current_focus.json"
focus.write_text(FIXTURE_FOCUS)
journal = tmpdir / "journal.db"

server_script = str(ROOT / "state_canon" / "server.py")
instances_dir = str(ROOT / "instances")
instance_spec = f"{instances_dir}/tasks_provider.py:{vsm}"

try:
    proc = subprocess.Popen(
        [sys.executable, "-m", "state_canon.server",
         "--instance", instance_spec,
         "--focus", str(focus),
         "--journal", str(journal)],
        cwd=str(ROOT),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Give it a moment to start
    time.sleep(0.5)

    # ── 1. initialize ────────────────────────────────────────────────
    init = _call(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    check("e2e.initialize_name",
          init["serverInfo"]["name"] == "state-canon",
          str(init.get("serverInfo")))
    check("e2e.initialize_version",
          isinstance(init["serverInfo"].get("version"), str),
          str(init.get("serverInfo")))

    # ── 2. tools/list — both reconciler domains present ──────────────
    tools = _call(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    tool_names = {t["name"] for t in tools["tools"]}
    for expected in ("state_onboard", "state_query", "state_verify", "state_reconcile",
                     "state_focus_mark", "state_focus_close",
                     "state_journal_mark", "state_journal_diff", "state_journal_history"):
        check(f"e2e.tool_{expected}", expected in tool_names, str(tool_names))

    # ── 3. state_reconcile — both reconcilers produce drifts ─────────
    rec = _call(proc, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                       "params": {"name": "state_reconcile", "arguments": {}}})
    rec_text = json.loads(rec["content"][0]["text"])
    check("e2e.reconcile_is_list", isinstance(rec_text, list), str(type(rec_text)))
    # Should have 3 drifts: 1 from TaskSessionReconciler (RESOLVED-TASK open but resolved)
    # + 2 from FocusTaskReconciler (DONE-TASK stale_focus_task_done, RESOLVED-TASK stale_focus_session_resolved)
    check("e2e.reconcile_count", len(rec_text) >= 2,
          f"expected ≥2 drifts, got {len(rec_text)}: {rec_text}")

    # Check both drift domains appear
    drift_kinds = {(d.get("kind"), d.get("subject")) for d in rec_text}
    check("e2e.reconcile_task_drift",
          any(k[0] == "declared_but_resolved" for k in drift_kinds),
          f"drift kinds: {drift_kinds}")
    check("e2e.reconcile_focus_drift",
          any(k[0] == "stale_focus_task_done" for k in drift_kinds),
          f"drift kinds: {drift_kinds}")

    # ── 4. state_query('focus') — all 3 entries present ──────────────
    q = _call(proc, {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                     "params": {"name": "state_query",
                                "arguments": {"domain": "focus"}}})
    q_text = json.loads(q["content"][0]["text"])
    check("e2e.query_focus_count", len(q_text) == 3,
          f"expected 3 focus entries, got {len(q_text)}")
    refs = {e.get("ref") for e in q_text}
    check("e2e.query_focus_refs", refs == {"DONE-TASK", "RESOLVED-TASK", "OPEN-TASK"},
          f"refs: {refs}")

    # ── 5. state_query('focus', filter={'ref': '...'}) ───────────────
    qf = _call(proc, {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                      "params": {"name": "state_query",
                                 "arguments": {"domain": "focus",
                                               "filter": {"ref": "OPEN-TASK"}}}})
    qf_text = json.loads(qf["content"][0]["text"])
    check("e2e.query_focus_filter", len(qf_text) == 1 and qf_text[0]["ref"] == "OPEN-TASK",
          str(qf_text))

    # ── 6. state_journal_mark — opt-in journal works ─────────────────
    jm = _call(proc, {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                      "params": {"name": "state_journal_mark",
                                 "arguments": {"session_id": "e2e-test"}}})
    jm_text = json.loads(jm["content"][0]["text"])
    check("e2e.journal_mark",
          jm_text.get("snapshot_id") == 1 and jm_text.get("drift_count", 0) >= 2,
          str(jm_text))

    # ── 7. state_focus_mark — upsert a new entry ─────────────────────
    fm = _call(proc, {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                      "params": {"name": "state_focus_mark",
                                 "arguments": {"ref": "E2E-MARKED",
                                               "status": "active",
                                               "note": "created via e2e"}}})
    fm_text = json.loads(fm["content"][0]["text"])
    check("e2e.focus_mark_ref", fm_text.get("ref") == "E2E-MARKED", str(fm_text))
    check("e2e.focus_mark_status", fm_text.get("status") == "active", str(fm_text))

    # ── 8. state_focus_close — close a focus entry ───────────────────
    fc = _call(proc, {"jsonrpc": "2.0", "id": 8, "method": "tools/call",
                      "params": {"name": "state_focus_close",
                                 "arguments": {"ref": "E2E-MARKED",
                                               "note": "closed via e2e"}}})
    fc_text = json.loads(fc["content"][0]["text"])
    check("e2e.focus_close_ref", fc_text.get("ref") == "E2E-MARKED", str(fc_text))
    check("e2e.focus_close_status", fc_text.get("status") == "done", str(fc_text))

    # ── 9. state_onboard — digest succeeds ───────────────────────────
    ob = _call(proc, {"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                      "params": {"name": "state_onboard", "arguments": {}}})
    ob_text = ob["content"][0]["text"]
    check("e2e.onboard_mentions_drift", "drift" in ob_text.lower(),
          f"onboard: {ob_text[:100]}...")
    check("e2e.onboard_mentions_focus", "focus" in ob_text.lower(),
          f"onboard: {ob_text[:100]}...")

    # ── 10. Verify journal actually persisted (file exists, non-empty) ──
    check("e2e.journal_file_exists", journal.exists(),
          f"expected {journal} to exist")
    check("e2e.journal_file_nonempty", journal.stat().st_size > 0,
          f"journal size: {journal.stat().st_size}")

    print(f"\nALL {PASSED} CHECKS PASSED")

finally:
    # Cleanup: kill subprocess, remove temp dir
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
    shutil.rmtree(str(tmpdir), ignore_errors=True)
