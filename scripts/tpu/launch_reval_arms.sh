#!/usr/bin/env bash
# Materialise + launch the six v0.3 re-validation arms (A..F), one per v6e-8.
#
# WHY THIS EXISTS
# ---------------
# The v0.3 re-validation exercised the frozen recipe at a
# 5,000-step full-corpus horizon across SIX parallel single-host v6e-8 slices.
# The startup script runs exactly ONE config file per slice with no extra-args
# passthrough, so each arm needs a self-contained config. This script overlays
# the per-arm recipe knobs onto the base (configs/tpu/stage2_tpu_v6e8_reval.yaml),
# writes configs/tpu/reval/arm_<X>.yaml (committed as reproducible artifacts),
# and launches each via the existing launch_spot.sh (TRC_PROFILE=v6e-8-eu) with
# a distinct QR_NAME / NODE_ID. The launch path itself is UNCHANGED -- every arm
# is just a normal CONFIG_FILE run.
#
# The arm matrix below is the single source of truth for what differs per arm.
#
# Usage:
#   # 0. one-time: stage the full corpus to GCS (Phase 0c), then export its URI:
#   export SWEEP_DATA_GS_URI=gs://tinyaya-stage2-eu/data/full-corpus-YYYYMMDD.tar.gz
#
#   DRY_RUN=1 bash scripts/tpu/launch_reval_arms.sh        # just write the 6 configs
#   ARMS="A" bash scripts/tpu/launch_reval_arms.sh         # launch a single arm
#   bash scripts/tpu/launch_reval_arms.sh                  # write + launch all six
#
# Env:
#   ARMS               space/comma list of arm letters to act on (default: A B C D E F)
#   DRY_RUN=1          materialise configs only; do not create any QR
#   SWEEP_DATA_GS_URI  full-corpus tarball in GCS (forwarded to each slice; if
#                      unset each slice falls back to the full HF download)
#   REPO_TARBALL_GS_URI  GCS repo tarball the slice runs (REQUIRED for live launch:
#                      the repo is private so a bare VM cannot git-clone it, and the
#                      startup default branch is stale. Build with `git archive HEAD`
#                      + upload to gs://tinyaya-stage2-eu/code/). DRY_RUN skips this.
#   GIT_SHA            optional provenance string logged to W&B (default: HEAD sha)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BASE_CONFIG="$REPO_ROOT/configs/tpu/stage2_tpu_v6e8_reval.yaml"
OUT_DIR="$REPO_ROOT/configs/tpu/reval"

# ---- arm matrix: LETTER  r  lr_lora  exclude_top  dropout  wd  depth_unfreeze ----
# (dash '-' means "inherit the base value"). alpha is always 2*r (rsLoRA).
read -r -d '' ARM_MATRIX <<'EOF' || true
A 32 1.716e-4 2 0.05 0.01 0
B 64 1.2e-4   2 0.05 0.01 0
C 16 2.4e-4   2 0.05 0.01 0
D 32 1.716e-4 0 0.05 0.01 0
E 32 1.716e-4 2 0.10 0.05 0
F 32 1.716e-4 2 0.05 0.01 2
EOF

WANT="${ARMS:-A B C D E F}"
WANT="${WANT//,/ }"

# Repo tarball is mandatory for a real launch (private repo, stale default branch).
# Fail loud BEFORE provisioning any slice rather than silently git-cloning the wrong code.
if [ "${DRY_RUN:-0}" != "1" ] && [ -z "${REPO_TARBALL_GS_URI:-}" ]; then
    echo "ERROR: REPO_TARBALL_GS_URI is unset. The repo is private and the startup" >&2
    echo "  default branch is stale, so the slice must run a GCS repo tarball. Build one:" >&2
    echo "    git archive --format=tar.gz -o /tmp/repo.tgz HEAD" >&2
    echo "    gcloud storage cp /tmp/repo.tgz gs://tinyaya-stage2-eu/code/reval-\$(git rev-parse --short HEAD).tar.gz" >&2
    echo "  then re-run with REPO_TARBALL_GS_URI set. (DRY_RUN=1 skips this check.)" >&2
    exit 3
fi
GIT_SHA="${GIT_SHA:-$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)}"

mkdir -p "$OUT_DIR"

