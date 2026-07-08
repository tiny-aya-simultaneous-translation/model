# memories — long-term project decisions

> Permanent record of architecture decisions, gotchas, and domain knowledge for the
> TinyAya Stage 2 repo. Append via `/remember <text>` or by hand. Decisions reversed later
> are marked SUPERSEDED rather than deleted.
>
> **The active, finer-grained store is the `memory/` directory** (one file per fact +
> `MEMORY.md` index), loaded each session. This file is the condensed legacy monolith.
> **Full May–July 2026 decision history (1,355 lines) archived to
> [`.claude/archive/memories-2026-07-06.md`](archive/memories-2026-07-06.md).**

---

## Project context (2026-07-06; amended 2026-07-08)

- **Name / goal:** TinyAya Stage 2 — **text+audio** TR↔HI speech-to-speech translation on
  TPU (TRC). *(SUPERSEDED: "audio-only" — see Data below.)*
- **Model:** composite Cohere2 backbone (LoRA) + **frozen** Moshi depth decoder → 8 RVQ
  Mimi codebooks. **~3.4B total params**, ~57M trainable (LoRA + projection + audio heads +
  depth I/O + embeddings). CB0 from backbone+audio_heads; CB1–7 from the depth decoder.
- **Data:** synthetic `tr-hi-mimi-encoded`, ~1.24M → 1,178,302 train / 62,036 val.
  **SUPERSEDED 2026-07-08: the corpus DOES ship text alignments** — 840,426
  `.src.alignments.json` + 840,426 `.tgt.alignments.json` at the data root (100%
  coverage); the "no alignments" verification used legacy filenames and the loader only
  looked in `encoded/`. Loader fixed (`dataset.py::_resolve_alignment` + fail-loud
  coverage guard); v0.3 trains **text_weight 0.2**.
- **Recipe (capacity-sweep winner):** LoRA r=32, alpha=64, rsLoRA, **+MLP** target modules,
  `lr_lora=1.716e-4`, `exclude_top=2`. Production config `stage2_tpu_v6e16_full_v03.yaml`
  (14,532 steps) on **v6e-16**.
- **Hardware:** v6e-16 (production) + v6e-8 (smoke/eval), europe-west4-a, TRC spot. 32 GiB HBM/chip.
- **GCS:** `gs://tinyaya-stage2-eu` (europe-west4, co-located with TPUs). Keep it in-region.

---

## Timeless architecture / TPU facts (still true)

- **Seam:** `torch_xla` lives ONLY in `src/backend/tpu_backend.py` (CI-enforced). Never
  import it under `src/model/` or `src/data/`.
- **SPMD strategies** (env `TPU_STRATEGY`): `fsdpv2_lora` (default — shards LoRA-bearing
  layers, replicates frozen ones), `fsdpv2`, `replicated`. Selected in `wrap_model`.
- **bf16 via explicit cast** in `wrap_model`, NOT env vars (`XLA_USE_BF16`/`XLA_DOWNCAST_BF16`
  are deprecated no-ops in torch_xla ≥2.6).
- **`XLA_NO_SPECIAL_SCALARS=1`** required for inline TPU validation (disables assume-no-NaN
  rewrites that corrupt the val loss scalar); `XLA_DISABLE_FUNCTIONALIZATION=0` required.
- **scan / grad-ckpt proxy** (`_ScannedLayerStack`, `src/model/scan_utils.py`): when
  `xla_grad_checkpoint`/`use_scan_layers` is on, backbone blocks are renamed to
  `layers.layers_list.<i>.layer.…`. This is the **#71 root cause** — a checkpoint saved
  under it loads 0 adapter tensors onto a vanilla (plain-namespace) eval/export model.
  `load_checkpoint` now remaps the namespace both ways and **raises** on any unfilled LoRA
  tensor (`eb17609`).
- **No persistent XLA compile cache** (pytorch/xla #8930/#9094) → every process restart
  re-pays ~35–40 min compile. Minimizing restarts is the top hardening lever.
- **Checkpoint format:** LoRA `peft_adapter/` + `projection.pt` / `depth_decoder.pt` /
  `audio_heads.pt` / `text_embed.pt` / `model_audio_embed.pt` + `metadata.json`. Resume via
  `--resume auto`; optimizer (Adam moments) persist; dataloader cursor is at-least-once.
- **Codebook delay pattern** (`apply_/undo_codebook_delay`): CB_k shifted right by k frames;
  `SILENCE_TOKEN=2048`. The model predicts the DELAYED `model_audio_codes`; decode requires
  `undo_codebook_delay` first. The per-codebook accuracy metric must score against the
  delayed target (fixed `8854698`) — scoring the undelayed target pinned CB1–7 at false ~0%.
- **transformers pin:** 4.49.x (5.x / 4.57 break Cohere2/Moshi).
- **Data staging:** `/mnt/data` is ephemeral on spot (re-staged on preempt); the
  `.unpacked` marker prevents re-extract — clear it when switching subset↔full corpus.
- **Multi-host sweep:** 4 hosts = one 16-chip mesh, so a plain per-host `wandb agent`
  desyncs; use `sweep_coordinator.py` (grid) / `sweep_agent_primary.sh` (bayes) broadcast.

---

## Gotchas
- `uv` not on `PATH` under sudo on fresh VMs → enumerate `/root/.local/bin/uv`.
- `pkill -f`/`pgrep -f` self-match → use the `[s]cripts/...` bracket trick.
- fd limit: v6e init needs `ulimit -n 1048576`.
- gsutil `/.` (contents-of) idiom works for local `cp` but NOT a GCS source (use `/*`).
- Secrets (`HF_TOKEN`, `WANDB_API_KEY`) in Google Secret Manager — never print; rotate any
  leaked tokens before public release.
