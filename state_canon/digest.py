"""DigestAssembler — the compact onboard digest.

This text sits in the model's context (the C1 front-load path / state://digest):
compactness IS the point. Registered domains + live reconcilers + a per-domain
POLICY (what matters) → a terse, grounded summary an agent can act on without
exploration.

The policy exists because reality demanded it: the first run over a real
production canon produced a 44k-char digest (64-char binary hashes, exec paths, timestamps
— all true, none of it onboard-worthy). Policy shape, per domain:
  {"fields": [...]}   → only these fields, in this order (first = the label)
  {"max": n}          → cap records (default 50)
  {"last": True}      → take the LAST n records (e.g. recent deploys)
  {"skip": True}      → omit the domain entirely
"""
from __future__ import annotations

from typing import Any

from .provider import StateProvider
from .reconcile import Reconciler

Policy = dict[str, dict[str, Any]]


def _fmt_record(r: dict, fields: list[str] | None = None) -> str:
    if fields:
        label = str(r.get(fields[0], "?"))
        rest = [f"{k}={r[k]}" for k in fields[1:] if r.get(k) is not None]
        return label + (" [" + " ".join(rest) + "]" if rest else "")
    conventional = next(((k, r[k]) for k in ("name", "id", "rule", "value") if k in r), None)
    if conventional is not None:
        skip = {"name", "id", "value", "evidence"}
        name = str(conventional[1])
    else:
        # No conventional identifier field present — fall back to the record's
        # first field instead of a bare, uninformative "?".
        first = next(iter(r.items()), None)
        name = f"{first[0]}={first[1]}" if first else "?"
        skip = {first[0]} if first else set()
    rest = [f"{k}={v}" for k, v in r.items()
            if k not in skip and not isinstance(v, (dict, list)) and v is not None]
    return name + (" [" + " ".join(rest) + "]" if rest else "")


def assemble(provider: StateProvider,
             reconcilers: list[Reconciler] | None = None,
             max_records: int = 50,
             policy: Policy | None = None) -> str:
    """Build the digest. Live reconcilers (if given) take precedence over any
    stored 'drift' domain — fresh reality beats a stale snapshot."""
    policy = policy or {}
    lines: list[str] = []

    meta = (provider.query("meta") or [{}])[0]
    system = meta.get("system", provider.__class__.__name__)
    stamp = meta.get("reconciled_at", "")
    lines.append(f"CURRENT STATE ({system}{', ' + stamp if stamp else ''})")

    live_drift: list[dict] = []
    if reconcilers:
        for rec in reconcilers:
            live_drift += [d.as_dict() for d in rec.diff()]

    for domain in provider.list_domains():
        if domain == "meta" or (domain == "drift" and live_drift):
            continue
        p = policy.get(domain, {})
        if p.get("skip"):
            continue
        records = provider.query(domain)
        total = len(records)
        cap = p.get("max", max_records)
        records = records[-cap:] if p.get("last") else records[:cap]
        if records:
            shown = f"{total}" if total == len(records) else f"{len(records)}/{total}"
            lines.append(f"{domain}({shown}): " +
                         " · ".join(_fmt_record(r, p.get("fields")) for r in records))

    if live_drift:
        lines.append(f"drift-live({len(live_drift)}): " +
                     " · ".join(f"{d['kind']}:{d['subject']} — {d['detail']}" for d in live_drift))

    last = meta.get("last_decision")
    if isinstance(last, dict):
        lines.append(f"last_decision: {last.get('id', '')} {last.get('text', '')}".strip())

    return "\n".join(lines)
