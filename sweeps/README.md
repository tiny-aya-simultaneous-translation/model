# W&B Hyperparameter Sweeps — Stage 2

Proxy-first HP search before the expensive multi-day long-horizon run. The v0.3 recipe was
chosen by a **two-stage capacity sweep** on the full 1.24M corpus (nominal batch 256 — real optimizer batch 32 per the batch-semantics audit, where
overfitting is no longer the binding constraint). Sweep specs live here; the launchers +
multi-host coordination live in `scripts/tpu/`. See
[`docs/tpu-runbook.md`](../docs/tpu-runbook.md) for the mesh/launch details.

## The two-stage capacity sweep

- **Stage 1 — structural grid** (`sweep_stage2_scale_grid.yaml`): which LoRA target
  modules, 3 arms to 1500 steps, rsLoRA on, `r=16`, `lr=2e-4`, `exclude_top=2`. Winner:
  **+MLP** (`q,k,v,o + gate,up,down + embed_tokens`) — in the data-rich regime *more* LoRA
  capacity → lower loss (the opposite of the small-data overfit regime).
- **Stage 2 — Bayesian `lr × rank`** (`sweep_stage2_scale_bayes.yaml`): structure fixed to
  +MLP, `lr_lora` log-uniform `1e-5…5e-4` × `lora_r ∈ {8,16,32,64}`, rsLoRA (`α=2r`).
  **Winner: `lora_r=32, lr_lora=1.716e-4`** (`val/composite=5.1189`).

Winner promoted to `configs/tpu/stage2_tpu_v6e16_full_v03_mh.yaml` (110,463 steps = 3 epochs).
Throughput is rank-independent (~5.5 s/step on v6e-16), so rank choice doesn't change the
wall-clock model. **W&B project:** https://wandb.ai/cataluna84/tinyaya-stage2-tpu

## Multi-host coordination (the reusable learning)

On a single v6e-16 the 4 hosts form **one** 16-chip SPMD mesh, so a plain per-host
`wandb agent` desyncs (each host pulls a different trial → mesh corruption). Two patterns
solve it:
- **Stage-1 grid** — `sweep_coordinator.py` (host-0) broadcasts each trial's args to all
  hosts via a shared GCS control file; deterministic run ids + checkpoint-truth completion
  make it idempotent/resumable across preemptions.
- **Stage-2 Bayesian with the native W&B dashboard** — ONE `wandb agent` on host-0 runs
  `sweep_agent_primary.sh`, which broadcasts trial args to the 3 worker hosts (they form
  the mesh) AND runs host-0's PRIMARY training — whose run the agent creates INSIDE the
  sweep, so parallel-coordinates / param-importance populate. Workers attach via a GCS
  rendezvous.

Launchers: `scripts/tpu/launch_sweep_coordinated.sh` (Stage 1),
`scripts/tpu/launch_sweep_bayes.sh` (Stage 2).

## Running a sweep

```bash
# 1. create the sweep (workstation; needs `wandb login`)
wandb sweep sweeps/sweep_stage2_scale_bayes.yaml     # -> ENTITY/PROJECT/SWEEP_ID

# 2. launch the coordinated fleet on the mesh (see scripts/tpu/ for env vars)
SWEEP_ID=ENTITY/PROJECT/SWEEP_ID bash scripts/tpu/launch_sweep_bayes.sh

# 3. pick the winner in the W&B dashboard (lowest val/composite), then promote:
python scripts/promote_sweep_winner.py \
    --sweep ENTITY/PROJECT/SWEEP_ID \
    --config configs/tpu/stage2_tpu_v6e16_full_v03_mh.yaml --metric val/composite
```

The trial proxy is `configs/tpu/stage2_tpu_v6e16_scale_proxy.yaml` (de-regularized,
checkpointing on, nominal batch 256 / real 32 — batch-semantics audit). `train_hierarchical.py`'s `--sweep` path maps swept
args flat→nested (`lr_lora`→`optim`, `lora_r`/`lora_alpha_mult`→`lora`, etc.).

> Note: `val/composite` is logged as a flat scalar (a prior `summary="min"` stored it as a
> nested dict that broke parallel-coordinates; fixed). For the audio-only v0.3 data it
> reduces to `val_audio`.

*Historical: the first v6e-8 proxy sweep (`9ba8h0ho`, r=64 winner) and the small-data
regularization sweep predate the capacity sweep and are superseded — see W&B + git history.*
