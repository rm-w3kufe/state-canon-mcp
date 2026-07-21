"""microstack instance — the controlled corpus as a reference instance.

declared = raw/manifest.txt · reality = raw/processes.txt. The 3 drifts in
GROUND_TRUTH.md must FALL OUT of the generic diff + one rule (R1) — if they
don't, the abstraction is wrong, not the corpus.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from state_rag.provider import JsonStateProvider
from state_rag.reconcile import Drift, Reconciler


def parse_manifest(path: Path) -> list[dict]:
    rows = []
    for ln in path.read_text().splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        svc, node, state, ver, deps = [p.strip() for p in ln.split("|")]
        rows.append({"name": svc, "node": node, "state": state, "version": ver,
                     "depends_on": [] if deps == "-" else [d.strip() for d in deps.split(",")]})
    return rows


def parse_processes(path: Path) -> list[dict]:
    rows, node = [], None
    for ln in path.read_text().splitlines():
        ln = ln.strip()
        if ln.startswith("## "):
            node = ln[3:].strip()
            continue
        if not ln or ln.startswith("#"):
            continue
        parts = ln.split()
        version = next((p.split("=", 1)[1] for p in parts if p.startswith("--version=")), None)
        rows.append({"name": parts[1], "node": node, "pid": int(parts[0]),
                     "state": parts[-1], "version": version})
    return rows


def rule_r1_same_version(declared: list[dict], observed: list[dict]) -> list[Drift]:
    """R1: api and worker MUST run the same version (checked against reality)."""
    obs = {o["name"]: o for o in observed}
    api, worker = obs.get("api"), obs.get("worker")
    if api and worker and api.get("version") != worker.get("version"):
        return [Drift("rule_violation", "R1",
                      f"R1: api@{api['version']} != worker@{worker['version']} — versions must match",
                      {"api": api, "worker": worker})]
    return []


class MicrostackReconciler(Reconciler):
    domain = "services"
    rules = [rule_r1_same_version]

    def __init__(self, corpus_dir: str | Path):
        self.raw = Path(corpus_dir) / "raw"

    def declared(self) -> list[dict]:
        return parse_manifest(self.raw / "manifest.txt")

    def observe(self) -> list[dict]:
        return parse_processes(self.raw / "processes.txt")


def load(corpus_dir: str | Path):
    """(provider, [reconciler]) for the microstack corpus."""
    corpus_dir = Path(corpus_dir)
    provider = JsonStateProvider(corpus_dir / "synthesized" / "state.json")
    return provider, [MicrostackReconciler(corpus_dir)]
