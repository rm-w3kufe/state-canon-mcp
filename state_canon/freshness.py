"""FreshnessReconciler — warns when a file's data hasn't been refreshed within N seconds.

A generic core primitive: any consumer can assert that a data file, database,
or artifact has been updated recently enough. Not BBH-specific — it belongs
in the public core because *any* agent that reads persisted state wants to
know whether that state is stale.

Two drift kinds:
  *missing* — the path does not exist at all
  *stale*   — the path exists but (now - mtime) > max_age_seconds

Usage::

    from state_canon.freshness import FreshnessReconciler

    reconciler = FreshnessReconciler(
        path="/var/lib/vsf/state.db",
        max_age_seconds=86400,          # 1 day
        domain="my-domain",             # optional, default "freshness"
        label="state DB",               # optional, defaults to str(path)
    )
    drifts = reconciler.diff()  # → list[Drift]
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from .reconcile import Drift, Reconciler


class FreshnessReconciler(Reconciler):
    """Flags a file as stale if its mtime is older than *max_age_seconds*.

    Does NOT use the base ``Reconciler.diff()`` (which does declared-vs-observed
    key matching for services); it overrides ``diff()`` with a dedicated
    freshness check.

    Domain defaults to ``"freshness"`` but is overridable via ``domain``.
    """

    domain = "freshness"

    def __init__(self, path: str | Path, max_age_seconds: float,
                 domain: str | None = None, label: str | None = None):
        self._path = Path(path)
        self._max_age = max_age_seconds
        if domain is not None:
            self.domain = domain
        self._label = label or str(self._path)

    # ── model / declared ──────────────────────────────────────────────

    def declared(self) -> list[dict]:
        return [{
            "path": str(self._path),
            "max_age_seconds": self._max_age,
        }]

    # ── reality / observed ────────────────────────────────────────────

    def observe(self) -> list[dict]:
        try:
            st = self._path.stat()
            return [{
                "path": str(self._path),
                "mtime": st.st_mtime,
                "exists": True,
            }]
        except OSError:
            return [{
                "path": str(self._path),
                "mtime": None,
                "exists": False,
            }]

    # ── drift ─────────────────────────────────────────────────────────

    def diff(self) -> list[Drift]:
        now = time.time()
        try:
            st = self._path.stat()
        except OSError:
            return [Drift(
                "missing", str(self._path),
                f"{self._label} does not exist (expected at {self._path})",
                {"path": str(self._path), "max_age_seconds": self._max_age},
            )]

        age = now - st.st_mtime
        if age > self._max_age:
            age_days = age / 86400
            max_age_days = self._max_age / 86400
            return [Drift(
                "stale", str(self._path),
                f"{self._label} is {age_days:.1f} days old "
                f"(max {max_age_days:.1f})",
                {
                    "path": str(self._path),
                    "max_age_seconds": self._max_age,
                    "age_seconds": round(age, 1),
                    "age_days": round(age_days, 1),
                    "mtime": st.st_mtime,
                },
            )]
        return []
