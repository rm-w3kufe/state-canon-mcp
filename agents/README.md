# agents/ — the agent, as an adoptable spec

The [methodology](../METHODOLOGY.md) describes the single-agent, canon-grounded pattern; this file
makes it **installable**. It is one agent definition you can drop into a harness. The human is the
second role and stays a human.

- [`agent.md`](./agent.md) — designs, executes, and **verifies its own claims against live ground
  truth**; diagnoses before patching; orders changes by blast radius; stops at checkpoints;
  escalates policy / irreversible / outward-facing decisions.

**Format:** YAML frontmatter (`name`, `description`, `model`, `tools`) + the instructions — the
Claude Code subagent convention. For any other harness, the body is a system prompt; the frontmatter
is metadata you map to your own config.

**It embeds the disciplines.** The agent references the [`skills/`](../skills/) it leans on, and
grounds itself through **canon** — onboard at the start of a task, verify claims against canonical
state rather than against its own recall.

**Wiring:**

```
human ──decisions / approval──► agent ──acts──► reality
                                  ▲               │
                                  └──verify LIVE──┘
                          (the agent checks ground truth,
                           not its own report of what it did)
```

**Why one agent, not two.** An earlier version of this pattern used two agents — a reasoner checking
an executor — to get the property that *what verifies a claim is not what produced it*. But that
property does not require a second agent; it requires that verification run against **canon that is
external to the agent's reasoning.** One agent that reconciles against ground truth — reading the
artifact's hash rather than trusting its memory of the deploy — has the same guarantee at lower cost.
The invariant was never head-count; it was grounding.
