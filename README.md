# TinyAya — TR↔HI Speech-to-Speech Translation

Moshi-style **speech-to-speech translation with a text inner-monologue** for
Turkish↔Hindi, built on a LoRA-fine-tuned Cohere2 backbone (3B) with a **frozen** Moshi
depth decoder producing 8 RVQ Mimi codebooks.

> **Status (v0.3):** recipe frozen and pipeline-validated; the full 3-epoch production
> run has not yet completed, so eval numbers are pending. This is a research checkpoint
> for low-resource S2ST, not a production translator. See
> [`docs/v0.3-public-release-plan.md`](docs/v0.3-public-release-plan.md) for the honest
> release narrative.

## Architecture

```
User audio stream ──┐
                    ├──▶ Backbone (Cohere2 3B, LoRA) ──▶ CB0 prediction
Model audio stream ─┘         │                              │
Text stream ────────┘         ▼                              ▼
                         Projection (2048→4096)        audio_heads[0]
                              │
                              ▼
                    Depth Decoder (Moshiko 6L, frozen) ──▶ CB1-CB7 predictions
                              │
                              ▼
                    Mimi Codec Decode ──▶ Audio output
```

Key design choices:
- **Parallel two-stream format** — user audio + model audio run simultaneously (Moshi-style), the model learns turn-taking via silence tokens
- **Codebook delay pattern** — CB_k shifted right by k frames for causal lookahead (predictions are decoded with `undo_codebook_delay` before Mimi decode)
- **CB0 from backbone, CB1-7 from the frozen depth decoder** — only the depth decoder's I/O layers are trained; its transformer blocks stay frozen
- **Text+audio** (corrected 2026-07-08) — the corpus ships word-level alignments for every sample (`{stem}.{src,tgt}.alignments.json` at the dataset root; earlier "no alignments" checks used the wrong filenames), so the Moshi inner-monologue/text stream IS supervised; v0.3 trains `text_weight=0.2`

## Repository Structure

```
├── configs/                    # Training configs (YAML), split per backend
│   ├── gpu/                     # CUDA + FSDP configs
│   └── tpu/                     # XLA/SPMD configs
│       ├── stage2_tpu_v6e16_full_v03.yaml   # ★ v0.3 production run (v6e-16, 14,532 steps)
│       ├── stage2_tpu_v6e16_smoke_r32.yaml  # r=32 winner full-corpus smoke
│       └── stage2_tpu_v6e8_overfit.yaml     # pipeline-validation (32-example memorize)
├── scripts/
│   ├── train_hierarchical.py   # Main training script (SHARED, backend-dispatched)
│   ├── eval_checkpoint.py       # Eval: teacher-forced + AR decode, per-codebook acc, ASR-BLEU
│   ├── ci/check_backend_seam.sh # CI: forbid module-level torch_xla in shared code
│   └── tpu/                     # TPU run-infra (queued-resource launch, redeploy, sweeps, ops)
├── sweeps/                     # W&B capacity sweep (two-stage: grid + Bayesian)
├── src/
│   ├── model/                  # composite, backbone, depth_decoder, lora_setup, scan_utils
│   ├── data/                   # dataset (delay pattern), collator (parallel stream), mimi
│   ├── training/               # checkpointing, scheduler, translation_loss
│   └── backend/                # base + gpu_backend + tpu_backend (ONLY torch_xla importer)
├── docs/                       # release plan, model cards, TPU runbook, onboarding
├── .claude/                    # External Memory System (PLAN/PROGRESS/VERIFY/memories, hooks, skills)
├── AGENTS.md                   # agent briefing + TPU↔GPU seam rules
└── pyproject.toml
```

### Backends (GPU ↔ TPU)

The repo is **dual-backend**. The same `src/` and `scripts/train_hierarchical.py` run on
either GPU or TPU; only **configs** (`configs/gpu/` vs `configs/tpu/`) and **launchers**
(`torchrun` vs `scripts/tpu/`) differ. `torch_xla` is confined to
`src/backend/tpu_backend.py` (enforced by `scripts/ci/check_backend_seam.sh`), so GPU
runs and CPU-only tests never import it.

## Quick Start

