# TPU launch scripts

Operator-side scripts for training Stage 2 on Google Cloud TPU (TRC) via the Queued
Resource API. Current path: **v6e-16 spot in `europe-west4-a`** (production) + **v6e-8**
(smoke/overfit/eval). For the launch flow, resume, and staging, see
[`../../docs/tpu-runbook.md`](../../docs/tpu-runbook.md); this file documents the scripts
and their env vars.

## Files

| File | Where it runs | Purpose |
|---|---|---|
| `setup_gcp.sh` | workstation, once | enables APIs, creates the GCS bucket, seeds Secret Manager from `.env`, grants IAM |
| `launch_qr.sh` | workstation | submits a Queued Resource (on-demand path / config via `CONFIG_FILE`) |
| `launch_spot.sh` | workstation | submits a spot QR via `TRC_PROFILE` (e.g. `v6e-16-eu`, `v6e-8-eu`) |
| `launch_release.sh` | on the VM | long-horizon launcher: injects `GIT_SHA`, tees + uploads a sanitized log |
| `startup_script.sh` | every TPU host at boot | installs uv + Python, fetches code (GCS tarball or clone), syncs `uv.lock`, fetches secrets, stages data, starts training in a `tmux` restart loop with `--resume auto` |
| `hot_redeploy.sh` / `_remote_redeploy.sh` | workstation | push code to a live QR without recreating it |
| `ops.sh` | workstation | `status`, `tail-logs`, `attach`, `ssh`, `pull-best`, `delete` |
| `sweep_coordinator.py`, `sweep_agent_primary.sh`, `launch_sweep_*.sh` | VM / workstation | multi-host sweep coordination (see [`sweeps/README.md`](../../sweeps/README.md)) |

## Configuration

Local scripts auto-source `<repo-root>/.env` if present. Override per-invocation by
prefixing `VAR=value bash ...`.

| Var | Default | Used by |
|---|---|---|
| `PROJECT_ID` | `ml-pipelines-315702` | all |
| `REGION` | `europe-west4` | `setup_gcp.sh` (bucket location) |
| `ZONE` | `europe-west4-a` | `launch_*`, `ops.sh` |
| `TRC_PROFILE` | unset | `launch_spot.sh` — `v6e-16-eu` (prod) / `v6e-8-eu` (smoke/eval) |
| `CONFIG_FILE` | `configs/tpu/stage2_tpu_v6e16_full_v03_mh.yaml` | `launch_*` |
| `BUCKET` | `tinyaya-stage2-eu` | `setup_gcp.sh`, `ops.sh pull-best` |
| `CKPT_PREFIX` | `checkpoints/stage2-tpu` | `ops.sh pull-best` |
| `REPO_TARBALL_GS_URI` | unset | when set, startup fetches code from GCS instead of cloning GitHub |
| `SECRET_HF` / `SECRET_WANDB` | `hf-token` / `wandb-api-key` | Secret Manager names (override only if renamed) |
| `HF_TOKEN` / `WANDB_API_KEY` | from `.env` | seeded into Secret Manager by `setup_gcp.sh` |

`.env` is `.gitignored` and never leaves the workstation. Secrets are seeded into GCP
Secret Manager once; VMs fetch them at boot.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| QR stuck in `WAITING_FOR_RESOURCES` | TRC spot capacity exhausted in zone | check `gcloud compute tpus accelerator-types list --zone=<zone>`; try the other TRC zone |
| HF download stalls | rate-limit (many hosts in parallel) | pre-stage to `gs://$BUCKET/data/` and use the subset/tarball path |
| `secretmanager … not enabled` / GCS `permission denied` | `setup_gcp.sh` not run | run it (idempotent; re-applies IAM) |
| `uv: command not found` after boot / under sudo | astral.sh unreachable / root-owned uv | pip-fallback in startup; enumerate `/root/.local/bin/uv` |
| Private GitHub clone fails | fresh VM has no GitHub creds | pass `REPO_TARBALL_GS_URI=gs://...` |
| `ImportError: libpython3.12.so.1.0` | torch_xla can't find uv-managed CPython lib | libpython fallback on `LD_LIBRARY_PATH` (see `_remote_redeploy.sh`) |
| adapter loads but model reads ~random | TPU scan-wrapper namespace mismatch | fixed in `load_checkpoint` (remap + raise); ensure the checkpoint was saved by current code |

## What this does NOT do

- Multislice (single slice only) · async checkpointing (synchronous via `xm.save`)
- Auto-eval after training — run `scripts/eval_checkpoint.py` separately (CPU/GPU)
