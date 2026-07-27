# AGENTS.md — TinyAya Stage 2 (flattened repo)

Briefing for agents editing this repository. The repo was **flattened**:
training/model/eval/TPU code lives at the root (`src/`, `scripts/`,
`configs/{gpu,tpu}/`, `sweeps/`) — there is no `simultaneous-translation/`
subdir anymore.

## Scope

The **training, model, eval, and TPU launch** code. The composite model
fuses a Cohere2 backbone (LoRA-fine-tuned) with a frozen Moshi depth
decoder. The repo is **dual-backend**: a backend interface
(`src/backend/{base,gpu_backend,tpu_backend}.py`, dispatched by
`get_backend()`) lets the *same* `src/` + `scripts/train_hierarchical.py`
run on GPU or TPU.

## Memory System (read first)

This repo uses the External Memory System. Before any non-trivial task,
read in order: `.claude/PLAN.md` → `.claude/PROGRESS.md` (top) →
`.claude/VERIFY.md` → `.claude/memories.md`. Lifecycle hooks load these
automatically; `Skill("keep-context-fresh")` primes them on demand.

## TPU ↔ GPU separation (the seam — keep it clean)

- **Shared & backend-agnostic:** everything in `src/` (except
  `src/backend/tpu_backend.py`) and `scripts/train_hierarchical.py`.
  Phase 0/1 fixes (loss padding-weight, collator parallel-stream, LoRA
  config, resume) and Phase 2/3 (diag dashboard, `--sweep`) help both
  backends and live in shared code behind flags.
- **TPU-only:** `configs/tpu/` + `scripts/tpu/` + `src/backend/tpu_backend.py`
  (the ONLY place that may `import torch_xla`). All XLA env flags
  (`XLA_NO_SPECIAL_SCALARS`), `mark_sharding`, on-device metric
  accumulation, and compile-warmup stay here.
- **GPU-only:** `configs/gpu/` + (future) `scripts/gpu/`.
- **Rule:** never `import torch_xla` under `src/model/` or `src/data/`.
  CI enforces this (`scripts/ci/check_backend_seam.sh`); scoped configs
  stop the GPU and TPU collaborators from stepping on each other.

## Build & test

```bash
# from the repo root
uv sync                                       # install / update deps
uv run python -m pytest tests/ -q             # CI gate
uv run python -m py_compile $(git ls-files '*.py')  # quick lint
```

## TPU launch (canonical commands)

Current long-horizon path: **v6e-16 spot in `europe-west4-a`** (4 hosts × 4 chips = one
16-chip SPMD mesh, 32 GiB HBM/chip). A v6e-8 (single host) is used for smoke/overfit/eval.
Checkpoints → **`gs://tinyaya-stage2-eu/`** (europe-west4, co-located with the TPUs).

```bash
# v0.3 long-horizon run (r=32 / +MLP / rsLoRA winner, 110,463 steps @ real global batch 32)
TRC_PROFILE=v6e-16-eu CONFIG_FILE=configs/tpu/stage2_tpu_v6e16_full_v03_mh.yaml \
SWEEP_DATA_GS_URI=gs://tinyaya-stage2-eu/data/full-corpus-ta-20260708.tar.gz \
bash scripts/tpu/launch_spot.sh
# babysit the QR for the whole run (local tmux):
#   QR_NAME=... ZONE=europe-west4-a LAUNCH_ENV_FILE=launch.env bash scripts/tpu/qr_watch.sh
# DURABLE MONITORING RULE: run/error watchers for multi-hour work go in tmux
# ON the TPU VM (scripts/tpu/vm_watcher.sh -> GCS status file), never as
# workstation-local loops — see docs/tpu-runbook.md "Durable monitoring".

# hot-redeploy code without recreating the QR
bash scripts/tpu/hot_redeploy.sh
```

See [`docs/tpu-runbook.md`](docs/tpu-runbook.md) for provisioning, resume, and the
sweep-fleet launchers under `scripts/tpu/`.

## TPU sharding strategies (env: `TPU_STRATEGY`)

| Value | Behaviour |
|-------|-----------|
| `replicated` | Every chip holds a full model copy; only data is sharded. **What the v0.3 long-horizon run actually used** (v6e-16, 32 GiB/chip). Historically OOM'd on v5e's 16 GiB. |
| `fsdpv2_lora` | Shards layers that contain trainable params (LoRA-bearing CohereDecoderLayer); replicates frozen MoshiDecoderLayer. |
| `fsdpv2` | Shards every transformer layer including frozen ones. Tightest memory but highest comm cost. |
| `auto` | Lets the backend pick — `_resolve_strategy` returns **`replicated`** below ~500M trainable params (v0.3 is ≈192M) and `fsdpv2` above. This is the default the launchers pass. |

