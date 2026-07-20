---
language:
  - tr
  - hi
# Weights are a derivative of CohereLabs/tiny-aya-base (CC-BY-NC-4.0) -> the
# model inherits NC. The training/eval CODE is Apache-2.0 (GitHub repo).
license: cc-by-nc-4.0
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
    results: []   # TODO: filled post-run by scripts/eval_release.py (ASR-chrF++/BLEU/WER
                  # vs GT-audio topline, MOS deltas, BLASER-2.0) over the frozen
                  # eval/subsets/* -- procedure in docs/evals-runbook.md
---

# TinyAya — Turkish⇄Hindi Speech-to-Speech Translation (v0.3)

> ✅ **Training complete (2026-07-19).** The long-horizon run
> ([`v0.3-long-horizon-mh-r2`](https://wandb.ai/cataluna84/tinyaya-stage2-tpu/runs/xzcb60bl))
> ended by **designed early stopping at step 65,250** of the 110,463-step horizon
> (10 validation cycles without improvement), with **best val composite 2.9048 at
> step 62,750** — every metric improved monotonically to the end of its budget.
> An optional WSD anneal leg from the best checkpoint is under consideration.
> **Checkpoints are live in this repo** as an interim 12-point ladder (see
> *Release design*); the full 78-checkpoint suite and the end-task release evals
> (ASR-chrF++, MOS, BLASER) land at the public flip.

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

## Training run

**Run:** [`v0.3-long-horizon-mh-r2` (xzcb60bl)](https://wandb.ai/cataluna84/tinyaya-stage2-tpu/runs/xzcb60bl)
— TPU **v6e-16** (4 hosts × 4 chips, multi-host data-parallel), global batch 32,
~1.45 s/step, **zero spot preemptions**, config
`configs/tpu/stage2_tpu_v6e16_full_v03_mh.yaml`. Ended by designed early stop at
**step 65,250** (patience 10 val cycles); 261 validation cycles over the run.

**Validation metrics** (teacher-forced, fixed 3,200-sample val gate — *not* the
end-task release evals, which are pending; see *Evaluation*):

| metric | step 250 | best (step 62,750) |
|---|---|---|
| val composite (0.4·text + 0.6·audio) | 6.719 | **2.9048** |
| val text loss / perplexity | 4.328 / 75.8 | **0.486 / 1.63** |
| val audio loss | 8.313 | **4.518** |
| val text token accuracy | 25.6% | **94.4%** |
| val cb0 (semantic codebook) accuracy | 10.4% | **40.4%** |
| val cb1–7 accuracies | 10.5 → 0.1% | **21.0 / 17.4 / 11.5 / 8.8 / 7.2 / 6.1 / 5.9%** |

Every deep codebook is alive and far above the 0.05% chance floor — the
deep-codebook collapse that capped v0.2 (cb0 ~14%, cb1–7 <4%) is resolved
(coarse→fine unmask curriculum + per-codebook loss weights). Chart-reading
notes: `train/audio_loss` shows upward steps at the curriculum onsets
(cb2–cb7 activate at steps 1,579/3,157/4,735/6,313/7,891/9,469 — the metric's
*definition* grows; per-codebook CEs actually **drop** at each onset). Use
`train/audio_loss_full` (unweighted all-codebook mean, logged natively) for the
jump-free audio learning curve.

## Listen: audio samples (click ▶ to play)

Inline audio demos generated **on the TPU during training** every 5,000 steps —
4 s, greedy, free-running audio (text stream teacher-forced). Final milestone,
full trio:

**Step 65,000 — source (Turkish):**
<audio controls src="https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/samples/step_065000/source.wav"></audio>

**Step 65,000 — ground-truth target (Hindi, synthetic TTS):**
<audio controls src="https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/samples/step_065000/target_gt.wav"></audio>

**Step 65,000 — model-generated translation:**
<audio controls src="https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/samples/step_065000/generated.wav"></audio>

**Hear it learn** — the same fixed sample generated at every 5,000-step
milestone (source/target links per row):

| step | generated | source / target |
|---|---|---|
| 5,000 | <audio controls src="https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/samples/step_005000/generated.wav"></audio> | [src](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/samples/step_005000/source.wav) / [tgt](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/samples/step_005000/target_gt.wav) |
| 10,000 | <audio controls src="https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/samples/step_010000/generated.wav"></audio> | [src](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/samples/step_010000/source.wav) / [tgt](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/samples/step_010000/target_gt.wav) |
| 15,000 | <audio controls src="https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/samples/step_015000/generated.wav"></audio> | [src](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/samples/step_015000/source.wav) / [tgt](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/samples/step_015000/target_gt.wav) |
| 20,000 | <audio controls src="https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/samples/step_020000/generated.wav"></audio> | [src](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/samples/step_020000/source.wav) / [tgt](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/samples/step_020000/target_gt.wav) |
| 25,000 | <audio controls src="https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/samples/step_025000/generated.wav"></audio> | [src](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/samples/step_025000/source.wav) / [tgt](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/samples/step_025000/target_gt.wav) |
| 30,000 | <audio controls src="https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/samples/step_030000/generated.wav"></audio> | [src](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/samples/step_030000/source.wav) / [tgt](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/samples/step_030000/target_gt.wav) |
| 35,000 | <audio controls src="https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/samples/step_035000/generated.wav"></audio> | [src](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/samples/step_035000/source.wav) / [tgt](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/samples/step_035000/target_gt.wav) |
| 40,000 | <audio controls src="https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/samples/step_040000/generated.wav"></audio> | [src](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/samples/step_040000/source.wav) / [tgt](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/samples/step_040000/target_gt.wav) |
| 45,000 | <audio controls src="https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/samples/step_045000/generated.wav"></audio> | [src](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/samples/step_045000/source.wav) / [tgt](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/samples/step_045000/target_gt.wav) |
| 50,000 | <audio controls src="https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/samples/step_050000/generated.wav"></audio> | [src](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/samples/step_050000/source.wav) / [tgt](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/samples/step_050000/target_gt.wav) |
| 55,000 | <audio controls src="https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/samples/step_055000/generated.wav"></audio> | [src](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/samples/step_055000/source.wav) / [tgt](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/samples/step_055000/target_gt.wav) |
| 60,000 | <audio controls src="https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/samples/step_060000/generated.wav"></audio> | [src](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/samples/step_060000/source.wav) / [tgt](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/samples/step_060000/target_gt.wav) |
| 65,000 | <audio controls src="https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/samples/step_065000/generated.wav"></audio> | [src](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/samples/step_065000/source.wav) / [tgt](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/samples/step_065000/target_gt.wav) |

The same clips are browsable with a step slider in the
[W&B run's](https://wandb.ai/cataluna84/tinyaya-stage2-tpu/runs/xzcb60bl)
`audio/` media panels.

## Checkpoints

All released checkpoints are browsable **directly in this repo's file tree**
under [`checkpoints/`](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/tree/main/checkpoints)
— no branch dropdown needed. Each folder is a complete weights-only bundle
(`peft_adapter/` + projection / depth-decoder / embeddings / audio heads +
`metadata.json` with full provenance):

| checkpoint | val composite ↓ | browse |
|---|---|---|
| **`best` (step 62,750)** | **2.9048** | [checkpoints/best](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/tree/main/checkpoints/best) |
| `step-65250` (final) | 2.9084 | [checkpoints/step-65250](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/tree/main/checkpoints/step-65250) |
| `step-60000` | 2.9191 | [checkpoints/step-60000](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/tree/main/checkpoints/step-60000) |
| `step-54000` | 2.9307 | [checkpoints/step-54000](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/tree/main/checkpoints/step-54000) |
| `step-48000` | 2.9486 | [checkpoints/step-48000](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/tree/main/checkpoints/step-48000) |
| `step-42000` | 2.9679 | [checkpoints/step-42000](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/tree/main/checkpoints/step-42000) |
| `step-36000` | 2.9897 | [checkpoints/step-36000](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/tree/main/checkpoints/step-36000) |
| `step-30000` | 3.0203 | [checkpoints/step-30000](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/tree/main/checkpoints/step-30000) |
| `step-24000` | 3.0693 | [checkpoints/step-24000](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/tree/main/checkpoints/step-24000) |
| `step-18000` | 3.1292 | [checkpoints/step-18000](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/tree/main/checkpoints/step-18000) |
| `step-12000` | 3.2263 | [checkpoints/step-12000](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/tree/main/checkpoints/step-12000) |
| `step-6000` | 3.9410 | [checkpoints/step-6000](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/tree/main/checkpoints/step-6000) |

The same bundles are also available as git revisions (Pythia convention) for
programmatic loading — `revision="best"`, `revision="step-60000"`, etc. This
is the interim ladder; the **full per-1,000 suite (78 checkpoints)** is
published at the public flip.

## Evaluation

**Published so far: training-time validation metrics only** (the table above —
teacher-forced, fixed 3,200-sample gate, synthetic references). The end-task
**release evals are pending** and will be produced by the repo's 8-stage
harness (`scripts/eval_release.py`) over frozen, digest-verified subsets:
ASR-chrF++/BLEU/WER per direction **with the ground-truth-audio topline**
(same judge on GT target audio — the TTS+Mimi+ASR ceiling), DNSMOS/Distill-MOS
reported as Δ(generated − GT), BLASER-2.0 QE/Ref, an LLM adequacy judge, and
RTF/first-audio latency. Subsets: `v03-val-500` (in-domain) and
`v03-fleurs-200` (real human recordings — an **acoustic** domain-shift set
only; its texts overlap the training corpus 200/200 via FLORES, audited and
disclosed). References throughout are **machine-translation-synthetic**;
chrF++ is primary (BLEU is unreliable at these ranges). Numbers land in
`model-index` and this section when the eval pass completes.

## Intended use & limitations

- **Intended:** research on speech-to-speech translation, training-dynamics
  study over the checkpoint trajectory, and TR↔HI S2ST prototyping.
  **Non-commercial only** (CC-BY-NC-4.0, inherited from the base model).
- **Not intended:** production/commercial use, surveillance, or speaker
  impersonation. Training speech is **synthetic multi-voice TTS** (kokoro /
  XTTS-v2 / chatterbox) — no real-speaker cloning data — and output voices are
  those synthetic voices.
- **Limitations:** Turkish↔Hindi only; translation references are
  MT-synthetic (quality ceilings reflect that); Mimi operates at 12.5 Hz
  frames (80 ms granularity); the training-time demos use a 4 s generation
  window; release-eval quality numbers are not yet published (see above).

## License & attribution

- **Weights (this repo): CC-BY-NC-4.0** — derivative of
  [`CohereLabs/tiny-aya-base`](https://huggingface.co/CohereLabs/tiny-aya-base)
  (CC-BY-NC-4.0). Depth-decoder and Mimi components derive from
  [kyutai's Moshi](https://huggingface.co/kyutai/moshiko-pytorch-bf16)
  (CC-BY-4.0; attribution hereby given).
- **Training/eval code: Apache-2.0** — the
  [GitHub repository](https://github.com/tiny-aya-simultaneous-translation/model).
- Some evaluation tools referenced by the harness (BLASER-2.0/SONAR, CometKiwi)
  are CC-BY-NC and are used for evaluation only; nothing from them ships in
  the weights.

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

Long-horizon run config: `configs/tpu/stage2_tpu_v6e16_full_v03_mh.yaml` —
**110,463 steps ≈ 3 real epochs at global batch 32** (2 rows/chip × 16 chips,
multi-host data-parallel), **WSD schedule** (linear warmup 1100 → peak plateau →
11,000-step linear anneal to 0; a stop-anytime anneal template covers early stops).

> **¹ Batch-semantics correction (2026-07-12 audit):** earlier configs (and the sweep
> table above) reported `batch × accum × chips` as "global batch 256" (batch-semantics). A live on-mesh
> audit proved the real optimizer batch is `loader batch × accum` — **32** for the reval
> arms and for this run. All v0.3 numbers in this card use the corrected semantics; the
> nominal-256 label is retained only where it names historical runs.

## Recipe re-validation: 6-arm text+audio sweep (`v03-5k-reval-ta`, 2026-07-09)

Before the long-horizon run, the recipe was re-validated as **text+audio** on the full 1.24 M-pair
corpus — 6 arms × 5,000 steps (≈1 epoch) at a *nominal* global batch 256 (batch-semantics
note¹ — real 32), one v6e-8 per arm. Full
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

**Parallelism = `replicated` (SPMD data-parallel), multi-host.** The composite is
**5.24B params total but only ~192M trainable** (LoRA r=32 on all 36 layers incl.
embed_tokens, projection, depth-decoder I/O), so the whole model is **replicated on
every TPU chip** and only the *data* is sharded: the long-horizon run trains on a
**v6e-16 (4 hosts × 4 chips)** where each host's `DistributedSampler` draws a disjoint
corpus shard and the minibatch input pipeline assembles the **global batch of 32**
(2 rows/chip) across the 16-chip mesh — verified bit-exact by a gradient-identity
probe; inter-host all-reduce costs ≤3% of the 1.8 s step. There is **no tensor/FSDP
sharding of weights** in the released checkpoints — a checkpoint is a plain
single-replica state and loads on one GPU without any resharding. (The trainer
auto-selects `replicated` whenever trainable params < 500M; see
`src/backend/tpu_backend.py::_resolve_strategy`.)

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

Before the long-horizon run, the exact shipping stack (scan + all-36-layer adapter layout +
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

## Release design: the checkpoint suite you will get

This repo (**`tiny-aya-translate/tr-hi-s2st-v0.3`**, private during training,
public at release) follows the Pythia/OLMo one-branch-per-checkpoint convention,
weights-only (optimizer/scheduler/RNG stay in archival storage):

- **Currently live: a 12-point interim ladder** — `best` (step 62,750),
  `step-65250` (final), and `step-{6000,12000,…,60000}` (every 6,000).
  *Ops disclosure:* the run saved **every** checkpoint (log-spaced early steps
  `{1,2,4,…,512}` + every 1,000 — 78 in total, all safe in GCS), but
  private-repo storage limits (~50 GB) capped what could be hosted here during
  the private phase; the **full 78-checkpoint suite is published at the public
  flip**. Consume any live point of the trajectory:
  ```python
  model = AutoModel.from_pretrained("tiny-aya-translate/tr-hi-s2st-v0.3",
                                    revision="step-60000")
  ```
- **`samples/step_NNNNNN/`** on `main`: source / ground-truth-target / generated
  WAVs from the inline audio demo that runs on the TPU every 5000 steps — you
  can *listen* to the model improve across training.
- **`logs/train_host0_latest.log`**: rolling training-log snapshot.
- Every checkpoint's `metadata.json` carries provenance (git SHA of the exact
  deployed code, dataset digest `rows/pt/al/md5`, seed, global batch) and a
  byte-exact file manifest.

Full telemetry is on W&B — the completed run
[`v0.3-long-horizon-mh-r2`](https://wandb.ai/cataluna84/tinyaya-stage2-tpu/runs/xzcb60bl)
(also via the [release dashboard](https://wandb.ai/cataluna84/tinyaya-stage2-tpu?nw=bg2vkino3r4))
carries losses, per-codebook prediction **entropy + active-code fraction** (the
codebook-collapse instrument), perplexities, tokens-seen axes, MFU estimate,
per-chip HBM for all 16 chips, and the audio demos. Post-hoc, each published
checkpoint gains teacher-forced text **chrF/BLEU** backfilled at its own step
(`eval/*`, via `scripts/eval_translation_proxy.py`).

## Status checklist

| Item | Status |
|---|---|
| Data source repointed to `tr-hi-mimi-encoded` | ✅ |
| Capacity sweep → recipe frozen (r=32/+MLP/rsLoRA) | ✅ |
| Pipeline validated (all 8 codebooks memorize) | ✅ |
| Long-horizon training run | ✅ completed 2026-07-19 (early stop @65,250; best val composite 2.9048 @62,750) |
| Checkpoints published | ✅ interim 12-point ladder live · ☐ full 78-checkpoint suite at public flip |
| Audio samples + training log on `main` | ✅ (13 milestones, playable above) |
| Release evals (ASR-chrF++ / MOS / BLASER) | ☐ pending — harness ready (`scripts/eval_release.py`) |
| Optional WSD anneal leg from best checkpoint | ☐ decision pending |

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
