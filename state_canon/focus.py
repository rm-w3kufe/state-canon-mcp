"""FocusTracker — atomic read-write tracker for a per-agent focus file.

A focus file is a JSON array of {ref, status, note, started_at, updated_at}
entries. One per agent (DS's ~/vsf/current_focus.json, bbh-lab's, etc).

Write side (mark/close) — upsert by ref with atomic temp+rename, guarded by an
flock() around the whole read-modify-write cycle so two near-simultaneous
writers (e.g. two agents sharing one focus file) can't lose an update to each
other — temp+rename alone prevents corruption, not lost writes.
Read side (query) — list or filter entries.

Same architectural role as StateJournal: an opt-in feature enabled via
--focus PATH on the server. Not tied to any specific provider — any
instance can use it.
"""
from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


class FocusTracker:
    """Atomic read-write tracker for a per-agent focus file (JSON array)."""

    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self._lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        self._ensure_file()

    @contextmanager
    def _locked(self) -> Iterator[None]:
        """Exclusive lock spanning a full read-modify-write cycle. A separate
        .lock file is used (not self.path itself) so it doesn't interfere with
        the temp+rename atomic replace of the data file."""
        with open(self._lock_path, "w") as lockfile:
            fcntl.flock(lockfile, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lockfile, fcntl.LOCK_UN)

    def _ensure_file(self) -> None:
        """Create an empty focus file if it doesn't exist."""
        if not self.path.exists():
            self.path.write_text("[]\n")

    def _load(self) -> list[dict[str, Any]]:
        try:
            return json.loads(self.path.read_text())
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def _save(self, entries: list[dict[str, Any]]) -> None:
        """Atomic write via temp file + rename (same filesystem)."""
        raw = json.dumps(entries, indent=2, ensure_ascii=False) + "\n"
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self.path.parent),
            prefix=".focus_",
        )
        try:
            os.write(fd, raw.encode("utf-8"))
        finally:
            os.close(fd)
        os.replace(tmp_path, self.path)

    # ── read ──

    def query(self, ref: str | None = None) -> list[dict[str, Any]]:
        """Return all focus entries, or filter by ref."""
        entries = self._load()
        if ref:
            return [e for e in entries if e.get("ref") == ref]
        return entries

    def list_domains(self) -> list[str]:
        """Return the single domain this tracker exposes."""
        return ["focus"]

    # ── write ──

    def mark(self, ref: str, status: str | None = None,
             note: str | None = None) -> dict[str, Any]:
        """Upsert a focus entry by ref.

        Creates a new entry if ref doesn't exist, or updates status/note
        on an existing one. Always updates timestamp. Returns the entry.
        """
        with self._locked():
            entries = self._load()
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            existing = [e for e in entries if e.get("ref") == ref]
            if existing:
                entry = existing[0]
                if status is not None:
                    entry["status"] = status
                if note is not None:
                    entry["note"] = note
                entry["updated_at"] = now
            else:
                entry = {
                    "ref": ref,
                    "status": status or "active",
                    "note": note or "",
                    "started_at": now,
                    "updated_at": now,
                }
                entries.append(entry)

            self._save(entries)
            return entry

    def close(self, ref: str, note: str | None = None) -> dict[str, Any]:
        """Mark a focus entry as done. Convenience wrapper around mark()."""
        return self.mark(ref, status="done", note=note)
