# Usage

## The 60-second demo (no MCP client needed)

The repo ships a tiny fictional deployment (`corpus/microstack/`) with **three seeded drifts**:
a service declared active but actually stopped, a rule violation, and an orphan process.

**1. Ask for the whole picture:**

```bash
cd state-rag-mcp
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"state_onboard","arguments":{}}}' \
  | python3 mcp_server.py --microstack corpus/microstack
```

→ one compact digest: 9 services, the 3 drifts (recomputed live from the raw files, not read from a
snapshot), the rules, the last recorded decision.

**2. Catch a lie** — claim that `cache` is running, against ground truth:

```bash
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"state_verify","arguments":{"domain":"services","filter":{"name":"cache"},"expect":{"actual":"running"}}}}' \
  | python3 mcp_server.py --microstack corpus/microstack
```

→ `"holds": false` **with evidence**: declared `active`, observed `stopped`. That is the whole
philosophy in one call: *don't trust the report — verify against state.*

**3. With your agent attached** (see [INSTALL.md](./INSTALL.md)), ask it:
- *"What's the current state of the system? Any drift?"* → it calls `state_onboard` once.
- *"Is the cache service consistent with what's declared?"* → it calls `state_query` / `state_verify`.

## The usage pattern that measured best

From our token experiment ([EXPERIMENT](./corpus/microstack/EXPERIMENT.md), [RESULTS](./corpus/microstack/RESULTS.md)):
**inject the digest once at session start** (broad orientation — cheapest for wide questions), then
**use targeted `state_query` calls for follow-ups** (cheapest for narrow questions). Cold re-exploration
is always the most expensive condition.

## Onboarding YOUR system — three steps

### Step 1 — point the server at your state

**JSON (quickest start).** Any JSON document whose top-level keys hold lists of records:

```json
{ "system": "my-stack",
  "services": [ {"name": "api", "state": "running", "version": "1.2.0"} ],
  "rules":    [ "api and worker versions must match" ],
  "last_decision": {"id": "D-1", "text": "approved cache upgrade"} }
```

```bash
python3 mcp_server.py --state /abs/path/my-state.json
```

**SQLite.** Every table/view becomes a queryable domain automatically — or pass an explicit mapping
(see `instances/sqlite_ops.py` for a real production example):

```python
from state_rag.sqlite_provider import SqliteStateProvider
provider = SqliteStateProvider("ops.db",
    domains={"services": "services", "blockers": "v_open_blockers"},
    meta={"system": "my-stack"})
```

Opened read-only by construction (`mode=ro`) — the RAG reads canon, it never writes it.

**An API / anything.** Implement two methods:

```python
from state_rag.provider import StateProvider
import json, urllib.request

class ApiStateProvider(StateProvider):
    def __init__(self, base_url):
        self.base = base_url
    def list_domains(self):
        return ["services", "incidents", "meta"]
    def query(self, domain, filter=None):
        if domain == "meta":
            return [{"system": "my-stack"}]
        with urllib.request.urlopen(f"{self.base}/{domain}") as r:
            records = json.load(r)
        if filter:
            records = [x for x in records if all(x.get(k) == v for k, v in filter.items())]
        return records
```

> Note: this **is remote mode** — the MCP server stays local beside your agent; the *provider* is
> what crosses the wire. An SSH-channel provider is the same shape
> (`subprocess.run(["ssh", host, "state-query", domain])` → parse JSON). The channel is entirely the
> provider's business: HTTP, SSH, a message bus — the core neither knows nor cares. Design notes and
> the considerations table (auth, latency, staleness) in [INTERFACE.md](./INTERFACE.md).

### Step 2 — shape the digest (what matters at onboard)

Raw dumps don't belong in a model's context (our first real-canon digest weighed 44k chars; the
policy cut it to 12k). Declare what matters per domain:

```python
DIGEST_POLICY = {
    "services": {"fields": ["name", "state", "version"], "max": 60},
    "deploys":  {"fields": ["component", "result"], "max": 5, "last": True},
    "audit_log": {"skip": True},          # queryable, but not onboard material
}
```

Detail is never lost — it stays one `state_query` away.

### Step 3 (optional but recommended) — add a reconciler

This is where the RAG earns its keep: **declared vs observed → typed drift**, computed live.

```python
from state_rag.reconcile import Reconciler

class MyReconciler(Reconciler):
    domain = "services"
    def declared(self):   # the model: your manifest / DB / config
        return load_manifest()
    def observe(self):    # the reality: ps, systemctl, an API probe...
        return probe_running_processes()
```

The generic diff yields `declared_but_missing`, `orphan`, and your registered `rule_violation`s —
exactly the three drift kinds seeded in the demo corpus. Wire it in an instance module
(`instances/microstack.py` is the 40-line reference).

## Use cases (explicit)

| Scenario | Call pattern |
|---|---|
| Agent session start — "where am I?" | `state://digest` resource injected, or one `state_onboard` |
| "Is service X ok?" mid-session | `state_query(services, {name: X})` — ~80 tokens |
| Reviewing another agent's (or person's) report | `state_verify(domain, filter, expect)` → holds/mismatches + evidence |
| Post-deploy sanity | `state_reconcile()` → live drift list (orphans, missing, rule violations) |
| CI gate | run the reconcile in a script; fail the pipeline if drift ≠ expected |
