"""StateJournal — persist + diff state snapshots over time.

Writes to the same DB the provider reads from, but uses a separate
READ-WRITE connection for the journal table. The journal is append-only:
it records what state was at each snapshot point, enabling:

  - session-to-session diff: "what changed since last session?"
  - trend analysis: "are stale findings increasing or decreasing?"
  - learning loop: "did the RAG's accuracy improve after calibration?"

Schema:
  state_journal(
    id, session_id, snapshot_type,
    production_findings, by_severity, by_target, by_status,
    drift_count, drifts, rag_accuracy, rag_feedback_total,
    created_at
  )

Domain scope: `drift_count`/`drifts` come from whatever reconcilers the
server was launched with, so they work for ANY instance — fully generic,
no configuration needed. The other columns (`production_findings`/
`by_severity`/`by_target`/`by_status`/`rag_accuracy`/`rag_feedback_total`)
are instance-specific stats with no fixed shape the core can assume — they
stay zeroed unless the consuming instance supplies `stats_fn`/`rag_fn`
callables at construction (see `instances/` for an example wiring one up
against a domain-specific schema). Keeping domain-specific schema
assumptions out of this shared file is deliberate: any instance's own
data shape belongs in that instance's own module, not here.

Usage:
  journal = StateJournal("/path/to/some.db")
  journal.mark()                          # save snapshot
  print(journal.diff())                    # last two snapshots
  print(journal.history(limit=5))          # recent snapshots
  print(journal.trend(field="production_findings"))  # over time

  # with instance-specific stats:
  journal = StateJournal("/path/to/some.db", stats_fn=my_stats, rag_fn=my_rag)
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Callable


SCHEMA = """
CREATE TABLE IF NOT EXISTS state_journal (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT,
    snapshot_type   TEXT NOT NULL DEFAULT 'manual',
    production_findings INTEGER DEFAULT 0,
    by_severity     TEXT,          -- JSON: {"critical": N, "high": N, ...}
    by_target       TEXT,          -- JSON: {"target": N, ...}
    by_status       TEXT,          -- JSON: {"lifecycle_status": N, ...}
    drift_count     INTEGER DEFAULT 0,
    drifts          TEXT,          -- JSON: [{"kind": ..., ...}]
    rag_accuracy    REAL,          -- from rag_feedback (0.0-1.0)
    rag_feedback_total INTEGER DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

StatsFn = Callable[[], dict[str, Any]]


class StateJournal:
    """Append-only journal of state snapshots over time."""

    def __init__(self, db_path: str | Path,
                 stats_fn: StatsFn | None = None,
                 rag_fn: StatsFn | None = None):
        """`stats_fn`/`rag_fn` are optional zero-arg callables an instance can
        supply to populate the instance-specific columns (see module docstring).
        Left unset, those columns just stay zeroed — the journal remains fully
        useful for drift tracking alone."""
        self.db_path = str(Path(db_path).resolve())
        self._stats_fn = stats_fn
        self._rag_fn = rag_fn
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self) -> None:
        with self._conn() as c:
            c.executescript(SCHEMA)

    # ── snapshot ──

    def mark(self, session_id: str | None = None,
             snapshot_type: str = "manual",
             drifts: list[dict] | None = None) -> int:
        """Save a snapshot of current state. Returns the new row id."""
        stats = self._stats_fn() if self._stats_fn else {}
        rag = self._rag_fn() if self._rag_fn else {}
        sev_json = json.dumps(stats.get("by_severity", {}))
        tgt_json = json.dumps(stats.get("by_target", {}))
        sts_json = json.dumps(stats.get("by_status", {}))
        drf_json = json.dumps(drifts or [])

        with self._conn() as c:
            cur = c.execute(
                """INSERT INTO state_journal
                   (session_id, snapshot_type, production_findings,
                    by_severity, by_target, by_status,
                    drift_count, drifts, rag_accuracy, rag_feedback_total)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, snapshot_type,
                 stats.get("production_findings", 0),
                 sev_json, tgt_json, sts_json,
                 len(drifts or []), drf_json,
                 rag.get("accuracy"), rag.get("total")),
            )
            return cur.lastrowid

    # ── diff ──

    def diff(self, from_id: int | None = None,
             to_id: int | None = None) -> dict[str, Any]:
        """Structural diff between two snapshots.

        If ids omitted, diffs the LAST TWO snapshots.
        Returns dict with:
          - meta: from_ts, to_ts, days_apart
          - changes: {field: {"from": X, "to": Y, "delta": +/-N}}
          - findings_gained: [targets that appeared]
          - findings_lost: [targets that disappeared]
          - drift_added: [new drifts]
          - drift_resolved: [drifts no longer present]
          - rag: accuracy change
        """
        rows = self._get_range(from_id, to_id, n=2)
        if len(rows) < 2:
            return {"error": f"need ≥2 snapshots, have {len(rows)}"}

        older, newer = rows[0], rows[1]
        if older["id"] > newer["id"]:
            older, newer = newer, rows[0]

        return self._compute_diff(dict(older), dict(newer))

    def _get_range(self, from_id: int | None, to_id: int | None,
                   n: int = 2) -> list[dict]:
        with self._conn() as c:
            if from_id and to_id:
                rows = c.execute(
                    "SELECT * FROM state_journal WHERE id BETWEEN ? AND ? ORDER BY id",
                    (from_id, to_id),
                ).fetchall()
            elif to_id:
                rows = c.execute(
                    "SELECT * FROM state_journal WHERE id <= ? ORDER BY id DESC LIMIT ?",
                    (to_id, n),
                ).fetchall()
            elif from_id:
                row = c.execute(
                    "SELECT * FROM state_journal WHERE id >= ? ORDER BY id LIMIT ?",
                    (from_id, n),
                ).fetchall()
                # get one before too for context
                prev = c.execute(
                    "SELECT * FROM state_journal WHERE id < ? ORDER BY id DESC LIMIT 1",
                    (from_id,),
                ).fetchone()
                if prev:
                    row.insert(0, dict(prev))
                rows = row
            else:
                rows = c.execute(
                    "SELECT * FROM state_journal ORDER BY id DESC LIMIT ?",
                    (n,),
                ).fetchall()
                rows = list(reversed(rows))
        return [dict(r) for r in rows]

    def _compute_diff(self, older: dict, newer: dict) -> dict[str, Any]:
        changes = {}
        numeric_fields = ["production_findings", "drift_count", "rag_feedback_total"]
        json_fields = ["by_severity", "by_target", "by_status"]
        for f in numeric_fields:
            if f in older and f in newer:
                a, b = older[f] or 0, newer[f] or 0
                if a != b:
                    changes[f] = {"from": a, "to": b, "delta": b - a}

        for f in json_fields:
            old_d = json.loads(older.get(f) or "{}")
            new_d = json.loads(newer.get(f) or "{}")
            diff = {}
            for k in set(list(old_d.keys()) + list(new_d.keys())):
                ov = old_d.get(k, 0)
                nv = new_d.get(k, 0)
                if ov != nv:
                    diff[k] = {"from": ov, "to": nv, "delta": nv - ov}
            if diff:
                changes[f] = diff

        # Drift comparison
        old_drifts = {d.get("subject", str(d)): d
                      for d in (json.loads(older.get("drifts") or "[]"))}
        new_drifts = {d.get("subject", str(d)): d
                      for d in (json.loads(newer.get("drifts") or "[]"))}
        drift_added = [v for k, v in new_drifts.items() if k not in old_drifts]
        drift_resolved = [v for k, v in old_drifts.items() if k not in new_drifts]

        # RAG accuracy change
        rag_change = None
        if older.get("rag_accuracy") is not None and newer.get("rag_accuracy") is not None:
            a, b = older["rag_accuracy"], newer["rag_accuracy"]
            if a != b:
                rag_change = {"from": a, "to": b, "delta": round(b - a, 4)}

        return {
            "meta": {
                "from_id": older["id"],
                "to_id": newer["id"],
                "from_ts": older["created_at"],
                "to_ts": newer["created_at"],
                "session_from": older.get("session_id"),
                "session_to": newer.get("session_id"),
            },
            "changes": changes,
            "drift": {
                "added": drift_added,
                "resolved": drift_resolved,
            },
            "rag": rag_change,
        }

    # ── history ──

    def history(self, limit: int = 10) -> list[dict]:
        """Recent snapshots, newest first."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT id, session_id, snapshot_type, production_findings, "
                "drift_count, rag_accuracy, created_at "
                "FROM state_journal ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── trend ──

    def trend(self, field: str = "production_findings", limit: int = 20) -> list[dict]:
        """Values of a numeric field over time, oldest first."""
        allowed = {"production_findings", "drift_count", "rag_accuracy", "rag_feedback_total"}
        if field not in allowed:
            return [{"error": f"field must be one of {sorted(allowed)}"}]
        with self._conn() as c:
            rows = c.execute(
                f"SELECT id, {field} AS val, created_at FROM state_journal ORDER BY id",
            ).fetchall()
        return [dict(r) for r in rows[-limit:]]

    # ── format for display ──

    def format_diff(self, diff_result: dict) -> str:
        """Pretty-print a diff result."""
        if "error" in diff_result:
            return f"⚠️  {diff_result['error']}"

        meta = diff_result["meta"]
        lines = [
            f"📊 State Diff: snapshot #{meta['from_id']} → #{meta['to_id']}",
            f"   {meta['from_ts']}  →  {meta['to_ts']}",
        ]

        changes = diff_result.get("changes", {})
        if numeric := {k: v for k, v in changes.items()
                       if isinstance(v, dict) and "delta" in v and k in ("production_findings", "drift_count", "rag_feedback_total")}:
            lines.append(f"\n📈 Numeric changes:")
            for f, c in numeric.items():
                icon = "📈" if c["delta"] > 0 else "📉"
                lines.append(f"   {icon} {f}: {c['from']} → {c['to']} ({c['delta']:+d})")

        if sev := changes.get("by_severity"):
            lines.append(f"\n🎯 Severity shifts:")
            for k, c in sorted(sev.items(), key=lambda x: (
                ["critical", "high", "medium", "low", "info", "none"].index(x[0].lower())
                if x[0].lower() in ["critical", "high", "medium", "low", "info", "none"]
                else 99, x[0])):
                icon = "📈" if c["delta"] > 0 else "📉"
                lines.append(f"   {icon} {k}: {c['from']} → {c['to']} ({c['delta']:+d})")

        if tgt := changes.get("by_target"):
            lines.append(f"\n🎯 Target shifts:")
            for k, c in sorted(tgt.items(), key=lambda x: -abs(x[1]["delta"])):
                icon = "📈" if c["delta"] > 0 else "📉"
                lines.append(f"   {icon} {k}: {c['from']} → {c['to']} ({c['delta']:+d})")

        if sts := changes.get("by_status"):
            lines.append(f"\n📋 Status shifts:")
            for k, c in sorted(sts.items(), key=lambda x: -abs(x[1]["delta"])):
                icon = "📈" if c["delta"] > 0 else "📉"
                lines.append(f"   {icon} {k}: {c['from']} → {c['to']} ({c['delta']:+d})")

        drift = diff_result.get("drift", {})
        if drift.get("added"):
            lines.append(f"\n🚨 New drifts ({len(drift['added'])}):")
            for d in drift["added"]:
                lines.append(f"   • {d.get('kind','?')}: {d.get('detail','')[:100]}")

        if drift.get("resolved"):
            lines.append(f"\n✅ Resolved drifts ({len(drift['resolved'])}):")
            for d in drift["resolved"]:
                lines.append(f"   ✓ {d.get('kind','?')}: {d.get('detail','')[:100]}")

        if diff_result.get("rag"):
            r = diff_result["rag"]
            icon = "📈" if r["delta"] > 0 else "📉"
            lines.append(f"\n🧠 RAG accuracy: {r['from']:.1%} → {r['to']:.1%} ({icon} {r['delta']:+.1%})")

        return "\n".join(lines)

    def format_history(self, entries: list[dict]) -> str:
        """Pretty-print history entries."""
        if not entries:
            return "📭 No snapshots yet."
        lines = ["📋 State Journal History:", ""]
        lines.append(f"  {'ID':<4s}  {'Type':<12s}  {'Findings':<9s}  {'Drift':<6s}  {'RAG':<8s}  {'Session':<20s}  {'Timestamp'}")
        lines.append(f"  {'-'*4}  {'-'*12}  {'-'*9}  {'-'*6}  {'-'*8}  {'-'*20}  {'-'*19}")
        for r in entries:
            acc = f"{r['rag_accuracy']:.0%}" if r['rag_accuracy'] else "-"
            ses = r['session_id'] or "-"
            lines.append(f"  {r['id']:<4d}  {r['snapshot_type']:<12s}  {r['production_findings']:<9d}  {r['drift_count']:<6d}  {acc:<8s}  {ses:<20s}  {r['created_at']}")
        return "\n".join(lines)
