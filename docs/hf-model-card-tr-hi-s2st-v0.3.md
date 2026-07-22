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
  # The model's OWN end-task scores on the frozen v03-val-500 subset (greedy,
  # MT-synthetic refs). The GT-audio topline (the codec+ASR ceiling: 92.1/86.6
  # chrF++) is shown beside these in the Evaluation section, not here, so a
  # scraper never mistakes the ceiling for the model. chrF++ is primary.
  - name: tr-hi-s2st-v0.3
    results:
      - task: { type: audio-to-audio, name: Speech-to-Speech Translation (HI->TR) }
        dataset: { type: tiny-aya-translate/tr-hi-mimi-encoded, name: v03-val-500 (in-domain; MT-synthetic refs) }
        metrics:
          - { type: chrf, name: ASR-chrF++ HI->TR (generated audio, greedy), value: 3.7 }
          - { type: chrf, name: free-run text chrF++ HI->TR, value: 25.7 }
      - task: { type: audio-to-audio, name: Speech-to-Speech Translation (TR->HI) }
        dataset: { type: tiny-aya-translate/tr-hi-mimi-encoded, name: v03-val-500 (in-domain; MT-synthetic refs) }
        metrics:
          - { type: chrf, name: ASR-chrF++ TR->HI (generated audio, greedy), value: 9.6 }
          - { type: chrf, name: free-run text chrF++ TR->HI, value: 25.1 }
          - { type: other, name: BLASER-2.0 QE (ASR-free speech-semantic, 1-5), value: 2.5 }
          - { type: other, name: DNSMOS delta (generated - GT), value: -1.34 }
          - { type: other, name: RTF (A100, greedy), value: 0.95 }
---

# 🗣️🔁 TinyAya — Turkish⇄Hindi Speech-to-Speech Translation (v0.3)

