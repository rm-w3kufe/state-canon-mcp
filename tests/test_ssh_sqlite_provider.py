"""SshSqliteStateProvider tests — mocked subprocess, no network required.

Structural: exercises query-building, shell-quoting safety, and error
handling without touching a real SSH host. For a live round-trip against a
real remote DB, see instances/ssh_sqlite_ops.py's docstring — that's a
manual/deployment-time check, not part of this hermetic suite.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

sys.path.insert(0, str(ROOT / "instances"))

from state_canon.ssh_sqlite_provider import RemoteQueryError, SshSqliteStateProvider  # noqa: E402
import ssh_sqlite_ops  # noqa: E402

PASSED = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASSED
    if not cond:
        print(f"✗ FAIL {name} {detail}")
        sys.exit(1)
    PASSED += 1
    print(f"✓ {name}")


def _mock_run(stdout="[]", returncode=0, stderr=""):
    return mock.Mock(stdout=stdout, returncode=returncode, stderr=stderr)


# ── construction runs one discovery query when domains=None ──
with mock.patch("subprocess.run", return_value=_mock_run(
        json.dumps([{"name": "widgets"}, {"name": "gadgets"}]))) as m:
    p = SshSqliteStateProvider("root@n02", "/tmp/x.db")
    check("ssh.discovers-domains", set(p.list_domains()) == {"widgets", "gadgets", "meta"},
          str(p.list_domains()))
    check("ssh.discovery-called-once", m.call_count == 1)

# ── explicit domains skip discovery ──
with mock.patch("subprocess.run") as m:
    p = SshSqliteStateProvider("root@n02", "/tmp/x.db", domains={"services": "services"})
    check("ssh.explicit-domains-no-discovery-call", m.call_count == 0)

# ── query() shells out to ssh with a properly quoted remote command ──
with mock.patch("subprocess.run", return_value=_mock_run(
        json.dumps([{"name": "id"}, {"name": "active"}]))) as m_cols:
    p = SshSqliteStateProvider("root@n02", "/tmp/x.db", domains={"services": "services"})

with mock.patch("subprocess.run") as m:
    m.side_effect = [
        _mock_run(json.dumps([{"name": "id"}, {"name": "active"}])),  # PRAGMA table_info
        _mock_run(json.dumps([{"id": 1, "active": 1}])),               # SELECT
    ]
    rows = p.query("services", {"active": 1})
    check("ssh.query-returns-rows", rows == [{"id": 1, "active": 1}], str(rows))
    call_args = m.call_args_list[-1][0][0]
    check("ssh.query-invokes-ssh", call_args[0] == "ssh", str(call_args))
    check("ssh.query-targets-host", "root@n02" in call_args, str(call_args))
    remote_cmd = call_args[-1]
    check("ssh.query-remote-cmd-quoted", "sqlite3" in remote_cmd and "-readonly" in remote_cmd,
          remote_cmd)

# ── a value containing shell metacharacters must not break the remote command
#    (this is the exact class of bug the first hand-test caught: unquoted
#    parens in `PRAGMA table_info(services)` were parsed as remote shell
#    syntax before the fix — this test locks that fix in) ──
with mock.patch("subprocess.run") as m:
    m.side_effect = [
        _mock_run(json.dumps([{"name": "id"}, {"name": "note"}])),
        _mock_run("[]"),
    ]
    p.query("services", {"note": "a) evil `rm -rf /` (b"})
    remote_cmd = m.call_args_list[-1][0][0][-1]
    check("ssh.query-value-with-shell-metachars-quoted",
          "rm -rf" in remote_cmd and remote_cmd.count("'") >= 2, remote_cmd)

# ── unknown filter field -> loud ValueError, matches SqliteStateProvider's contract ──
with mock.patch("subprocess.run") as m:
    m.side_effect = [_mock_run(json.dumps([{"name": "id"}]))]
    try:
        p.query("services", {"nonexistent": 1})
        check("ssh.unknown-filter-loud", False, "should have raised")
    except ValueError:
        check("ssh.unknown-filter-loud", True)

# ── nonzero remote exit -> RemoteQueryError, not a silent empty/crash ──
with mock.patch("subprocess.run", return_value=_mock_run(
        stdout="", returncode=1, stderr="Error: no such table: ghosts")):
    p2 = SshSqliteStateProvider("root@n02", "/tmp/x.db", domains={"ghosts": "ghosts"})
    try:
        p2._run_json("SELECT * FROM ghosts")
        check("ssh.remote-error-loud", False, "should have raised")
    except RemoteQueryError as e:
        check("ssh.remote-error-loud", "no such table" in str(e), str(e))

# ── SSH timeout -> RemoteQueryError, not an uncaught TimeoutExpired ──
with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ssh", timeout=30)):
    p3 = SshSqliteStateProvider("root@n02", "/tmp/x.db", domains={"services": "services"})
    try:
        p3._run_json("SELECT 1")
        check("ssh.timeout-loud", False, "should have raised")
    except RemoteQueryError:
        check("ssh.timeout-loud", True)

# ── meta domain works without any subprocess call ──
with mock.patch("subprocess.run") as m:
    p4 = SshSqliteStateProvider("root@n02", "/tmp/x.db", domains={},
                                 meta={"system": "ops"})
    meta = p4.query("meta")
    check("ssh.meta-no-subprocess", m.call_count == 0)
    check("ssh.meta-has-source", meta[0]["source"] == "root@n02:/tmp/x.db", str(meta))

# ── ssh_sqlite_ops.load() parses "host,path" (comma) correctly, and does
#    NOT get corrupted by the CLI's own `--instance MODULE.py:ARG` split,
#    which uses rpartition(":") -- an arg embedding scp-style "host:path"
#    (colon) would silently swallow part of the host into the module path
#    at the CLI layer, one level up from this test. This locks in the
#    comma-separator fix at the load()-parsing level. ──
with mock.patch("subprocess.run", return_value=_mock_run(
        json.dumps([{"name": "services"}]))):
    provider, reconcilers = ssh_sqlite_ops.load("root@n02,/var/lib/vsf-state/state.db")
    check("ssh-ops.load-parses-host", provider.host == "root@n02", provider.host)
    check("ssh-ops.load-parses-path", provider.path == "/var/lib/vsf-state/state.db", provider.path)
    check("ssh-ops.load-has-known-domains",
          {"services", "deploys"} <= set(provider.list_domains()))
    check("ssh-ops.load-rules-retracted", "rules" not in provider.list_domains())

    # R7 (2026-08-11): domain 'rules' is retracted from the VSF ops canon —
    # querying it must raise a loud not-served error pointing at the canonical
    # source (hard_rules.vsm), NOT return a silent [] like an unmapped domain.
    try:
        provider.query("rules")
        check("ssh-ops.query-rules-not-served", False, "should have raised")
    except ValueError as e:
        check("ssh-ops.query-rules-not-served",
              "hard_rules.vsm" in str(e), str(e))
    check("ssh-ops.query-other-domain-still-works",
          provider.query("services") == [{"name": "services"}])

try:
    ssh_sqlite_ops.load("root@n02:/var/lib/vsf-state/state.db")  # colon, not comma
    check("ssh-ops.load-rejects-colon-form", False, "should have raised")
except ValueError:
    check("ssh-ops.load-rejects-colon-form", True)

print(f"\nALL {PASSED} CHECKS PASSED")
