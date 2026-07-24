"""sqlite_ops instance — a REAL production ops database as a StateProvider.

This is the mapped-and-policied example: an explicit domain mapping over a live
operations SQLite canon, plus a digest policy shaped by real use. It is the
instance we run in production daily (names generalized).

Read-only by construction (mode=ro). Reconciler note (honest): in this
deployment the live model≡reality machinery already runs host-side on timers,
and its OUTPUT is the database itself — so this instance exposes reconciled
state rather than recomputing it. A live Reconciler here would need remote
observation; that belongs to the host machinery, not the canon layer.

Use it as a template: rename the domains to your tables, tune the policy.
Run:  python3 mcp_server.py --instance instances/sqlite_ops.py:/path/to/ops.db
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from state_canon.sqlite_provider import SqliteStateProvider

DOMAINS = {
    # canonical query surface
    "rules": "rules",
    "services": "services",
    "components": "components",
    "chains": "chain_state",
    "blockers": "v_open_blockers",
    "topology": "lxcs",
    # operational extras
    "coupling": "coupling_registry",
    "deploys": "deploys",
    "tasks": "tasks",
}

# What matters at onboard (the 44k→compact lesson — full detail stays one
# state_query away; the digest is for orientation, not exhaustiveness).
DIGEST_POLICY = {
    "services": {"fields": ["name", "lxc", "active"], "max": 60},
    "rules":    {"fields": ["id", "rule"]},
    "topology": {"fields": ["id", "role", "ip"]},
    "chains":   {"fields": ["chain_id", "lxc", "last_event_ts"], "max": 12},
    "blockers": {"fields": ["id", "subject", "status"]},
    "coupling": {"fields": ["resource", "kind", "status"]},
    "deploys":  {"fields": ["component", "target_lxc", "result"], "max": 5, "last": True},
    "tasks":    {"fields": ["id", "subject", "status"], "max": 30},
    "components": {"max": 24},
}


def load(db_path: str | Path):
    """(provider, [reconcilers]) for the ops canon. Reconcilers empty by design
    (see module docstring)."""
    provider = SqliteStateProvider(
        db_path, DOMAINS,
        meta={"system": "ops", "source": str(db_path)},
    )
    return provider, []
