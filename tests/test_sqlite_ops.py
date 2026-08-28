"""sqlite_ops instance tests — structural, NOT value-pinned (canon data changes;
the mechanics must not). Runs against a read-only SNAPSHOT of a production ops DB.

The snapshot is NEVER committed to the repo. DB path via:
  STATE_CANON_TEST_DB=/path/to/snapshot.db python3 tests/test_sqlite_ops.py
(skips cleanly when unset — this test is for deployments that have such a canon.)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "instances"))

import sqlite_ops  # noqa: E402
from state_canon.digest import assemble  # noqa: E402
from state_canon.server import StateRagServer  # noqa: E402

DB = os.environ.get("STATE_CANON_TEST_DB")
if not DB or not Path(DB).exists():
    import pytest
    pytest.skip("set STATE_CANON_TEST_DB to an ops-DB snapshot", allow_module_level=True)

PASSED = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASSED
    if not cond:
        print(f"✗ FAIL {name} {detail}")
        sys.exit(1)
    PASSED += 1
    print(f"✓ {name}")


provider, reconcilers = sqlite_ops.load(DB)
server = StateRagServer(provider, reconcilers)

# ── the canonical domains answer ──
domains = set(provider.list_domains())
check("ops.domains", {"rules", "services", "components", "chains", "blockers", "topology"} <= domains,
      str(sorted(domains)))

services = provider.query("services")
check("ops.services-nonempty", len(services) > 0, str(len(services)))
check("ops.services-shape", {"lxc", "name", "active"} <= set(services[0]), str(services[0].keys()))

rules = provider.query("rules")
check("ops.rules-nonempty", len(rules) > 0)

# ── filter pushes down to SQL ──
lxc_any = services[0]["lxc"]
subset = provider.query("services", {"lxc": lxc_any})
check("ops.filter-pushdown", len(subset) > 0 and all(r["lxc"] == lxc_any for r in subset), str(len(subset)))

# ── unknown filter field → loud error, not silent empty ──
try:
    provider.query("services", {"nonexistent_field": 1})
    check("ops.filter-unknown-loud", False, "should have raised")
except ValueError:
    check("ops.filter-unknown-loud", True)

# ── verify mechanics against real records (self-referential: data-independent) ──
probe = services[0]
v_true = server.state_verify("services", {"active": probe["active"]},
                             {"lxc": probe["lxc"], "name": probe["name"]})
check("ops.verify-truth", v_true["holds"] is True, str(v_true))
v_false = server.state_verify("services", {"active": None if probe["active"] is not None else 0},
                              {"lxc": probe["lxc"], "name": probe["name"]})
check("ops.verify-lie", v_false["holds"] is False)

# ── digest builds over the real canon — WITH the policy (the 44k lesson) ──
digest = assemble(provider, reconcilers, policy=sqlite_ops.DIGEST_POLICY)
check("ops.digest-header", digest.startswith("CURRENT STATE (ops"), digest[:60])
check("ops.digest-services", "services(" in digest)
check("ops.digest-size-sane", 200 < len(digest) < 12000, f"{len(digest)} chars")
check("ops.digest-no-hashes", "binary_sha" not in digest and "exec_path" not in digest,
      "onboard digest must not carry 64-char hashes / paths — that detail is one state_query away")

# ── MCP dispatch over the real canon ──
out = server.dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": "state_query",
                                  "arguments": {"domain": "blockers"}}})
check("ops.mcp-blockers", "result" in out and "content" in out["result"])
blockers = json.loads(out["result"]["content"][0]["text"])
check("ops.mcp-blockers-shape", isinstance(blockers, list))

print(f"\nALL {PASSED} CHECKS PASSED  (services={len(services)}, rules={len(rules)}, "
      f"blockers={len(blockers)}, digest={len(digest)} chars)")
