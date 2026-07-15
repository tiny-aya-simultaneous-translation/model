# Evals runbook — v0.3 S2ST evaluation harness

Operating manual for the evals program (design: `docs/v0.3-evals-plan.md`).
Status 2026-07-15: **code complete + CPU-tested; the live GPU session is
SHELVED until the long-horizon run finishes** (`docs/do.md`). Nothing here
touches the TPU slice or the training run.

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

## GPU box bringup (when the session un-shelves)

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
    --checkpoint gs://tinyaya-stage2-eu/ckpts/<run>/step_<N> \
    --subset eval/subsets/v03-val-500.jsonl \
    --val_jsonl /data/splits/val.jsonl --encoded_dir /data/encoded \
    --device cuda --gemini_referee 25 \
    --output_dir eval_out/step_<N> \
    --wandb_run cataluna84/tinyaya-stage2-tpu/<run_id> \
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

## Milestone cadence

Sweep with Tier 1 continuously (cheap); run Tier 2 on: log-spaced early
checkpoints {1k, 2k, 4k, 8k, ...}, every ~20k after, `best_by_val`, `final`,
and the **LAWA average** (`scripts/average_checkpoints.py`). Compare
LAWA-vs-best-vs-final with `src/evaluation/text_metrics.paired_bootstrap`
(report p-values). Tier 3 runs on release candidates only.

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

## Sanity gates for the (shelved) live verification

From `docs/do.md`: GT-audio topline ≫ model score; whisper-judge floor
consistent with corpus QC; DNSMOS(GT) ≈ codec ceiling; Gemini-vs-whisper
referee agreement high on GT audio. Record wall-clock + $ per sweep here
afterwards.
