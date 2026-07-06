#!/bin/bash
# Launch a short canary to validate the launch path cheaply.
#
# This is a thin wrapper over launch_qr.sh that overrides the QR / node names
# and uses a separate checkpoint prefix. Everything else (project, zone, runtime,
# startup script, secrets, IAM) is identical to the full run, so a green canary
# directly validates the full-run launch path. There is no dedicated short config
# any more — the operator watches the first ~200 steps, then tears the QR down;
# pass CONFIG_FILE=... to use a smaller config than the default.
#
# Run from your local workstation, after setup_gcp.sh has succeeded.
#
# Override anything via shell env:
#   QR_NAME=foo NODE_ID=bar bash launch_canary.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"

# Force canary identity: clear any shell/env QR_NAME / NODE_ID so they cannot
# leak from the full-run defaults in .env. Operators who want to override
# the canary names should set CANARY_QR_NAME / CANARY_NODE_ID explicitly.
unset QR_NAME NODE_ID

# shellcheck source=./_lib.sh
source "$SCRIPT_DIR/_lib.sh"
load_env_file "$ENV_FILE"

QR_NAME="${CANARY_QR_NAME:-tinyaya-stage2-canary-qr}"
NODE_ID="${CANARY_NODE_ID:-tinyaya-stage2-canary}"
CONFIG_FILE="${CONFIG_FILE:-configs/tpu/stage2_tpu_v6e16_full_v03.yaml}"
# Canary defaults to spot (preemptible) since its purpose is code validation,
# not producing a model. Override with SPOT=0 if you want canary on-demand.
SPOT="${SPOT:-1}"

echo "==> launching canary"
echo "    QR name:     $QR_NAME"
echo "    node id:     $NODE_ID"
echo "    config file: $CONFIG_FILE"
echo "    spot tier:   $SPOT"
echo

exec env QR_NAME="$QR_NAME" NODE_ID="$NODE_ID" CONFIG_FILE="$CONFIG_FILE" SPOT="$SPOT" \
    bash "$SCRIPT_DIR/launch_qr.sh"
