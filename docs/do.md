# do — deferred follow-ups (shelf)

Parked work that's known but not yet done. Not a plan (that's `.claude/PLAN.md`); this is
the backlog of loose ends. Delete an item when it's done.

## Open

_(none)_

---

## Done

### ~~Update stale defaults baked into the TPU scripts~~ ✅ (2026-07-06)

The docs pass left the `.sh`/`.py` scripts carrying v4 / v6e-8 / `v6e_v2` / `us-central2`
defaults; refreshed to v0.3 / v6e-16 / europe-west4:
- **Config default** `stage2_tpu_v6e_v2.yaml` → `stage2_tpu_v6e16_full_v03.yaml` across
  `launch_release`, `launch_qr`, `launch_canary`, `hot_redeploy`, `_remote_redeploy`,
  `startup_script`, and the `promote_sweep_winner.py` docstring.
- **`launch_spot.sh`**: added a `v6e-16-eu` profile (v6e-16 / europe-west4-a /
  `v2-alpha-tpuv6e`) and made it the default `TRC_PROFILE`; legacy profiles kept.
- **`launch_release.sh`**: header + `GCS_LOG_PREFIX` → v0.3 / `stage2-tpu-v6e16-full-v03`.
- **`setup_gcp.sh`** `REGION` → `europe-west4` (the bucket-location mismatch that caused the
  cross-region egress); **`ops.sh`** `ZONE` → `europe-west4-a`.
- **Kept** `launch_qr.sh`'s v4 hardware defaults on purpose — it's the *on-demand* launcher
  and TRC v6e is spot-only (on-demand v6e would fail / bill full-rate); only its header was
  clarified. **Kept** the `WANDB_PROJECT`/`WANDB_URL` = `tinyaya-stage2-tpu` (W&B namespace).

Verified: `bash -n scripts/tpu/*.sh` clean; no-arg `launch_release.sh` resolves to the v03
config + v6e16 GCS prefix; `v6e-16-eu` profile resolves correctly; tests + seam pass.
