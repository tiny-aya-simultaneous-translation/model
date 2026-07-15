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
- **No persistent XLA compile cache** — empirically DOA on torch_xla 2.9 v6e SPMD
  (2026-07-14 A/B: cache keys are nondeterministic across processes; identical config
  rerun rewrote entries and saved zero time). Cold compile on v6e-16 ≈ 14 min/boot —
  the accepted per-preemption cost.
- **Checkpoint format:** LoRA `peft_adapter/` + `projection.pt` / `depth_decoder.pt` /
  `audio_heads.pt` / `text_embed.pt` / `model_audio_embed.pt` + `metadata.json`. Resume via
  `--resume auto`; optimizer (Adam moments) persist; dataloader cursor is at-least-once.
- **Codebook delay pattern** (`apply_/undo_codebook_delay`): CB_k shifted right by k frames;
  `SILENCE_TOKEN=2048`. The model predicts the DELAYED `model_audio_codes`; decode requires
  `undo_codebook_delay` first. The per-codebook accuracy metric must score against the
  delayed target (fixed `8854698`) — scoring the undelayed target pinned CB1–7 at false ~0%.
- **transformers pin:** 4.49.x (5.x / 4.57 break Cohere2/Moshi).
- **Data staging:** `/mnt/data` is ephemeral on spot (re-staged on preempt); the
  `.unpacked` marker records its SOURCE (tarball URI / `hf:<dataset>`, 2026-07-14 fix) —
  a mismatch auto-wipes + re-stages, and boot preflight gates on `expected-train-rows`
  + `min-text-coverage` metadata with a cross-host digest check on the rendezvous marker.
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


## Long-horizon run facts (2026-07-15, pre-launch)
- **Run** = `configs/tpu/stage2_tpu_v6e16_full_v03_mh.yaml`: 110,463 steps ≈ 3 real
  epochs at REAL global batch 32 (2/chip × 16; the "256" of the sweep era was
  batch×accum fiction), WSD (warmup 1100 / anneal 11k; stop-anytime anneal template
  `_mh_anneal.yaml`), keep-all suite (log-spaced + every 1000, 4.23 GiB/ckpt with
  integrity manifest), val×4 gate (25 × global 128 = 3200 samples), per-host tpu
  telemetry, inline audio demos every 5000 (48 s cold / 29 s warm), W&B
  `v0.3-long-horizon-mh` — never say "production".
- **Rehearsals PASS**: 2k `7pj1dkht`, 5k `m3rmohn5` (bit-identical numerics to
  pre-instrumentation), audio smoke `xxbchrr6`. Dashboard `?nw=bg2vkino3r4`.
- **HF route**: 2026-07-14 GCP-EU stall was fixed upstream 07-15 (cas-bridge redirect,
  146–219 MB/s direct). `prefetch_backbones.sh` = direct-first, WARP fallback;
  `HF_HUB_OFFLINE=1` still gated on verified cache (revision pinning).
- **Hub publishing**: artifacts stream during the run to
  `tiny-aya-translate/tr-hi-s2st-v0.3` (PRIVATE until release): weights-only
  branch-per-step, audio → `samples/step_N/`, rolling log → `logs/`. Push rides the
  save closure (a post-hoc push of a `gs://` path silently uploads NOTHING — fixed).
  `publish_checkpoint_suite.py` backfills; flip public manually at release.
- **W&B shared-mode rule**: `wandb.log(step=)` is IGNORED — every metric must carry
  `"global_step"`; UI x-axis must be set to global_step (internal step ≈ row count).
- **Docs guard**: `scripts/ci/check_docs_sync.sh` (in CI) forbids regressions to the
  batch-256 fiction / old config / 14,532 steps / production framing.
