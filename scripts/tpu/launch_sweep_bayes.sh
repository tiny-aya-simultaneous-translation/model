#!/usr/bin/env bash
# Launch the Stage-2 BAYESIAN sweep with the NATIVE W&B sweep dashboard.
#
# Architecture (why not the coordinator): the native W&B sweep dashboard only
# populates for runs a `wandb agent` creates inside the sweep. A per-host agent
# desyncs the 4-host mesh, so ONE agent runs on HOST-0 and, per trial, its wrapper
# (sweep_agent_primary.sh) BROADCASTS the trial args to the 3 WORKER hosts (which
# run sweep_host_loop.sh -> the 16-chip mesh forms) AND runs host-0's PRIMARY
# training, whose run lands in the sweep. W&B bayes drives lr x rank.
#
# Usage:
#   NAME=scale-bayes MAX_TRIALS=8 bash scripts/tpu/launch_sweep_bayes.sh
# Monitor:
#   gcloud compute tpus tpu-vm ssh $NODE_ID --zone $ZONE --worker=0 \
#     --command 'tmux capture-pane -pt sweepagent | tail -40; echo ---; tail -20 /tmp/train.log'
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
# shellcheck source=./_lib.sh
source "$SCRIPT_DIR/_lib.sh"
load_env_file "$REPO_ROOT/.env"

PROJECT_ID="${PROJECT_ID:-ml-pipelines-315702}"
ZONE="${ZONE:-europe-west4-a}"
NODE_ID="${NODE_ID:-tinyaya-v6e16-sweep-ew4}"
BUCKET="${BUCKET:-tinyaya-stage2-eu}"
NAME="${NAME:-scale-bayes}"
MAX_TRIALS="${MAX_TRIALS:-8}"                 # W&B bayes trial budget (agent --count)
NUM_HOSTS="${NUM_HOSTS:-4}"
WANDB_ENTITY="${WANDB_ENTITY:-cataluna84}"
WANDB_PROJECT="${WANDB_PROJECT:-tinyaya-stage2-tpu}"
SWEEP_YAML="${SWEEP_YAML:-sweeps/sweep_stage2_scale_bayes.yaml}"
CONFIG_FILE="${CONFIG_FILE:-configs/tpu/stage2_tpu_v6e16_scale_proxy.yaml}"
SECRET_WANDB="${SECRET_WANDB:-wandb-api-key}"
REPO_DIR="/opt/tinyaya"
CONTROL_PREFIX="gs://$BUCKET/sweep-control/$NAME"

echo "==> bayes sweep: NODE_ID=$NODE_ID name=$NAME budget=$MAX_TRIALS"
echo "    control-prefix: $CONTROL_PREFIX"

# ----- 1. package + refresh code on every host -----
TARBALL="/tmp/tinyaya-bayes-code.tar.gz"
GCS_TARBALL="gs://$BUCKET/code/sweep-bayes-$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
echo "==> [1/5] packaging code -> $GCS_TARBALL"
cd "$REPO_ROOT"
tar --exclude='.git' --exclude='.venv' --exclude='.env' --exclude='.claude' \
    --exclude='__pycache__' --exclude='*.pyc' --exclude='.pytest_cache' \
    -czf "$TARBALL" src scripts configs sweeps docs pyproject.toml uv.lock README.md
gcloud storage cp "$TARBALL" "$GCS_TARBALL" --project="$PROJECT_ID"
rm -f "$TARBALL"

ssh_w() { gcloud compute tpus tpu-vm ssh "$NODE_ID" --zone="$ZONE" --project="$PROJECT_ID" --worker="$1" --command="$2"; }
ssh_all() { gcloud compute tpus tpu-vm ssh "$NODE_ID" --zone="$ZONE" --project="$PROJECT_ID" --worker=all --command="$1"; }

echo "==> [2/5] fetching code on all hosts"
ssh_all "set -e; gcloud storage cp '$GCS_TARBALL' /tmp/bayes-code.tar.gz && \
    sudo tar -xzf /tmp/bayes-code.tar.gz -C '$REPO_DIR' && rm -f /tmp/bayes-code.tar.gz && \
    echo \"[\$(hostname)] code refreshed\""

# ----- 3. create the W&B sweep (programmatically via wandb.sweep()) -----
# We create the sweep from Python (not the `wandb sweep` CLI, which also works)
# so the script captures the sweep id directly without parsing CLI output.
# Reuse a pre-created sweep if SWEEP_ID is passed (avoids orphan sweeps on relaunch).
WANDB_API_KEY="$(gcloud secrets versions access latest --secret="$SECRET_WANDB" --project="$PROJECT_ID" 2>/dev/null)"
export WANDB_API_KEY
SWEEP_ID="${SWEEP_ID:-}"
if [ -z "$SWEEP_ID" ]; then
    echo "==> [3/5] creating W&B sweep via Python API"
    SWEEP_ID="$(WANDB_SILENT=true uv run --project "$REPO_ROOT" python - "$SWEEP_YAML" "$WANDB_ENTITY" "$WANDB_PROJECT" <<'PY'
