"""Minimal MCP server (stdio, JSON-RPC 2.0, newline-delimited). Stdlib only.

Exposes the state-canon surface (INTERFACE.md):
  tools:     state_onboard · state_query · state_verify · state_reconcile ·
             state_journal_mark · state_journal_diff · state_journal_history (opt-in, --journal)
  resources: state://digest · state://schema · state://rules · state://handoff

Run:
  python3 -m state_canon.server --state path/to/state.json
  python3 -m state_canon.server --sqlite path/to/ops.db
  python3 -m state_canon.server --git path/to/repo
  python3 -m state_canon.server --microstack path/to/corpus/microstack
  python3 -m state_canon.server --instance path/to/my_instance.py:ARG   # bring your own
   # add --journal path/to/journal.db to any of the above to enable state_journal_*
   # add --focus path/to/focus.json to any of the above to enable state_focus_* + state_query('focus')
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .digest import assemble
from .focus import FocusTracker
from .journal import StateJournal
from .provider import JsonStateProvider, StateProvider
from .reconcile import Reconciler

PROTOCOL_VERSION = "2024-11-05"

# Cost hints in the descriptions are deliberate: EXP-TOKEN-GROUNDING showed all
# agents default to the broadest tool (state_onboard) even for narrow questions,
# wasting ~4x tokens. The description is the steering surface we have.
TOOLS = [
    {"name": "state_onboard",
     "description": "EXPENSIVE (full digest, ~500 tok): the whole current picture in one call — "
                    "services+status, drift, rules, last decision. Use ONCE at session start, or for "
                    "genuinely broad questions. For a specific service/record, use state_query instead.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "state_query",
     "description": "CHEAP (~80 tok): a narrow slice of canonical state, on demand — one domain, "
                    "optionally filtered by field equality. PREFER this for any specific question "
                    "(e.g. domain='services', filter={'name':'cache'}).",
     "inputSchema": {"type": "object",
                     "properties": {"domain": {"type": "string"},
                                    "filter": {"type": "object"}},
                     "required": ["domain"]}},
    {"name": "state_verify",
     "description": "Don't trust the report — check a claim against ground truth. "
                    "Claim = records matching `filter` in `domain` are expected to have `expect` field values.",
     "inputSchema": {"type": "object",
                     "properties": {"domain": {"type": "string"},
                                    "filter": {"type": "object"},
                                    "expect": {"type": "object"}},
                     "required": ["domain", "expect"]}},
    {"name": "state_reconcile",
     "description": "model≡reality: recompute declared-vs-observed drift live (fresh, not the stored snapshot).",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "state_journal_mark",
     "description": "MODERATE (~200 tok): save a state snapshot to the journal for later diff/tracking. "
                    "Call at session end to capture state; diff next session to see what changed. "
                    "Requires the server to be started with --journal.",
     "inputSchema": {"type": "object",
                     "properties": {"session_id": {"type": "string", "description": "optional session label"},
                                    "drifts": {"type": "array", "items": {"type": "object"},
                                               "description": "optional drift list"}}}},
    {"name": "state_journal_diff",
     "description": "CHEAP (~100 tok): diff two journal snapshots to see what changed.",
     "inputSchema": {"type": "object",
                     "properties": {"from_id": {"type": "integer", "description": "snapshot id (default: second-last)"},
                                    "to_id": {"type": "integer", "description": "snapshot id (default: last)"}}}},
    {"name": "state_journal_history",
     "description": "CHEAP (~80 tok): show recent journal snapshots.",
     "inputSchema": {"type": "object",
                     "properties": {"limit": {"type": "integer", "description": "max entries (default 10)"}}}},
    {"name": "state_focus_mark",
     "description": "Upsert a focus entry by ref. Creates if new, updates status/note if existing. "
                    "Requires --focus PATH at server start.",
     "inputSchema": {"type": "object",
                     "properties": {"ref": {"type": "string", "description": "focus entry identifier"},
                                    "status": {"type": "string",
                                               "description": "optional: active | paused | done (default: active)"},
                                    "note": {"type": "string", "description": "optional context note"}},
                     "required": ["ref"]}},
    {"name": "state_focus_close",
     "description": "Close (mark done) a focus entry by ref. Requires --focus PATH at server start.",
     "inputSchema": {"type": "object",
                     "properties": {"ref": {"type": "string", "description": "focus entry identifier"},
                                    "note": {"type": "string", "description": "optional closing note"}},
                     "required": ["ref"]}},
]

RESOURCES = [
    {"uri": "state://digest", "name": "digest", "description": "compact onboard digest", "mimeType": "text/plain"},
    {"uri": "state://schema", "name": "schema", "description": "domains + fields", "mimeType": "application/json"},
    {"uri": "state://rules", "name": "rules", "description": "active rules", "mimeType": "application/json"},
    {"uri": "state://handoff", "name": "handoff", "description": "last decision / handoff", "mimeType": "application/json"},
]


class StateRagServer:
    def __init__(self, provider: StateProvider, reconcilers: list[Reconciler] | None = None,
                 digest_policy: dict | None = None, journal_db: str | None = None,
                 focus_file: str | None = None):
        self.provider = provider
        self.reconcilers = reconcilers or []
        self.digest_policy = digest_policy
        self.journal = StateJournal(journal_db) if journal_db else None
        self.focus = FocusTracker(focus_file) if focus_file else None

    # ── tool implementations ──
    def state_onboard(self) -> str:
        return assemble(self.provider, self.reconcilers, policy=self.digest_policy)

    def state_query(self, domain: str, filter: dict | None = None) -> list[dict]:
        if domain == "focus":
            if not self.focus:
                return [{"error": "focus not enabled (start server with --focus)"}]
            return self.focus.query((filter or {}).get("ref"))
        return self.provider.query(domain, filter)

    def state_verify(self, domain: str, expect: dict, filter: dict | None = None) -> dict:
        records = self.provider.query(domain, filter)
        if not records:
            return {"holds": False, "reason": "no_records_matched", "filter": filter}
        mismatches = [
            {"record": r, "field": k, "expected": v, "actual": r.get(k)}
            for r in records for k, v in expect.items() if r.get(k) != v
        ]
        return {"holds": not mismatches,
                "checked": len(records),
                "mismatches": mismatches,
                "evidence": records if not mismatches else None}

    def state_reconcile(self) -> list[dict]:
        return [d.as_dict() for rec in self.reconcilers for d in rec.diff()]

    # ── resource reads ──
    def read_resource(self, uri: str) -> tuple[str, str]:
        if uri == "state://digest":
            return "text/plain", self.state_onboard()
        if uri == "state://schema":
            return "application/json", json.dumps(
                {d: self.provider.schema(d) for d in self.provider.list_domains()}, indent=1)
        if uri == "state://rules":
            return "application/json", json.dumps(self.provider.query("rules"), indent=1)
        if uri == "state://handoff":
            meta = (self.provider.query("meta") or [{}])[0]
            return "application/json", json.dumps(meta.get("last_decision", {}), indent=1)
        raise ValueError(f"unknown resource: {uri}")

    # ── JSON-RPC dispatch (pure function of request → response | None) ──
    def dispatch(self, req: dict) -> dict | None:
        method, req_id, params = req.get("method"), req.get("id"), req.get("params") or {}
        if req_id is None:  # notification → no response
            return None
        try:
            result = self._route(method, params)
            return {"jsonrpc": "2.0", "id": req_id, "result": result}
        except Exception as e:  # noqa: BLE001 — a server must answer, not die
            return {"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32603, "message": f"{type(e).__name__}: {e}"}}

    def _route(self, method: str, params: dict) -> Any:
        if method == "initialize":
            return {"protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}, "resources": {}},
                    "serverInfo": {"name": "state-canon", "version": "0.6.1"}}
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": TOOLS}
        if method == "resources/list":
            return {"resources": RESOURCES}
        if method == "resources/read":
            mime, text = self.read_resource(params["uri"])
            return {"contents": [{"uri": params["uri"], "mimeType": mime, "text": text}]}
        if method == "tools/call":
            out = self._call_tool(params["name"], params.get("arguments") or {})
            text = out if isinstance(out, str) else json.dumps(out, indent=1)
            return {"content": [{"type": "text", "text": text}]}
        raise ValueError(f"unknown method: {method}")

    def _call_tool(self, name: str, args: dict) -> Any:
        if name == "state_onboard":
            return self.state_onboard()
        if name == "state_query":
            return self.state_query(args["domain"], args.get("filter"))
        if name == "state_verify":
            return self.state_verify(args["domain"], args["expect"], args.get("filter"))
        if name == "state_reconcile":
            return self.state_reconcile()
        if name == "state_journal_mark":
            return self._journal_mark(args.get("session_id"), args.get("drifts"))
        if name == "state_journal_diff":
            return self._journal_diff(args.get("from_id"), args.get("to_id"))
        if name == "state_journal_history":
            return self._journal_history(args.get("limit", 10))
        if name == "state_focus_mark":
            return self._focus_mark(args["ref"], args.get("status"), args.get("note"))
        if name == "state_focus_close":
            return self._focus_close(args["ref"], args.get("note"))
        raise ValueError(f"unknown tool: {name}")

    # ── journal tools ──

    def _journal_mark(self, session_id: str | None = None,
                       drifts: list[dict] | None = None) -> dict:
        if not self.journal:
            return {"error": "journal not enabled (start server with --journal)"}
        if drifts is None and self.reconcilers:
            drifts = [d.as_dict() for rec in self.reconcilers for d in rec.diff()]
        jid = self.journal.mark(session_id=session_id or "",
                                 snapshot_type="mcp",
                                 drifts=drifts)
        return {"snapshot_id": jid, "drift_count": len(drifts or [])}

    def _journal_diff(self, from_id: int | None = None,
                       to_id: int | None = None) -> dict:
        if not self.journal:
            return {"error": "journal not enabled"}
        return self.journal.diff(from_id=from_id, to_id=to_id)

    def _journal_history(self, limit: int = 10) -> list[dict]:
        if not self.journal:
            return [{"error": "journal not enabled"}]
        h = self.journal.history(limit=limit)
        return [{
            "id": r["id"],
            "type": r["snapshot_type"],
            "findings": r["production_findings"],
            "drifts": r["drift_count"],
            "rag_accuracy": f"{r['rag_accuracy']:.0%}" if r.get("rag_accuracy") else "-",
            "session": r["session_id"] or "-",
            "at": r["created_at"],
        } for r in h]

    # ── focus tools ──

    def _focus_mark(self, ref: str, status: str | None = None,
                    note: str | None = None) -> dict:
        if not self.focus:
            return {"error": "focus not enabled (start server with --focus)"}
        entry = self.focus.mark(ref, status=status, note=note)
        return {"ref": entry["ref"], "status": entry["status"], "updated_at": entry["updated_at"]}

    def _focus_close(self, ref: str, note: str | None = None) -> dict:
        if not self.focus:
            return {"error": "focus not enabled (start server with --focus)"}
        entry = self.focus.close(ref, note=note)
        return {"ref": entry["ref"], "status": entry["status"], "updated_at": entry["updated_at"]}

    # ── stdio loop ──
    def serve(self) -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                continue
            resp = self.dispatch(req)
            if resp is not None:
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()


def _load_instance_file(module_path, arg: str):
    """Load an instance module (a .py with load(arg) [+ DIGEST_POLICY]) →
    (provider, reconcilers, digest_policy). This is the bring-your-own hook."""
    import importlib.util
    import sys
    from pathlib import Path
    inst = Path(module_path)
    spec = importlib.util.spec_from_file_location(inst.stem, inst)
    mod = importlib.util.module_from_spec(spec)
    # Register in sys.modules BEFORE exec_module — required by @dataclass and
    # other Python internals that look up cls.__module__ in sys.modules.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    provider, reconcilers = mod.load(arg)
    return provider, reconcilers, getattr(mod, "DIGEST_POLICY", None)


def main() -> None:
    from pathlib import Path
    instances_dir = Path(__file__).resolve().parents[1] / "instances"

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--state", help="path to a state.json (JsonStateProvider, no reconciler)")
    ap.add_argument("--sqlite", help="path to any SQLite DB (every table/view becomes a domain, read-only)")
    ap.add_argument("--git", help="path to a git repository (GitStateProvider + reconciler, read-only)")
    ap.add_argument("--microstack", help="path to the microstack corpus dir (demo: provider + reconciler)")
    ap.add_argument("--instance", metavar="MODULE.py:ARG",
                    help="bring your own instance: a module exposing load(arg) [+ DIGEST_POLICY]")
    ap.add_argument("--journal", metavar="PATH",
                    help="enable state_journal_* tools, persisting snapshots to PATH (SQLite DB)")
    ap.add_argument("--focus", metavar="PATH",
                    help="enable state_focus_* tools + state_query('focus'), "
                         "persisting per-agent focus entries to PATH (JSON)")
    args = ap.parse_args()

    if args.instance:
        module_path, _, arg = args.instance.rpartition(":")
        provider, reconcilers, policy = _load_instance_file(module_path, arg)
    elif args.microstack:
        provider, reconcilers, policy = _load_instance_file(instances_dir / "microstack.py", args.microstack)
    elif args.git:
        from .git_provider import DIGEST_POLICY as git_policy
        from .git_provider import load as git_load
        provider, reconcilers = git_load(args.git)
        policy = git_policy
    elif args.sqlite:
        from .sqlite_provider import SqliteStateProvider
        provider, reconcilers, policy = SqliteStateProvider(args.sqlite), [], None
    elif args.state:
        provider, reconcilers, policy = JsonStateProvider(args.state), [], None
    else:
        ap.error("need one of --state, --sqlite, --git, --microstack, --instance")

    StateRagServer(provider, reconcilers, policy, journal_db=args.journal, focus_file=args.focus).serve()


if __name__ == "__main__":
    main()
