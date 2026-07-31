"""ssh_sqlite_ops instance — sqlite_ops.py's remote-state sibling.

Same domain mapping and digest policy (this is genuinely the same production
ops canon sqlite_ops.py documents — this instance is how you query it when
the MCP server runs somewhere OTHER than the machine that holds the DB, the
exact "two SSH hops away" case INTERFACE.md's Remote mode section describes).

Arg syntax: `user@host,/path/to/db.sqlite` (comma, not colon -- the CLI's
own `--instance MODULE.py:ARG` splits on the LAST colon, so an arg that
embeds a colon of its own, like scp's user@host:path, would be parsed
wrong: everything after the true final colon becomes ARG, silently
swallowing part of the host into the module path instead).

Run:  python3 mcp_server.py --instance instances/ssh_sqlite_ops.py:root@n02,/var/lib/vsf-state/state.db

Reconciler note: same as sqlite_ops.py — the live model≡reality machinery
already runs host-side on timers there, and its OUTPUT is the database
itself, so no Reconciler is registered here either.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from state_canon.ssh_sqlite_provider import SshSqliteStateProvider

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


def load(arg: str):
    """(provider, [reconcilers]) for the ops canon, queried over SSH.

    arg: "user@host,/path/to/db.sqlite" — see module docstring for why the
    separator is a comma, not scp's usual colon.
    """
    host, _, path = arg.partition(",")
    if not path:
        raise ValueError(
            f"expected 'user@host,/path/to/db' (comma-separated), got {arg!r}")
    provider = SshSqliteStateProvider(
        host, path, DOMAINS,
        meta={"system": "ops", "host": host, "path": path},
    )
    return provider, []