import sys, yaml, wandb
cfg = yaml.safe_load(open(sys.argv[1]))
sid = wandb.sweep(cfg, entity=sys.argv[2], project=sys.argv[3])
print("SWEEP_ID=" + sid)
PY
)"
    SWEEP_ID="$(printf '%s' "$SWEEP_ID" | grep -oE 'SWEEP_ID=[A-Za-z0-9]+' | cut -d= -f2 | head -1)"
else
    echo "==> [3/5] reusing provided SWEEP_ID=$SWEEP_ID"
fi
if [ -z "$SWEEP_ID" ]; then echo "ERROR: sweep creation failed" >&2; exit 1; fi
SWEEP_PATH="$WANDB_ENTITY/$WANDB_PROJECT/$SWEEP_ID"
echo "    sweep: https://wandb.ai/$WANDB_ENTITY/$WANDB_PROJECT/sweeps/$SWEEP_ID"

# ----- 4. clear stale control state, then start WORKER loops on hosts 1..N-1 -----
echo "==> [4/5] clearing stale control state + starting worker loops (hosts 1..$((NUM_HOSTS-1)))"
gsutil rm "$CONTROL_PREFIX/current_trial.json" 2>/dev/null || true
gsutil -m rm "$CONTROL_PREFIX/agent_index" "$CONTROL_PREFIX/done/**" 2>/dev/null || true
# also invalidate any stale rendezvous run-id (e.g. from Stage 1) so workers can't
# attach to a dead run before host-0's first trial republishes it.
gsutil rm "gs://$BUCKET/wandb-rendezvous/scale-sweep.id" 2>/dev/null || true
for w in $(seq 1 $((NUM_HOSTS - 1))); do
    ssh_w "$w" "sudo -H tmux kill-session -t sweephost 2>/dev/null || true; \
        sudo pkill -9 -f '[s]cripts/train_hierarchical.py' 2>/dev/null || true; sleep 2; \
        sudo -H tmux new-session -d -s sweephost \
        \"CONTROL_PREFIX='$CONTROL_PREFIX' CONFIG_FILE='$CONFIG_FILE' \
          bash '$REPO_DIR/scripts/tpu/sweep_host_loop.sh'\"; \
        sleep 1; sudo tmux ls 2>/dev/null | grep -q sweephost && echo \"[\$(hostname)] worker OK\" || echo \"[\$(hostname)] worker FAILED\""
done

# ----- 5. start the `wandb agent` on host-0 (tmux 'sweepagent') -----
# The agent runs the wrapper per trial (native dashboard); when the budget is
# exhausted it signals the workers to stop.
echo "==> [5/5] starting wandb agent (tmux 'sweepagent') on host-0"
STOP_JSON='{"index": 999999999, "stop": true}'
ssh_w 0 "sudo -H tmux kill-session -t sweepagent 2>/dev/null || true; \
    sudo pkill -9 -f '[s]cripts/train_hierarchical.py' 2>/dev/null || true; sleep 2; \
    sudo -H tmux new-session -d -s sweepagent \
    \"cd '$REPO_DIR'; export PATH=/root/.local/bin:\\\$PATH; \
      export WANDB_API_KEY=\\\$(gcloud secrets versions access latest --secret='$SECRET_WANDB' 2>/dev/null); \
      export CONTROL_PREFIX='$CONTROL_PREFIX' CONFIG_FILE='$CONFIG_FILE' REPO_DIR='$REPO_DIR'; \
      uv run wandb agent --count $MAX_TRIALS '$SWEEP_PATH' 2>&1 | tee -a /tmp/agent.log; \
      printf '%s' '$STOP_JSON' | gsutil cp - '$CONTROL_PREFIX/current_trial.json'\"; \
    sleep 1; sudo tmux ls 2>/dev/null | grep -q sweepagent && echo 'agent OK' || echo 'agent FAILED'"

cat <<EOF

==> launched. NATIVE sweep dashboard:
    https://wandb.ai/$WANDB_ENTITY/$WANDB_PROJECT/sweeps/$SWEEP_ID
    Monitor: gcloud compute tpus tpu-vm ssh $NODE_ID --zone $ZONE --worker=0 \\
      --command 'tmux capture-pane -pt sweepagent | tail -30; echo ---; tail -15 /tmp/train.log'
    Tear down: ssh --worker=all 'tmux kill-session -t sweepagent; tmux kill-session -t sweephost'
EOF
echo "SWEEP_URL=https://wandb.ai/$WANDB_ENTITY/$WANDB_PROJECT/sweeps/$SWEEP_ID"
