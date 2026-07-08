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
  **`lora_r=32, alpha=64, rsLoRA, lr_lora=1.716e-4`** (`exclude_top=2`). In the data-rich
  regime more LoRA capacity → lower loss (opposite of the small-data overfit regime).
- **Deep-codebook learning** — per-codebook loss weighting; the frozen depth decoder's
  I/O layers train while its blocks stay frozen.
- **Pipeline validated** — an overfit gate (32-example train==val) memorizes **all 8
  codebooks to 89–98%**. Note: an earlier per-codebook accuracy metric scored CB1–7
  against the *undelayed* target and read a false ~0%; fixed — CB1–7 were always learning.

Production config: `configs/tpu/stage2_tpu_v6e16_full_v03.yaml`, **14,532 steps (3 epochs)**.

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
