# TPU Runbook — TinyAya Stage 2

Current operational guide for training on Cloud TPU. Replaces the historical
`tpu-launch-plan.md` + `tpu-changes.md` (Colab→v5e→v4-32→v6e-8 narrative lives in git
history). Companion: [`AGENTS.md`](../AGENTS.md) (seam rules + doc style),
[`sweeps/README.md`](../sweeps/README.md) (sweep infra).

## Hardware & zones (TRC)

| Slice | Topology | Use | Zone |
|---|---|---|---|
| **v6e-16** | 4 hosts × 4 chips = one 16-chip SPMD mesh | v0.3 production | `europe-west4-a` |
| **v6e-8** | 1 host × 8 chips | smoke / overfit / eval | `europe-west4-a` |

Both are **spot** under Google TRC. Free zones: `europe-west4-a` and `us-east1-d` (see
[`tpu-trc-allocation.md`](tpu-trc-allocation.md)). 32 GiB HBM/chip. **GCS bucket
`gs://tinyaya-stage2-eu` (europe-west4)** — keep it co-located with the TPUs (a
cross-region bucket makes every checkpoint write pay egress).

## Provisioning + launch

Queued resources (QR) provision the slice; `startup_script.sh` (metadata) deploys the
repo, stages data, and starts training under a TPU-side `tmux train` session.

```bash
# provision a spot QR (see scripts/tpu/launch_qr.sh / launch_spot.sh for env vars)
bash scripts/tpu/launch_spot.sh

# launch the production run on the mesh (after deploy)
bash scripts/tpu/launch_release.sh configs/tpu/stage2_tpu_v6e16_full_v03.yaml

# redeploy code without recreating the QR
bash scripts/tpu/hot_redeploy.sh

# observe / control (status, log tail, stop)
bash scripts/tpu/ops.sh <cmd>
```

Pass the config as the first arg to `launch_release.sh` — it sets `save_dir`, the recipe,
and `max_steps`. The launcher injects `GIT_SHA`/`GIT_DIRTY` for reproducibility and
uploads a secret-sanitized training log to GCS at end-of-run.

## Data staging (`startup_script.sh`)

- **Full corpus**: `huggingface-cli download tiny-aya-translate/tr-hi-mimi-encoded` →
  `/mnt/data/encoded` (~4M files, ~11.7 GB, one-time per host), guarded by a
  `/mnt/data/encoded/.unpacked` marker.
- **Sweep subset**: set the `sweep-data-gs-uri` VM metadata → pulls a small pre-staged
  subset tarball from GCS instead (much faster for sweep trials).
- `/mnt/data` is **ephemeral on spot** — re-staged on every preemption. The `.unpacked`
  marker means a stale subset is *not* re-extracted; clear `/mnt/data/{encoded,splits}`
  when switching subset ↔ full corpus.

## Required env (TPU runtime)

```bash
export PJRT_DEVICE=TPU                     # auto-set when libtpu present
export XLA_DISABLE_FUNCTIONALIZATION=0     # MUST be 0 (pytorch/xla #8607)
export XLA_NO_SPECIAL_SCALARS=1            # disables assume-no-NaN rewrites; required for inline val
export TPU_STRATEGY=fsdpv2_lora            # shards LoRA-bearing layers, replicates frozen ones
```

`XLA_USE_BF16`/`XLA_DOWNCAST_BF16` are deprecated (torch_xla ≥2.6, silent no-op) — bf16 is
cast explicitly in `wrap_model`.

## Resume & preemption

- `--resume auto` (in `startup_script.sh`) finds the latest GCS checkpoint and reattaches
  the same W&B run id on any VM reboot; `WANDB_RESUME=allow` in spot mode.
- Model weights + optimizer (Adam moments) persist; dataloader cursor is at-least-once
  (~500 steps re-seen per preemption, ~2% of an epoch — accepted).
- **No persistent XLA compile cache** (pytorch/xla #8930/#9094) → every process restart
  re-pays **~35–40 min** compile. Minimizing restarts is the highest-value hardening lever.
- **Checkpoint portability**: TPU saves the backbone LoRA under the grad-ckpt/scan proxy
  namespace (`layers.layers_list.<i>.layer.…`); `load_checkpoint` remaps it to the live
  model's namespace and **raises** on any unfilled LoRA tensor (a base-only model can never
  load silently). See `src/training/checkpointing.py`.

