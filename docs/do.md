# do — deferred follow-ups (shelf)

Parked work that's known but not yet done. Not a plan (that's `.claude/PLAN.md`); this is
the backlog of loose ends. Delete an item when it's done.

## Open

### Live GPU verification of the v0.3 evals harness — post-long-horizon-run (2026-07-15)

The evals program is planned in `docs/v0.3-evals-plan.md`; the end-to-end GPU
session is deliberately SHELVED until the long-horizon run completes (user
decision 2026-07-15 — no GPU instances before then). When the run finishes:
rent an H100/A100, install the `eval` extra, run `scripts/eval_release.py`
(full stages) on a real checkpoint over `v03-val-500` + `v03-fleurs-200` →
results.json + W&B backfill. Sanity gates: GT-audio topline ≫ model score,
ASR-judge floor consistent with corpus QC (86% pass @ WER ≤ 0.20), DNSMOS(GT)
≈ codec ceiling. Record wall-clock + $ cost per checkpoint sweep in
`docs/evals-runbook.md`.

### eval_checkpoint ASR needs a CPU path before release eval (2026-07-09)

`run_asr` hardcodes `WhisperModel(..., device="cuda", compute_type="float16")` and
`faster_whisper` is not in the lockfile. The pipeline-validation gate runs `--skip_asr`
(token-level reproduction is the right memorization metric); the RELEASE eval (ASR-BLEU
per release-plan §3) needs: `faster-whisper` pinned (+ int8 CPU branch or a GPU box),
and the `rows[i]`/`ds[i]` positional-desync fixed if eval ever runs on splits with
missing `.pt` rows (dataset drops them; `rows` doesn't).

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

### Keep the v0.3 HF model card's infra section in sync with the long-horizon run

`docs/hf-model-card-tr-hi-s2st-v0.3.md` now has a "Training infrastructure: replicated
strategy + XLA architecture changes" section (added 2026-07-08), and
`docs/v0.3-public-release-plan.md` §2 has the matching checklist item. Before publishing:

- Confirm which layout the published checkpoints actually use: `scan_homogeneous`
  (adapters on ALL 36 layers, top-2 frozen/zero — any run with `use_scan_layers: true`,
  e.g. the v6e-8 reval arms) vs classic `exclude_top=2` 34-layer layout (unscanned
  v6e-16). Update the card's bolded checkpoint-structural row + `metadata.json` note.
- Verify `metadata.json` actually records the adapter layout / `use_scan_layers` flag —
  add it to the checkpoint writer if it doesn't yet.
- Re-verify the "numerics-identical" claims one final time on the shipped code
  (FlexibleLinear bmm + identity-skip parity test, `_ScanSafeDropout` eval no-op,
  full-attention forcing gated to seq ≤ sliding_window).

---

## Done

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
