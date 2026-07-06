#!/usr/bin/env bash
# Submit a SPOT (preemptible) Queued Resource against the TRC grant.
#
# WHY THIS EXISTS
# ---------------
# TRC v6e is SPOT-only, so the current v6e-16 production path (and every
# other v6e/v5e slice) is provisioned here, not via the on-demand launch_qr.sh.
# This wrapper makes picking a slice a single-knob operation: the `TRC_PROFILE`
# environment variable (source of truth: `docs/tpu-trc-allocation.md`).
#
# Usage:
#   bash scripts/tpu/launch_spot.sh                            # default = v6e-16-eu (production)
#   TRC_PROFILE=v6e-8-eu     bash scripts/tpu/launch_spot.sh   # smoke / overfit / eval
#   TRC_PROFILE=v4-32-uc2b   bash scripts/tpu/launch_spot.sh   # legacy fallback
#   TRC_PROFILE=v6e-64-ew4a  bash scripts/tpu/launch_spot.sh
#
# All other knobs (CONFIG_FILE, TPU_STRATEGY, PROBE_FIRST, QR_NAME,
# NODE_ID, etc.) are forwarded to launch_qr.sh unchanged. SPOT is
# pinned to 1 because that is the whole point of this wrapper.
#
# TRC_PROFILE legend (see docs/tpu-trc-allocation.md):
#   v6e-16-eu    -> 16 chips spot v6e  in europe-west4-a  (current production, default)
#   v6e-8-eu     -> 8 chips spot v6e   in europe-west4-a  (smoke / overfit / eval)
#   v4-32-uc2b   -> 32 chips spot v4   in us-central2-b   (legacy fallback)
#   v5e-64-ew4b  -> 64 chips spot v5e  in europe-west4-b
#   v5e-64-uc1a  -> 64 chips spot v5e  in us-central1-a
#   v6e-64-ew4a  -> 64 chips spot v6e  in europe-west4-a
#   v6e-64-ue1d  -> 64 chips spot v6e  in us-east1-d
#
# The on-demand v4 path is reached via launch_qr.sh directly (no SPOT,
# no profile); use that whenever the on-demand quota is available.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

TRC_PROFILE="${TRC_PROFILE:-v6e-16-eu}"

case "$TRC_PROFILE" in
    v6e-16-eu)
        ACCEL_TYPE="${ACCEL_TYPE:-v6e-16}"
        ZONE="${ZONE:-europe-west4-a}"
        RUNTIME="${RUNTIME:-v2-alpha-tpuv6e}"
        DEFAULT_QR="tinyaya-stage2-spot-v6e16-eu-qr"
        DEFAULT_NODE="tinyaya-stage2-spot-v6e16-eu"
        ;;
    v4-32-uc2b)
        ACCEL_TYPE="${ACCEL_TYPE:-v4-32}"
        ZONE="${ZONE:-us-central2-b}"
        RUNTIME="${RUNTIME:-tpu-ubuntu2204-base}"
        DEFAULT_QR="tinyaya-stage2-spot-v4-qr"
        DEFAULT_NODE="tinyaya-stage2-spot-v4"
        ;;
    v5e-64-ew4b)
        ACCEL_TYPE="${ACCEL_TYPE:-v5litepod-64}"
        ZONE="${ZONE:-europe-west4-b}"
        RUNTIME="${RUNTIME:-v2-alpha-tpuv5-lite}"
        DEFAULT_QR="tinyaya-stage2-spot-v5e-ew4-qr"
        DEFAULT_NODE="tinyaya-stage2-spot-v5e-ew4"
        ;;
    v5e-64-uc1a)
        ACCEL_TYPE="${ACCEL_TYPE:-v5litepod-64}"
        ZONE="${ZONE:-us-central1-a}"
        RUNTIME="${RUNTIME:-v2-alpha-tpuv5-lite}"
        DEFAULT_QR="tinyaya-stage2-spot-v5e-uc1-qr"
        DEFAULT_NODE="tinyaya-stage2-spot-v5e-uc1"
        ;;
    v6e-64-ew4a)
        ACCEL_TYPE="${ACCEL_TYPE:-v6e-64}"
        ZONE="${ZONE:-europe-west4-a}"
        RUNTIME="${RUNTIME:-v2-alpha-tpuv6e}"
        DEFAULT_QR="tinyaya-stage2-spot-v6e-ew4-qr"
        DEFAULT_NODE="tinyaya-stage2-spot-v6e-ew4"
        ;;
    v6e-8-eu)
        ACCEL_TYPE="${ACCEL_TYPE:-v6e-8}"
        ZONE="${ZONE:-europe-west4-a}"
        RUNTIME="${RUNTIME:-v2-alpha-tpuv6e}"
        DEFAULT_QR="tinyaya-stage2-spot-v6e8-eu-qr"
        DEFAULT_NODE="tinyaya-stage2-spot-v6e8-eu"
        ;;
    v6e-64-ue1d)
        ACCEL_TYPE="${ACCEL_TYPE:-v6e-64}"
        ZONE="${ZONE:-us-east1-d}"
        RUNTIME="${RUNTIME:-v2-alpha-tpuv6e}"
        DEFAULT_QR="tinyaya-stage2-spot-v6e-ue1-qr"
        DEFAULT_NODE="tinyaya-stage2-spot-v6e-ue1"
        ;;
    *)
        echo "ERROR: unknown TRC_PROFILE '$TRC_PROFILE'" >&2
        echo "Valid profiles: v6e-16-eu v6e-8-eu v4-32-uc2b v5e-64-ew4b v5e-64-uc1a v6e-64-ew4a v6e-64-ue1d" >&2
        echo "See docs/tpu-trc-allocation.md for the source of truth." >&2
        exit 2
        ;;
esac

QR_NAME="${QR_NAME:-$DEFAULT_QR}"
NODE_ID="${NODE_ID:-$DEFAULT_NODE}"

echo "==> launch_spot: TRC_PROFILE=$TRC_PROFILE"
echo "    ACCEL_TYPE=$ACCEL_TYPE  ZONE=$ZONE  RUNTIME=$RUNTIME"
echo "    QR_NAME=$QR_NAME  NODE_ID=$NODE_ID"
echo "    forwarding to launch_qr.sh with SPOT=1"
echo

exec env \
    SPOT=1 \
    ACCEL_TYPE="$ACCEL_TYPE" \
    ZONE="$ZONE" \
    RUNTIME="$RUNTIME" \
    QR_NAME="$QR_NAME" \
    NODE_ID="$NODE_ID" \
    bash "$SCRIPT_DIR/launch_qr.sh" "$@"
