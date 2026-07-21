# state-rag-mcp — interface design (v0 draft)

Draft informed by the 2 EXP-TOKEN-GROUNDING tasks. To be **validated/refined by the C0/C1/C2 numbers**
(the measurement shapes the form). Design sketch: `docs/plan/METHODOLOGY_VITRINE.vsm`.

## The MCP surface

### Tools — parameterized queries the agent *calls* (C2 lazy path)
| tool | signature | returns | answers |
|---|---|---|---|
| `state_onboard` | `() ` | digest: services+status, open drift, rules, last decision | the whole broad picture in one call |
| `state_query` | `(domain, filter?)` | records | a narrow slice — `domain ∈ {services, drift, rules, topology, decisions}` |
| `state_verify` | `(claim)` | `{holds, actual, evidence}` | ★ "don't trust the report, verify against ground truth" |
| `state_reconcile` | `(domain?)` | `[drift]` | model≡reality: declared vs observed → drift/orphan report |
| `memory_search` | `(topics)` | `[finding]` | (optional) non-derivable findings/memory |

### Resources — addressable read-only context the client *injects/reads* (C1 onboard path)
| uri | content |
|---|---|
| `state://digest` | same as `state_onboard()` — for clients that inject context up front |
| `state://schema` | domains + their fields |
| `state://rules` | active rules |
| `state://handoff` | last decision / session block |

The split is deliberate: **resources** feed the front-load (C1 onboard injects `state://digest`);
**tools** feed the lazy path (C2 calls `state_query`/`state_verify` for only what it needs). Same
backing state, two consumption modes — which is exactly the trade-off the experiment measures.

## The abstraction — decouple from `state.db` → generic provider (the real work)
The core is domain-agnostic; a user plugs in their own state:
- **`StateProvider`** (user implements): `list_domains()` · `query(domain, filter)` · `schema(domain)`
- **`Reconciler`** (user registers per domain): `observe(domain) -> reality` · `diff(declared, reality) -> [drift]`
  (the user supplies "how to observe reality"; the framework does the diff + drift typing)
- **`DigestAssembler`**: registered domains + a policy (what matters) → the compact onboard digest
- **MCP adapter**: thin wrapper exposing the tools/resources above over provider + reconciler

## Reference instances (the abstraction has ≥2 instances from day one — proves it generalizes)
- **A production ops canon** — the mapped-and-policied `SqliteStateProvider` over a live operations
  database (`instances/sqlite_ops.py`; domains: rules/services/components/chains/blockers/topology);
  the deployment's own host-side reconciliation timers write the DB. The real, live instance.
- **microstack** (the corpus) — `StateProvider` over `synthesized/state.json`; reconciler = `raw/manifest.txt`
  (declared) vs `raw/processes.txt` (reality). The tiny, reproducible instance.

## Roadmap instance: version control (Git first, VCS-agnostic by construction)

Version control integration is not a bolt-on — it is a *natural third instance*, because **git is
already a reconciler**: the index/HEAD is the *declared* state, the working tree is the *observed*
reality, and `git status` is a drift report. A `GitStateProvider` maps directly onto the existing
primitive, no new concepts:

| primitive | git realization |
|---|---|
| domains | `branches`, `status`, `log`, `tags`, `remotes` |
| declared | index / HEAD |
| observed | working tree (+ remote heads for ahead/behind) |
| `declared_but_missing` | deleted-in-worktree file |
| `orphan` | untracked file |
| `mismatch` | modified / staged-but-changed · branch ahead/behind its remote |
| `state_verify` | "is the tree clean? is `main` at `abc123`? is the tag signed?" |

VCS-agnostic falls out of the abstraction: the same domains implemented over jj/hg/svn is just
another provider — nothing in the core knows about git.

Second design direction: **versioning the state store itself** (state.json under git) gives
time-travel for free — `state_query(..., at=<revision>)`, and diffs *between* states become
first-class ("what changed since yesterday's digest?"). Both directions are roadmap, not v0.

## Remote mode: remote state, local server (and the alternative)

Sometimes the state cannot live beside the agent — ours doesn't: our production canon lives on a
server two SSH hops away from where the agent runs. Remote mode is supported, but at the **right
layer** — and the plug already exists.

**The recommended pattern — remote STATE, local SERVER.** The MCP server stays local beside the
agent (stdio, local-first); its `StateProvider` is what reaches over the wire. The provider
abstraction *is* the plug: `query()` can be implemented over HTTP (the `ApiStateProvider` example in
USAGE.md is already remote mode), over SSH (a subprocess calling a remote query command — our own
production channel), over a message bus, gRPC — the core neither knows nor cares.
**Channel-agnostic by construction**, because the channel is entirely the provider's business.

| concern | where it lives |
|---|---|
| transport / channel (HTTP, SSH, bus, gRPC...) | your provider implementation |
| auth / credentials | your provider (env / keychain — never in MCP config args) |
| latency | per-query cost — consider caching the digest between calls |
| staleness | **declare it**: put `observed_at` / `reconciled_at` in `meta` so the agent *knows* the age of what it reads |
| write access | none — providers are read-only by contract, remote included |

**The alternative — remote MCP transport** (the MCP spec's streamable HTTP): moving the whole server
to the remote side. Possible, and the right call when *many agents share one state service* — but you
inherit service security (TLS, authz, exposure) and lose the local-first simplicity. v0 ships stdio
only; the remote-transport wrapper is a **developer integration point**, deliberately left open, not
a missing feature.

## Composing with other context artifacts (content RAG, memory, tools)

State RAG is deliberately **one instrument, not the whole rack**. The connection point already
exists and is the protocol itself: MCP clients attach servers side-by-side, so State RAG composes
with a content/vector RAG, a memory server, and any other tool without either knowing about the other.
What each source is *for* — and who wins when they disagree — is the part worth making explicit:

| source | answers | authoritative for |
|---|---|---|
| **State RAG** (this) | "what IS, right now" | current system truth (reconciled) |
| content / vector RAG | "what do we know about X" | knowledge, documents, how-tos |
| memory server | "what happened, what did we learn" | history, preferences, decisions past |
| other tools | "do X" | actuation — not context |

The discipline that keeps the ensemble honest is **authority ordering**: for *current* truth,
reconciled state outranks memory, and memory outranks the model's own recall — documents and memory
describe the intended or the past; the state describes what is. (In our own production system this is
a hard rule: *"when the state store disagrees with a memory file, the state store wins."*) Give your
agent that ordering explicitly — a line in the system prompt is enough.

v0 deliberately builds **no deeper coupling** — no cross-references from the digest into your document
store. If real usage asks for it, the roadmap shape is *content anchors on drift*: each drift kind
carrying a pointer into your knowledge base (the runbook for that failure class), so "what is wrong"
arrives together with "where it's documented". Whether that's wanted depends on the architecture each
user builds — the primitive stays minimal either way.

## How the 3 experiment conditions consume this
- **C0 cold** — NO MCP. Gets `raw/` only. The agent must *be* the reconciler (manual cross-reference).
- **C1 onboard** — `state://digest` injected as context. Front-load; zero exploration.
- **C2 MCP** — tools available. Lazy: query only the needed slice.

Closure worth noting: **C0 does by hand what the `Reconciler` does automatically; C2 queries the
`Reconciler`'s output.** The token delta = the cost of manual reconciliation. That *is* the value we measure.
