# Memory System — Keep Context Fresh

This repo implements the **External Memory System** pattern (from Factory.ai's
power-user playbook): a small set of living markdown files under `.claude/` that act as
the long-term memory of every agent session. Sessions are stateless — without external
memory, every restart re-explores and re-discovers the same gotchas. We pay that cost
once and write the answer down.

> Historical note: the system was originally under `.factory/`; it has been ported to
> **`.claude/`** (hooks, skills, agents, memory files). All paths below are `.claude/`.

## The memory files

| File | Role | Lifetime |
|------|------|----------|
| `AGENTS.md` (repo root) | Repo norms, commands, seam rules, gotchas | Stable; human-edited |
| `.claude/PROGRESS.md` | Append-only log of what changed / failed / next steps | Hot; hook-managed |
| `.claude/PLAN.md` | Current goal + checklist + Definition of Done | One per active goal |
| `.claude/VERIFY.md` | Ordered shell commands that prove "done" | Stable; human-edited |
| `.claude/memories.md` | Long-term decisions (architecture, trade-offs, domain facts) | Curated |

A per-fact `memory/` directory (one file per fact + an index) is the newer,
finer-grained store loaded each session; `memories.md` is the legacy monolith.

## The lifecycle (autonomous loop)

```
SessionStart -> read the memory files, inject as context
UserPromptSubmit -> #progress / #plan / #decision / #verify routes to the right file
PostToolUse  -> after each Edit/Create/Execute, append a structured PROGRESS entry
PreCompact   -> dump current state into PROGRESS.md so compaction never loses context
Stop         -> run the verifier (VERIFY.md); on pass tick PLAN.md; on fail log PROGRESS
SessionEnd   -> write a "Next steps" block to PROGRESS.md from unchecked PLAN items
```

The next session's `SessionStart` reads exactly what the previous `SessionEnd` wrote, so
the tape is unbroken. Hooks (`.claude/hooks/*.py`) are the deterministic glue; skills
(`.claude/skills/`) are reusable workflows; agents (`.claude/agents/`) are specialised
subagents; commands (`.claude/commands/`) are the manual slash-command overrides;
`settings.json` wires hooks to events.

## How to operate

| You want to… | Use |
|----------------|-----|
| Remember a permanent decision | `/remember <text>` |
| Note progress manually | `/progress <text>` or `#progress <text>` |
| Generate a checklist for a new goal | `/plan` |
| Run all verifications | `/verify` |
| See current memory state in chat | `/recall` |
| Prune + archive old entries | `/curate` |

## Maintenance

- **PROGRESS.md** grows unbounded — periodically archive it: snapshot to
  `.claude/archive/PROGRESS-<date>.md` and replace with a concise current-state summary
  (the `archive-progress` skill). Keep the header/format block.
- **memories.md / `memory/`** — dedupe and prune stale entries (`/curate`,
  `memory-curator` agent). Verify any file:line citation still resolves before trusting it.
- **VERIFY.md** — keep it to the checks that currently matter (they run on every Stop).

## Installation / extension

The system ships pre-installed with the repo (`.claude/` is committed). To extend: add
skills under `.claude/skills/<name>/SKILL.md`, agents under `.claude/agents/<name>.md`,
or commands under `.claude/commands/<name>.md`; register hooks in `settings.json`. A
file-based archive can be swapped for an MCP memory server (e.g. mem0) for vector recall
over long histories, and `verify` can be wired into CI to gate PRs.
