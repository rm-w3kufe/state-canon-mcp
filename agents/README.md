# agents/ — the two roles, as adoptable specs

The [methodology](../METHODOLOGY.md) describes the two-agent pattern; these two files make it
**installable**. Each is an agent definition you can drop into a harness — the reasoner (an advanced
model) and the executor (a cost-efficient model). The human is the third role and stays a human.

- [`reasoner.md`](./reasoner.md) — designs, reviews, does RCA, **verifies live**, holds the gates.
- [`executor.md`](./executor.md) — builds, deploys, tests, **reports with evidence**, stops at checkpoints.

**Format:** YAML frontmatter (`name`, `description`, `model`, `tools`) + the role instructions —
the Claude Code subagent convention. For any other harness, the body is a system prompt; the
frontmatter is metadata you map to your own config.

**They embed the disciplines.** Each role references the [`skills/`](../skills/) it leans on, and
both ground themselves through **State RAG** — onboard at the start of a task, verify claims against
canonical state rather than against each other's prose.

**Wiring** (conceptual — harness-specific in practice):

```
human ──decisions/approval──► reasoner ──framed prompt──► executor
                                  ▲                            │
                                  └──────report + evidence─────┘
                                  (reasoner verifies LIVE, not the report)
```

The two roles never collapse into one, and neither trusts the other's claims without verification —
that mutual verification, not the number of agents, is where the quality comes from.
