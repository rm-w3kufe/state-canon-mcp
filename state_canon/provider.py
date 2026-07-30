"""StateProvider — the pluggable canonical-state interface (the canon's ground truth).

The core is domain-agnostic: implement StateProvider over YOUR store (SQLite, JSON,
an API — anything). JsonStateProvider is the reference implementation, usable over
any state.json-shaped snapshot (and used by the microstack corpus instance).
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class StateProvider(ABC):
    """Read-only interface over a canonical state store."""

    @abstractmethod
    def list_domains(self) -> list[str]:
        """Names of the queryable domains (e.g. services, drift, rules)."""

    @abstractmethod
    def query(self, domain: str, filter: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Records of a domain, optionally filtered by field equality."""

    def schema(self, domain: str) -> dict[str, str]:
        """Field names → type names, inferred from the first record."""
        records = self.query(domain)
        return {k: type(v).__name__ for r in records[:1] for k, v in r.items()}


class JsonStateProvider(StateProvider):
    """Reference provider over a JSON document.

    Domains = top-level keys whose value is a list of records. Scalar/object
    top-level keys are exposed together under the synthetic 'meta' domain.

    Reloads the document when its mtime changes, so a long-lived stdio server
    session doesn't keep serving a stale snapshot forever (checked cheaply —
    one stat() per query — not on every access unconditionally).

    Some callers build an instance without going through __init__ (e.g.
    instances/tasks_provider.py uses JsonStateProvider.__new__(...) and fills
    _doc itself, because its data comes from a VSM-file parse, not
    json.loads(path)) — for those, `_mtime` stays at the class default of
    None, which disables reload-on-change: re-json.loads()'ing a non-JSON
    source file would corrupt _doc, so opting out is the only correct
    behavior, not a bug.
    """

    _mtime: float | None = None  # class default: reload-on-change disabled

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._mtime = -1.0  # guaranteed to differ from a real mtime -> forces first load
        self._doc: dict[str, Any] = {}
        self._reload_if_changed()

    def _reload_if_changed(self) -> None:
        if self._mtime is None:
            return
        mtime = self.path.stat().st_mtime
        if mtime != self._mtime:
            self._doc = json.loads(self.path.read_text())
            self._mtime = mtime

    def list_domains(self) -> list[str]:
        self._reload_if_changed()
        return [k for k, v in self._doc.items() if isinstance(v, list)] + ["meta"]

    def query(self, domain: str, filter: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        self._reload_if_changed()
        if domain == "meta":
            records = [{k: v for k, v in self._doc.items() if not isinstance(v, list)}]
        else:
            raw = self._doc.get(domain, [])
            records = [r if isinstance(r, dict) else {"value": r} for r in raw]
        if filter:
            known_fields = {k for r in records for k in r}
            unknown = set(filter) - known_fields
            if unknown and records:
                # Mirrors SqliteStateProvider's unknown-filter-field ValueError —
                # a JSON record has no fixed schema, so "unknown" is judged against
                # the fields actually present in this domain's records right now.
                raise ValueError(f"unknown filter fields for {domain}: {sorted(unknown)}")
            records = [r for r in records if all(r.get(k) == v for k, v in filter.items())]
        return records
