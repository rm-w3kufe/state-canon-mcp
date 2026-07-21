"""state-rag-mcp tests — no LLM, pure asserts against GROUND_TRUTH.

The contract: the 3 corpus drifts (declared_but_missing:cache, rule_violation:R1,
orphan:debug-shell) must FALL OUT of the generic Reconciler diff + one rule.
If they don't, the abstraction is wrong.

Run:  python3 tests/test_state_rag.py   (from projects/state-rag-mcp/)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "instances"))

import microstack  # noqa: E402
from state_rag.digest import assemble  # noqa: E402
from state_rag.server import StateRagServer  # noqa: E402

CORPUS = ROOT / "corpus" / "microstack"
PASSED = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASSED
    if not cond:
        print(f"✗ FAIL {name} {detail}")
        sys.exit(1)
    PASSED += 1
    print(f"✓ {name}")


provider, reconcilers = microstack.load(CORPUS)
server = StateRagServer(provider, reconcilers)

# ── provider ──
domains = provider.list_domains()
check("provider.domains", {"services", "drift", "rules", "meta"} <= set(domains), str(domains))
cache = provider.query("services", {"name": "cache"})
check("provider.query.filter", len(cache) == 1 and cache[0]["actual"] == "stopped", str(cache))

# ── reconciler: the 3 drifts fall out of the generic diff ──
drifts = reconcilers[0].diff()
kinds = {(d.kind, d.subject) for d in drifts}
check("drift.count", len(drifts) == 3, f"got {len(drifts)}: {kinds}")
check("drift.cache", ("declared_but_missing", "cache") in kinds)
check("drift.r1", ("rule_violation", "R1") in kinds)
check("drift.orphan", ("orphan", "debug-shell") in kinds)
check("drift.backup-not-flagged", not any(d.subject == "backup" for d in drifts),
      "backup is declared inactive — a correct stop, not drift (R2)")

# ── verify: don't trust the report ──
v_bad = server.state_verify("services", {"actual": "running"}, {"name": "cache"})
check("verify.catches-lie", v_bad["holds"] is False and v_bad["mismatches"], str(v_bad))
v_ok = server.state_verify("services", {"version": "1.2.0"}, {"name": "api"})
check("verify.confirms-truth", v_ok["holds"] is True, str(v_ok))
v_none = server.state_verify("services", {"actual": "running"}, {"name": "ghost"})
check("verify.no-records", v_none["holds"] is False and v_none.get("reason") == "no_records_matched")

# ── digest: compact, grounded, live drift beats stored ──
digest = assemble(provider, reconcilers)
for needle in ("cache", "declared_but_missing", "R1", "debug-shell", "D-42"):
    check(f"digest.contains[{needle}]", needle in digest)
check("digest.compact", len(digest) < 2500, f"{len(digest)} chars")

# ── MCP dispatch (in-process protocol smoke) ──
def rpc(method: str, params: dict | None = None, req_id: int = 1) -> dict:
    resp = server.dispatch({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}})
    assert "error" not in resp, resp
    return resp["result"]

init = rpc("initialize")
check("mcp.initialize", init["serverInfo"]["name"] == "state-rag-mcp")
tools = {t["name"] for t in rpc("tools/list")["tools"]}
check("mcp.tools", tools == {"state_onboard", "state_query", "state_verify", "state_reconcile"}, str(tools))
out = rpc("tools/call", {"name": "state_reconcile", "arguments": {}})
live = json.loads(out["content"][0]["text"])
check("mcp.reconcile-live", len(live) == 3 and {d["kind"] for d in live}
      == {"declared_but_missing", "orphan", "rule_violation"})
res = rpc("resources/read", {"uri": "state://digest"})
check("mcp.resource-digest", "CURRENT STATE" in res["contents"][0]["text"])
check("mcp.notification-silent", server.dispatch({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None)
check("mcp.error-answered", "error" in server.dispatch({"jsonrpc": "2.0", "id": 9, "method": "nope"}))

print(f"\nALL {PASSED} CHECKS PASSED")
