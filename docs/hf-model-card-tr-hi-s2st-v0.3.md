---
language:
  - tr
  - hi
license: apache-2.0
library_name: peft
pipeline_tag: audio-to-audio
tags:
  - speech-to-speech-translation
  - simultaneous-translation
  - moshi
  - mimi
  - lora
  - tpu
  - turkish
  - hindi
base_model: CohereLabs/tiny-aya-base
datasets:
  - tiny-aya-translate/tr-hi-mimi-encoded
model-index:
  - name: tr-hi-s2st-v0.3
    results: []   # TODO: ASR-BLEU / chrF / DNSMOS — to be filled after GPU eval
---

# TinyAya — Turkish⇄Hindi Speech-to-Speech Translation (v0.3)

> 🚧 **Held — recipe frozen, weights pending.** The 3-epoch production run has not yet
> completed, so weights and downstream metrics are **not yet published**. This card
> documents the dataset and the recipe-as-frozen, for transparency; it will be updated
> with checkpoints and evaluation once the run finishes.

Moshi-style **audio-only speech-to-speech translation** for **Turkish ⇄ Hindi**:
a LoRA-fine-tuned **Cohere2** backbone fused with a **frozen Moshi depth decoder**,
operating on **Mimi** audio codes in a parallel two-stream format. **Audio-only**: the
corpus has no text alignments, so the Moshi inner-monologue/text stream is untrainable
(`text_weight=0`).

- **Developed by:** [tiny-aya-translate](https://huggingface.co/tiny-aya-translate)
- **Funded by:** Google **TPU Research Cloud (TRC)**
- **Model type:** parallel two-stream S2ST (Cohere2 + LoRA → CB0; frozen Moshi depth decoder → CB1–7)
- **Languages:** Turkish (`tr`), Hindi (`hi`)
- **Previous version:** [`tr-hi-s2st-v0.2`](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.2)

## Dataset (corrected from v0.2)

v0.3 trains on **[`tiny-aya-translate/tr-hi-mimi-encoded`](https://huggingface.co/datasets/tiny-aya-translate/tr-hi-mimi-encoded)**
— the project's **synthetic** pipeline: parallel text from **FLORES**, **OPUS-100**, and
machine-translated **conversational** datasets, rendered with multi-voice TTS (kokoro /
XTTS-v2 / chatterbox) into ~**1.24M** Mimi-encoded clips. After filtering ~5% of rows
with missing `.pt` files: **1,178,302 train / 62,036 val**. **No text alignments ship
with the corpus** → trained audio-only.

### ⚠️ The honest mistake this fixes

**v0.2 was trained on the wrong dataset.** It used the **`fleurs-`**-prefixed
*sibling* repo — [`fleurs-tr-hi-mimi-encoded`](https://huggingface.co/datasets/tiny-aya-translate/fleurs-tr-hi-mimi-encoded)
(Mimi-encoded **FLEURS** read speech: real FLEURS audio + TTS over FLEURS text) —
because the training launcher's `HF_DATASET` default pointed there. So v0.2's
experimental setup did **not** match the FLORES/OPUS-100/conversational synthetic
corpus described in our write-up. v0.3 repoints the data loader to
`tr-hi-mimi-encoded` so the run and the description agree. We're documenting this
openly rather than silently re-labeling v0.2.

## Recipe (capacity-sweep winner)

Beyond the data-source fix, v0.3 carries codebase corrections and a recipe chosen by a
**two-stage capacity sweep on the full corpus** (not the small-data anti-overfit tuning):

- **Parallel-stream collator fix** — v0.2's pre-fix collator dropped the model audio
  stream, so `model_audio_embed` received **zero gradient**. Restored in v0.3.
- **Capacity sweep** — Stage 1 (structural grid) chose **+MLP** target modules
  (`q,k,v,o + gate,up,down + embed_tokens`); Stage 2 (Bayesian `lr × rank`) chose
  **`lora_r=32, alpha=64, rsLoRA, lr_lora=1.716e-4`** (`exclude_top=2`). In the data-rich
  regime more LoRA capacity → lower loss (opposite of the small-data overfit regime).
- **Deep-codebook learning** — per-codebook loss weighting; the frozen depth decoder's
  I/O layers train while its blocks stay frozen.
- **Pipeline validated** — an overfit gate (32-example train==val) memorizes **all 8
  codebooks to 89–98%**. Note: an earlier per-codebook accuracy metric scored CB1–7
  against the *undelayed* target and read a false ~0%; fixed — CB1–7 were always learning.

Production config: `configs/tpu/stage2_tpu_v6e16_full_v03.yaml`, **14,532 steps (3 epochs)**.

## Status checklist

| Item | Status |
|---|---|
| Data source repointed to `tr-hi-mimi-encoded` | ✅ |
| Capacity sweep → recipe frozen (r=32/+MLP/rsLoRA) | ✅ |
| Pipeline validated (all 8 codebooks memorize) | ✅ |
| Production training run (3 epochs) | ☐ held |
| Checkpoints published | ☐ pending |
| Per-codebook acc / ASR-BLEU / DNSMOS eval | ☐ pending |

## Acknowledgements

Trained on Cloud TPU **v6e-16** provided by **Google's TPU Research Cloud (TRC)**.

## Citation

```bibtex
@misc{tinyaya_tr_hi_s2st_v0_3,
  title  = {TinyAya: Turkish-Hindi Speech-to-Speech Translation (v0.3)},
  author = {tiny-aya-translate},
  year   = {2026},
  note   = {Cohere2 + frozen Moshi depth decoder, LoRA (r=32, +MLP, rsLoRA); audio-only synthetic FLORES/OPUS/conversational corpus; Google TRC TPU v6e-16},
  url    = {https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3}
}
```