The strategy is selected inside
`src/backend/tpu_backend.py::wrap_model`. See
`.claude/memories.md` for empirical compile / step / HBM
measurements per strategy.

## Required env vars (TPU runtime)

```bash
export PJRT_DEVICE=TPU                        # auto-set when libtpu present
export XLA_DISABLE_FUNCTIONALIZATION=0        # MUST be 0 (pytorch/xla #8607)
export TPU_STRATEGY=auto                      # resolves to `replicated` here; see table above
export LD_LIBRARY_PATH=/opt/conda/lib:$LD_LIBRARY_PATH   # libpython
```

`XLA_USE_BF16` and `XLA_DOWNCAST_BF16` are **deprecated** in
torch_xla >= 2.6 and silently no-op. Use the explicit
`model.to(torch.bfloat16)` already wired into `wrap_model`.

## Configs (split per backend)

**GPU** (`configs/gpu/`):
- `stage2_26k_parallel.yaml` — GPU parallel-stream run. Carries the
  Phase 0 `text_padding_weight` fix (ported from TPU).

**TPU** (`configs/tpu/`):
- `stage2_tpu_v6e16_full_v03_mh.yaml` — **v0.3 long-horizon** run (v6e-16 multi-host, r=32/+MLP/rsLoRA, 110,463 steps @ real global batch 32).
- `stage2_tpu_v6e16_smoke_r{8,32,64}.yaml` — full-corpus smoke arms (capacity-sweep candidates).
- `stage2_tpu_v6e16_scale_proxy.yaml` — the capacity-sweep proxy (de-regularized, batch 256).
- `stage2_tpu_v6e8_overfit.yaml` — overfit / pipeline-validation (32-example memorize).

Each TPU config carries: the `loss:` text/audio weights (text+audio since 2026-07-08:
`text_weight 0.2`, `composite_text_w 0.4` — the corpus ships alignments), the
`lora:` block (`r`/`alpha`/`use_rslora`/`target_modules`/`lora_exclude_top`/
`num_full_ft_layers`), and `logging.{val_on_tpu,diag_metrics,save_dir}` (save_dir under
`gs://tinyaya-stage2-eu/`).

## Per-chip memory budget

