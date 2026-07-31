"""SshSqliteStateProvider — SqliteStateProvider's remote-state sibling.

For the case INTERFACE.md's "Remote mode" section describes directly: the
canonical SQLite store lives on a machine the agent doesn't run on. Same
domain/table mapping and filter-validation contract as SqliteStateProvider,
but each query runs over SSH via the remote host's own `sqlite3` CLI
(`-readonly -json`) instead of a local `sqlite3.connect()` — the provider
*is* the remote-vs-local seam; nothing above it (server, tools, digest
policy) needs to know the difference.

Read-only by construction: `sqlite3 -readonly` refuses writes even if a
query tried one, and this class never builds anything but SELECT statements.

Cost/staleness, stated plainly (per INTERFACE.md's own guidance — "declare
it"): every query is a real SSH round-trip, there is no caching here. Fine
for on-demand queries and onboard digests; if a caller needs many queries
per second, wrap this provider with a caching layer rather than assuming
sub-millisecond latency the way the local SqliteStateProvider has.

Requires: passwordless SSH access to `host` already configured (key-based,
outside this code — never pass credentials as a provider argument, per
INTERFACE.md's own rule) and a `sqlite3` binary on the remote host.
"""
from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path
from typing import Any

from .provider import StateProvider


class RemoteQueryError(RuntimeError):
    """A remote sqlite3 invocation failed (SSH, or the query itself)."""


class SshSqliteStateProvider(StateProvider):
    def __init__(self, host: str, path: str | Path,
                 domains: dict[str, str] | None = None,
                 meta: dict[str, Any] | None = None,
                 ssh_opts: list[str] | None = None):
        self.host = host
        self.path = str(path)
        self._ssh_opts = ssh_opts or ["-o", "ConnectTimeout=10", "-o", "BatchMode=yes"]
        self._meta = dict(meta or {})
        self._meta.setdefault("source", f"{host}:{path}")
        if domains is None:
            rows = self._run_json(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')")
            domains = {r["name"]: r["name"] for r in rows}
        self._domains = domains  # domain name -> table/view name

    def _run_json(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        if params:
            # sqlite3 CLI has no bind-parameter flag; parameters here are
            # always either identifiers already validated against real
            # column names (see query()) or values quoted with SQLite's
            # own '' escaping — never raw user text concatenated in.
            for p in params:
                sql = sql.replace("?", _sql_quote(p), 1)
        # ssh hands its trailing args to the REMOTE shell as one joined,
        # re-parsed command line -- unquoted SQL (parens, quotes) would be
        # interpreted as remote shell syntax, not passed through literally.
        # Quote each remote-side token ourselves so the remote `sh -c` sees
        # exactly what we intend, regardless of what's in `sql`.
        remote_argv = ["sqlite3", "-readonly", "-json", self.path, sql]
        remote_cmd = " ".join(shlex.quote(a) for a in remote_argv)
        cmd = ["ssh", *self._ssh_opts, self.host, remote_cmd]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired as e:
            raise RemoteQueryError(f"SSH query to {self.host} timed out") from e
        if result.returncode != 0:
            raise RemoteQueryError(
                f"remote sqlite3 on {self.host} failed: {result.stderr.strip()}")
        out = result.stdout.strip()
        return json.loads(out) if out else []

    def list_domains(self) -> list[str]:
        return list(self._domains) + ["meta"]

    def query(self, domain: str, filter: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if domain == "meta":
            records = [dict(self._meta)]
            if filter:
                records = [r for r in records if all(r.get(k) == v for k, v in filter.items())]
            return records

        table = self._domains.get(domain)
        if table is None:
            return []
        cols = {r["name"] for r in self._run_json(f"PRAGMA table_info({table})")}
        where, params = "", []
        if filter:
            unknown = set(filter) - cols
            if unknown:
                raise ValueError(f"unknown filter fields for {domain}: {sorted(unknown)}")
            where = " WHERE " + " AND ".join(f"{k}=?" for k in filter)
            params = list(filter.values())
        return self._run_json(f"SELECT * FROM {table}{where}", params)


def _sql_quote(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"
