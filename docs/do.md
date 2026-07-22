# do — deferred follow-ups (shelf)

Parked work that's known but not yet done. Not a plan (that's `.claude/PLAN.md`); this is
the backlog of loose ends. Delete an item when it's done.

## Open

### Cohere Labs blog revision — v0.3 backend specifics (2026-07-20)

USER-OWNED. The team blog
([Adapting Moshi for Low-Resource Speech Translation](https://labscommunity.cohere.com/blog/2026/adapting-moshi-low-resource-speech-translation/))
has had multiple iterations; the user is contributing the backend/training
revision. Planned sections, sourced from the model card
(`docs/hf-model-card-tr-hi-s2st-v0.3.md`):

1. **the training run** (⚡ section: run xzcb60bl, early stop 65,250, val table)
2. **the curriculum notes** (onset steps, cross-codebook transfer drop,
   `audio_loss_full` — investigation arc in PR #10 comments)
3. **the infra lowering tables** (XLA/scan/bmm changes, replicated strategy)
4. **the checkpoint story** (keep-all suite, interim ladder, storage-cap saga,
   Xet-dedup main mirror)

Evals + numbers get added later, after the GPU `eval_release.py` session —
same `results.json` feeds card model-index and blog so they can't drift.

### Live GPU verification of the v0.3 evals harness — UNBLOCKED (2026-07-20)

The long-horizon run **completed incl. anneal 2026-07-20** (xzcb60bl; plateau
early-stop 65,250 then anneal → best **2.8199 @ step 76,000**, final 76,250),
so the GPU session is no longer shelved — it runs on the user's word (rented
H100/A100). Procedure: install the `eval` extra, run `scripts/eval_release.py`
(full stages) over `v03-val-500` + `v03-fleurs-200` → results.json + W&B
backfill. **Eval targets: annealed best (76,000) + final (76,250) + LAWA.**
Checkpoint sources (repo is now PUBLIC): GCS
`gs://tinyaya-stage2-eu/checkpoints/stage2-v6e16-mh-v03-r2/` (all ~89 incl.
`best_by_val`=76,000, full optimizer state), or hub
`tiny-aya-translate/tr-hi-s2st-v0.3` (all ~89 revisions + `main:checkpoints/`).
Sanity gates: GT-audio topline ≫ model score, ASR-judge floor consistent with
corpus QC (86% pass @ WER ≤ 0.20), DNSMOS(GT) ≈ codec ceiling. Record
wall-clock + $ cost per checkpoint sweep in `docs/evals-runbook.md`.

### eval_checkpoint ASR needs a CPU path before release eval (2026-07-09; scope narrowed 2026-07-20)

Largely SUPERSEDED for release evals: the evals program's
`src/evaluation/asr_judge.py` (transformers Whisper, benchmarked judges)
replaced the legacy faster-whisper `run_asr` path in `eval_release.py`.
Remaining scope only if someone revives `eval_checkpoint.py --skip_asr`'s ASR:
`run_asr` hardcodes `WhisperModel(..., device="cuda", compute_type="float16")`,
`faster_whisper` is not in the lockfile, and the `rows[i]`/`ds[i]`
positional-desync bites on splits with missing `.pt` rows.

### Text+audio pivot follow-ups (2026-07-08)

- **Fix the upstream split manifests** (or publish corrected ones): the dataset repo's
  `splits/{train,val}.jsonl` still carry `encoded/{stem}_src.json` alignment paths; our
  loader fallback (`_resolve_alignment`) papers over it, but external consumers will hit
  the same silent-audio-only wall. Consider a dataset-repo PR + card note.
- **`smoke-b1` QR still ACTIVE** (8 idle chips, unrolled batch-1 experiment — moot since
  scan works). Delete on user approval; it's the quota needed for arms E/F.
- **Audio-only partials**: arms A/B/C's first ~100-125 audio-only steps live in W&B group
  `v03-5k-reval` — cite as ablation reference in the writeup, or clean up.
- **Post-hoc composite-weight ranking script**: selection rule §5 needs a small script
  pulling `val/{text,audio}_loss` series from the W&B group and re-ranking arms under
  {0.2/0.8, 0.4/0.6, 0.5/0.5} (can be a notebook; write before arms finish).
- **`val/text_acc` sanity**: after the first TA val passes, eyeball that the metric's
  real-token masking (< 262144) matches the interleaver's token layout — a first-word-
  subtoken-only stream means acc is measured on sparse positions; document the expected
  scale on the card.

---

## Done

### ~~Add anneal-leg details + results to the model card~~ ✅ (2026-07-20)

Anneal leg completed (65,250 → 76,250; best val composite 2.8199 @ 76,000).
Card updated same day: banner + val table annealed column + anneal-leg
subsection + full-suite Checkpoints section (repo now PUBLIC, ~87 points
backfilled from GCS). Eval-target extension per runbook remains with the GPU
session.

### ~~Keep the v0.3 HF model card's infra section in sync with the long-horizon run~~ ✅ (2026-07-20)

Card fully refreshed post-run (run results, playable samples, checkpoints
table, license correction to CC-BY-NC-4.0, intended-use + attribution
sections) and pushed to the hub as `main:README.md` — byte-verified against
`docs/hf-model-card-tr-hi-s2st-v0.3.md`. The run used `use_scan_layers: true`
⇒ published checkpoints carry the all-36-layer adapter layout described in
the card's bolded checkpoint-structural row. Residual (fold into the GPU eval
session): one final parity re-verification of the "numerics-identical" claims
on the shipped code while a checkpoint is loaded anyway.

### ~~Update stale defaults baked into the TPU scripts~~ ✅ (2026-07-06)

The docs pass left the `.sh`/`.py` scripts carrying v4 / v6e-8 / `v6e_v2` / `us-central2`
defaults; refreshed to v0.3 / v6e-16 / europe-west4:
- **Config default** `stage2_tpu_v6e_v2.yaml` → `stage2_tpu_v6e16_full_v03_mh.yaml` across
  `launch_release`, `launch_qr`, `launch_canary`, `hot_redeploy`, `_remote_redeploy`,
  `startup_script`, and the `promote_sweep_winner.py` docstring.
- **`launch_spot.sh`**: added a `v6e-16-eu` profile (v6e-16 / europe-west4-a /
  `v2-alpha-tpuv6e`) and made it the default `TRC_PROFILE`; legacy profiles kept.
- **`launch_release.sh`**: header + `GCS_LOG_PREFIX` → v0.3 / `stage2-tpu-v6e16-full-v03`.
- **`setup_gcp.sh`** `REGION` → `europe-west4` (the bucket-location mismatch that caused the
  cross-region egress); **`ops.sh`** `ZONE` → `europe-west4-a`.
- **Kept** `launch_qr.sh`'s v4 hardware defaults on purpose — it's the *on-demand* launcher
  and TRC v6e is spot-only (on-demand v6e would fail / bill full-rate); only its header was
  clarified. **Kept** the `WANDB_PROJECT`/`WANDB_URL` = `tinyaya-stage2-tpu` (W&B namespace).

Verified: `bash -n scripts/tpu/*.sh` clean; no-arg `launch_release.sh` resolves to the v03
config + v6e16 GCS prefix; `v6e-16-eu` profile resolves correctly; tests + seam pass.
