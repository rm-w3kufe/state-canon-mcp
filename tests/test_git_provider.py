"""GitStateProvider tests — self-contained: builds a scratch repo, seeds the three
drift kinds, asserts they fall out of the reconciler. Skips cleanly if git is absent.

Run:  python3 tests/test_git_provider.py   (from projects/state-rag-mcp/)
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if shutil.which("git") is None:
    print("SKIP: git not installed")
    sys.exit(2)

from state_rag.digest import assemble  # noqa: E402
from state_rag.git_provider import DIGEST_POLICY, _git, load  # noqa: E402
from state_rag.server import StateRagServer  # noqa: E402

PASSED = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASSED
    if not cond:
        print(f"✗ FAIL {name} {detail}")
        sys.exit(1)
    PASSED += 1
    print(f"✓ {name}")


def sh(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
                    *args], check=True, capture_output=True)


# ── fixture: scratch repo with the three drift kinds seeded ──
tmp = Path(tempfile.mkdtemp(prefix="gitrag-"))
try:
    sh(tmp, "init", "-q", "-b", "main")
    for f in ("a.txt", "b.txt", "c.txt"):
        (tmp / f).write_text(f"{f}\n")
    sh(tmp, "add", ".")
    sh(tmp, "commit", "-q", "-m", "seed")
    (tmp / "b.txt").write_text("changed\n")   # → mismatch
    (tmp / "c.txt").unlink()                  # → declared_but_missing
    (tmp / "d.txt").write_text("new\n")       # → orphan

    provider, reconcilers = load(tmp)
    server = StateRagServer(provider, reconcilers, DIGEST_POLICY)

    # ── provider ──
    check("git.domains", set(provider.list_domains())
          == {"status", "branches", "tags", "remotes", "log", "meta"})
    meta = provider.query("meta")[0]
    check("git.meta", meta["branch"] == "main" and len(meta["head"]) >= 7, str(meta))
    log = provider.query("log")
    check("git.log", len(log) == 1 and log[0]["subject"] == "seed", str(log))
    st_b = provider.query("status", {"path": "b.txt"})
    check("git.filter", len(st_b) == 1 and st_b[0]["worktree_modified"] is True, str(st_b))
    check("git.unknown-domain-empty", provider.query("nope") == [])

    # ── read-only allow-list: mutating subcommands are rejected ──
    try:
        _git(tmp, "commit", "-m", "nope")
        check("git.readonly-allowlist", False, "commit should have been rejected")
    except ValueError:
        check("git.readonly-allowlist", True)

    # ── reconciler: the three drift kinds fall out ──
    drifts = reconcilers[0].diff()
    kinds = {(d.kind, d.subject) for d in drifts}
    check("git.drift-count", len(drifts) == 3, f"got {len(drifts)}: {kinds}")
    check("git.drift-mismatch", ("mismatch", "b.txt") in kinds)
    check("git.drift-missing", ("declared_but_missing", "c.txt") in kinds)
    check("git.drift-orphan", ("orphan", "d.txt") in kinds)

    # ── digest with the git policy ──
    digest = assemble(provider, reconcilers, policy=DIGEST_POLICY)
    for needle in ("CURRENT STATE (git:", "drift-live(3)", "b.txt", "d.txt", "seed"):
        check(f"git.digest[{needle}]", needle in digest)
    check("git.digest-compact", len(digest) < 3000, f"{len(digest)} chars")

    # ── MCP dispatch: verify catches a dirty-tree lie ──
    out = server.dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": "state_verify",
                                      "arguments": {"domain": "status",
                                                    "filter": {"path": "b.txt"},
                                                    "expect": {"worktree_modified": False}}}})
    v = json.loads(out["result"]["content"][0]["text"])
    check("git.verify-catches-dirty", v["holds"] is False and v["mismatches"], str(v))

    print(f"\nALL {PASSED} CHECKS PASSED")
finally:
    shutil.rmtree(tmp, ignore_errors=True)