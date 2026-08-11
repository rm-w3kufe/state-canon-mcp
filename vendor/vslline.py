#!/usr/bin/env python3
"""vslline.py — one shared structural line-reader for every .vsm reader.

WHAT THIS IS
------------
The lexical core extracted verbatim from scripts/vsl/tokenizer.py's
`_scan_line` (2026-08-11, VSLLINE-SHARED-TOKENIZER-2026-08-11): a single
character scan of ONE physical VSL line that knows where strings and `//`
comments are, blanks their BODIES out, and leaves only structural
characters. It answers the question every brace/depth/declaration counter
in this repo was guessing at with regexes: "which braces are real?".

Two independent hand-rolled imitations of this existed in parsers that
read TASKS.vsm — tasks_provider.py's `_structural_brace_delta` and
onboard.sh's form-B collect loop — and the divergence between them cost a
full day on 2026-08-10 (BOOT-RECONCILE-2026-08-10 P2 brace-in-string, P4
indentation). Both are now wired onto THIS module; tokenizer.py itself
imports it rather than keeping its own copy. One implementation, three
consumers, one pin (see checks/vslline-manifest-valid).

SCOPE DISCIPLINE
----------------
This is the LEXICAL read only: string state, comment recognition, brace
depth. It deliberately carries NO Doc/Line taxonomy, NO declaration
detection, NO kind/name logic — tokenizer.py owns the semantics on top.
If a consumer needs to know whether a line "is a task header", that is its
grammar, not this module's. Keeping this file small and pure is what lets
it be vendored byte-identical into state-canon-mcp (a multi-project tool
that must not hard-wire a vsf-specific import) and pinned by hash.

VSL SPECIFICS baked in (each learned from a real defect, see tokenizer.py
for the incident history):
  * `//` opens a comment, but `://` inside a URL does not
  * a string may span many lines (VSL quoted blocks are containers)
  * inside a string, a backslash-quote is an escape; OUTSIDE a string,
    a backslash is NOT an escape (set difference WΩ\\A, BNF classes
    [a-zA-Z0-9./\\-]*)
  * blanking preserves column positions, so callers can report locations

Deterministic, stdlib-only. No LLM in this path (R10).
Self-test:  python3 scripts/vsl/vslline.py --selftest
"""
from __future__ import annotations

__all__ = ["scan_line", "brace_delta"]


def scan_line(raw: str, in_string: bool) -> tuple[str, bool]:
    """Return (code, still_in_string) for one physical VSL line.

    `code` keeps structural characters and blanks out comment text and
    string BODIES. Blanking rather than deleting preserves column
    positions, which matters when a caller wants to report a location.
    `in_string` is the quote state at line start (VSL strings span lines).
    """
    out = []
    i, n = 0, len(raw)
    while i < n:
        ch = raw[i]
        if in_string:
            # An ESCAPED quote does not close the string. vsl_language's
            # BNF section quotes literals as \" — without this the state
            # flipped on every one of them, desynchronised, and then
            # reported the document as having an unclosed block.
            if ch == "\\" and i + 1 < n:
                out.append("  "); i += 2; continue
            if ch == '"':
                in_string = False
                out.append('"')
            else:
                out.append(" ")
            i += 1
            continue
        # `//` opens a comment unless it is part of `://`
        if ch == "/" and i + 1 < n and raw[i + 1] == "/":
            if not (i > 0 and raw[i - 1] == ":"):
                out.append(" " * (n - i))
                break
            out.append(ch); i += 1; continue
        # OUTSIDE a string, `\` is NOT an escape: VSL writes set
        # difference (vol(W_Ω\A)) and BNF character classes
        # ([a-zA-Z0-9_./\-]*). Treating it as an escape here would blank
        # the character after it — including a real `{`.
        if ch == '"':
            in_string = True
            out.append('"')
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out), in_string


def brace_delta(code: str) -> int:
    """Structural brace delta of an already-scanned line.

    The caller must pass a line produced by scan_line (or, equivalently,
    one already stripped of string bodies and comment tails) so that
    braces inside quoted values — math literals like `{x : L(x) ≤ τ}` or
    a session note quoting `ident = { sin paréntesis` — do not count.
    """
    return code.count("{") - code.count("}")


# ── self-test ────────────────────────────────────────────────────────────────
# The acceptance fixtures from checks/tasks-census-converge (the two
# defects that cost BOOT-RECONCILE-2026-08-10): a quoted '{' inside a
# session note, and an indented task() definition. scan_line has no
# notion of a "line kind", so the test asserts the LEXICAL facts the
# consumers rely on.
CASES = [
    # 1. brace-in-string: a '{' inside a quoted value must not count.
    ('  note: "ident = { sin paréntesis"', False,
     False, 0),          # raw, began_in_string, opens_string, delta
    # 2. braces inside a math literal must not count either.
    ('  s: "the set {x : L(x) ≤ τ} and [a,b)"', False,
     False, 0),
    # 3. a real open brace DOES count.
    ('task("ID", status=open) = {', False, False, 1),
    # 4. a real close brace counts back.
    ("}", False, False, -1),
    # 5. unterminated string: delta until the quote, string still open.
    ('  what: "an open value', False, True, 0),
    # 6. a string begun on a PREVIOUS line — brace inside is not counted.
    ('the set {x} still inside the value', True, True, 0),
    # 7. // comment swallows the rest of the line (URLs excepted first).
    ('  status = open   // note with { brace', False, False, 0),
    # 8. :// inside a URL is not a comment opener.
    ('  u: "http://x/y"', False, False, 0),
    # 9. escaped quote inside a string does not close it.
    ('  bnf: "\\"quoted\\""', False, False, 0),
]


def _selftest() -> int:
    ok = fail = 0
    for raw, began, want_open, want_delta in CASES:
        code, end_open = scan_line(raw, began)
        got_delta = brace_delta(code)
        if end_open == want_open and got_delta == want_delta:
            ok += 1
        else:
            fail += 1
            print(f"  ✗ {raw!r}: want opens={want_open} delta={want_delta}, "
                  f"got opens={end_open} delta={got_delta}")
    print(f"  vslline selftest: {ok} passed, {fail} failed")
    return 1 if fail else 0


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(_selftest())