## Sweeps (multi-host)

On a single v6e-16 the 4 hosts form **one** 16-chip mesh, so a plain per-host `wandb agent`
desyncs (each host pulls a different trial → mesh corruption). Two patterns solve it —
Stage-1 grid via `sweep_coordinator.py` (GCS control-file broadcast) and Stage-2 Bayesian
via `sweep_agent_primary.sh` (host-0 runs the native W&B agent, broadcasts trial args to
workers over a GCS rendezvous). Details + launchers in [`sweeps/README.md`](../sweeps/README.md).

## Single-host v6e-8 scan recipe (2026-07-08 — REQUIRED)

Replicated strategy (trainable <500M) puts the whole 5.17B composite + activations on
EVERY chip; the unrolled 36-layer path OOMs v6e-8 outright (64–94G vs 31.25G HBM) and is
not viable at any batch size. The working recipe — all pieces mandatory together:

- `use_scan_layers: true` + `micro_mark_step: true` + `depth_chunk_size: 100`. One graph
  per macro-step = 82.5% XLA allocator fragmentation (81G "used" over 14.2G real buffers);
  the per-micro-batch graph break fixes it. Proven: 8.4 s/step, peak 25–29G, batch 4×8.
- Scan needs parameter-uniform layers → `scan_homogeneous` LoRA (adapters on ALL 36
  layers, top-`exclude_top` frozen at zero — state-dict shape differs from the classic
  34-layer layout; loader remaps, see checkpoint portability above).
- LoRA dropout under scan needs `_ScanSafeDropout` (auto-swapped): `native_dropout`'s
  bool-mask meta vs torch_xla's bf16-mask lowering breaks scan's stacked buffers
  ("Dynamic update slice: operand PRED vs update BF16").
- Scan backward under SPMD needs **jax + torchax + flax** (pinned in pyproject; torchax
  imports flax without declaring it). CPU wheels; jax only traces sharding hints.
- The depth decoder is never scanned (6 layers; `index_select` breaks scan tracing) and
  runs the equal-batch `bmm` FlexibleLinear patch (stock transformers' broadcast matmul
  materializes a 5.5G weight copy PER TOKEN on XLA — the real historical OOM cause).

Full blocker chain + evidence: PR #10 comments (2026-07-08).

## Gotchas

- **`uv` under `sudo`** is not on `PATH` on fresh TPU VMs — enumerate `/root/.local/bin/uv`.
- **fd limit**: v6e init creates ~100k FDs; launch with `ulimit -n 1048576`.
- **`pkill -f`/`pgrep -f` self-match**: use the `[s]cripts/...` bracket trick so the command
  doesn't match its own process line.
- **SSH via `--command='...'`**, never nested heredocs; use the SCP-companion pattern in
  `_remote_redeploy.sh`.
- **Never write to `/opt/tinyaya/` from a worker session** — `hot_redeploy.sh` overwrites it.
- **TRC is a free grant** — never stop/delete/reprovision a slice without explicit intent.
- **SUSPENDED/FAILED QRs still hold TPU quota**: preempted-spot husks silently book chips
  against the 64-chip limit and 429 every new launch (`RESOURCE_EXHAUSTED`). Delete dead
  QRs promptly (`ops.sh delete`) — with explicit approval, per the TRC rule above.
- **`--resume auto` + reused `save_dir`**: a re-purposed config that keeps an old
  `save_dir` resumes the OLD run's final checkpoint and may exit instantly at
  `step >= max_steps`. New experiment ⇒ new `save_dir`.
- **`set -o pipefail` + `find | head`** in helper scripts: `head`'s early exit SIGPIPEs
  `find` (exit 141) and `set -e` kills the script silently mid-line. Use a candidate loop
  (see `_remote_redeploy.sh`) instead of piping to `head`.
- **`wandb.log` per-chip TPU telemetry** is on by default now (`tpu/chip{i}/hbm_gib`,
  `duty_pct`, `tpu/hbm_max_gib`): straggler chips are visible in W&B, chip 0 alone is not
  representative under load imbalance.
