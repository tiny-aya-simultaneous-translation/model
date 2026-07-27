# Onboarding Guide: TinyAya Stage 2 (TR↔HI Speech-to-Speech Translation)

A codebase tour for someone who has just cloned the repo. It explains what each
piece does and *why* it is shaped that way — the XLA and memory constraints that
drove most of the odd-looking decisions.

> **Citations use symbol names, not line numbers.** An earlier version of this
> guide cited `file.py:NN` throughout; every one of those numbers had rotted.
> Search for the symbol instead — e.g. `grep -rn "def apply_lora" src/`.

## Table of Contents

1. [What this project does](#1-what-this-project-does)
2. [Where v0.3 landed](#2-where-v03-landed)
3. [Architecture overview](#3-architecture-overview)
4. [Repository structure](#4-repository-structure)
5. [Data pipeline](#5-data-pipeline)
6. [Model architecture](#6-model-architecture)
7. [Training pipeline](#7-training-pipeline)
8. [Evaluation pipeline](#8-evaluation-pipeline)
9. [Configuration system](#9-configuration-system)
10. [Running the code](#10-running-the-code)
11. [Key constants and magic numbers](#11-key-constants-and-magic-numbers)

---

## 1. What this project does

Turkish ⇄ Hindi **speech-to-speech translation**: audio in, audio out, with a
text "inner monologue" running alongside the audio stream (the Moshi idea).

The pipeline is:

1. **Encode** source audio to discrete tokens with **Mimi** (a neural audio
   codec) — 8 residual codebooks at 12.5 Hz.
2. **Interleave** those audio tokens with text tokens on a shared timeline, so
   the model predicts text and audio in the same autoregressive stream.
3. **Process** the stream through a **Cohere2 backbone** (`tiny-aya-base`,
   ~3.4B params, bf16), LoRA-adapted.
4. **Predict** codebook 0 (the semantic codebook) from the backbone, and
   codebooks 1–7 from a **frozen Moshi depth decoder**.
5. **Decode** the 8 codebooks back to a waveform with Mimi.

Stage 2 is the *translation* stage: it adapts an already-pretrained text model
to consume and emit speech, rather than training a speech model from scratch.

## 2. Where v0.3 landed

The v0.3 long-horizon run is complete and the model is public. Read
[`docs/v0.3-eval-report.md`](v0.3-eval-report.md) for the full analysis; the
short version:

| | |
|---|---|
| Run | W&B [`xzcb60bl`](https://wandb.ai/cataluna84/tinyaya-stage2-tpu/runs/xzcb60bl), TPU v6e-16 |
| Horizon | **76,250 steps / 2.07 epochs** (WSD early-stop at 65,250 + an 11k-step linear anneal) |
| Best | **val composite 2.8199 @ step 76,000**; text-token accuracy 96.6% |
| Weights | [`tiny-aya-translate/tr-hi-s2st-v0.3`](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3) (~89-checkpoint suite) |

The honest result, framed as a data-efficiency study: **the text inner-monologue
learns to translate** (free-run chrF++ ~25.7 / 25.1) while **intelligible audio
synthesis is the frontier** (ASR-chrF++ 3.7 / 9.6 against a 92 / 87 GT-audio
topline). Capability arrives in the order *language identity → text translation
→ audio synthesis*, and this run buys the first two. The bottleneck is the
frozen depth decoder, not the translation understanding.

## 3. Architecture overview

```
User audio stream ──┐
                    ├──▶ Backbone (Cohere2 3B, LoRA) ──▶ CB0 prediction
Model audio stream ─┘         │                              │
Text stream ────────┘         ▼                              ▼
                         Projection (2048→4096)        audio_heads[0]
                              │
                              ▼
                    Depth Decoder (Moshiko 6L, frozen) ──▶ CB1–CB7
                              │
                              ▼
                    Mimi Codec Decode ──▶ Audio output
```

Four design choices explain most of the code:

- **Parallel two-stream format.** User audio and model audio advance
  simultaneously (Moshi-style); the model learns turn-taking from silence
  tokens rather than from an explicit turn signal.
- **Codebook delay pattern.** Codebook *k* is shifted right by *k* frames so
  each codebook can condition causally on coarser ones. Predictions must be run
  through `undo_codebook_delay` (`src/data/dataset.py`) before Mimi decodes them
  — decoding delayed predictions directly produces garbled audio.
- **CB0 from the backbone, CB1–7 from the frozen depth decoder.** Only the depth
  decoder's I/O layers train; its transformer blocks stay frozen. This is what
  keeps the trainable count small — and, per the v0.3 evaluation, it is also the
  ceiling on audio quality.
- **Text + audio.** The corpus ships word-level alignments, so the text stream
  *is* supervised (`text_weight 0.2`). An earlier premise that the corpus had no
  alignments was wrong — see the correction in
  [`docs/v0.3-public-release-plan.md`](v0.3-public-release-plan.md).

**Sizes:** composite ≈ **5.24B params**, of which ≈ **192M are trainable**
(~3.7%) under the v0.3 recipe. The trainer prints the exact count at startup
(`freeze_depth_internals` plus the "Total … trainable …" line) — treat that as
ground truth. (A `122M trainable / 5.17B composite` figure appears in older
notes; that is the **v0.2-era** config, `r=16` with the top two layers excluded.)

## 4. Repository structure

The repo is **flattened** — everything lives at the root. There is no
`simultaneous-translation/` subdirectory.

```
├── configs/                      # YAML training configs, split per backend
│   ├── gpu/                      # CUDA path
│   └── tpu/                      # XLA/SPMD path
│       ├── stage2_tpu_v6e16_full_v03_mh.yaml         # ★ the v0.3 run config
│       ├── stage2_tpu_v6e16_full_v03_mh_anneal.yaml  # ★ its anneal leg
│       └── stage2_tpu_v6e8_overfit.yaml              # 32-example memorization gate
├── src/
│   ├── backend/      # base.py + gpu_backend.py + tpu_backend.py (ONLY torch_xla importer)
│   ├── model/        # backbone, composite, depth_decoder, lora_setup, scan_utils, surgery
│   ├── data/         # dataset (delay pattern), interleaver, collator, bucket_sampler,
│   │                 #   spec_augment, mimi_encoder
│   ├── training/     # translation_loss, scheduler, checkpointing, codebook_schedule,
│   │                 #   early_stop, multitask, param_classify
│   └── evaluation/   # 10 modules behind scripts/eval_release.py (see §8)
├── scripts/
│   ├── train_hierarchical.py     # the training entrypoint (backend-dispatched)
│   ├── eval_release.py           # 8-stage release evaluator
│   ├── eval_checkpoint.py        # teacher-forced + AR decode, per-codebook accuracy
│   ├── eval_translation_proxy.py # cheap CPU text-quality proxy
│   ├── gen_parallel.py           # generate audio from a checkpoint
│   ├── make_splits.py            # leak-free train/val splits
│   ├── average_checkpoints.py    # LAWA / windowed weight averaging
│   ├── publish_checkpoint_suite.py   # push the checkpoint suite to the Hub
│   ├── ci/                       # the two gates CI enforces
│   └── tpu/                      # provisioning, launch, staging, redeploy, monitoring
├── sweeps/                       # W&B sweep definitions (grid + Bayesian)
├── eval/subsets/                 # frozen, digest-verified eval sets
├── tests/                        # torch-free unit tests (CI runs these)
└── docs/
```

**Note on `src/training/trainer.py` and `src/training/loss.py`:** these are
Stage-1 legacy, kept for compatibility. The live training loop is inline in
`scripts/train_hierarchical.py`, and the live loss is
`src/training/translation_loss.py`.

### The TPU ↔ GPU seam

The same `src/` and `scripts/train_hierarchical.py` run on both backends; only
**configs** and **launchers** differ. `import torch_xla` is allowed **only** in
`src/backend/tpu_backend.py`, enforced by `scripts/ci/check_backend_seam.sh`.

Two modules need XLA at *runtime* but must not import it at module scope, so
they import lazily inside functions — `src/model/scan_utils.py` and
`src/training/checkpointing.py`. Do not "tidy" those imports to the top of the
file; the seam gate greps for column-0 imports and the build will fail.

## 5. Data pipeline

### 5.1 Mimi encoding

`src/data/mimi_encoder.py` (`MimiEncoder`) wraps the Mimi codec: waveform →
`[8, T]` integer codes at 12.5 Hz (80 ms per frame) and back. The **bulk offline
encode lives in a separate data-pipeline repo**; in this repo the encoder is
used by `scripts/gen_parallel.py` and the eval harness to round-trip audio.

### 5.2 Interleaving

`src/data/interleaver.py` (`Interleaver`) places text tokens on the audio
timeline using word-level alignments (`{stem}.{src,tgt}.alignments.json` at the
dataset root), producing the Moshi-style parallel stream. The loader resolves
those files via `_resolve_alignment` in `src/data/dataset.py`, which also
enforces a fail-loud coverage guard — a silent 0% coverage is what caused the
early "the text stream doesn't learn" mystery.

### 5.3 Splits

`scripts/make_splits.py` builds leak-free train/val splits. The v0.3 corpus is
~1.24M pairs → **1,178,302 train / 62,036 val** after dropping the ~5% of rows
whose `.pt` file is missing upstream.

### 5.4 Dataset classes

`src/data/dataset.py` provides `TranslationDataset` and
`StreamingTranslationDataset` (plus `InterleavedAudioDataset`). This module also
owns the delay-pattern helpers `apply_codebook_delay` / `undo_codebook_delay`
and the `SILENCE_TOKEN` constant.

### 5.5 Batching

- `src/data/collator.py` (`InterleavedCollator`) pads and stacks the parallel
  streams.
- `src/data/bucket_sampler.py` (`BucketedMacroBatchSampler`) groups similar
  lengths together. On XLA this matters more than usual: every distinct shape
  triggers a recompile, so bucketing keeps the graph count bounded.
- `src/data/spec_augment.py` (`apply_spec_augment`) masks time spans and whole
  codebooks of the **input** stream only — never targets, never validation.
  Flag-gated, default off.

## 6. Model architecture

### 6.1 Backbone — `src/model/backbone.py`

`TinyAyaBackbone` wraps `CohereLabs/tiny-aya-base` (Cohere2, ~3.4B, bf16) and
resizes its embedding to cover the audio vocabulary: 262,144 text tokens + 4
special tokens + 2,048 audio tokens = **264,196** rows.

### 6.2 LoRA — `src/model/lora_setup.py`

`apply_lora` attaches the adapters and `get_parameter_groups` builds the
per-group optimizer sets (each group gets its own LR — see §9). `LoRAEmbedding`
wraps the text embedding separately. `src/training/param_classify.py` classifies
parameters for the per-group gradient diagnostics.

The v0.3 recipe (**arm D**) is `r=32`, `alpha=64`, rsLoRA on, target modules
`q,k,v,o + gate,up,down + embed_tokens` (**+MLP**), and
**`lora_exclude_top: 0`** — adapters on **all 36 layers**, all trained. The
earlier champion excluded the top two layers and finished *last* on the
text+audio objective: top-layer adapters turned out to be the text lever.
`num_full_ft_layers` is 0 — nothing is fully fine-tuned.

### 6.3 Composite — `src/model/composite.py`

`TinyAyaMoshiComposite.forward` runs: backbone → `projection` (2048→4096) →
depth decoder (chunked over time for memory, `depth_chunk_size`) → per-codebook
`audio_heads`. Audio logits are shaped **`[B, 8, T, 2048]`** — 8 codebooks,
2048 codes each.

Only `audio_heads[0]` reaches the loss (CB0); CB1–7 come from the depth decoder.
`apply_lora` nonetheless marks all 8 heads trainable, so ~29M parameters are
trainable-but-dead — see the CAVEAT block in `scripts/report_capacity.py`.

### 6.4 Depth decoder — `src/model/depth_decoder.py`, `src/model/surgery.py`

`create_depth_decoder` builds the 6-layer Moshi depth decoder;
`src/model/surgery.py` extracts those weights from `kyutai/moshiko`.
`freeze_depth_internals` (in `scripts/train_hierarchical.py`) freezes the
transformer blocks and leaves only the I/O layers — input projections,
`embed_tokens`, `lm_heads` — trainable.

### 6.5 Scan — `src/model/scan_utils.py`

On TPU the 36 backbone layers compile as a single scanned stack rather than 36
unrolled copies, which collapses compile time and graph size. This module is
where the sharp edges live: `_ScanLayerWrapper` presents a `ModuleList`-shaped
proxy, `_force_full_attention_for_scan` avoids masks scan cannot handle,
`_ScanSafeDropout` keeps dropout deterministic under scan, and
`_patch_flexible_linear_bmm` works around a Moshi `FlexibleLinear` shape.

One consequence you *will* meet: scan puts (frozen, zero) adapters on all 36
layers, so the `peft_adapter/` layout differs from a 34-layer non-scan
checkpoint. `metadata.json` records which layout a checkpoint uses, and
`load_checkpoint` remaps namespaces on load.

## 7. Training pipeline

### 7.1 Loss — `src/training/translation_loss.py`

`compute_hierarchical_translation_loss` combines a text cross-entropy with a
per-codebook audio cross-entropy:

- `text_weight: 0.2`, `audio_weight: 1.0`
- `text_padding_weight: 0.01` — the un-learnable, mean-initialised padding rows
  would otherwise pin text loss at ≈ln(V)
- **Per-codebook multipliers** and **progressive coarse→fine unmasking**
  (`src/training/codebook_schedule.py`, `active_codebooks`): supervise CB0
  first, then ramp to all 8. This is the fix for the deep-codebook collapse that
  capped v0.2.
- The reported metric is `val/composite` = `0.4·text + 0.6·audio`
  (`composite_text_w` / `composite_audio_w`); `src/training/multitask.py`
  computes the text-weight curriculum and the composite.

### 7.2 Training loop — `scripts/train_hierarchical.py`

One file, backend-dispatched via `get_backend()`. It owns argument parsing,
config loading (`DEFAULTS`), the step loop, validation, metric logging,
checkpointing, and the W&B integration. It is large; navigate by symbol.

### 7.3 Scheduler — `src/training/scheduler.py`

Two are implemented: `WarmupCosineScheduler` and **`WSDScheduler`**. v0.3 used
**WSD** — warmup → stable plateau → linear anneal to zero. The property that
matters: the plateau is *stop-anytime*, so a run can early-stop on a val plateau
and then be annealed from that point. That is exactly what happened (early stop
at 65,250, an 11,000-step anneal, best at 76,000).

`src/training/early_stop.py` (`EarlyStopDecision`) implements plateau detection.
`best_by_val` is saved regardless, so stopping never degrades the released
checkpoint.

### 7.4 Checkpointing — `src/training/checkpointing.py`

`save_checkpoint` / `load_checkpoint` / `prune_checkpoints` /
`find_latest_checkpoint`, with GCS support (`is_gcs_path`). Each checkpoint is
the LoRA adapter (`peft_adapter/`) plus `projection.pt`, `depth_decoder.pt`,
`audio_heads.pt`, `text_embed.pt`, `model_audio_embed.pt`, and `metadata.json`.

`load_checkpoint` **raises loudly** if any LoRA tensor fails to load, so an
adapter can never silently run un-adapted — a real bug once made evaluation load
1 of 239 adapter tensors and report ~19% teacher-forced accuracy.

v0.3 kept **every** checkpoint (`keep_last_n: 0`), which is what made the
published Pythia-style suite and the weight-averaging experiments possible.

### 7.5 Multi-host data parallelism

On a v6e-16 the four hosts form **one** 16-chip SPMD mesh. Each host feeds its
own rows through `per_chip_batch` × `DistributedSampler` × `shard_to_device`.
`_resolve_strategy` in `src/backend/tpu_backend.py` picks the strategy: below
~500M trainable parameters it selects **`replicated`** (a full model copy per
chip, data sharded), which is what v0.3 ran. `fsdpv2` is for larger trainable
counts.

> **Batch semantics.** The real optimizer batch is `batch_size × grad_accum`.
> Historical notes multiplied by the chip count and reported a much larger
> number; that factor is not real. Surviving mentions carry a `batch-semantics`
> marker.

## 8. Evaluation pipeline

`src/evaluation/` (10 modules) sits behind `scripts/eval_release.py`, an
**8-stage resumable** evaluator: generate → ASR judges → text metrics → MOS →
semantic → LLM judge → latency → report.

| module | role |
|---|---|
| `subset.py` | frozen eval sets with a self-verifying digest — refuses on drift |
| `normalize.py` | text normalization (`NORM_VERSION`) |
| `asr_judge.py` | Whisper judges (hi: `vasista22/whisper-hindi-large-v2`, tr: `openai/whisper-large-v3`) |
| `text_metrics.py` | chrF++ / BLEU / WER |
| `mos.py` | DNSMOS, reported as Δ(generated − ground truth) only |
| `semantic.py` | BLASER-2.0 QE — ASR-free speech-semantic similarity |
| `llm_judge.py` | GEMBA adequacy (Gemini) |
| `latency.py` | RTF / time-to-first-audio |
| `stats.py` | paired bootstrap for checkpoint comparison |
| `report.py` | results.json, W&B backfill, Hub push |

Frozen subsets live in `eval/subsets/`: `v03-val-500` (in-domain) and
`v03-fleurs-200` (**real-speech acoustic shift only** — its texts overlap
training, so it must never be described as held-out text).

Lighter options: `scripts/eval_checkpoint.py` (teacher-forced + AR decode,
per-codebook accuracy) and `scripts/eval_translation_proxy.py` (CPU text proxy).

Reporting rules that are not optional: chrF++ is primary (BLEU is unreliable
below ~5), MOS is Δ-only, references are MT-synthetic, and **every ASR score is
published next to its GT-audio topline** — without the topline a low score is
unreadable.

## 9. Configuration system

YAML, loaded by `train_hierarchical.py` and merged over `DEFAULTS`. Sections:

| section | holds |
|---|---|
| `data` | corpus paths, `max_frames`, workers |
| `train` | batch, `grad_accum`, `max_steps`, schedule, precision, XLA knobs |
| `loss` | text/audio weights, per-codebook multipliers, unmask curriculum |
| `lora` | `r`, `alpha`, `dropout`, `target_modules`, `lora_exclude_top` |
| `optim` | per-group learning rates |
| `logging` | cadence, `save_dir`, W&B, checkpoint retention |
| `perf`, `spec_augment` | profiling; input augmentation |

Per-group LRs exist because the parts of this model are at very different
training stages: LoRA adapters over a pretrained backbone want a small LR, while
the projection and audio heads are randomly initialised and want a larger one.

## 10. Running the code

### 10.1 Setup

```bash
uv sync
cp example.env .env      # then fill in HF_TOKEN
```

`HF_TOKEN` is required — the base model is gated. Details in `example.env` and
`CONTRIBUTING.md`.

### 10.2 Training

GPU:

```bash
uv run python scripts/train_hierarchical.py --config configs/gpu/stage2_26k_parallel.yaml
torchrun --nproc_per_node=2 scripts/train_hierarchical.py --config configs/gpu/stage2_26k_parallel.yaml
```

TPU (the v0.3 path) — `scripts/tpu/startup_script.sh` deploys the repo, stages
the corpus, and launches under a TPU-side `tmux` session with `--resume auto`
for spot-preemption recovery:

```bash
TRC_PROFILE=v6e-16-eu \
CONFIG_FILE=configs/tpu/stage2_tpu_v6e16_full_v03_mh.yaml \
SWEEP_DATA_GS_URI=gs://<bucket>/data/<corpus>.tar.gz \
bash scripts/tpu/launch_spot.sh
```

`XLA_NO_SPECIAL_SCALARS=1` (set by the launchers) is required: without it XLA's
"assume no NaN/Inf" rewrites corrupt the inline-validation loss scalar. Full
procedure in [`docs/tpu-runbook.md`](tpu-runbook.md).

### 10.3 Evaluation

```bash
uv run --extra eval python scripts/eval_release.py \
    --checkpoint <path-or-hub-ref> \
    --subset eval/subsets/v03-val-500.jsonl \
    --output_dir eval_out/
```

Stages are resumable per `output_dir`. See
[`docs/evals-runbook.md`](evals-runbook.md) — note that two eval tools
(`unbabel-comet`, `sonar-space`) cannot co-resolve with the training pins and
live in a standalone venv.

### 10.4 Before you push

```bash
uv run python -m pytest tests/ -q
uv run ruff check .
bash scripts/ci/check_backend_seam.sh
bash scripts/ci/check_docs_sync.sh
```

CI runs exactly these (plus byte-compile, YAML parse, and shell parse) in a bare
`pytest pyyaml` environment — which is why heavy imports in `src/evaluation/`
must stay lazy.

## 11. Key constants and magic numbers

| constant | value | where |
|---|---|---|
| Audio frame rate | 12.5 Hz (80 ms/frame) | Mimi |
| Codebooks | 8 | `num_codebooks` |
| Audio vocab | 2048 per codebook | Mimi |
| Text vocab | 262,144 (+4 special, +2048 audio = 264,196) | `src/model/backbone.py` |
| Backbone hidden | 2048 | Cohere2 |
| Depth decoder | 6 layers, 4096 hidden, blocks frozen | `src/model/depth_decoder.py` |
| Backbone layers | 36 (all LoRA-adapted in v0.3) | `lora_exclude_top: 0` |
| Max frames | 300 (~24 s) | `configs/*/…` |
| Tokens per frame | 9 (1 text + 8 audio) | `tokens_seen` axis |
| Composite / trainable | ≈5.24B / ≈192M (~3.7%) | printed at startup |

Two that bite people:

- **Codebook delay** — CB*k* is shifted by *k* frames. Always
  `undo_codebook_delay` before Mimi decode, and score predictions against the
  *delayed* target. Scoring against the undelayed target once made CB1–7 read a
  false ~0% while the model was learning them fine.
- **`XLA_NO_SPECIAL_SCALARS=1`** — required on TPU (see §10.2).
