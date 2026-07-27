"""FocusTracker tests — atomic read-write focus file via FocusTracker + MCP dispatch.

Same structure as test_state_canon.py: stdlib-only, check() harness, in-process RPC.

Run:  python3 tests/test_focus.py   (from state-canon-mcp/)
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "instances"))

from state_canon.focus import FocusTracker  # noqa: E402
from state_canon.server import StateRagServer  # noqa: E402
from state_canon.provider import JsonStateProvider  # noqa: E402

PASSED = 0

# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════
#                                FOCUS TRACKER UNIT TESTS
# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASSED
    if not cond:
        print(f"✗ FAIL {name} {detail}")
        sys.exit(1)
    PASSED += 1
    print(f"✓ {name}")


def _check_entry(name: str, entry: dict, field: str,
                 expected: object) -> None:
    check(f"{name}.{field}", entry.get(field) == expected,
          f"expected {expected!r}, got {entry.get(field)!r}")


# ── FocusTracker: create on new file ──────────────────────

tmpdir = Path(tempfile.mkdtemp(prefix="focus-"))
try:
    focus_path = tmpdir / "current_focus.json"
    ft = FocusTracker(focus_path)

    check("ft.file_created", focus_path.exists())
    check("ft.file_empty_array", focus_path.read_text().strip() == "[]")

    # ── FocusTracker: mark creates new entry ──

    entry = ft.mark("TASK-ONE", status="active", note="first task")
    check("ft.mark_returns_ref", entry.get("ref") == "TASK-ONE")
    check("ft.mark_returns_status", entry.get("status") == "active")
    check("ft.mark_returns_note", entry.get("note") == "first task")
    check("ft.mark_has_started_at", bool(entry.get("started_at")))
    check("ft.mark_has_updated_at", bool(entry.get("updated_at")))

    all_entries = ft.query()
    check("ft.mark_one_entry", len(all_entries) == 1)
    check("ft.mark_entry_ref", all_entries[0]["ref"] == "TASK-ONE")

    # ── FocusTracker: mark upserts existing entry ──

    entry2 = ft.mark("TASK-ONE", status="paused", note="pausing for now")
    all_entries2 = ft.query()
    check("ft.mark_still_one_entry", len(all_entries2) == 1)
    _check_entry("ft.mark_upsert", all_entries2[0], "status", "paused")
    _check_entry("ft.mark_upsert", all_entries2[0], "note", "pausing for now")

    # ── FocusTracker: close sets status=done ──

    entry3 = ft.close("TASK-ONE", note="completed successfully")
    _check_entry("ft.close_status", entry3, "status", "done")
    _check_entry("ft.close_note", entry3, "note", "completed successfully")

    # ── FocusTracker: mark creates second entry ──

    entry4 = ft.mark("TASK-TWO", status="active", note="second task")
    all_entries3 = ft.query()
    check("ft.two_entries", len(all_entries3) == 2)

    # ── FocusTracker: query with ref filter ──

    q1 = ft.query(ref="TASK-ONE")
    check("ft.query_ref_one_result", len(q1) == 1)
    _check_entry("ft.query_ref_one_ref", q1[0], "ref", "TASK-ONE")

    q2 = ft.query(ref="NONEXISTENT")
    check("ft.query_ref_none", len(q2) == 0)

    # ── FocusTracker: query on empty file returns [] ──

    empty_path = tmpdir / "empty.json"
    ft_empty = FocusTracker(empty_path)
    check("ft.empty_query", ft_empty.query() == [])
    check("ft.empty_query_ref", ft_empty.query(ref="x") == [])

    # ── FocusTracker: mark on empty file ──

    ft_empty.mark("FIRST", note="auto-created file")
    check("ft.empty_mark_one", len(ft_empty.query()) == 1)

    # ── FocusTracker: atomic write ──

    # Check that during write, a temp file with .focus_ prefix appears briefly
    # (we can test this by checking there are no .focus_ files after the fact)
    focus_path2 = tmpdir / "atomic_test.json"
    ft_atomic = FocusTracker(focus_path2)
    ft_atomic.mark("A", note="test atomicity")
    leftovers = list(tmpdir.glob(".focus_*"))
    check("ft.atomic_no_leftovers", len(leftovers) == 0,
          f"leftover temp files: {leftovers}")

    # Accessing file content directly verifies it's valid JSON
    raw = json.loads(focus_path2.read_text())
    check("ft.atomic_valid_json", isinstance(raw, list))
    check("ft.atomic_content", len(raw) == 1 and raw[0]["ref"] == "A")

    # ── FocusTracker: mark without status defaults to "active" ──

    entry5 = ft.mark("TASK-THREE", note="default status")
    _check_entry("ft.mark_default_status", entry5, "status", "active")

    # ── FocusTracker: close with no note keeps existing note ──

    entry6 = ft.close("TASK-TWO")
    _check_entry("ft.close_without_note", entry6, "status", "done")
    # note should still be "second task" from mark
    _check_entry("ft.close_preserves_note", entry6, "note", "second task")

    # ═══════════════════════════════════════════════════════════
    # ═══════════════════════════════════════════════════════════
    # ═══════════════════════════════════════════════════════════
    #                              FOCUS MCP TOOL TESTS
    # ═══════════════════════════════════════════════════════════
    # ═══════════════════════════════════════════════════════════
    # ═══════════════════════════════════════════════════════════

    tmp2 = Path(tempfile.mkdtemp(prefix="focus-mcp-"))
    focus_mcp_path = tmp2 / "mcp_focus.json"
    dummy_state_path = tmp2 / "state.json"
    dummy_state_path.write_text('{"test": [{"key": "val"}]}')

    provider = JsonStateProvider(str(dummy_state_path))
    server = StateRagServer(provider, reconcilers=[],
                             focus_file=str(focus_mcp_path))

    def rpc(method: str, params: dict | None = None, req_id: int = 1) -> dict:
        resp = server.dispatch({"jsonrpc": "2.0", "id": req_id,
                                "method": method, "params": params or {}})
        assert "error" not in resp, f"RPC error: {resp.get('error')}"
        return resp["result"]

    # ── tools/list includes state_focus_* ──

    tools = {t["name"] for t in rpc("tools/list")["tools"]}
    check("mcp.tools_has_focus_mark", "state_focus_mark" in tools)
    check("mcp.tools_has_focus_close", "state_focus_close" in tools)

    # ── state_focus_mark via MCP ──

    resp = rpc("tools/call", {"name": "state_focus_mark",
                               "arguments": {"ref": "MCP-TASK",
                                             "status": "active",
                                             "note": "created via MCP"}})
    result = json.loads(resp["content"][0]["text"])
    _check_entry("mcp.mark_ref", result, "ref", "MCP-TASK")
    _check_entry("mcp.mark_status", result, "status", "active")

    # ── state_focus_close via MCP ──

    resp = rpc("tools/call", {"name": "state_focus_close",
                               "arguments": {"ref": "MCP-TASK",
                                             "note": "closed via MCP"}})
    result = json.loads(resp["content"][0]["text"])
    _check_entry("mcp.close_ref", result, "ref", "MCP-TASK")
    _check_entry("mcp.close_status", result, "status", "done")

    # ── state_query('focus') reflects mutations ──

    q = server.state_query("focus")
    check("mcp.query_all_count", len(q) == 1, f"got {len(q)} entries")
    _check_entry("mcp.query_all_ref", q[0], "ref", "MCP-TASK")
    _check_entry("mcp.query_all_status", q[0], "status", "done")

    # ── state_query('focus', filter={'ref': '...'}) ──

    qf = server.state_query("focus", {"ref": "MCP-TASK"})
    check("mcp.query_filter_one", len(qf) == 1)
    qf2 = server.state_query("focus", {"ref": "NOPE"})
    check("mcp.query_filter_none", len(qf2) == 0)

    # ── Multiple marks + queries in sequence ──

    for i in range(3):
        server.dispatch({"jsonrpc": "2.0", "id": i + 10, "method": "tools/call",
                          "params": {"name": "state_focus_mark",
                                     "arguments": {"ref": f"BATCH-{i}",
                                                   "status": "active"}}})
    q_all = server.state_query("focus")
    check("mcp.batch_3_plus_1", len(q_all) == 4,
          f"expected 4 (1 MCP-TASK + 3 batch), got {len(q_all)}")

    # ── state_focus_mark without --focus gives error ──

    server_no_focus = StateRagServer(provider, reconcilers=[])
    resp_no = server_no_focus.dispatch({
        "jsonrpc": "2.0", "id": 99,
        "method": "tools/call",
        "params": {"name": "state_focus_mark",
                   "arguments": {"ref": "NOPE"}},
    })
    err_text = json.loads(resp_no["result"]["content"][0]["text"])
    check("mcp.error_without_flag",
          err_text.get("error", "").startswith("focus not enabled"),
          str(err_text))

    # ── state_focus_close without --focus gives error ──

    resp_no2 = server_no_focus.dispatch({
        "jsonrpc": "2.0", "id": 100,
        "method": "tools/call",
        "params": {"name": "state_focus_close",
                   "arguments": {"ref": "NOPE"}},
    })
    err_text2 = json.loads(resp_no2["result"]["content"][0]["text"])
    check("mcp.close_error_without_flag",
          err_text2.get("error", "").startswith("focus not enabled"),
          str(err_text2))

    # ── state_query('focus') without --focus gives error ──

    q_no = server_no_focus.state_query("focus")
    check("mcp.query_error_without_flag",
          len(q_no) == 1 and "error" in q_no[0],
          str(q_no))

    # ── Cleanup ──
    shutil.rmtree(str(tmp2), ignore_errors=True)

    print(f"\nALL {PASSED} CHECKS PASSED")
finally:
    shutil.rmtree(str(tmpdir), ignore_errors=True)
