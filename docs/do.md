# do — deferred follow-ups (shelf)

Parked work that's known but not yet done. Not a plan (that's `.claude/PLAN.md`); this is
the backlog of loose ends. Delete an item when it's done.

---

## 1. Update stale defaults baked into the TPU scripts

The 2026-07-06 docs pass updated every `.md` to v0.3 reality, but the **scripts** (`.sh` /
`.py`) still carry legacy defaults from the v4 / v6e-8 / v6e_v2 era. They're always
overridden per-invocation (the `${VAR:-default}` fallback + the config passed as `$1`), so
nothing is broken today — but the defaults now disagree with the docs and would mislead a
fresh operator or a copy-paste run.

**Stale config default** `stage2_tpu_v6e_v2.yaml` → should be
`configs/tpu/stage2_tpu_v6e16_full_v03.yaml`:
- `scripts/tpu/launch_release.sh:24` (`CONFIG="${1:-…}"`)
- `scripts/tpu/launch_qr.sh:33`, `launch_canary.sh:32`, `hot_redeploy.sh:28`,
  `_remote_redeploy.sh:16`, `startup_script.sh:42`
- `scripts/promote_sweep_winner.py:8` (docstring example)

**Stale zone / region / accelerator defaults** (`us-central2-b` / `us-central2` / `v4`) →
should be `europe-west4-a` / `europe-west4` / `v6e-16` (or `v6e-8`):
- `scripts/tpu/launch_qr.sh:28,31` (`ZONE=us-central2-b`, `ACCEL_TYPE=v4-64`)
- `scripts/tpu/launch_spot.sh:41,42` (legacy `v4-32-uc2b` default profile)
- `scripts/tpu/ops.sh:28` (`ZONE=us-central2-b`)
- `scripts/tpu/setup_gcp.sh:32` (`REGION=us-central2` — **note:** re-running `setup_gcp.sh`
  as-is would create the bucket in us-central2; the live bucket is `gs://tinyaya-stage2-eu`
  in europe-west4, so set `REGION=europe-west4`).

**Also** `launch_release.sh` header/comment still says "public 15k-step v6e-8 run" and its
`GCS_LOG_PREFIX` defaults to `.../stage2-tpu-v6e-v2` — refresh to the v0.3 / v6e-16 story.

**Leave unchanged:** the `WANDB_PROJECT` / `WANDB_ENTITY_PROJECT` / `WANDB_URL` /
`--wandb-project` defaults of `tinyaya-stage2-tpu` — that is the **W&B project name** (a
separate wandb.ai namespace), deliberately kept even after the GCS bucket moved to `-eu`.

Verify after: `bash -n scripts/tpu/*.sh` clean; a dry `launch_release.sh` with no arg
resolves to the v03 config; `setup_gcp.sh` targets europe-west4.
