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
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._doc: dict[str, Any] = json.loads(self.path.read_text())

    def list_domains(self) -> list[str]:
        return [k for k, v in self._doc.items() if isinstance(v, list)] + ["meta"]

    def query(self, domain: str, filter: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if domain == "meta":
            records = [{k: v for k, v in self._doc.items() if not isinstance(v, list)}]
        else:
            raw = self._doc.get(domain, [])
            records = [r if isinstance(r, dict) else {"value": r} for r in raw]
        if filter:
            records = [r for r in records if all(r.get(k) == v for k, v in filter.items())]
        return records
