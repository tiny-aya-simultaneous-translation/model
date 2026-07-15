---
license: apache-2.0
base_model: CohereLabs/tiny-aya-base
base_model_relation: adapter
library_name: peft
datasets:
  - tiny-aya-translate/tr-hi-mimi-encoded
language:
  - tr
  - hi
tags:
  - speech-to-speech-translation
  - speech-translation
  - lora
  - moshi
  - mimi
  - tinyaya
pipeline_tag: audio-to-audio
metrics:
  - bleu
# Eval results (ASR-BLEU + per-codebook accuracy + DNSMOS) go here once the v0.3
# long-horizon run finishes and the release eval has run. Template:
# model-index:
#   - name: tinyaya-stage2-tr-hi
#     results:
#       - task: { type: audio-to-audio, name: Speech-to-Speech Translation }
#         dataset: { type: tiny-aya-translate/tr-hi-mimi-encoded, name: tr-hi-mimi-encoded }
#         metrics:
#           - { type: bleu, name: ASR-BLEU (tr->hi), value: TBD }
#           - { type: bleu, name: ASR-BLEU (hi->tr), value: TBD }
---

> **Version:** `v0.3` — audio-only, capacity-sweep recipe. **Held**: the full 3-epoch
> long-horizon run (110,463 steps, multi-host v6e-16) has not yet completed, so weights + eval are pending. Versions are git
> tags; load a specific one with `revision=`. See **Version history** at the bottom.

# TinyAya Stage 2 — Turkish ↔ Hindi Speech-to-Speech Translation (LoRA)

Stage-2 **audio-only** speech-to-speech translation adapter for Turkish↔Hindi, trained
on Cloud TPU v6e. This repo ships the authors' **trained deltas only** — a LoRA adapter
over `CohereLabs/tiny-aya-base` plus the custom projection / Moshi depth-decoder /
audio-head / embedding tensors.

> ## ⚠️ License scope — read first
> The **`apache-2.0`** license above covers **only the trained weights in this repo**
> (the LoRA adapter + custom heads) and the authors' code. It does **NOT** relicense the
> components this model builds on (see `THIRD_PARTY_NOTICES.md`):
> - **`CohereLabs/tiny-aya-base`** → **Cohere model license** (NOT Apache; not included — obtain it from Cohere).
> - **Moshi / Mimi** (depth decoder + audio codec) → **MIT**.
> - **Source data**: FLORES (CC BY-SA 4.0), OPUS-100, conversational MT, and TTS-model outputs (per-source terms).

## What this is

| | |
|---|---|
| Task | TR↔HI **audio-only** speech-to-speech translation (Moshi hierarchical codebook decode) |
| Base | `CohereLabs/tiny-aya-base` + frozen Moshi depth decoder + Mimi codec |
| Method | LoRA (r=32, +MLP, rsLoRA) + trained projection/heads/embeds; bf16, FSDPv2 SPMD |
| Hardware | Cloud TPU v6e-16 (4 hosts × 4 chips), europe-west4-a, via Google TRC |
| Horizon | 110,463 steps (3 epochs, effective batch 256) |
| Data | `tiny-aya-translate/tr-hi-mimi-encoded` (synthetic, Mimi-encoded, audio-only) |

## Training procedure

- **Init**: LoRA on the `tiny-aya-base` backbone; Moshi depth decoder from
  `kyutai/moshiko` (transformer **blocks frozen**, only I/O layers trained); projection /
  per-codebook audio heads / audio & text embeddings trained from scratch.
- **Recipe (capacity-sweep winner)**: `lora {r:32, alpha:64, use_rslora:true}`,
  target modules **+MLP** (`q,k,v,o + gate,up,down + embed_tokens`, `exclude_top:2`),
  `lr_lora 1.716e-4`, 150 warmup, `max_frames 300`, 8 codebooks, **audio-only loss**
  (`text_weight 0`, `audio_weight 1`; the corpus has no text alignments).
