"""tasks_provider — VSM task/session file as canonical state.

Parses VSM-notation .vsm files containing ``task()`` and ``session()``
blocks into JSON-structured records exposed as domains ``tasks``,
``sessions``, and ``meta``.  Includes a ``TaskSessionReconciler`` that
flags tasks whose status is open/dispatched/seeded but whose id/ref
appears in a later session's ``resolved:[]`` list — declared-vs-observed
drift, same pattern as the other reconcilers.

Also optionally loads a ``current_focus.json`` file co-located with the
VSM file, providing a ``focus`` domain for per-agent work tracking.

Two call styles::

    # Just the VSM task file
    provider, reconcilers = load("/path/to/TASKS.vsm")

    # From a directory (auto-discovers TASKS.vsm + current_focus.json)
    provider, reconcilers = load("/path/to/project/dir")
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from state_canon.provider import JsonStateProvider, StateProvider
from state_canon.reconcile import Drift, Reconciler

# ── VSM block types and their open-like statuses ──────────────────────
# The reconciler checks these against session resolved:[] references.
OPEN_STATUSES = frozenset({
    "open", "dispatched", "seeded", "investigated",
    "phase_0_dispatched", "phase_a_dispatched",
})
# Also pattern-match: any status containing "dispatched", "open", "seeded"
OPEN_PATTERNS = re.compile(r"\b(open|dispatched|seeded|investigated)\b", re.IGNORECASE)

# Statuses that indicate a task is closed/finished — used by FocusTaskReconciler
# to flag focus entries that track already-done tasks.
CLOSED_STATUSES = frozenset({
    "done", "closed", "resolved", "deployed", "verified",
    "complete", "completed",
})

# ── Line-based VSM parser ─────────────────────────────────────────────

# Leading whitespace TOLERATED on purpose, mirroring scripts/state/onboard.sh
# (its form A/C census regexes use ^[ \t]*). P4 (BOOT-RECONCILE-2026-08-10
# round 2): TASKS.vsm may contain a task()/session() definition that starts
# indented; a column-0-only regex silently hides it from the census, the same
# failure class as the quoted-'{' P2 bug, one level down.
_BLOCK_START = re.compile(r'^[ \t]*(task|session)\s*\(\s*"([^"]*)"\s*(.*?)\)\s*[=:]\s*\{?\s*$')
_SINGLE_LINE_OLD = re.compile(r'^[ \t]*(task|session)\(([^)]+)\)\s*:\s*(.+)$')
_HEADER_ONLY = re.compile(r'^[ \t]*(task|session)\(([^)]+)\)\s*:\s*$')
_KV_PAIR = re.compile(r'(\w[\w_]*)\s*[=:]\s*(?:"((?:[^"\\]|\\.)*)"|(\[.*?\]|true|false|[\d.]+|\w[\w_]*))')


def _tokenize_attributes(attr_str: str) -> dict[str, Any]:
    """Parse the parenthesised attribute string of a task()/session() header.

    Handles: key=value, key="quoted value", key=[S], key=[S,b],
    which are comma-separated key=value pairs without spaces around =.

    Examples::

        priority=P1, agent=[S], status=open
        priority=P2, agent=ds, status=done
    """
    result: dict[str, Any] = {}
    if not attr_str or not attr_str.strip():
        return result
    # Split on commas NOT inside brackets or quotes
    parts = _split_attrs(attr_str)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            continue
        key, _, raw_val = part.partition("=")
        key = key.strip()
        raw_val = raw_val.strip()
        # Unquote and parse
        if raw_val.startswith('"') and raw_val.endswith('"'):
            result[key] = raw_val[1:-1]
        elif raw_val.startswith("["):
            # List like [S] or [S,b] — strip brackets and split
            inner = raw_val[1:-1].strip()
            result[key] = [x.strip() for x in inner.split(",") if x.strip()] if inner else []
        elif raw_val in ("true", "True"):
            result[key] = True
        elif raw_val in ("false", "False"):
            result[key] = False
        else:
            # Try number, fall back to string
            try:
                result[key] = int(raw_val)
            except ValueError:
                try:
                    result[key] = float(raw_val)
                except ValueError:
                    result[key] = raw_val
    return result


def _split_attrs(s: str) -> list[str]:
    """Split comma-separated attribute string, respecting brackets and quotes."""
    parts = []
    depth = 0
    in_quote = False
    current = []
    for ch in s:
        if ch == '"':
            in_quote = not in_quote
            current.append(ch)
        elif ch == "[" and not in_quote:
            depth += 1
            current.append(ch)
        elif ch == "]" and not in_quote:
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0 and not in_quote:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current))
    return parts


def _parse_kv_continuation(lines: list[str]) -> dict[str, Any]:
    """Parse indented continuation KV pairs::

        key: value
        key: "multiline
          continued value"
        key = value
        key: [
          "item1",
          "item2",
        ]
    """
    result: dict[str, Any] = {}

    # First pass: collect bracket blocks (key: [...]) separately
    bracket_key: str | None = None
    bracket_lines: list[str] = []
    regular_lines: list[str] = []

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("//"):
            continue

        # If we're collecting a bracket block
        if bracket_key is not None:
            bracket_lines.append(line)
            # Check for closing bracket (with optional trailing comma)
            stripped = line.rstrip().rstrip(",").strip()
            if stripped.endswith("]") and not stripped.endswith("]]"):
                # End of bracket block — strip the trailing ] and any comma after it
                closed_text = " ".join(bracket_lines)
                items = re.findall(r'"([^"]*)"', closed_text)
                result[bracket_key] = items
                bracket_key = None
                bracket_lines = []
            continue

        # Check if this line starts a bracket block: key: [  or  key = [
        bm = re.match(r'(\w[\w_]*)\s*[=:]\s*\[\s*$', line)
        if bm:
            bracket_key = bm.group(1)
            bracket_lines = [line]
            # Check if bracket closes on same line
            stripped = line.rstrip().rstrip(",").strip()
            if stripped.endswith("]") and not stripped.endswith("]]"):
                closed_text = " ".join(bracket_lines)
                items = re.findall(r'"([^"]*)"', closed_text)
                result[bracket_key] = items
                bracket_key = None
                bracket_lines = []
            continue

        regular_lines.append(line)

    # If bracket block never closed, add what we have as raw text
    if bracket_key is not None:
        result[bracket_key] = " ".join(bracket_lines)

    # Second pass: join continuation lines (indented continuation of a quoted value)
    joined_lines = []
    i = 0
    while i < len(regular_lines):
        line = regular_lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            i += 1
            continue
        # If line starts with whitespace and previous line needs continuation
        if line.startswith((" ", "\t")) and joined_lines and joined_lines[-1].endswith('"'):
            joined_lines[-1] += " " + stripped
        else:
            joined_lines.append(stripped)
        i += 1

    for line in joined_lines:
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        for m in _KV_PAIR.finditer(line):
            key = m.group(1)
            if key in result:
                continue  # already set from bracket block
            if m.group(2) is not None:
                result[key] = m.group(2)
            else:
                val = m.group(3)
                if val in ("true", "True"):
                    result[key] = True
                elif val in ("false", "False"):
                    result[key] = False
                else:
                    try:
                        result[key] = int(val)
                    except ValueError:
                        try:
                            result[key] = float(val)
                        except ValueError:
                            if val.startswith("[") and val.endswith("]"):
                                inner = val[1:-1].strip()
                                result[key] = [x.strip() for x in inner.split(",") if x.strip()] if inner else []
                            else:
                                result[key] = val
    return result


def _structural_brace_delta(line: str, in_string: bool) -> tuple[int, bool]:
    """Count structural braces in a line, ignoring those inside string literals
    and ``//`` comments. Returns ``(delta, in_string)`` where ``in_string`` is
    the quote state at end of line (VSL double-quoted strings may span lines).

    NOT ``line.count("{") - line.count("}")``: brace counting must be
    string-aware or a literal ``{`` quoted inside a body value (real case:
    TASKS.vsm session 2026-08-05-ds-worklist-vsl, note line quoting
    ``ident = { sin paréntesis``) inflates block depth, the close-brace
    collector never reaches 0, and everything after that point — including
    real task() blocks — is silently swallowed into the wrong record. That
    exact bug dropped DASHAI-S4-LAB-EVAL and VSF-FEED-SPEC-REVIEW from the
    parsed census until 2026-08-10 (BOOT-RECONCILE-2026-08-10).
    """
    delta = 0
    n = len(line)
    i = 0
    while i < n:
        ch = line[i]
        if in_string:
            if ch == "\\":
                i += 2  # skip escaped char (same rule as _KV_PAIR)
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            i += 1
            continue
        if ch == "/" and i + 1 < n and line[i + 1] == "/":
            break  # rest of line is a comment
        if ch == "{":
            delta += 1
        elif ch == "}":
            delta -= 1
        i += 1
    return delta, in_string


def _parse_resolved_list(raw: Any) -> list[str]:
    """Parse a ``resolved: [...]`` value into a list of task references.

    Handles both list-of-strings and the VSM multi-line style where the
    value is a string with bullet-like items::

        resolved: [
            "TASK-ID — description",
            "OTHER-TASK — evidence",
        ]
    """
    if isinstance(raw, list):
        return [str(x) for x in raw]
    if isinstance(raw, str):
        # Extract quoted strings from brackets
        items = re.findall(r'"([^"]*)"', raw)
        return items
    return []


def _extract_references(text: str) -> list[str]:
    """Extract task references from resolved:[] text entries.

    A resolved entry looks like::

        "TASK-ID — description of what was done"

    or::

        "TASK-ID — evidence of completion"

    Returns the task ID (everything before `` — `` or first space).
    """
    # Try " — " separator first
    if " — " in text:
        return [text.split(" — ")[0].strip()]
    # Fall back to first word
    first = text.split()[0].strip() if text.split() else text
    return [first]


def _is_open_status(status: Any) -> bool:
    """Check if a task status is considered 'open' for drift detection."""
    if not status:
        return False
    s = str(status).lower().strip()
    return bool(OPEN_PATTERNS.search(s))


def _is_closed_status(status: Any) -> bool:
    """Check if a task status indicates the work is finished.

    Used by FocusTaskReconciler to detect focus entries tracking
    tasks that are already done.
    """
    if not status:
        return False
    s = str(status).lower().strip()
    return s in CLOSED_STATUSES or any(
        s.startswith(prefix) for prefix in ("done", "closed", "complete")
    )


def parse_vsm_file(path: str | Path) -> dict[str, Any]:
    """Parse a .vsm file into structured records.

    Returns::

        {
            "tasks": [ ... ],
            "sessions": [ ... ],
            "meta": { "path": ..., "lines": ..., "tasks_count": ...,
                      "sessions_count": ..., "sha256": ... }
        }
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    tasks: list[dict[str, Any]] = []
    sessions: list[dict[str, Any]] = []

    i = 0
    while i < len(lines):
        line = lines[i]

        # Skip header and comment lines
        if line.startswith("@vsm") or line.strip().startswith("//"):
            i += 1
            continue

        # Try new-style block start: task("ID", ...) = {
        m = _BLOCK_START.match(line)
        if m:
            block_type = m.group(1)
            block_id = m.group(2)
            attr_str = m.group(3)
            attrs = _tokenize_attributes(attr_str)
            has_open_brace = "{" in line

            i += 1
            body_lines = []
            if has_open_brace:
                # Collect until closing brace. Brace depth is structural only —
                # braces inside double-quoted strings and // comments must not
                # count (see _structural_brace_delta; naive counting swallowed
                # every block after a quoted '{' in TASKS.vsm).
                brace_depth = 1
                in_string = False
                while i < len(lines) and brace_depth > 0:
                    cl = lines[i]
                    body_lines.append(cl)
                    delta, in_string = _structural_brace_delta(cl, in_string)
                    brace_depth += delta
                    if brace_depth <= 0:
                        # Remove the closing brace line (or its leftover part)
                        # Actually the whole line is included; we'll strip braces later
                        break
                    i += 1
                # Strip trailing brace from last line
                if body_lines:
                    last = body_lines[-1]
                    idx = last.rfind("}")
                    if idx >= 0:
                        body_lines[-1] = last[:idx]
                body_text = "\n".join(body_lines)
                body_kv = _parse_kv_continuation(body_lines)
            else:
                # Check next lines for indented continuation style
                continuation = []
                while i < len(lines):
                    cl = lines[i]
                    if not cl.strip() or cl.strip().startswith("//") or cl.strip() == "}":
                        break
                    if cl.startswith((" ", "\t")):
                        continuation.append(cl)
                        i += 1
                    else:
                        # Check if next line starts with task/session
                        if _BLOCK_START.match(cl) or _SINGLE_LINE_OLD.match(cl):
                            break
                        continuation.append(cl)
                        i += 1
                body_kv = _parse_kv_continuation(continuation)

            record: dict[str, Any] = {"id": block_id, **attrs}

            # Body KV pairs: only for new keys not already in attrs from header
            for k, v in body_kv.items():
                if k not in record:
                    record[k] = v

            # Post-process specific fields
            if "resolved" in record:
                record["resolved"] = _parse_resolved_list(record["resolved"])

            if block_type == "task":
                # Normalise title/what
                if "title" in record and "what" not in record:
                    record["what"] = record["title"]
                tasks.append(record)
            elif block_type == "session":
                sessions.append(record)

            i += 1
            continue

        # Try old-style: task(X): key=value key=value ...
        m = _SINGLE_LINE_OLD.match(line)
        if m:
            block_type = m.group(1)
            block_id = m.group(2).strip().strip('"')
            rest = m.group(3)
            attrs = _parse_kv_continuation([rest])

            # Collect continuation on next lines if indented
            i += 1
            continuation = []
            while i < len(lines):
                cl = lines[i]
                if not cl.strip() or cl.strip().startswith("//") or cl.strip() == "}":
                    break
                if cl.startswith((" ", "\t")):
                    continuation.append(cl)
                    i += 1
                else:
                    break

            body_kv = _parse_kv_continuation(continuation)
            record = {"id": block_id, **attrs, **body_kv}

            if "title" in record and "what" not in record:
                record["what"] = record["title"]

            if block_type == "task":
                tasks.append(record)
            elif block_type == "session":
                sessions.append(record)

            continue

        # Try header-only: task(X):\n  indented body
        m = _HEADER_ONLY.match(line)
        if m:
            block_type = m.group(1)
            block_id = m.group(2).strip().strip('"')

            i += 1
            continuation = []
            while i < len(lines):
                cl = lines[i]
                if not cl.strip() or cl.strip().startswith("//") or cl.strip() == "}":
                    break
                if cl.startswith((" ", "\t")):
                    continuation.append(cl)
                    i += 1
                else:
                    break

            body_kv = _parse_kv_continuation(continuation)
            record = {"id": block_id, **body_kv}

            if "title" in record and "what" not in record:
                record["what"] = record["title"]

            if block_type == "task":
                tasks.append(record)
            elif block_type == "session":
                sessions.append(record)

            continue

        i += 1

    # Post-process: cast resolved/commits to list for all sessions
    for s in sessions:
        raw_resolved = s.get("resolved", [])
        s["resolved"] = _parse_resolved_list(raw_resolved)
        raw_commits = s.get("commits", [])
        if isinstance(raw_commits, str):
            s["commits"] = [c.strip().strip('"') for c in raw_commits.strip("[]").split(",") if c.strip()]
        elif not isinstance(raw_commits, list):
            s["commits"] = [str(raw_commits)]
        # Deduplicate resolved entries
        seen = set()
        deduped = []
        for entry in s["resolved"]:
            if entry not in seen:
                seen.add(entry)
                deduped.append(entry)
        s["resolved"] = deduped

    import hashlib
    sha = hashlib.sha256(text.encode()).hexdigest()

    meta = {
        "path": str(path.resolve()),
        "lines": len(lines),
        "tasks_count": len(tasks),
        "sessions_count": len(sessions),
        "sha256": sha,
    }
    return {"tasks": tasks, "sessions": sessions, "meta": meta}


def _load_focus(path: Path) -> list[dict[str, Any]]:
    """Load a current_focus.json co-located with the task file."""
    focus_file = path.parent / "current_focus.json"
    if not focus_file.exists():
        return []
    try:
        data = json.loads(focus_file.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "focus_items" in data:
            return data["focus_items"]
        return []
    except (json.JSONDecodeError, OSError):
        return []


class VsmStateProvider(JsonStateProvider):
    """JsonStateProvider variant whose document comes from parsing a .vsm
    file (parse_vsm_file), not json.loads — otherwise identical, including
    reload-on-mtime-change (inherited query()/list_domains() both call
    _reload_if_changed() first). A long-lived MCP server session that has
    TASKS.vsm edited on disk (the normal case — agents edit it directly,
    not through this server) now sees the change on the next query, instead
    of serving whatever was parsed once at server startup forever."""

    def __init__(self, vsm_path: str | Path):
        self.path = Path(vsm_path)
        self._mtime = -1.0
        self._doc: dict[str, Any] = {}
        self._reload_if_changed()

    def _reload_if_changed(self) -> None:
        mtime = self.path.stat().st_mtime
        if mtime != self._mtime:
            data = parse_vsm_file(self.path)
            focus_items = _load_focus(self.path)
            if focus_items:
                data["focus"] = focus_items
            self._doc = data
            self._mtime = mtime


def load(path: str | Path):
    """Load a VSM task file (or directory containing TASKS.vsm).

    Returns ``(provider, [reconciler])``.

    If *path* is a directory, looks for ``TASKS.vsm`` inside it.
    If a ``current_focus.json`` exists next to the VSM file, its
    contents are exposed as the ``focus`` domain (used only as a fallback —
    see FocusTaskReconciler.bind_focus_tracker for the live path).
    """
    path = Path(path)
    if path.is_dir():
        vsm_path = path / "TASKS.vsm"
        if not vsm_path.exists():
            raise FileNotFoundError(f"no TASKS.vsm in directory: {path}")
    else:
        vsm_path = path

    provider = VsmStateProvider(vsm_path)

    reconcilers: list[Reconciler] = [
        TaskSessionReconciler(vsm_path),
        FocusTaskReconciler(vsm_path),
    ]

    return provider, reconcilers


# ── Reconciler ────────────────────────────────────────────────────────

@dataclass
class SessionResolvedRef:
    """A single resolved entry with its source session id and text."""
    session_id: str
    text: str

    def ref_ids(self) -> list[str]:
        """Extract candidate task IDs from this resolved entry."""
        return _extract_references(self.text)


class TaskSessionReconciler(Reconciler):
    """Flags tasks whose status says open but whose id is referenced
    as resolved in a later session block.

    This is declared-vs-observed drift: the task record (declared) says
    "still open", but a session (observed reality) says "resolved".
    """

    domain = "tasks"

    def __init__(self, vsm_path: str | Path):
        self._vsm_path = Path(vsm_path)
        # Cached parsed data, invalidated on mtime change (not cached forever —
        # a long server session outlives many direct edits to the VSM file).
        self._data: dict[str, Any] | None = None
        self._data_mtime: float | None = None

    def _get_data(self) -> dict[str, Any]:
        mtime = self._vsm_path.stat().st_mtime
        if self._data is None or mtime != self._data_mtime:
            self._data = parse_vsm_file(self._vsm_path)
            self._data_mtime = mtime
        return self._data

    def declared(self) -> list[dict]:
        """Tasks — the declared state."""
        return self._get_data().get("tasks", [])

    def observe(self) -> list[dict]:
        """Sessions — the observed reality of what was resolved."""
        return self._get_data().get("sessions", [])

    def diff(self) -> list[Drift]:
        data = self._get_data()
        tasks = data.get("tasks", [])
        sessions = data.get("sessions", [])

        # Build a map: session id → list of resolved reference ids
        session_resolved: dict[str, list[str]] = {}
        for sess in sessions:
            sid = sess.get("id", "")
            raw = sess.get("resolved", [])
            refs: list[str] = []
            for entry in raw:
                refs.extend(_extract_references(entry))
            if refs:
                session_resolved[sid] = refs

        # Collect all task IDs that are referenced as resolved in ANY session
        resolved_task_ids: set[str] = set()
        for sid, refs in session_resolved.items():
            resolved_task_ids.update(refs)

        # Build task lookup
        task_map: dict[str, dict] = {}
        for t in tasks:
            tid = t.get("id", "")
            # Also index by alternative name fields
            task_map[tid] = t
            for alt_field in ("name", "title", "ref"):
                alt_val = t.get(alt_field)
                if alt_val and alt_val not in task_map:
                    task_map[str(alt_val)] = t

        drifts: list[Drift] = []

        # Check each resolved reference against task status
        for ref in resolved_task_ids:
            task = task_map.get(ref)
            if not task:
                # Reference to something not in task list — could be a
                # session-only reference or a different naming convention.
                # Still flag it as a potential orphan resolution.
                continue

            status = task.get("status", "")
            if _is_open_status(status):
                # Find which session resolved it
                resolving_sessions = [
                    sid for sid, refs in session_resolved.items()
                    if ref in refs
                ]
                drifts.append(Drift(
                    "declared_but_resolved",
                    ref,
                    f"Task '{ref}' has status='{status}' but is referenced "
                    f"as resolved in session(s): {', '.join(resolving_sessions)}",
                    {
                        "task": {k: v for k, v in task.items() if k in ("id", "status", "what", "title")},
                        "resolved_in": resolving_sessions,
                        "status_field": status,
                    },
                ))

        return drifts


class FocusTaskReconciler(Reconciler):
    """Flags focus entries whose status says active/paused but whose
    referenced task is actually done or resolved.

    Two drift kinds:
    - *stale_focus_task_done*: focus entry is active/paused but the task's
      own status is closed-like (done/closed/completed/...)
    - *stale_focus_session_resolved*: focus entry is active/paused but the
      task ref appears in a session's ``resolved:[]`` list (even if the
      task status wasn't updated).

    Domain ``focus`` — coexists with ``TaskSessionReconciler`` (domain
    ``tasks``). Both are wired in ``load()``.

    ``declared()`` prefers, in order: (1) a bound live FocusTracker (see
    ``bind_focus_tracker`` — this is what the server wires up when started
    with ``--focus PATH``, guaranteeing this reads the exact same store
    ``state_focus_mark``/``state_query('focus')`` use, not an independently
    re-derived path that could silently diverge); (2) an explicit
    ``focus_items`` list passed at construction (test/manual-injection use);
    (3) a fresh read of the co-located ``current_focus.json`` next to the
    VSM file, as a last-resort fallback when neither of the above applies
    (e.g. the server was started without ``--focus``).
    """

    domain = "focus"

    def __init__(self, vsm_path: str | Path,
                 focus_items: list[dict] | None = None):
        self._vsm_path = Path(vsm_path)
        self._focus_items = focus_items  # explicit override (tests) — static, by design
        self._focus_tracker = None       # bound later by the server, if --focus is set
        self._data: dict[str, Any] | None = None
        self._data_mtime: float | None = None

    def bind_focus_tracker(self, tracker) -> None:
        """Called by StateRagServer.__init__ when the server was started with
        --focus PATH. Makes declared() read the live, authoritative focus
        store instead of re-deriving a (possibly different) path."""
        self._focus_tracker = tracker

    def _get_data(self) -> dict[str, Any]:
        mtime = self._vsm_path.stat().st_mtime
        if self._data is None or mtime != self._data_mtime:
            self._data = parse_vsm_file(self._vsm_path)
            self._data_mtime = mtime
        return self._data

    def _session_resolved_ids(self) -> set[str]:
        """Build a set of all task refs that appear in session resolved:[] lists.

        Reuses the same reference extraction as TaskSessionReconciler. Not
        cached across calls — cheap to recompute from _get_data() (itself
        already cached-with-freshness), and caching it separately would need
        its own invalidation logic for no real benefit."""
        data = self._get_data()
        sessions = data.get("sessions", [])
        ids: set[str] = set()
        for sess in sessions:
            raw = sess.get("resolved", [])
            for entry in raw:
                ids.update(_extract_references(str(entry)))
        return ids

    # ── Reconciler protocol ──

    def declared(self) -> list[dict]:
        """Focus entries — the declared state. See class docstring for the
        (tracker > explicit override > co-located fallback) priority."""
        if self._focus_tracker is not None:
            return self._focus_tracker.query()
        if self._focus_items is not None:
            return self._focus_items
        return _load_focus(self._vsm_path)

    def observe(self) -> list[dict]:
        """Tasks — the observed reality of whether work is done."""
        return self._get_data().get("tasks", [])

    def diff(self) -> list[Drift]:
        tasks = self._get_data().get("tasks", [])
        focus_entries = self.declared()
        session_resolved = self._session_resolved_ids()

        # Build task map for quick lookup
        task_map: dict[str, dict] = {}
        for t in tasks:
            tid = t.get("id", "")
            task_map[tid] = t
            for alt_field in ("name", "title", "ref"):
                alt_val = t.get(alt_field)
                if alt_val and alt_val not in task_map:
                    task_map[str(alt_val)] = t

        drifts: list[Drift] = []

        for entry in focus_entries:
            ref = entry.get("ref", "")
            if not ref:
                continue

            f_status = entry.get("status", "").lower().strip()

            # Skip already-closed focus entries
            if f_status in ("done", "closed", "resolved", "completed"):
                continue

            # Only flag active/paused entries
            if f_status not in ("", "active", "paused"):
                continue

            task = task_map.get(ref)

            # (a) Task's own status is closed-like
            if task and _is_closed_status(task.get("status", "")):
                task_status = str(task.get("status", ""))
                drifts.append(Drift(
                    "stale_focus_task_done",
                    ref,
                    f"Focus entry '{ref}' is '{f_status}' but task "
                    f"has status='{task_status}'",
                    {
                        "focus_entry": {"ref": ref, "status": entry.get("status", ""),
                                        "note": entry.get("note", "")},
                        "task_status": task_status,
                    },
                ))
                continue

            # (b) Ref appears in session resolved:[] list
            if ref in session_resolved:
                drifts.append(Drift(
                    "stale_focus_session_resolved",
                    ref,
                    f"Focus entry '{ref}' is '{f_status}' but resolved "
                    f"in session",
                    {
                        "focus_entry": {"ref": ref, "status": entry.get("status", ""),
                                        "note": entry.get("note", "")},
                    },
                ))
                continue

        return drifts