want_arm() {
    local a="$1"
    for w in $WANT; do [ "$w" = "$a" ] && return 0; done
    return 1
}

while read -r LETTER R LR EXCL DROP WD DUNF; do
    [ -z "${LETTER:-}" ] && continue
    want_arm "$LETTER" || continue

    arm_config="$OUT_DIR/arm_${LETTER}.yaml"
    # Overlay the arm knobs onto the base via an in-place YAML edit. Python (not
    # sed) so nested keys are set unambiguously and alpha stays 2*r.
    BASE_CONFIG="$BASE_CONFIG" ARM_CONFIG="$arm_config" \
    LETTER="$LETTER" R="$R" LR="$LR" EXCL="$EXCL" DROP="$DROP" WD="$WD" DUNF="$DUNF" \
    python3 - <<'PY'
import os
import yaml

with open(os.environ["BASE_CONFIG"]) as f:
    cfg = yaml.safe_load(f)

letter = os.environ["LETTER"]
r = int(os.environ["R"])
cfg["lora"]["r"] = r
cfg["lora"]["alpha"] = 2 * r  # rsLoRA convention
cfg["lora"]["dropout"] = float(os.environ["DROP"])
cfg["lora"]["lora_exclude_top"] = int(os.environ["EXCL"])
cfg["lora"]["depth_unfreeze_blocks"] = int(os.environ["DUNF"])
cfg["optim"]["lr_lora"] = float(os.environ["LR"])
cfg["train"]["weight_decay"] = float(os.environ["WD"])
# "-ta" (text+audio) namespace: keeps runs + checkpoints cleanly separated
# from the aborted audio-only pass (group v03-5k-reval, .../stage2-reval-5k/).
cfg["logging"]["save_dir"] = f"gs://tinyaya-stage2-eu/checkpoints/stage2-reval-5k-ta/arm_{letter}"
cfg["logging"]["wandb_run_name"] = f"v03-reval-ta-arm_{letter}"
cfg["logging"]["wandb_group"] = "v03-5k-reval-ta"

with open(os.environ["ARM_CONFIG"], "w") as f:
    f.write(f"# GENERATED by scripts/tpu/launch_reval_arms.sh -- arm {letter}.\n")
    f.write("# Edit the ARM_MATRIX in that script + regenerate; do not hand-edit.\n")
    yaml.safe_dump(cfg, f, sort_keys=False, default_flow_style=False)
print(f"[reval] wrote {os.environ['ARM_CONFIG']}  (r={r} lr={os.environ['LR']} "
      f"excl={os.environ['EXCL']} drop={os.environ['DROP']} wd={os.environ['WD']} "
      f"depth_unfreeze={os.environ['DUNF']})")
PY

    if [ "${DRY_RUN:-0}" = "1" ]; then
        continue
    fi

    rel_config="configs/tpu/reval/arm_${LETTER}.yaml"
    qr="tinyaya-reval-arm-${LETTER,,}-qr"
    node="tinyaya-reval-arm-${LETTER,,}"
    echo "==> launching reval arm $LETTER"
    echo "    config: $rel_config"
    echo "    QR/node: $qr / $node"
    echo "    repo tarball: $REPO_TARBALL_GS_URI  (git_sha=$GIT_SHA)"
    echo "    SWEEP_DATA_GS_URI=${SWEEP_DATA_GS_URI:-<unset: full HF download>}"
    # NOTE: GIT_SHA is shown above for operator provenance but is NOT forwarded to
    # the VM -- launch_qr.sh only stamps specific metadata, and the git-archive
    # tarball has no .git. W&B logs git_sha="unknown"; the tarball name carries it.
    TRC_PROFILE=v6e-8-eu \
    CONFIG_FILE="$rel_config" \
    QR_NAME="$qr" \
    NODE_ID="$node" \
    REPO_TARBALL_GS_URI="$REPO_TARBALL_GS_URI" \
    SWEEP_DATA_GS_URI="${SWEEP_DATA_GS_URI:-}" \
        bash "$SCRIPT_DIR/launch_spot.sh"
done <<< "$ARM_MATRIX"

echo "==> done. Watch an arm with:  QR_NAME=tinyaya-reval-arm-a-qr bash scripts/tpu/ops.sh status"
