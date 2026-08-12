"""ssh_sqlite_ops instance — sqlite_ops.py's remote-state sibling.

Same domain mapping and digest policy EXCEPT 'rules' (this is genuinely the
same production ops canon sqlite_ops.py documents — this instance is how you
query it when the MCP server runs somewhere OTHER than the machine that holds
the DB, the exact "two SSH hops away" case INTERFACE.md's Remote mode section
describes). Domain 'rules' was retracted from this instance only (R7, resolved
2026-08-11 — TASKS.vsm R7-RULES-TABLE-CLEANUP-2026-08-11): the ops canon on
n02 is deterministic (services, lxcs, chains — polled), while rules live in
the agent's non-deterministic world and are DECLARED, never polled. The only
canonical rules source is docs/spec_revision/system/boot/hard_rules.vsm.
Querying domain 'rules' here raises a clear not-served error, never data.

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
    # NOTE: 'rules' intentionally ABSENT — retracted R7 (2026-08-11).
    # Rules are declared in docs/spec_revision/system/boot/hard_rules.vsm,
    # never polled from state.db. Querying 'rules' raises, see
    # VsfSshSqliteStateProvider.query(). (sqlite_ops.py template keeps it;
    # that template is generic, this instance is the VSF ops canon.)
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
    "topology": {"fields": ["id", "role", "ip"]},
    "chains":   {"fields": ["chain_id", "lxc", "last_event_ts"], "max": 12},
    "blockers": {"fields": ["id", "subject", "status"]},
    "coupling": {"fields": ["resource", "kind", "status"]},
    "deploys":  {"fields": ["component", "target_lxc", "result"], "max": 5, "last": True},
    "tasks":    {"fields": ["id", "subject", "status"], "max": 30},
    "components": {"max": 24},
}


class VsfSshSqliteStateProvider(SshSqliteStateProvider):
    """VSF ops-canon provider (n02 state.db) with the 'rules' domain retracted.

    R7, resolved 2026-08-11 (rmw3, S5): state.db observes n02's deterministic
    world (services, lxcs, chains — polled); rules live in the agent's
    non-deterministic world and are DECLARED, never polled. The base
    SshSqliteStateProvider.query() returns a silent [] for unmapped domains —
    indistinguishable from "no rules in effect", which would read as a
    denial-of-service on the rule layer. So the retraction is loud, not
    silent: querying 'rules' here raises with the canonical pointer.
    """

    RULES_NOT_SERVED = (
        "domain 'rules' is not served by state-canon-infra (R7, resolved "
        "2026-08-11). Rules are declared, never polled: the only canonical "
        "source is docs/spec_revision/system/boot/hard_rules.vsm — read them "
        "there. (TASKS.vsm R7-RULES-TABLE-CLEANUP-2026-08-11)"
    )

    def query(self, domain: str, filter: dict | None = None) -> list[dict]:
        if domain == "rules":
            raise ValueError(self.RULES_NOT_SERVED)
        return super().query(domain, filter)


def load(arg: str):
    """(provider, [reconcilers]) for the ops canon, queried over SSH.

    arg: "user@host,/path/to/db.sqlite" — see module docstring for why the
    separator is a comma, not scp's usual colon.
    """
    host, _, path = arg.partition(",")
    if not path:
        raise ValueError(
            f"expected 'user@host,/path/to/db' (comma-separated), got {arg!r}")
    provider = VsfSshSqliteStateProvider(
        host, path, DOMAINS,
        meta={"system": "ops", "host": host, "path": path},
    )
    return provider, []
