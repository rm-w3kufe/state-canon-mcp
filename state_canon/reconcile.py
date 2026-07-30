"""Reconciler — model≡reality made mechanical.

The user supplies how to read each side (declared = the model; observe = the
reality); the framework does the diff and types the drift. Extra domain rules
are pluggable callables.

Drift kinds:
  declared_but_missing — declared active, not observed running
  orphan               — observed running, not declared
  duplicate_key        — declared()/observe() has the same key twice (last wins, silently)
  rule_violation       — a registered rule check failed
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any, Callable


@dataclass
class Drift:
    kind: str
    subject: str
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


RuleCheck = Callable[[list[dict], list[dict]], list[Drift]]


class Reconciler(ABC):
    """One per domain. declared() = the model; observe() = the reality."""

    domain: str = "services"
    key: str = "name"                 # identity field matching declared ↔ observed
    status_field: str = "state"       # field expressing alive/dead
    active_values = frozenset({"active", "running"})
    rules: list[RuleCheck] = []       # extra checks: (declared, observed) -> [Drift]

    @abstractmethod
    def declared(self) -> list[dict]: ...

    @abstractmethod
    def observe(self) -> list[dict]: ...

    def _is_active(self, record: dict | None) -> bool:
        return record is not None and str(record.get(self.status_field, "")).lower() in self.active_values

    def _index(self, records: list[dict], side: str) -> tuple[dict, list[Drift]]:
        """Build a key -> record index, reporting duplicate keys instead of
        silently overwriting (last-wins) — a tool built to catch inconsistency
        shouldn't itself hide one."""
        indexed: dict[Any, dict] = {}
        dup_drifts: list[Drift] = []
        for r in records:
            k = r[self.key]
            if k in indexed:
                dup_drifts.append(Drift(
                    "duplicate_key", str(k),
                    f"{side} data has {self.key}={k!r} more than once — only the "
                    f"last record is used, earlier ones are silently dropped",
                    {"kept": r, "side": side},
                ))
            indexed[k] = r
        return indexed, dup_drifts

    def diff(self) -> list[Drift]:
        dec, dec_dup_drifts = self._index(self.declared(), "declared")
        obs, obs_dup_drifts = self._index(self.observe(), "observed")
        drifts: list[Drift] = [*dec_dup_drifts, *obs_dup_drifts]

        for name, d in dec.items():
            if self._is_active(d) and not self._is_active(obs.get(name)):
                drifts.append(Drift(
                    "declared_but_missing", name,
                    f"{name} declared {d.get(self.status_field)} but not observed running",
                    {"declared": d, "observed": obs.get(name)},
                ))

        for name, o in obs.items():
            if name not in dec:
                drifts.append(Drift(
                    "orphan", name,
                    f"{name} observed running (pid {o.get('pid', '?')}) but not declared",
                    {"observed": o},
                ))

        for rule in self.rules:
            drifts.extend(rule(list(dec.values()), list(obs.values())))
        return drifts
