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

Moshi-style **speech-to-speech translation with a text inner-monologue** for
**Turkish ⇄ Hindi**: a LoRA-fine-tuned **Cohere2** backbone fused with a **frozen Moshi
depth decoder**, operating on **Mimi** audio codes in a parallel two-stream format.
**Text+audio** (`text_weight=0.2`): the corpus ships word-level alignments for every
sample (see Dataset), so the inner-monologue/text stream is supervised alongside audio —
earlier versions trained audio-only due to a loader bug, disclosed below.

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
with missing `.pt` files: **1,178,302 train / 62,036 val**. The corpus ships
**word-level text alignments for every sample** (`{stem}.{src,tgt}.alignments.json`,
840,426 pairs, 100% coverage) → **trained text+audio**. Note for reimplementers: the
alignment files live at the dataset root (not `encoded/`) under names that differ from
the split manifests' `src_align_path`/`tgt_align_path` fields — v0.1–v0.2 missed them
entirely because of this (silently zero text loss); our loader maps the names
(`src/data/dataset.py::_resolve_alignment`).

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
  **`lora_r=32, alpha=64, rsLoRA, lr_lora=1.716e-4`**. In the data-rich
  regime more LoRA capacity → lower loss (opposite of the small-data overfit regime).
  The final re-validation (below) then flipped `exclude_top` 2 → **0**.
- **Deep-codebook learning** — per-codebook loss weighting; the frozen depth decoder's
  I/O layers train while its blocks stay frozen.
- **Pipeline validated** — an overfit gate (32-example train==val) memorizes **all 8
  codebooks to 89–98%**. Note: an earlier per-codebook accuracy metric scored CB1–7
  against the *undelayed* target and read a false ~0%; fixed — CB1–7 were always learning.

Production config: `configs/tpu/stage2_tpu_v6e16_full_v03.yaml`, **14,532 steps (3 epochs)**.

## Recipe re-validation: 6-arm text+audio sweep (`v03-5k-reval-ta`, 2026-07-09)

Before production, the recipe was re-validated as **text+audio** on the full 1.24 M-pair
corpus — 6 arms × 5,000 steps (≈1 epoch) at global batch 256, one v6e-8 per arm. Full
report: [`v0.3-reval-report.md`](v0.3-reval-report.md). Winner: **arm D,
`lora_exclude_top: 0`** — adapters on all 36 layers. The previously frozen champion
(exclude_top=2) placed **last at every composite weighting**; the ranking
E ≺ D ≺ C ≺ F ≺ B ≺ A is unanimous across text/audio weightings {0.2/0.8, 0.4/0.6,
0.5/0.5}, and D is the winner after the pre-registered cb0-accuracy gate (E and C fall
>1 pt below best cb0). Headline science: **top-layer adapters are the text lever** —
exclude_top=0 buys ~0.5 text CE at zero audio cost.

