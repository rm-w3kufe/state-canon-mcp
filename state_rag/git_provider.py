"""GitStateProvider + GitReconciler — version control as a state instance.

git is already a reconciler: index/HEAD = the DECLARED state, the working tree =
the OBSERVED reality, `git status` = a drift report. This maps the existing
primitive onto git with no new concepts.

Read-only: only ever runs `git` query/plumbing subcommands (status, log, branch,
tag, remote, rev-parse). Never mutates the repo.

VCS-agnostic note: nothing in the core knows about git — this is just one provider.
The same shape over jj/hg/svn is another provider.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .provider import StateProvider
from .reconcile import Drift, Reconciler

# Only these git subcommands are ever invoked. Read-only by allow-list.
_ALLOWED = {"status", "log", "branch", "tag", "remote", "rev-parse", "config"}


def _git(repo: Path, *args: str, timeout: float = 10) -> str:
    if args and args[0] not in _ALLOWED:
        raise ValueError(f"git subcommand not allowed (read-only provider): {args[0]}")
    out = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, timeout=timeout,
    )
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {out.stderr.strip()}")
    return out.stdout


class GitStateProvider(StateProvider):
    """Domains: status, branches, tags, remotes, log, meta."""

    def __init__(self, repo_path: str | Path, log_limit: int = 20):
        self.repo = Path(repo_path)
        self.log_limit = log_limit
        if not (self.repo / ".git").exists() and not (self.repo / "HEAD").exists():
            # allow bare repos and worktrees; a hard check happens on first query
            _git(self.repo, "rev-parse", "--git-dir")

    def list_domains(self) -> list[str]:
        return ["status", "branches", "tags", "remotes", "log", "meta"]

    def _status(self) -> list[dict[str, Any]]:
        # porcelain v1: XY<space>path ; renames as "orig -> new"
        rows: list[dict[str, Any]] = []
        for ln in _git(self.repo, "status", "--porcelain").splitlines():
            if not ln:
                continue
            xy, path = ln[:2], ln[3:]
            rows.append({
                "path": path,
                "code": xy,
                "staged": xy[0] not in " ?",
                "worktree_modified": xy[1] not in " ",
                "untracked": xy == "??",
            })
        return rows

    def _branches(self) -> list[dict[str, Any]]:
        fmt = "%(refname:short)%09%(upstream:short)%09%(upstream:track)%09%(objectname:short)"
        rows = []
        for ln in _git(self.repo, "branch", f"--format={fmt}").splitlines():
            if not ln.strip():
                continue
            name, upstream, track, sha = (ln.split("\t") + ["", "", ""])[:4]
            rows.append({"name": name, "upstream": upstream or None,
                         "track": track.strip("[]") or None, "head": sha})
        return rows

    def _simple(self, *args: str, key: str) -> list[dict[str, Any]]:
        return [{key: v} for v in _git(self.repo, *args).split()]

    def _log(self) -> list[dict[str, Any]]:
        fmt = "%h%x09%an%x09%ad%x09%s"
        rows = []
        for ln in _git(self.repo, "log", f"-{self.log_limit}",
                       f"--pretty=format:{fmt}", "--date=short").splitlines():
            if not ln:
                continue
            h, an, ad, s = (ln.split("\t") + ["", "", "", ""])[:4]
            rows.append({"commit": h, "author": an, "date": ad, "subject": s})
        return rows

    def _meta(self) -> dict[str, Any]:
        head = _git(self.repo, "rev-parse", "--short", "HEAD").strip()
        try:
            branch = _git(self.repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
        except RuntimeError:
            branch = "(detached)"
        return {"system": f"git:{self.repo.name}", "repo": str(self.repo),
                "head": head, "branch": branch}

    def query(self, domain: str, filter: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if domain == "status":
            records = self._status()
        elif domain == "branches":
            records = self._branches()
        elif domain == "tags":
            records = self._simple("tag", key="tag")
        elif domain == "remotes":
            records = self._simple("remote", key="remote")
        elif domain == "log":
            records = self._log()
        elif domain == "meta":
            records = [self._meta()]
        else:
            return []
        if filter:
            records = [r for r in records if all(r.get(k) == v for k, v in filter.items())]
        return records


class GitReconciler(Reconciler):
    """Working-tree drift = git status, typed into the standard drift kinds.

    orphan               = untracked file
    declared_but_missing = tracked file deleted in the worktree
    mismatch             = modified/staged file · branch ahead-or-behind its upstream
    """

    domain = "status"

    def __init__(self, provider: GitStateProvider):
        self.provider = provider

    # These aren't used directly (we override diff) but satisfy the ABC and
    # document the declared/observed mapping.
    def declared(self) -> list[dict]:
        return [{"name": b["name"], "state": "tracked"} for b in self.provider.query("branches")]

    def observe(self) -> list[dict]:
        return self.provider.query("status")

    def diff(self) -> list[Drift]:
        drifts: list[Drift] = []
        for r in self.provider.query("status"):
            path, code = r["path"], r["code"]
            if r["untracked"]:
                drifts.append(Drift("orphan", path, f"untracked file: {path}", {"code": code}))
            elif "D" in code:
                drifts.append(Drift("declared_but_missing", path,
                                    f"tracked file deleted in worktree: {path}", {"code": code}))
            else:
                drifts.append(Drift("mismatch", path,
                                    f"working-tree change ({code.strip()}): {path}", {"code": code}))
        for b in self.provider.query("branches"):
            if b.get("track") and ("ahead" in b["track"] or "behind" in b["track"]):
                drifts.append(Drift("mismatch", b["name"],
                                    f"branch {b['name']} {b['track']} vs {b['upstream']}",
                                    {"upstream": b["upstream"]}))
        return drifts


def load(repo_path: str | Path):
    """(provider, [reconciler]) for a git repository."""
    provider = GitStateProvider(repo_path)
    return provider, [GitReconciler(provider)]


DIGEST_POLICY = {
    "status":   {"fields": ["path", "code"], "max": 40},
    "branches": {"fields": ["name", "track"], "max": 20},
    "log":      {"fields": ["commit", "date", "subject"], "max": 8},
    "tags":     {"max": 20},
    "remotes":  {"max": 10},
}