**v6e (32 GiB / chip)** — the current path. The v0.3 run used `replicated` (a full
composite copy per chip) and still sat inside the 32 GB budget. The binding constraint
in practice is **activation memory**, not the HBM ceiling. If `diagnose()` reports
per-chip HBM climbing toward the budget, switch strategy or enable
`xla_grad_checkpoint`. Measured throughput on v6e-16 was **~1.45–1.8 s/step at the real
optimizer batch of 32** (`batch_size × grad_accum`; older notes quoting ~5.5 s/step "at
effective batch 256" multiplied by the chip count — see the batch-semantics audit).
*(Historical v5e-16 (16 GiB) OOM'd the model under `replicated`.)*

## Conventions

- Default to `dataclasses` + YAML configs over kwargs forests.
- New training scripts live under `scripts/`. Keep them runnable
  with `uv run python scripts/<name>.py --help`.
- New TPU launch scripts go under `scripts/tpu/`. They must:
  - Be `bash -n`-clean.
  - Quote all paths.
  - Use `gcloud compute tpus tpu-vm ssh --command='...'`, never
    nested heredocs (use the SCP-companion pattern in
    `_remote_redeploy.sh`).
- Do not write to `/opt/tinyaya/` from a session running on a TPU
  worker — that path is overwritten by `hot_redeploy.sh`.

## TPU code documentation style (mandatory)

Every new or edited Python file under the repo root
follows the conventions below. The explicit goal is that a research
engineer fluent in **PyTorch + GPUs but new to TPU** can read the
file top-to-bottom and understand both *what* the code does and *why
the TPU forces it to look that way*.

### Audience contract

Assume the reader knows: `nn.Module`, autograd, AMP (`torch.cuda.amp`),
DDP, FSDP-on-GPU, gradient checkpointing in concept, and HuggingFace
Trainer-style flows.

Assume the reader does **not** know: PJRT, SPMD partitioner,
`torch_xla.distributed.spmd.Mesh`, FSDPv2 (the SPMD variant),
`scan_layers`, `xm.optimizer_step` vs. `optimizer.step()`,
HBM vs. host RAM, why `XLA_USE_BF16` is deprecated, why
`use_cache=True` breaks XLA tracing, why `xla_device()` is logical
and lazy, or what "lowering" / "tracing" / "HLO" mean.

### File header — `WHY THIS EXISTS`

Every Python file starts with a module docstring whose first section
is titled `WHY THIS EXISTS` and gives a 4–10 line plain-English
description of the module's role and any TPU concept introduced for
the first time in the file. Example:

```python
"""TPU backend with multiple SPMD sharding strategies.

WHY THIS EXISTS
---------------
On GPU we use DDP (one process per GPU, NCCL all-reduce on
backward). On a TPU pod we use **SPMD** — one logical Python
program drives every chip via PJRT, and the XLA partitioner
decides where each tensor lives. This file picks the partitioner's
*sharding strategy* and is the only place that should know about
XLA-specific primitives like `xs.mark_sharding`, `Mesh`, or FSDPv2.
...
"""
```

### GPU-vs-TPU comparison callouts

Whenever a TPU primitive replaces a GPU equivalent, attach a
`# GPU analogue:` comment. Examples already in the codebase:

```python
xm.optimizer_step(optimizer)            # GPU analogue: optimizer.step()
xs.mark_sharding(x, mesh, ("fsdp",))    # GPU analogue: input.cuda(rank) under DDP
model = model.to(torch.bfloat16)        # GPU analogue: torch.cuda.amp.autocast(...)
```

### Function docstrings — NumPy-style with TPU notes

Every public function/method gets a NumPy-style docstring. When the
behavior differs on TPU, add a `Notes` section starting with
`TPU note:`. Example:

```python
def wrap_model(model: nn.Module) -> nn.Module:
    """Wrap `model` with the SPMD strategy chosen via TPU_STRATEGY.

    Args:
        model: The unwrapped composite model. Must be on the XLA
            device already.

    Returns:
        The wrapped model. On a single chip this is a no-op; on a
        pod it is either a replicated mark_sharding'd model, or an
        FSDPv2-wrapped model.

    Notes:
        TPU note: bf16 cast happens *here*, not via env vars. The
        legacy `XLA_USE_BF16=1` was removed in torch_xla 2.6 and
        silently no-ops in 2.9; tensors stay in f32 and the model
        OOMs on v5e (16 GiB / chip). See `.claude/memories.md`.
    """
```

### Inline comments — explain trade-offs, don't restate code

Bad: `# loop over layers`. Good:
```python
# scan_layers compiles ONE layer's HLO and runs it via xla.while; this
# replaces the 36-way unrolled HLO that was costing 25+ min compile
# (see PROGRESS 2026-05-03T14:30:00Z).
```

### Type hints + PEP8

- All new public APIs are fully annotated.
- Run `.venv/bin/python -m ruff format` and `... -m ruff check --fix`
  on every touched file before committing. The repo's ruff config
  (`[tool.ruff]` in `pyproject.toml`) is the source of truth:
  py312 / 100-col / E,F,W,I,B,UP / ignore E501.

### YAML configs

Configs are read by both human researchers and lifecycle hooks. Each
section gets a block comment explaining what the knob does *and* what
changes when running on TPU vs GPU. Cross-link to the relevant memory
entry where useful (`# see .claude/memories.md "Per-chip memory ..."`).

### When you don't have to

Pure utility code with no TPU contact (e.g., text-tokenisation
helpers) only needs the module docstring and NumPy docstrings on
public functions; the GPU-vs-TPU callouts and the `WHY THIS EXISTS`
TPU paragraph are skipped.

### Skill alias

Run `Skill("tpu-doc-style")` to load this convention into a fresh
session's context as a checklist.

## Gotchas (training-specific)

- **XLA compile time blows up with unrolled transformer stacks.**
  36 `CohereDecoderLayer` + 6 `MoshiDecoderLayer` => 25+ minute
  compile. Mitigation: `scan_layers` — **shipped** and on by default for the
  long-horizon path (`use_scan_layers: true`, `src/model/scan_utils.py`; see
  `docs/tpu-runbook.md`).
- **`which uv` is empty under sudo on fresh TPU VMs.** Enumerate
  `/root/.local/bin/uv`, `/usr/local/bin/uv`, `/usr/bin/uv` until
  one resolves.
- **TRC quotas pre-empt.** Spot/preemptible v6e in `europe-west4-a`
  reclaims regularly. Use queued resources + checkpoint every N steps +
  `--resume auto`. No persistent XLA compile cache → each restart re-pays ~35-40 min compile.
- **Mimi audio loading uses `transformers` API**, not the older
  `kyutai/mimi` path; keep the `transformers` pin in `pyproject.toml`.

## Where to log

| Event | Where |
|-------|-------|
| New TPU strategy decision | `.claude/memories.md` (## Architecture decisions) |
| Compile time / HBM measurement | `.claude/memories.md` (## Hardware facts) |
| Failed training run | `.claude/PROGRESS.md` (status: `fail`, kind: `exec`) |
| Successful eval result | `.claude/memories.md` (## Milestones) |

Use `/remember`, `/progress`, or the `#progress` / `#decision` quick-
capture tags.

## Out of scope (this repo)

- Data encoding / generation (separate data-pipeline repo).
- Inference / serving (separate future repo).
- v4-64 path tuning (separate config; not blocking the v6e milestone).
