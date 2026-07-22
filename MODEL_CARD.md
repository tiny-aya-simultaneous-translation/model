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
  - chrf
model-index:
  - name: tinyaya-stage2-tr-hi-s2st-v0.3
    results:
      - task: { type: audio-to-audio, name: Speech-to-Speech Translation }
        dataset: { type: tiny-aya-translate/tr-hi-mimi-encoded, name: v03-val-500 (in-domain) }
        metrics:
          # Free-run text inner-monologue — the translation the model produces (chrF++).
          - { type: chrf, name: "Free-run text chrF++ (hi->tr)", value: 25.7 }
          - { type: chrf, name: "Free-run text chrF++ (tr->hi)", value: 25.1 }
          # Generated-audio ASR-chrF++ (Whisper-transcribed); report WITH the GT-audio
          # topline (92.1 / 86.6) — the pipeline ceiling — so the gap reads honestly.
          - { type: chrf, name: "ASR-chrF++ (hi->tr)", value: 3.7 }
          - { type: chrf, name: "ASR-chrF++ (tr->hi)", value: 9.6 }
---

> **Version:** `v0.3` — text+audio, capacity-swept recipe. **Complete**: the full-corpus
> long-horizon run finished (WSD early-stop @ 65,250 + anneal → 76,250; **best val composite
> 2.8199 @ step 76,000**, 2.07 epochs), and the release evaluation has run. Versions are git
> tags; load a specific one with `revision=`. See **Version history** at the bottom.

# TinyAya Stage 2 — Turkish ↔ Hindi Speech-to-Speech Translation (LoRA)

Stage-2 **text+audio** speech-to-speech translation adapter for Turkish↔Hindi, trained
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
| Task | TR↔HI speech-to-speech translation with a **text inner-monologue** (Moshi hierarchical codebook decode) |
| Base | `CohereLabs/tiny-aya-base` + frozen Moshi depth decoder + Mimi codec |
| Method | LoRA (r=32, +MLP, rsLoRA, adapters on all 36 layers) + trained projection/heads/embeds; bf16, FSDPv2 SPMD |
| Hardware | Cloud TPU v6e-16 (4 hosts × 4 chips), europe-west4-a, via Google TRC |
| Horizon | 76,250 steps (2.07 epochs); WSD schedule with a linear anneal leg; **best val 2.8199 @ 76,000** |
| Data | `tiny-aya-translate/tr-hi-mimi-encoded` (synthetic, Mimi-encoded, with word-level text alignments) |

## Training procedure

- **Init**: LoRA on the `tiny-aya-base` backbone; Moshi depth decoder from
  `kyutai/moshiko` (transformer **blocks frozen**, only I/O layers trained); projection /
  per-codebook audio heads / audio & text embeddings trained from scratch.
- **Recipe (re-validation winner, arm D)**: `lora {r:32, alpha:64, use_rslora:true}`,
  target modules **+MLP** (`q,k,v,o + gate,up,down + embed_tokens`, **`exclude_top:0`** —
  adapters on all 36 layers), `lr_lora 1.716e-4`, 150 warmup, `max_frames 300`, 8 codebooks,
  **text+audio loss** (`text_weight 0.2`, `composite_text_w 0.4`; the corpus ships
  word-level alignments, so the text inner-monologue is supervised).
- **Data**: synthetic `tr-hi-mimi-encoded`, ~1.24M pairs → **1,178,302 train / 62,036
  val** after filtering ~5% rows with missing `.pt` files.

**Pipeline validation (honest):** an overfit gate (32-example train==val) memorizes **all
8 codebooks to 89–98%**, confirming the full data→backbone(CB0)→frozen-depth(CB1–7)→
loss→metric path is correct. A per-codebook accuracy metric bug (predictions were scored
against the *undelayed* target while the model predicts *delayed* codes) understated
CB1–7 in earlier dashboards and is fixed; loss-based metrics were never affected.

## Evaluation

Full end-task evaluation (500-row in-domain `v03-val-500`, greedy) framed as a
**data-efficiency / emergence** study — *how much full-corpus training before translation
quality emerges, not just language identity?* Reproduce with `scripts/eval_release.py`;
the detailed report is `docs/v0.3-eval-report.md`.

| Metric | hi→tr | tr→hi | notes |
|--------|-------|-------|-------|
| Free-run **text** chrF++ (inner-monologue) | **25.7** | **25.1** | the model *translates* — text emerges |
| Generated-audio **ASR-chrF++** | 3.7 | 9.6 | audio not yet ASR-intelligible |
| **GT-audio topline** chrF++ (ceiling) | 92.1 | 86.6 | pipeline is sound — the gap is synthesis, not the harness |
| **BLASER-2.0 QE** (ASR-free, 1–5) | ~2.5 | ~2.5 | speech carries real, weak translation signal ASR can't recover |
| **DNSMOS** Δ(gen − GT) | −1.34 | −1.34 | naturalness gap |

**Honest reading:** the full-corpus run learns the translation *mapping* — a 96.6%
teacher-forced text inner-monologue that free-runs to ~25 chrF++ — and genuine
speech-semantic signal (BLASER-QE 2.5), within ~2 epochs. **Intelligible audio
*synthesis* is the remaining, quantified frontier**, bounded by the frozen Moshi depth
decoder rather than the translation understanding. On real human speech (FLEURS) the
model is distribution-bound (acoustic-shift only; texts overlap training).

## Intended use & limitations

- **Intended**: research on low-resource speech-to-speech and simultaneous translation.
- **Limitations**: **audio synthesis is the frontier** — the text inner-monologue
  translates, but generated speech is not yet ASR-intelligible free-run (frozen depth
  decoder); trained on synthetic TTS speech (expect degradation on spontaneous/noisy
  audio, and heavy distribution-dependence); two directions only; AR generation not
  latency-optimized here. References are MT-synthetic; report any ASR score next to its
  GT-audio topline.

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
- **Emergence report (W&B)**: https://wandb.ai/cataluna84/tinyaya-stage2-tpu/reports/TinyAya-v0.3-Emergence-and-Data-Efficiency--VmlldzoxNzU1OTU1NQ==
- **Checkpoints (GCS)**: `gs://tinyaya-stage2-eu/checkpoints/`
- **Dataset**: https://huggingface.co/datasets/tiny-aya-translate/tr-hi-mimi-encoded
- **Code**: https://github.com/tiny-aya-simultaneous-translation/model

## Version history

Versions are **git tags** in this repo (HF convention: one checkpoint per repo). Load one
with `revision=`.

| Version | Data | Outcome | Note |
|---------|------|---------|------|
| `v0.1` | synthetic `tr-hi-mimi-encoded` (~1.18M) | audio learned; text stream weak | Early runs under-supervised the text stream; the corpus *does* ship alignments (later corrected). |
| `v0.2` | `fleurs-tr-hi-mimi-encoded` (~8.3k) | overfit (val bottomed ~step 1000) | Trained on the wrong (FLEURS) dataset via a launcher default (disclosed). |
| `v0.3` | synthetic `tr-hi-mimi-encoded` (~1.24M) | **text+audio, capacity-swept; complete + evaluated** | r=32/+MLP/rsLoRA/`exclude_top:0` winner; 2.07-epoch run, best val 2.8199 @ 76,000; text translation emerges, audio synthesis is the frontier. |

## Acknowledgments

Cloud TPU compute provided by Google's **TPU Research Cloud (TRC)**. See `NOTICE` and
`THIRD_PARTY_NOTICES.md`.