> ✅ **Training complete — plateau + anneal (2026-07-20).** The long-horizon run
> ([`v0.3-long-horizon-mh-r2`](https://wandb.ai/cataluna84/tinyaya-stage2-tpu/runs/xzcb60bl))
> early-stopped on the WSD plateau at step 65,250 (best 2.9048 @ 62,750), then
> completed its **11,000-step linear LR→0 anneal leg** to step **76,250** —
> improving validation on essentially every cycle of the descent to a final
> **val composite 2.8199** (text ppl 1.489, text acc 96.6%). Best = step 76,000
> ≈ final. **The repo is public and carries the FULL checkpoint suite**
> (~87 training points as branches and under `checkpoints/`). **End-task release
> evals are complete** — a data-efficiency / emergence study (the model learns
> text translation ~25 chrF++ but audio synthesis is the next frontier); see
> *Evaluation*.

Moshi-style **speech-to-speech translation with a text inner-monologue** for
**Turkish ⇄ Hindi**: a LoRA-fine-tuned **Cohere2** backbone fused with a **frozen Moshi
depth decoder**, operating on **Mimi** audio codes in a parallel two-stream format.
**Text+audio** (`text_weight=0.2`): the corpus ships word-level alignments for every
sample (see Dataset), so the inner-monologue/text stream is supervised alongside audio —
earlier versions trained audio-only due to a loader bug, disclosed below.

- **Developed by:** [tiny-aya-translate](https://huggingface.co/tiny-aya-translate)
- **Blog post:** [Adapting Moshi for Low-Resource Speech Translation](https://labscommunity.cohere.com/blog/2026/adapting-moshi-low-resource-speech-translation/)
  (Cohere Labs Community — the v0.3 training/infrastructure specifics land in its current revision)
- **Funded by:** Google **TPU Research Cloud (TRC)**
- **Model type:** parallel two-stream S2ST (Cohere2 + LoRA → CB0; frozen Moshi depth decoder → CB1–7)
- **Languages:** Turkish (`tr`), Hindi (`hi`)
- **Previous version:** [`tr-hi-s2st-v0.2`](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.2)

## ⚡ Training run

**Run:** [`v0.3-long-horizon-mh-r2` (xzcb60bl)](https://wandb.ai/cataluna84/tinyaya-stage2-tpu/runs/xzcb60bl)
— TPU **v6e-16** (4 hosts × 4 chips, multi-host data-parallel), global batch 32,
~1.45 s/step, **zero spot preemptions**, config
`configs/tpu/stage2_tpu_v6e16_full_v03_mh.yaml`. Ended by designed early stop at
**step 65,250** (patience 10 val cycles); 261 validation cycles over the run.

**Validation metrics** (teacher-forced, fixed 3,200-sample val gate — *not* the
end-task release evals, which are pending; see *Evaluation*):

| metric | step 250 | plateau best (62,750) | **annealed (76,000 = best ≈ final)** |
|---|---|---|---|
| val composite (0.4·text + 0.6·audio) | 6.719 | 2.9048 | **2.8199** |
| val text loss / perplexity | 4.328 / 75.8 | 0.486 / 1.63 | **0.398 / 1.489** |
| val audio loss | 8.313 | 4.518 | **4.435** |
| val text token accuracy | 25.6% | 94.4% | **96.6%** |
| val cb0 (semantic codebook) accuracy | 10.4% | 40.4% | **41.5%** |
| val cb1–7 accuracies | 10.5 → 0.1% | 21.0 … 5.9% | **22.0 / 18.2 / 12.1 / 9.2 / 7.5 / 6.4 / 6.1%** |

**Anneal leg.** The early stop fired on the WSD *plateau*, skipping the
scheduled decay — so the run was resumed from step 65,250 (weights + Adam
state + RNG) with `max_steps` extended to 76,250, placing the entire remaining
horizon in the pre-registered **11,000-step linear LR descent 1.716e-4 → 0**
(the shape and length our round-3 probe validated against cosine and plateau).
Everything else stayed byte-identical; the same W&B run continues across both
legs. The descent improved validation on essentially every 250-step cycle —
the WSD "harvest" phase working as the literature predicts.

Every deep codebook is alive and far above the 0.05% chance floor — the
deep-codebook collapse that capped v0.2 (cb0 ~14%, cb1–7 <4%) is resolved
(coarse→fine unmask curriculum + per-codebook loss weights). Chart-reading
notes: `train/audio_loss` shows upward steps at the curriculum onsets
(cb2–cb7 activate at steps 1,579/3,157/4,735/6,313/7,891/9,469 — the metric's
*definition* grows; per-codebook CEs actually **drop** at each onset). Use
`train/audio_loss_full` (unweighted all-codebook mean, logged natively) for the
jump-free audio learning curve.

## 🎧 Listen: audio samples (click ▶ to play)

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

## 📦 Checkpoints — the full training trajectory

**Every checkpoint of the run is published** (~87 training points): log-spaced
early steps `{1, 2, 4, …, 512}`, **every 1,000 steps from 1,000 → 76,000**
(covering both the plateau and anneal legs), the annealed final `step-76250`,
and 🏆 `best` (step **76,000**, val composite **2.8199**). Each is a complete
weights-only bundle (`peft_adapter/` + projection / depth-decoder / embeddings
/ audio heads + `metadata.json` with full provenance), available two ways:

- **Browse in the file tree** — no branch dropdown needed:
  [`checkpoints/`](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/tree/main/checkpoints)
  (e.g. [checkpoints/best](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/tree/main/checkpoints/best),
  [checkpoints/step-76250](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/tree/main/checkpoints/step-76250))
- **Git revisions** (Pythia/OLMo convention) for programmatic loading:
  ```python
  model = AutoModel.from_pretrained("tiny-aya-translate/tr-hi-s2st-v0.3",
                                    revision="best")   # or "step-42000", …
  ```

Trajectory landmarks (val composite): step 6,000 → 3.941 · 24,000 → 3.069 ·
48,000 → 2.949 · 62,750 (plateau best) → 2.9048 · anneal onset 65,250 →
**76,000 → 2.8199**. Curriculum onsets, the WSD plateau, and the anneal
descent are all visible across the suite — built for training-dynamics and
mech-interp study, not just the final weights.

## 📊 Evaluation — a data-efficiency study of S2ST emergence

End-task release evals are **complete**. Full report + reproducibility:
[`docs/v0.3-eval-report.md`](https://github.com/tiny-aya-simultaneous-translation/model/blob/feat/v0.3-implementation/docs/v0.3-eval-report.md).

**The question v0.3 answers** (from the [blog](https://labscommunity.cohere.com/blog/2026/adapting-moshi-low-resource-speech-translation/),
written on a 26K-sample pilot): *how much training on the full 840K dataset
before translation quality emerges, not just language identity?* v0.3 is that
full-corpus run (**2.07 epochs · 76,250 steps · 6.59B tokens**). The answer:
capability emerges in a clear order — **language identity (early) → text
translation (strong) → audio synthesis (the remaining frontier).**

![Emergence of translation quality over training — teacher-forced text accuracy
reaches 96.6% and free-run text chrF++ ~25 while generated-audio ASR-chrF++ stays
low; language identity then text translation emerge, audio synthesis is the
frontier.](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/assets/v0.3/emergence-curve.png)

Interactive training charts: **W&B run
[`xzcb60bl`](https://wandb.ai/cataluna84/tinyaya-stage2-tpu/runs/xzcb60bl)**.

**Disclosures:** greedy decoding; frozen digest-verified subsets `v03-val-500`
(in-domain) + `v03-fleurs-200` (**acoustic shift only** — texts 200/200 seen,
*not* held-out); references are **MT-synthetic**; **chrF++ primary** (BLEU
unreliable < ~5); MOS as **Δ(gen − GT) only**; judges hi
`vasista22/whisper-hindi-large-v2` · tr `openai/whisper-large-v3`; every model
ASR score is shown **beside its GT-audio topline** (the codec+ASR ceiling).

**End-task `@best` (step 76,000 · 500-row `v03-val-500` · greedy):**

| metric | hi→tr | tr→hi | reads as |
|---|---|---|---|
| free-run **text** chrF++ (inner-monologue) | **25.7** | **25.1** | the model *translates* |
| generated-audio **ASR-chrF++** | 3.7 | 9.6 | speech not yet ASR-intelligible |
| **GT-audio topline** chrF++ | 92.1 | 86.6 | ceiling intact → pipeline sound |
| **BLASER-2.0 QE** (ASR-free, 1–5) | 2.53 | 2.49 | real, weak speech-semantic signal |
| **GEMBA** adequacy (gemini-3.6-flash, 1–5) | 1.08 | 1.10 | transcript ≈ no meaning |
| **DNSMOS** Δ(gen − GT) | −1.34 | −1.34 | low perceptual quality |
| **RTF** / TTFA | 0.95 / 76 ms | | faster than real-time (A100) |

**What this means — honestly.** The **text inner-monologue** learns the
translation *mapping* data-efficiently (96.6% teacher-forced, ~25 free-run
chrF++). The generated **audio** carries a **genuine but weak** translation
signal — BLASER-2.0 QE **2.5/5** is *higher* than the ASR/GEMBA metrics imply, so
the audio is acoustically degraded rather than semantically empty. What has
**not** yet emerged at this data/compute budget is **intelligible speech
synthesis** (ASR-chrF++ 3.7–9.6 vs an 86–92 ceiling; DNSMOS −1.34) — the
bottleneck is audio-codebook generation, **bounded by the frozen Moshi depth
decoder, not the translation understanding.** Release checkpoint = **`@best`
(76,000)**: `@final` is a statistical tie and LAWA gives no gain (paired
bootstrap). On **FLEURS** (real human speech, acoustic shift) even the text
stream collapses to ~8 chrF++ → v0.3 is **distribution-bound** to its
synthetic-TTS training acoustics. This is a first full-corpus run framed as what
it is: a **data-efficiency / emergence** result and a training-dynamics study
artifact, with speech-synthesis fidelity as the concrete next frontier.

**See it learn** — mel-spectrograms of the generated audio across training
(companion to *Hear it learn* above; acoustic structure develops even before it
is ASR-intelligible):

![Mel-spectrograms of the generated audio at each 5k-step milestone, cycling —
the acoustic structure develops over training.](https://huggingface.co/tiny-aya-translate/tr-hi-s2st-v0.3/resolve/main/assets/v0.3/see-it-learn.gif)

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
note¹ — real 32), one v6e-8 per arm. Winner: **arm D,
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

## 🚀 Release design: the checkpoint suite you will get

This repo (**`tiny-aya-translate/tr-hi-s2st-v0.3`**, now **public**) follows
the Pythia/OLMo one-branch-per-checkpoint convention, weights-only
(optimizer/scheduler/RNG stay in archival storage):

- **The full suite is live** — see *Checkpoints* above for the complete
  ladder and loading examples. *Ops disclosure:* during the private training
  phase, private-repo storage limits (~50 GB) meant only a 12-point interim
  ladder could be hosted; the flip to public (no such cap) enabled the full
  ~87-point publication, backfilled from the keep-all GCS archive.
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
| Long-horizon training run (plateau leg) | ✅ completed 2026-07-19 (early stop @65,250; plateau best 2.9048 @62,750) |
| WSD anneal leg (65,250 → 76,250, linear LR→0) | ✅ completed 2026-07-20 — **best val composite 2.8199 @76,000** |
| Repo public + full checkpoint suite (~87 points) | ✅ (branches + `checkpoints/` tree) |
| Audio samples + training log on `main` | ✅ (13 milestones, playable above) |
| Release evals (ASR-chrF++ / MOS / BLASER / GEMBA / RTF) | ✅ complete 2026-07-22 — data-efficiency study; `@best` (76,000) released; report [`docs/v0.3-eval-report.md`](https://github.com/tiny-aya-simultaneous-translation/model/blob/feat/v0.3-implementation/docs/v0.3-eval-report.md) |

## 🙏 Acknowledgements

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
