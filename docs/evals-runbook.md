# Evals runbook — v0.3 S2ST evaluation harness

Operating manual for the evals program (design: `docs/v0.3-evals-plan.md`).

## Post-run state (2026-07-20)

The long-horizon run is **COMPLETE incl. anneal** (run
[`xzcb60bl`](https://wandb.ai/cataluna84/tinyaya-stage2-tpu/runs/xzcb60bl):
plateau early-stop @ 65,250 then anneal 65,250→76,250; **best val composite
2.8199 @ step 76,000**, final @ 76,250), so the GPU release-eval **ran** —
results in [`v0.3-eval-report.md`](v0.3-eval-report.md). The repo is **public** with the full suite;
checkpoint access routes for every command below:

1. **GCS (all ~89 dirs, full optimizer state — LAWA + resume):**
   `gs://tinyaya-stage2-eu/checkpoints/stage2-v6e16-mh-v03-r2/step_0NNNNN`
   + `.../best_by_val` (= **step 76,000**)
2. **Hub revisions (all ~89, weights-only):**
   `hub:tiny-aya-translate/tr-hi-s2st-v0.3@best` (=76,000), `@step-76250`,
   `@step-{1000,…,76000}`
3. **Hub main tree (browsing):** `main:checkpoints/<label>/`

Eval targets are the **annealed** best (76,000) + final (76,250) + LAWA
candidate; the plateau best (62,750) is optional ablation context.

## What runs where

| tier | what | hardware | entry point |
|---|---|---|---|
| 0 | val CE/ppl, TF accs, codebook entropy/active-frac | in-loop (TPU) | trainer (already live) |
| 1 | TF gold chrF++/BLEU/WER + CIs, per direction | CPU box | `scripts/eval_translation_proxy.py` |
| 2 | AR gen → ASR judges → chrF++/BLEU/WER + topline; MOS Δ; RTF/TTFA; gen-codebook stats | **GPU** (H100/A100) | `scripts/eval_release.py` |
| 3 | BLASER-2.0, CometKiwi/COMET-ref, Gemini GEMBA judge, FLEURS acoustic-shift set | GPU (+standalone venv) | `scripts/eval_release.py --stages semantic,judge` |

## Frozen eval sets (committed, digest-verified)

- `eval/subsets/v03-val-500.jsonl` — 250/direction from the host val split
  (62,036 rows), gold `src_text`/`tgt_text` embedded, sha256 self-verified.
  Loaders REFUSE on digest drift or missing corpus rows.
- `eval/subsets/v03-fleurs-200.jsonl` — 100/direction, **real human FLEURS
  recordings** (`source_type=fleurs_real`). ⚠️ The overlap audit found
  **200/200 texts inside the training corpus** (its FLORES slice — FLEURS is
  FLoRes speech): this set measures **real-speech ACOUSTIC domain shift
  only** and must never be described as held-out text. The audit is recorded
  in the file header and pinned by `tests/test_evaluation.py`.
- Rebuild/freeze new sets with `scripts/build_eval_subset.py` (supports
  `--filter key=value` and the `--exclude_norm_texts` overlap audit with
  `--overlap_policy exclude|record`). New subsets get NEW names — never
  overwrite a frozen file.

## GPU box bringup

```bash
git clone <repo> && cd tinyaya-stage2-scale
uv sync --extra eval                    # jiwer, faster-whisper, distillmos,
                                        # speechmos, google-genai, torchaudio
# secrets via env, NEVER printed:
export HF_TOKEN=...                     # gcloud secrets versions access latest --secret=hf-token
export WANDB_API_KEY=...                # ... --secret=wandb-api-key
export GEMINI_API_KEY=...               # Gemini referee + GEMBA judge
```

Data: stage the corpus val split + encoded dir (GCS tarball
`gs://tinyaya-stage2-eu/data/full-corpus-ta-20260708.tar.gz` or the HF
dataset — see `scripts/tpu/stage_dataset.sh` for both routes). For the FLEURS
set, download `packed/encoded_pt.tar.gz` + `packed/encoded_alignments.tar.gz`
+ `splits/val.jsonl` from `tiny-aya-translate/fleurs-tr-hi-mimi-encoded`
(~30 MB total) and extract; pass its `val.jsonl`/`encoded` as
`--val_jsonl`/`--encoded_dir`.

**Semantic venv** (Tier 3): `sonar-space` + `unbabel-comet` are
UNRESOLVABLE against the training pins (numpy<2, own torch pins), so they
live in a standalone venv:

```bash
uv venv ~/eval-sem && source ~/eval-sem/bin/activate
uv pip install torch sonar-space unbabel-comet sacrebleu soundfile
# CometKiwi is a GATED HF repo: accept the license for
# Unbabel/wmt22-cometkiwi-da once with the eval token.
python scripts/eval_release.py ... --stages semantic,report
```

## Commands

Smoke (first thing on a fresh box, ~10 min):

```bash
uv run python scripts/eval_release.py \
    --checkpoint hub:tiny-aya-translate/tr-hi-s2st-v0.3@step-1000 \
    --subset eval/subsets/v03-val-500.jsonl \
    --val_jsonl /data/splits/val.jsonl --encoded_dir /data/encoded \
    --device cuda --limit 8 --n_bootstrap 1 \
    --stages generate,asr,text,report --output_dir eval_out/smoke
```

Full milestone sweep (per checkpoint):

```bash
uv run python scripts/eval_release.py \
    --checkpoint gs://tinyaya-stage2-eu/checkpoints/stage2-v6e16-mh-v03-r2/best_by_val \
    --subset eval/subsets/v03-val-500.jsonl \
    --val_jsonl /data/splits/val.jsonl --encoded_dir /data/encoded \
    --device cuda --gemini_referee 25 \
    --output_dir eval_out/best-76000 \
    --wandb_run cataluna84/tinyaya-stage2-tpu/xzcb60bl \
    --hub_repo tiny-aya-translate/tr-hi-s2st-v0.3
```

Then the FLEURS acoustic-shift pass (same checkpoint, fleurs data dirs,
`--subset eval/subsets/v03-fleurs-200.jsonl`, output `eval_out/step_<N>-fleurs`).

Tier-1 CPU sweep (any box, no GPU):

```bash
uv run python scripts/eval_translation_proxy.py \
    --checkpoint <ckpt> --subset eval/subsets/v03-val-500.jsonl \
    --val_jsonl ... --encoded_dir ... --device cpu \
    --wandb_run cataluna84/tinyaya-stage2-tpu/<run_id>
```

Stages are RESUMABLE: `generate`/`asr` skip rows already in their jsonl, so
a killed run continues with the same command.

## Eval targets (run complete — the cadence is now a concrete list)

- **Tier 1 (CPU, run now):** all ~89 GCS/hub checkpoints (or a coarse
  ladder) with `--subset v03-val-500`.
- **Tier 2 (GPU):** `best_by_val` (**76,000**), `step_076250` (final), a span
  ladder, and the **LAWA average** (`scripts/average_checkpoints.py` over the
  late per-1000 window, e.g. **65k–76k** — the anneal descent). Compare
  LAWA-vs-best-vs-final with `src/evaluation/text_metrics.paired_bootstrap`
  (report p-values).
- **Tier 3:** release candidates only (best, final, LAWA) + the FLEURS
  acoustic-shift pass.

## Reporting checklist (every published number)

- checkpoint step/revision + `results.json` (schema v1 records all of this);
- subset NAME + sha256 digest; identical subset across all compared points;
- ASR judge ids (`vasista22/whisper-hindi-large-v2` hi /
  `openai/whisper-large-v3` tr) — scores are NOT comparable across judges;
- `NORM_VERSION` (`hi-tr-v1`) + sacrebleu version (in results.json);
- decoding mode (greedy default; sampled configs are listening-only);
- **references are synthetic** (machine-translated corpus text) — disclose;
- chrF++ is primary; BLEU secondary (near-meaningless below ~5);
- ASR metrics always next to the **GT-audio topline** (same judge on
  ground-truth target audio — the TTS+Mimi+ASR ceiling; corpus QC context:
  86% pass @ WER ≤ 0.20 with faster-whisper large-v3);
- MOS: report **Δ(generated − GT)** only (predictors are biased on codec
  speech); BLASER/SONAR + COMET weights are CC-BY-NC (eval-only);
- FLEURS numbers: label as real-speech ACOUSTIC shift (text 100% seen — see
  audit).
- **Loss charts**: `train/audio_loss` is the CURRICULUM loss — its definition
  grows at progressive-unmask onsets (v0.3 long run: cb2..cb7 activate at
  steps 1579/3157/4735/6313/7891/9469; onset→codebook mapping pinned by
  `test_v03_long_run_onset_mapping`), so upward steps there are accounting,
  not regressions. Per-codebook panels show the opposite at each onset: the
  newly-activated AND all still-masked deeper codebooks' CEs drop together
  (real transfer — the shared backbone context gains acoustic-residual
  features that the frozen trunk's pre-trained deeper heads exploit; verified
  live on both long-run attempts). For public / cross-run charts use
  `train/audio_loss_full` (unweighted all-codebook mean, pre-mask; logged
  natively by the trainer; for runs recorded before it landed, derive +
  backfill after the run finishes with
  `scripts/wandb_audio_full_backfill.py --run <entity/project/run_id>
  --backfill` — it refuses while the run is live).

## Sanity gates for the live verification (executed)

GT-audio topline ≫ model score; whisper-judge floor
consistent with corpus QC; DNSMOS(GT) ≈ codec ceiling; Gemini-vs-whisper
referee agreement high on GT audio. Record wall-clock + $ per sweep here
afterwards.
