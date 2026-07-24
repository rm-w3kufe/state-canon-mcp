"""SqliteStateProvider — generic provider over any SQLite store. READ-ONLY by
construction (URI mode=ro): state-canon reads, it never writes.

Domains map to tables/views via an explicit mapping; default = every table/view.
Identifier safety: table names come from the trusted constructor mapping; filter
keys are validated against the table's actual columns; values are parameterized.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .provider import StateProvider


class SqliteStateProvider(StateProvider):
    def __init__(self, path: str | Path,
                 domains: dict[str, str] | None = None,
                 meta: dict[str, Any] | None = None):
        self.path = Path(path)
        self._uri = f"file:{self.path}?mode=ro"
        self._meta = dict(meta or {})
        if domains is None:
            with self._conn() as c:
                rows = c.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table','view')").fetchall()
            domains = {r["name"]: r["name"] for r in rows}
        self._domains = domains  # domain name → table/view name

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn

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
        with self._conn() as c:
            cols = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
            where, params = "", []
            if filter:
                unknown = set(filter) - cols
                if unknown:
                    raise ValueError(f"unknown filter fields for {domain}: {sorted(unknown)}")
                where = " WHERE " + " AND ".join(f"{k}=?" for k in filter)
                params = list(filter.values())
            rows = c.execute(f"SELECT * FROM {table}{where}", params).fetchall()
        return [dict(r) for r in rows]
