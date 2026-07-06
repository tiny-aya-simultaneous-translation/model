# PROGRESS

Append-only running log of changes, decisions, failures, and next steps.

Auto-managed by `.claude/hooks/post_tool_use.py`,
`.claude/hooks/stop.py`, `.claude/hooks/pre_compact.py`, and
`.claude/hooks/session_end.py`. Quick-capture entries land here when
you start a message with `#progress`. Manual capture via
`/progress <text>`.

Format per entry:

```
## YYYY-MM-DDTHH:MM:SSZ | <branch>@<short-sha> | <status> | <kind>
<one-line summary>

<optional detail block>
```

Status: `info | done | fail | block`
Kind: `edit | exec | decide | plan | verify | session`

The most recent entry is at the top. Older entries beyond 90 days are
moved to `.claude/archive/PROGRESS-YYYY-Qn.md` by the
`archive-progress` skill.

> **Full history through 2026-07-06 (13,998 lines) archived to
> [`.claude/archive/PROGRESS-2026-07-06.md`](archive/PROGRESS-2026-07-06.md).**
> The summary below is the current state; new entries append under it.

---

## 2026-07-06T02:11:45Z | feat/v0.3-implementation@ba2b0cc | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-06T02:11:20Z | feat/v0.3-implementation@ba2b0cc | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-06T02:10:57Z | feat/v0.3-implementation@ba2b0cc | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/.claude/agents/tpu-watchdog.md`


## 2026-07-06T02:10:24Z | feat/v0.3-implementation@ba2b0cc | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-06T02:10:05Z | feat/v0.3-implementation@ba2b0cc | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-06T02:09:41Z | feat/v0.3-implementation@ba2b0cc | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-06T02:09:31Z | feat/v0.3-implementation@ba2b0cc | done | edit
created `/tmp/claude-1000/-home-cataluna84-Workspace-tinyaya-stage2-scale/9d91a9c6-d22b-474c-8971-e137f68da904/scratchpad/memories_new.md`


## 2026-07-06T02:08:56Z | feat/v0.3-implementation@ba2b0cc | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-06T02:08:27Z | feat/v0.3-implementation@ba2b0cc | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-06T02:08:10Z | feat/v0.3-implementation@ba2b0cc | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/.claude/VERIFY.md`


## 2026-07-06T02:07:38Z | feat/v0.3-implementation@ba2b0cc | done | edit
created `/home/cataluna84/Workspace/tinyaya-stage2-scale/.claude/PLAN.md`


## 2026-07-06T02:06:58Z | feat/v0.3-implementation@ba2b0cc | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## Current state — 2026-07-06

**Project:** TinyAya v0.3 — audio-only TR↔HI speech-to-speech translation on `feat/v0.3-implementation` (PR #10).

- **Recipe frozen** (capacity-sweep winner): LoRA **r=32, alpha=64, rsLoRA, +MLP** target
  modules, `lr_lora=1.716e-4`, `exclude_top=2`. Production config
  `configs/tpu/stage2_tpu_v6e16_full_v03.yaml` (14,532 steps = 3 epochs) on **v6e-16**.
- **Data:** synthetic `tr-hi-mimi-encoded` ~1.24M → 1,178,302 train / 62,036 val
  (audio-only; corpus ships no text alignments → `text_weight=0`).
- **Pipeline validated:** overfit gate memorizes all 8 codebooks (89–98%). The
  per-codebook accuracy metric bug (undelayed vs delayed target) fixed (`8854698`).
- **#71 fixed** (`eb17609`): TPU scan-wrapper adapter-load bug — eval loaded 1/239 LoRA
  tensors → ~19%; now 239/239, eval reconciles with training (97.3% vs 98.1% CB0), with a
  fidelity guard that raises on any unfilled LoRA tensor. Prior `eval_checkpoint.py`
  numbers vs TPU checkpoints were invalid.
- **Infra** (`ba2b0cc`): GCS bucket migrated us-central2 → **`gs://tinyaya-stage2-eu`**
  (europe-west4, co-located with TPUs), old bucket deleted (killed cross-region egress,
  ~98% of the bill). Obsolete sweep/opt/v2 checkpoints pruned (265 → 49.5 GiB); 3 keepers
  remain (`v6e16-smoke-r32`, `v6e16-b256`, `v6e8-overfit-r32`).
- **Docs pass** (this session): all `.md` updated to v0.3 reality + pruned; plan sprawl,
  MEMORY-* meta, and tpu-changes/launch-plan consolidated; this log archived.
- **Slices:** v6e-16 + v6e-8 idle/ACTIVE in europe-west4-a (TRC, do not tear down without intent).

**Next:** production run is **held** (launched then stopped) — relaunch when ready, then
eval (`scripts/eval_checkpoint.py`) → publish v0.3 card + checkpoints (see
`docs/v0.3-public-release-plan.md`). Rotate any leaked tokens before going public.

---
