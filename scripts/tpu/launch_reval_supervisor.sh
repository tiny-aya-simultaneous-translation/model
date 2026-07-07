#!/usr/bin/env bash
# Deploy the always-on 6-arm reval SUPERVISOR on a tiny e2-small GCE VM.
#
# WHY: makes the reval orchestration (resubmit FAILED arms, teardown when done,
# notify) workstation-independent -- the training already survives via tmux-on-TPU
# + GCS + --resume auto; this covers the parts that needed a live session.
#
# Usage:
#   bash scripts/tpu/launch_reval_supervisor.sh
#   # logs:      gcloud compute ssh tinyaya-reval-supervisor --zone <VM_ZONE> --command 'sudo journalctl -u revalsup -n 60 --no-pager'
#   # tear down: gcloud compute instances delete tinyaya-reval-supervisor --zone <VM_ZONE> --quiet
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$SCRIPT_DIR/_lib.sh"
load_env_file "$REPO_ROOT/.env"

PROJECT_ID="${PROJECT_ID:-ml-pipelines-315702}"
VM_NAME="${VM_NAME:-tinyaya-reval-supervisor}"
VM_ZONE="${VM_ZONE:-us-central1-a}"            # cheap always-on zone (non-TPU)
ZONE="${ZONE:-europe-west4-a}"                 # the TPUs' zone
BUCKET="${BUCKET:-tinyaya-stage2-eu}"
NTFY_TOPIC="${NTFY_TOPIC:-tinyaya-v6e64-e35c80e64dea}"
WANDB_URL="${WANDB_URL:-https://wandb.ai/cataluna84/tinyaya-stage2-tpu/groups/v03-5k-reval}"
ARMS_ENV="${ARMS:-A B C D E F}"

# ----- 1. stage a supervisor code tarball (launcher + configs + supervisor loop) -----
TB="$(mktemp --suffix=.tgz)"
GCS_TB="gs://$BUCKET/code/reval-supervisor-$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
cd "$REPO_ROOT"
tar --exclude='.git' --exclude='.venv' --exclude='.env' --exclude='.claude' \
    --exclude='__pycache__' --exclude='*.pyc' --exclude='.pytest_cache' \
    -czf "$TB" scripts configs pyproject.toml uv.lock
gcloud storage cp "$TB" "$GCS_TB" --project="$PROJECT_ID"; rm -f "$TB"

# ----- 2. VM startup script (self-sufficient: gcloud CLI + pyyaml, then the loop) -----
STARTUP=$(mktemp)
cat >"$STARTUP" <<STARTUP_EOF
#!/bin/bash
set -uxo pipefail
export HOME=/root
export DEBIAN_FRONTEND=noninteractive
# python3-yaml is required by launch_reval_arms.sh (config generation).
apt-get update -y && apt-get install -y python3-yaml curl
# google-cloud-cli may be absent on the base debian image; install if missing.
if ! command -v gcloud >/dev/null 2>&1; then
    apt-get install -y apt-transport-https ca-certificates gnupg
    echo "deb https://packages.cloud.google.com/apt cloud-sdk main" > /etc/apt/sources.list.d/google-cloud-sdk.list
    curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg 2>/dev/null || \
      curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg | apt-key add -
    apt-get update -y && apt-get install -y google-cloud-cli
fi
rm -rf /opt/tinyaya-sup && mkdir -p /opt/tinyaya-sup
for i in \$(seq 1 30); do gsutil cp "$GCS_TB" /tmp/code.tar.gz && break || sleep 10; done
tar -xzf /tmp/code.tar.gz -C /opt/tinyaya-sup
cat >/etc/systemd/system/revalsup.service <<UNIT
[Unit]
Description=TinyAya 6-arm reval supervisor
After=network-online.target
Wants=network-online.target
[Service]
Environment=PROJECT_ID=$PROJECT_ID ZONE=$ZONE BUCKET=$BUCKET REPO_DIR=/opt/tinyaya-sup
Environment=NTFY_TOPIC=$NTFY_TOPIC WANDB_URL=$WANDB_URL ARMS=$ARMS_ENV
ExecStart=/bin/bash /opt/tinyaya-sup/scripts/tpu/reval_supervisor.sh
Restart=always
RestartSec=30
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now revalsup.service
STARTUP_EOF

# ----- 3. create the VM (default compute SA already has editor+cloud-platform) -----
echo "==> creating reval supervisor VM $VM_NAME in $VM_ZONE"
gcloud compute instances create "$VM_NAME" \
    --project="$PROJECT_ID" --zone="$VM_ZONE" \
    --machine-type=e2-small --image-family=debian-12 --image-project=debian-cloud \
    --scopes=cloud-platform \
    --metadata-from-file=startup-script="$STARTUP"
rm -f "$STARTUP"

echo "==> supervisor VM up. It resubmits FAILED arms, tears down finished ones, and"
echo "    ntfy's on completion -- survives a workstation shutdown."
echo "    Logs:  gcloud compute ssh $VM_NAME --zone $VM_ZONE --command 'sudo journalctl -u revalsup -n 60 --no-pager'"
echo "    Stop:  gcloud compute instances delete $VM_NAME --zone $VM_ZONE --quiet"
