# TinyAya — TR↔HI Speech-to-Speech Translation

Moshi-style **speech-to-speech translation with a text inner-monologue** for
Turkish↔Hindi, built on a LoRA-fine-tuned Cohere2 backbone (3B) with a **frozen** Moshi
depth decoder producing 8 RVQ Mimi codebooks.

> **Status (v0.3): training complete (plateau + anneal).** The long-horizon run
> on multi-host v6e-16
> ([W&B `v0.3-long-horizon-mh-r2`](https://wandb.ai/cataluna84/tinyaya-stage2-tpu/runs/xzcb60bl))
> early-stopped on the WSD plateau at step 65,250 (2.9048), then completed its
> 11k-step linear LR→0 **anneal leg** to step 76,250 — **best val composite
> 2.8199 @ step 76,000**. The **public** repo
> [`tiny-aya-translate/tr-hi-s2st-v0.3`](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3)
> carries the **full ~89-checkpoint suite** (branches + `checkpoints/` tree) +
> playable audio samples. **Release eval complete**
> ([`docs/v0.3-eval-report.md`](docs/v0.3-eval-report.md)): the inner-monologue
> *translates* — free-run **text chrF++ 25.7 / 25.1** (hi→tr / tr→hi) — while
> intelligible audio *synthesis* is the frontier (**ASR-chrF++ 3.7 / 9.6** vs a
> **92 / 87** GT-audio topline). Explore the interactive
> [**W&B emergence report**](https://wandb.ai/cataluna84/tinyaya-stage2-tpu/reports/TinyAya-v0.3-Emergence-and-Data-Efficiency--VmlldzoxNzU1OTU1NQ==).
> This is a research checkpoint for
> low-resource S2ST, not a production translator. See
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
│       ├── stage2_tpu_v6e16_full_v03_mh.yaml # ★ v0.3 long-horizon run (v6e-16 multi-host, 110,463 steps)
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
├── .claude/                    # External Memory System (hooks, skills, agents, orchestration)
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
git clone https://github.com/tiny-aya-simultaneous-translation/model.git
cd model
uv sync

cp example.env .env      # then fill in your tokens (see below)
```

**Credentials.** Secrets go in a gitignored repo-root `.env`; `example.env` is the
annotated template. Minimum to start a run:

| variable | required? | why |
|---|---|---|
| `HF_TOKEN` | **yes** | pulls the gated `CohereLabs/tiny-aya-base` + Moshi/Mimi weights; `scripts/tpu/setup_gcp.sh` aborts without it |
| `WANDB_API_KEY`, `WANDB_PROJECT`, `WANDB_ENTITY` | recommended | training runs without them, but you get no metrics, checkpoint index, or audio demos |
| `GEMINI_API_KEY` | evals only | the GEMBA adequacy judge + ASR referee in `scripts/eval_release.py` |
| `PROJECT_ID`, `REGION`, `BUCKET` | optional | GCP overrides; the defaults reproduce the published v0.3 run |

Precedence is **shell env > `.env` > script defaults**. On TPU, `setup_gcp.sh`
seeds `HF_TOKEN`/`WANDB_API_KEY` into GCP Secret Manager and the workers fetch
them at boot, so keys never land in a VM image. Per-run settings (slice, recipe,
corpus URIs) are passed to the launcher on the command line, not via `.env` —
see the training command below and [`docs/tpu-runbook.md`](docs/tpu-runbook.md).

### Training (TPU v6e-16, SPMD data-parallel — the long-horizon path)
The v0.3 long-horizon run trains on **v6e-16** (4 hosts × 4 chips) in `europe-west4-a` —
real global batch **32** (2 rows/chip × 16 chips, multi-host minibatch DP; the historical
"global batch 256" label was batch-semantics fiction, see the reval report), WSD schedule,
keep-all checkpoint suite streaming to GCS + the HF hub. Full runbook:
[`docs/tpu-runbook.md`](docs/tpu-runbook.md).
`startup_script.sh` deploys the repo, stages the corpus, and launches under a TPU-side
`tmux train` session with `--resume auto` for spot-preemption recovery:

```bash
# long-horizon run: r=32 / +MLP / rsLoRA winner, 110,463 steps (3 epochs)
# (metadata gates: expected-train-rows=1100000, min-text-coverage=99)
TRC_PROFILE=v6e-16-eu CONFIG_FILE=configs/tpu/stage2_tpu_v6e16_full_v03_mh.yaml \
SWEEP_DATA_GS_URI=gs://<your-bucket>/data/<corpus>.tar.gz \
bash scripts/tpu/launch_spot.sh
```

`XLA_NO_SPECIAL_SCALARS=1` (set by the launchers) is required — it disables XLA's
"assume no NaN/Inf" rewrites that otherwise corrupt the inline-validation loss scalar.
Checkpoints go to **`gs://<your-bucket>/`** (keep it in the TPUs' region -- a cross-region bucket makes every checkpoint write pay egress).

### Training (single / multi-GPU)
```bash
uv run python scripts/train_hierarchical.py --config configs/gpu/stage2_26k_parallel.yaml
# multi-GPU:
torchrun --nproc_per_node=2 scripts/train_hierarchical.py --config configs/gpu/stage2_26k_parallel.yaml
```

### Evaluation
```bash
uv run python scripts/eval_checkpoint.py \
    --checkpoint hub:tiny-aya-translate/tr-hi-s2st-v0.3@best \
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

**Winner** — the capacity sweep picked +MLP / r=32 / `lr_lora 1.716e-4`; the later
text+audio re-validation finalized **arm D** (`exclude_top: 0`, adapters on all 36
layers):
```yaml
lora:  { r: 32, alpha: 64, use_rslora: true }   # +MLP target modules, exclude_top: 0
optim: { lr_lora: 1.716e-4 }
loss:  { text_weight: 0.2, composite_text_w: 0.4 }   # text+audio (corrected 2026-07-08)
train: { max_steps: 110463, warmup_steps: 150 }   # 3 epochs; trained to 76,250 (WSD early-stop + anneal)
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

## Related Links
- [Blog: Adapting Moshi for Low-Resource Speech Translation](https://labscommunity.cohere.com/blog/2026/adapting-moshi-low-resource-speech-translation/) — Cohere Labs Community
- [Model + checkpoints on Hugging Face](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3)

## Related Repos
- `data-pipeline` — TTS generation, deployment, Mimi encoding *(private repo — not publicly browsable)*
- [`sound-quality-check`](https://github.com/tiny-aya-simultaneous-translation/sound-quality-check) — 4-stage audio QC pipeline

## License

- **Code (this repository): Apache-2.0** (see [`LICENSE`](LICENSE)).
- **Released weights** (LoRA adapters + trained embeddings/projection at
  [`tiny-aya-translate/tr-hi-s2st-v0.3`](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3)):
  **CC-BY-NC-4.0** — they are derivatives of `CohereLabs/tiny-aya-base`
  (CC-BY-NC-4.0) and inherit its non-commercial terms; Moshi/Mimi components
  are CC-BY-4.0 (attribution given). Details in
  [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

## Acknowledgements

Training compute (Cloud TPU v6e) provided by **Google's TPU Research Cloud (TRC)**.
Built on [Cohere Labs tiny-aya](https://huggingface.co/CohereLabs/tiny-aya-base) and
[kyutai's Moshi/Mimi](https://github.com/kyutai-labs/moshi).