| arm | delta | val text loss | val audio loss | composite (0.4/0.6) | W&B |
|---|---|---|---|---|---|
| **D (winner)** | exclude_top=0 | 1.181 | 4.985 | **3.464** | [0noyz5tr](https://wandb.ai/cataluna84/tinyaya-stage2-tpu/runs/0noyz5tr) |
| E | dropout .10/wd .05 | 1.140 | 4.989 | 3.450 (cb0 gate ⚠) | [7rb9pc85](https://wandb.ai/cataluna84/tinyaya-stage2-tpu/runs/7rb9pc85) |
| C | r16, lr 2.4e-4 | 1.155 | 5.009 | 3.467 (cb0 gate ⚠) | [rag7amc2](https://wandb.ai/cataluna84/tinyaya-stage2-tpu/runs/rag7amc2) |
| F | depth_unfreeze=2 | 1.476 | 4.953 | 3.562 | [jqozgc36](https://wandb.ai/cataluna84/tinyaya-stage2-tpu/runs/jqozgc36) |
| B | r64 | 1.566 | 4.958 | 3.601 | [2jtqcnla](https://wandb.ai/cataluna84/tinyaya-stage2-tpu/runs/2jtqcnla) |
| A | frozen champion | 1.692 | 4.960 | 3.653 | [powp1a50](https://wandb.ai/cataluna84/tinyaya-stage2-tpu/runs/powp1a50) |

All per-arm `best_by_val` checkpoints:
`gs://tinyaya-stage2-eu/checkpoints/stage2-reval-5k-ta/arm_{A..F}/best_by_val`.

## Training infrastructure: replicated strategy + XLA architecture changes

**Parallelism = `replicated` (SPMD data-parallel).** The composite is **5.23B params
total but only ~122M trainable** (LoRA + depth-decoder I/O), so the whole model is
**replicated on every TPU chip** and only the *data* is sharded (global batch 256 across
chips; gradients are averaged by SPMD). There is **no tensor/FSDP sharding of weights**
in the released checkpoints — a checkpoint is a plain single-replica state and loads on
one GPU without any resharding. (The trainer auto-selects `replicated` whenever
trainable params < 500M; see `src/backend/tpu_backend.py::_resolve_strategy`.)

**Architecture / lowering changes made to train this on TPU** (all verified
numerics-identical to stock; needed because XLA compiles static graphs and has no
stride-0 broadcast views):

| Change | Why | Inference impact |
|---|---|---|
| `MoshiFlexibleLinear.forward` rewritten as equal-batch `bmm` (`src/model/depth_decoder.py::_patch_flexible_linear_bmm`) | stock broadcast-batched `matmul` materialises the per-codebook weight **per token** on XLA (5.5 GiB/FFN call → OOM) | none on GPU (identical math); apply the patch if running inference on XLA |
| Identity-gather skip in the same patch (`index_select(weight, arange(C))` → read weight directly) | the training path always selects ALL codebook rows; XLA copies the full weight per call otherwise | none (identical math) |
| Full-attention forcing under `use_scan_layers` (`composite.py::_force_full_attention_for_scan`) | Cohere2 interleaves sliding/full attention (`sliding_window_pattern=4`); `scan_layers` needs 36 homogeneous layers. Sliding window 4096 ≫ max seq 300 ⇒ identical | none — attention pattern is a config read at load; released config unchanged |
| **LoRA adapters on ALL 36 layers, top-2 frozen** (`lora_setup.py::apply_lora(scan_homogeneous=True)`) instead of `exclude_top=2` omitting them | scan stacks per-layer param pytrees and requires identical keys | **checkpoint-structural**: `peft_adapter/` contains 36 layers of adapters; the top-2 are zero (`lora_B` never trained) ⇒ mathematically identical to exclusion. Load with the shipped `adapter_config.json`, not a hand-written one |
| Scan-safe dropout (`scan_utils.py::_ScanSafeDropout`) | `native_dropout`'s bool-mask meta vs bf16 XLA lowering breaks `scan`'s stacked activation buffers | none — train-time only, eval-mode is a no-op |
| Per-micro-batch graph break (`train.micro_mark_step`) + `depth_chunk_size` | XLA buffer-assignment fragmentation (81 GiB "used" over 14 GiB real) when 8 grad-accum micros trace into one program | none — pure scheduling |

> **Note for checkpoint consumers:** only the bolded row changes what is *in* the
> checkpoint (extra zero adapters on the top layers). Everything else is training-time
> lowering. Runs trained without `use_scan_layers` (e.g. an unscanned v6e-16 run) keep
> the classic 34-layer adapter layout; `metadata.json` records which applies.

## Pipeline validation (memorization gate, 2026-07-09)

Before the production run, the exact shipping stack (scan + all-36-layer adapter layout +
FlexibleLinear bmm + text+audio objective) passed a 32-example memorization gate
(train==val, regularization stripped, 800 steps) with an independent checkpoint-reload
inference examination. W&B: [`v03-overfit-ta-scan`](https://wandb.ai/cataluna84/tinyaya-stage2-tpu/runs/n768udgi).

| check | result |
|---|---|
| CB0 teacher-forced accuracy | **99.6%** (train-val) / **99.5%** (independent reload+eval) |
| CB1–7 TF accuracy | 97.9 → 88.6% monotone — the **frozen Moshi depth-decoder ceiling** (only its I/O layers train); at parity with the pre-scan stack, i.e. no regression from the XLA changes |
| Text TF accuracy | **99.8%** (CE 0.187); decoded predictions **character-identical** to targets in both TR→HI and HI→TR |
| Per-component losses | all → ~0 (audio 0.021, text 0.187; all 8 per-CB losses collapsed) |
| Checkpoint→eval parity | per-CB within 0.1–0.6 pt (CB0–3); CB4–7 1.3–1.7 pt (metric weighting + fp32-CPU vs bf16-TPU precision) |
| Greedy AR reproduction | **CB0 100.0%**; all-CB match numerically identical to TF accuracy — the AR path reproduces the training-time forward |

**Disclosure:** this gate caught an off-by-one in the *evaluation harness's*
autoregressive loop (predictions shifted one frame and conditioned on a placeholder
token). The model and training were never affected, but **AR/ASR-BLEU numbers reported
for earlier versions (v0.2 included) used the broken decoding and understate AR
quality**. Fixed in `scripts/eval_checkpoint.py`; all v0.3 release numbers use the
corrected loop.

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
  note   = {Cohere2 + frozen Moshi depth decoder, LoRA (r=32, +MLP, rsLoRA); text+audio S2ST on the synthetic FLORES/OPUS/conversational corpus; Google TRC TPU v6e},
  url    = {https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3}
}
```
