"""Tests for FreshnessReconciler.

Run:  python3 tests/test_freshness.py   (from state-canon-mcp/)

Covers:
  - fresh file → no drift
  - stale file → one Drift with kind="stale", correct age_days
  - missing file → one Drift with kind="missing"
  - custom domain name → domain property returns it
  - declared()/observe() contract (list[dict], correct shape)
"""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

# Ensure we can import from the repo root
_SCRIPT_DIR = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(_SCRIPT_DIR))

from state_canon.freshness import FreshnessReconciler

PASSED = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASSED
    if not cond:
        print(f"✗ FAIL {name} {detail}")
        raise SystemExit(1)
    PASSED += 1
    print(f"✓ {name}")


# ── Helpers ───────────────────────────────────────────────────────────


def _make_file(contents: bytes = b"data") -> str:
    """Create a temporary file, return its path.  Caller must unlink."""
    fd, path = tempfile.mkstemp(suffix=".freshness_test")
    os.close(fd)
    with open(path, "wb") as f:
        f.write(contents)
    return path


# ── 1. Fresh file (no drift) ─────────────────────────────────────────

def test_fresh() -> None:
    path = _make_file()
    try:
        r = FreshnessReconciler(path, max_age_seconds=3600, label="fresh-test")
        drifts = r.diff()
        check("fresh.no_drift", len(drifts) == 0, f"got {len(drifts)} drifts: {drifts}")
    finally:
        os.unlink(path)


# ── 2. Stale file (one drift, correct age) ────────────────────────────

def test_stale() -> None:
    path = _make_file()
    try:
        # Set mtime to 3 days ago
        old_ts = time.time() - 3 * 86400
        os.utime(path, (old_ts, old_ts))

        r = FreshnessReconciler(path, max_age_seconds=86400, label="stale-test")
        drifts = r.diff()
        check("stale.one_drift", len(drifts) == 1, f"got {len(drifts)} drifts: {drifts}")
        d = drifts[0]
        check("stale.kind", d.kind == "stale", f"kind={d.kind}")
        check("stale.subject_contains_path", str(path) in d.subject, d.subject)
        check("stale.evidence_has_age_days", "age_days" in d.evidence,
              f"evidence keys: {list(d.evidence.keys())}")
        check("stale.age_days_correct",
              abs(d.evidence["age_days"] - 3.0) < 0.2,
              f"age_days={d.evidence['age_days']}")
    finally:
        os.unlink(path)


# ── 3. Missing file (one drift, kind=missing) ────────────────────────

def test_missing() -> None:
    path = "/tmp/state_canon_freshness_missing_test_XXXX"
    # Ensure it does not exist
    if os.path.exists(path):
        os.unlink(path)
    # Confirm it truly doesn't exist
    assert not os.path.exists(path), f"test bug: {path} should not exist"

    r = FreshnessReconciler(path, max_age_seconds=3600, label="missing-test")
    drifts = r.diff()
    check("missing.one_drift", len(drifts) == 1, f"got {len(drifts)} drifts: {drifts}")
    d = drifts[0]
    check("missing.kind", d.kind == "missing", f"kind={d.kind}")
    check("missing.subject_contains_path", str(path) in d.subject, d.subject)
    check("missing.detail_mentions_not_exist", "does not exist" in d.detail, d.detail)
    check("missing.evidence_has_path", d.evidence.get("path") == str(path),
          f"evidence path={d.evidence.get('path')}")


# ── 4. Custom domain name ────────────────────────────────────────────

def test_custom_domain() -> None:
    path = _make_file()
    try:
        r = FreshnessReconciler(path, max_age_seconds=3600,
                                domain="my-reports", label="custom-domain")
        check("domain.custom", r.domain == "my-reports", f"domain={r.domain}")
    finally:
        os.unlink(path)


# ── 5. declared() / observe() contract ───────────────────────────────

def test_declared_observe_contract() -> None:
    path = _make_file()
    try:
        r = FreshnessReconciler(path, max_age_seconds=3600, label="contract-test")

        dec = r.declared()
        check("declared.is_list", isinstance(dec, list), str(type(dec)))
        check("declared.nonempty", len(dec) >= 1, str(len(dec)))
        check("declared.has_path", dec[0].get("path") == path, str(dec[0]))
        check("declared.has_max_age", dec[0].get("max_age_seconds") == 3600, str(dec[0]))

        obs = r.observe()
        check("observed.is_list", isinstance(obs, list), str(type(obs)))
        check("observed.nonempty", len(obs) >= 1, str(len(obs)))
        check("observed.exists_true", obs[0].get("exists") is True, str(obs[0]))
        check("observed.mtime_is_float", isinstance(obs[0].get("mtime"), float),
              f"mtime type={type(obs[0].get('mtime'))}")
    finally:
        os.unlink(path)


# ── 6. Stale file — verify detail message format ──────────────────────

def test_stale_detail_message() -> None:
    """Message should mention 'days old' and 'max'. """
    path = _make_file()
    try:
        old_ts = time.time() - 48 * 3600  # 2 days ago
        os.utime(path, (old_ts, old_ts))
        r = FreshnessReconciler(path, max_age_seconds=3600,
                                label="detail-msg")
        drifts = r.diff()
        check("detail.one_drift", len(drifts) == 1, str(drifts))
        msg = drifts[0].detail
        check("detail.days_old", "days old" in msg, f"msg={msg}")
        check("detail.max", "max" in msg, f"msg={msg}")
        check("detail.label", "detail-msg" in msg, f"msg={msg}")
    finally:
        os.unlink(path)


# ── Main ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_fresh()
    test_stale()
    test_missing()
    test_custom_domain()
    test_declared_observe_contract()
    test_stale_detail_message()
    print(f"\nALL {PASSED} CHECKS PASSED")