### Prerequisites
- Python 3.12, [`uv`](https://docs.astral.sh/uv/)
- 1-2× NVIDIA GPUs ≥24GB VRAM (GPU path) **or** a Cloud TPU v6e (TPU path)
- Access to `CohereLabs/tiny-aya-base` (gated model, request on HF)

### Setup
```bash
git clone https://github.com/tiny-aya-simulatenous-translation/model.git
cd model
uv sync
```

### Training (TPU v6e-16, SPMD/FSDPv2 — the production path)
The v0.3 production run trains on **v6e-16** (4 hosts × 4 chips) in `europe-west4-a`.
`startup_script.sh` deploys the repo, stages the corpus, and launches under a TPU-side
`tmux train` session with `--resume auto` for spot-preemption recovery:

```bash
# production run: r=32 / +MLP / rsLoRA winner, 14,532 steps (3 epochs)
bash scripts/tpu/launch_release.sh configs/tpu/stage2_tpu_v6e16_full_v03.yaml
```

`XLA_NO_SPECIAL_SCALARS=1` (set by the launchers) is required — it disables XLA's
"assume no NaN/Inf" rewrites that otherwise corrupt the inline-validation loss scalar.
Checkpoints go to **`gs://tinyaya-stage2-eu/`** (europe-west4, co-located with the TPUs).

### Training (single / multi-GPU)
```bash
uv run python scripts/train_hierarchical.py --config configs/gpu/stage2_26k_parallel.yaml
# multi-GPU:
torchrun --nproc_per_node=2 scripts/train_hierarchical.py --config configs/gpu/stage2_26k_parallel.yaml
```

### Evaluation
```bash
uv run python scripts/eval_checkpoint.py \
    --checkpoint gs://tinyaya-stage2-eu/checkpoints/<run>/best_by_val \
    --val_jsonl /path/to/val.jsonl --encoded_dir /path/to/encoded \
    --lora_r 32 --num_samples 20 --output_dir eval_results
```
Reports teacher-forced **per-codebook accuracy** (CB0–CB7), runs autoregressive decode,
and (optionally, `--skip_asr` to disable) Whisper ASR-BLEU. The loader auto-detects the
checkpoint's LoRA structure from `peft_adapter/adapter_config.json` and remaps the TPU
scan-wrapper namespace so the adapter loads correctly on CPU/GPU (see below).

## Stage 2 recipe (capacity-sweep winner)

The v0.3 recipe was chosen by a **two-stage capacity sweep** on the full 1.24M corpus:
1. **Stage 1 (structural grid)** — which LoRA target modules: **+MLP**
   (`q,k,v,o + gate,up,down + embed_tokens`) wins; more capacity → lower loss in the
   data-rich regime.
2. **Stage 2 (Bayesian `lr × rank`)** — structure fixed to +MLP, rsLoRA on (`α=2r`).

**Winner:**
```yaml
lora:  { r: 32, alpha: 64, use_rslora: true }   # +MLP target modules, exclude_top: 2
optim: { lr_lora: 1.716e-4 }
train: { max_steps: 14532, warmup_steps: 150 }   # 3 epochs over 1,178,302 train pairs
```

Pipeline validated end-to-end via an overfit gate (32-example train==val): **all 8
codebooks memorize to 89–98%**, confirming data → LoRA backbone (CB0) → frozen depth
decoder (CB1–7) → loss → metric are all correct.

- **Sweep infra + full ranked results:** [`sweeps/README.md`](sweeps/README.md)
- **W&B project:** https://wandb.ai/cataluna84/tinyaya-stage2-tpu

## Training Data

Mimi-encoded **synthetic** parallel TR↔HI speech pairs (FLORES/OPUS-100/conversational
MT → TTS → Mimi-encode):
- ~1.24M pairs; ~5% missing `.pt` filtered → **1,178,302 train / 62,036 val**
- Each sample: source audio (8 codebooks) + target audio (8 codebooks) as `.pt` files
  **plus** word-level text alignments (`{stem}.{src,tgt}.alignments.json` at the dataset
  root — note the split manifests point at legacy names; `src/data/dataset.py` maps them)

Dataset on HuggingFace: `tiny-aya-translate/tr-hi-mimi-encoded`

## Notes on checkpoints (portability)

TPU checkpoints are saved under the grad-checkpoint/scan proxy namespace
(`layers.layers_list.<i>.layer.…`). `src/training/checkpointing.py::load_checkpoint`
remaps this to whichever namespace the live model uses (plain for CPU/GPU eval, wrapped
for TPU resume) and **raises loud** if any LoRA tensor fails to load — so an adapter can
never silently run un-adapted. Each checkpoint = LoRA adapter (`peft_adapter/`) + the
custom `projection.pt` / `depth_decoder.pt` / `audio_heads.pt` / `text_embed.pt` /
`model_audio_embed.pt` + `metadata.json`.

## Related Repos
- [`data-pipeline`](https://github.com/tiny-aya-simulatenous-translation/data-pipeline) — TTS generation, deployment, Mimi encoding
- [`sound-quality-check`](https://github.com/tiny-aya-simulatenous-translation/sound-quality-check) — 4-stage audio QC pipeline

## License
Apache 2.0 (trained deltas + our code). Base weights from Cohere and Moshi/Mimi carry
their own licenses — see [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
