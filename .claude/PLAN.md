# PLAN — v0.3 production run → eval → public release

Branch: `feat/v0.3-implementation` (PR #10). Strategy detail:
[`docs/v0.3-public-release-plan.md`](../docs/v0.3-public-release-plan.md).

## Goal
Ship the v0.3 **audio-only** TR↔HI S2ST model: run the frozen recipe to completion on
v6e-16, evaluate honestly, and publish everything (model, all checkpoints, dataset cards,
code, blog).

## Definition of Done
- [ ] v0.3 production run completes (14,532 steps / 3 epochs) on v6e-16; `best_by_val` chosen.
- [ ] Release eval with the loader-fixed path: per-codebook accuracy (teacher-forced),
      ASR-BLEU, DNSMOS — filled into `MODEL_CARD.md` + `docs/hf-model-card-tr-hi-s2st-v0.3.md`.
- [ ] v0.3 HF repo published (card + all checkpoints); dataset cards note the no-alignments gap.
- [ ] Code repos opened; `THIRD_PARTY_NOTICES.md` covers the synthetic sources.
- [ ] Blog updated to the audio-only honest result; leaked tokens rotated before public.

## State (2026-07-06)
- **Recipe frozen** (capacity-sweep winner: r=32/+MLP/rsLoRA/lr 1.716e-4), config
  `configs/tpu/stage2_tpu_v6e16_full_v03.yaml`. ✅
- **Pipeline validated** (overfit gate: all 8 codebooks 89–98%); metric bug fixed. ✅
- **#71 checkpoint adapter-load fixed** (`eb17609`) — release eval is now trustworthy. ✅
- **Bucket migrated** to `gs://tinyaya-stage2-eu` (europe-west4); obsolete checkpoints pruned. ✅
- **Docs pass** — all `.md` updated + pruned; PROGRESS archived. ✅
- **Production run: HELD** (launched then stopped) — awaiting relaunch. ☐

## Next steps (mostly user decisions)
1. **Relaunch** the production run when ready: `bash scripts/tpu/launch_release.sh
   configs/tpu/stage2_tpu_v6e16_full_v03.yaml` on the v6e-16 (redeploys code w/ the #71 fix).
2. **Eval** at `best_by_val`: `scripts/eval_checkpoint.py` (per-codebook acc + ASR-BLEU + DNSMOS).
3. **Publish** per `docs/v0.3-public-release-plan.md`; rotate secrets; flip repos public.

## Guardrails
- TPU slices are a free TRC grant — never stop/delete/reprovision without explicit intent.
- Keep the GCS bucket in the TPUs' region (europe-west4) — a cross-region bucket re-incurs
  the egress that was ~98% of the bill.
- No persistent XLA compile cache → minimize restarts (~35–40 min recompile each).