- **Data**: synthetic `tr-hi-mimi-encoded`, ~1.24M pairs → **1,178,302 train / 62,036
  val** after filtering ~5% rows with missing `.pt` files.

**Pipeline validation (honest):** an overfit gate (32-example train==val) memorizes **all
8 codebooks to 89–98%**, confirming the full data→backbone(CB0)→frozen-depth(CB1–7)→
loss→metric path is correct. A per-codebook accuracy metric bug (predictions were scored
against the *undelayed* target while the model predicts *delayed* codes) understated
CB1–7 in earlier dashboards and is fixed; loss-based metrics were never affected.

## Evaluation

Audio-only, so we report what the model actually does — **per-codebook accuracy**
(teacher-forced), **ASR-BLEU** (Whisper transcribes generated target audio, BLEU vs.
reference), and **DNSMOS/UTMOS** (naturalness). Reproduce with `scripts/eval_checkpoint.py`.
**Pending** for this release (long-horizon run launch-ready); will be filled into the YAML
`model-index` + below.

| Metric | tr→hi | hi→tr | overall |
|--------|-------|-------|---------|
| ASR-BLEU | _TBD_ | _TBD_ | _TBD_ |
| Per-codebook acc (CB0 / mean) | _TBD_ | _TBD_ | _TBD_ |
| DNSMOS (ovrl) | _TBD_ | _TBD_ | _TBD_ |

## Intended use & limitations

- **Intended**: research on low-resource speech-to-speech and simultaneous translation.
- **Limitations**: **audio-only** — no text/inner-monologue supervision (the corpus has
  no alignments), so sentence-level translation quality is expected to be limited; trained
  on synthetic TTS speech (expect degradation on spontaneous/noisy audio); two directions
  only; AR generation not latency-optimized here.

## Inference quickstart

```python
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel

BASE = "CohereLabs/tiny-aya-base"                      # obtain per Cohere license
ADAPTER = "tiny-aya-translate/tr-hi-s2st-v0.3"          # this repo

tok = AutoTokenizer.from_pretrained(BASE, trust_remote_code=True)
base = AutoModelForCausalLM.from_pretrained(BASE, torch_dtype=torch.bfloat16, trust_remote_code=True)
model = PeftModel.from_pretrained(base, ADAPTER)        # loads adapter_model.safetensors
```

Then attach the custom heads (`projection` / `depth_decoder` / `audio_heads` /
`text_embed` / `model_audio_embed`) and the Mimi codec; the full speech→speech pipeline
(Mimi encode → backbone+depth-decoder → `undo_codebook_delay` → Mimi decode) is in
`scripts/eval_checkpoint.py`.

## Links

- **Training (W&B)**: https://wandb.ai/cataluna84/tinyaya-stage2-tpu
- **Checkpoints (GCS)**: `gs://tinyaya-stage2-eu/checkpoints/`
- **Dataset**: https://huggingface.co/datasets/tiny-aya-translate/tr-hi-mimi-encoded
- **Code**: https://github.com/tiny-aya-simulatenous-translation/model

## Version history

Versions are **git tags** in this repo (HF convention: one checkpoint per repo). Load one
with `revision=`.

| Version | Data | Outcome | Note |
|---------|------|---------|------|
| `v0.1` | synthetic `tr-hi-mimi-encoded` (~1.18M) | audio learned; text stream did not | Corpus has **no text alignments** — text is structurally untrainable (card corrected). |
| `v0.2` | `fleurs-tr-hi-mimi-encoded` (~8.3k) | overfit (val bottomed ~step 1000) | Trained on the wrong (FLEURS) dataset via a launcher default (disclosed). |
| `v0.3` | synthetic `tr-hi-mimi-encoded` (~1.24M) | **audio-only, capacity-swept** | r=32/+MLP/rsLoRA winner; 3-epoch run held; eval pending. |

## Acknowledgments

Cloud TPU compute provided by Google's **TPU Research Cloud (TRC)**. See `NOTICE` and
`THIRD_PARTY_NOTICES.md`.
