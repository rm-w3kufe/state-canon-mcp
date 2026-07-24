# skills/ — the disciplines, portable

Nine working disciplines from the [two-agent pattern](../METHODOLOGY.md), packaged as portable
skills. Each one exists because something real broke without it — every skill carries its scar.

**Format:** one directory per skill, `SKILL.md` with YAML frontmatter (`name`, `description`) +
instructions. This is the Claude Code skill convention; for any other harness they are plain
markdown you can drop into system context.

**Install (Claude Code):** copy a skill directory into `.claude/skills/` (project) or
`~/.claude/skills/` (personal). The `description` is what tells the agent *when* to load it.

**They compose with state-canon** — several disciplines lean on having a ground truth to check
against (`state_verify`, `state_reconcile`). They work without it, but verification degrades from
*mechanical* to *manual*.

| skill | the rule in one line |
|---|---|
| [verify-live-not-report](./verify-live-not-report/SKILL.md) | reports describe intentions; systems describe reality — check the live system |
| [confirm-first](./confirm-first/SKILL.md) | diagnose before patching; report and STOP before the fix |
| [work-gated-liveness](./work-gated-liveness/SKILL.md) | a heartbeat from a bare timer is theater — gate it on real work |
| [blast-radius-gating](./blast-radius-gating/SKILL.md) | one pilot before the fleet; a window before "done" |
| [loud-death](./loud-death/SKILL.md) | services die noisily or not at all — and never cry wolf |
| [fix-source-keep-detector](./fix-source-keep-detector/SKILL.md) | never widen a threshold to quiet an alarm |
| [logical-gates-not-time-estimates](./logical-gates-not-time-estimates/SKILL.md) | sequence by preconditions, never by duration guesses |
| [framed-prompts](./framed-prompts/SKILL.md) | the handoff is a contract, not a conversation |
| [system-holds-the-pen](./system-holds-the-pen/SKILL.md) | managed surfaces are written by the system; hand-edits are drift |
