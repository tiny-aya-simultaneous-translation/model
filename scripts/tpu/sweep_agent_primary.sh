#!/usr/bin/env bash
# HOST-0 wrapper invoked BY `wandb agent` once per Stage-2 Bayesian trial.
#
# WHY: a plain per-host `wandb agent` desyncs the 4-host SPMD mesh (each host
# pulls a different trial). So ONE agent runs on host-0 only and, per trial, this
# wrapper:
#   1. BROADCASTS the trial's args (agent's suggested lr/rank + the FIXED Stage-1
#      structure) to a shared GCS control file, so the 3 WORKER hosts running
#      sweep_host_loop.sh pick up the identical args and the 16-chip mesh forms.
#   2. Runs host-0's training as the PRIMARY (rank 0). Because the agent set
#      WANDB_SWEEP_ID / WANDB_RUN_ID, train_hierarchical's wandb.init joins the
#      agent's sweep run -> the NATIVE W&B sweep dashboard populates and the agent
#      reads back val/composite to drive Bayesian search. (Workers attach to this
#      same run via the GCS rendezvous, so there is exactly one run per trial.)
#
# The agent passes the suggested params as "$@" (e.g. --lr_lora=2e-4 --lora_r=32);
# WANDB_API_KEY / WANDB_SWEEP_ID / WANDB_RUN_ID / CONTROL_PREFIX / CONFIG_FILE are
# inherited from the agent's environment (`${env}` in the sweep command).
set -uo pipefail

CONTROL_PREFIX="${CONTROL_PREFIX:?set CONTROL_PREFIX=gs://.../sweep-control/scale-bayes}"
REPO_DIR="${REPO_DIR:-/opt/tinyaya}"
CONFIG_FILE="${CONFIG_FILE:-configs/tpu/stage2_tpu_v6e16_scale_proxy.yaml}"
TPU_STRATEGY="${TPU_STRATEGY:-fsdpv2_lora}"
SECRET_HF="${SECRET_HF:-hf-token}"
LOG=/tmp/train.log

# Stage-1 WINNER (+MLP) structure + fixed rsLoRA knobs -- NOT swept. Injected here
# because a JSON list can't ride wandb's ${args}; workers receive them verbatim via
# the control file so every host trains the identical model.
FIXED_ARGS=(
    --lora_alpha_mult 2
    --use_rslora true
    --lora_exclude_top 2
    --target_modules '["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj","embed_tokens"]'
)

export HOME="${HOME:-/root}"
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
cd "$REPO_DIR"

SUGGESTED=("$@")                                   # e.g. --lr_lora=2e-4 --lora_r=32
ALL_ARGS=("${SUGGESTED[@]}" "${FIXED_ARGS[@]}")

# ---- 1. broadcast to the worker hosts (monotonic index -> new trial) ----
idx_uri="$CONTROL_PREFIX/agent_index"
cur="$(gsutil cat "$idx_uri" 2>/dev/null || echo 0)"
[ -z "$cur" ] && cur=0
idx=$((cur + 1))
printf '%s' "$idx" | gsutil cp - "$idx_uri" >/dev/null 2>&1 || true
args_json="$(printf '%s\n' "${ALL_ARGS[@]}" \
    | python3 -c 'import json,sys; print(json.dumps([l.rstrip("\n") for l in sys.stdin if l.strip("\n")!=""]))')"
printf '{"index": %s, "args": %s, "wandb_run_id": "", "sweep_id": "", "stop": false}' \
    "$idx" "$args_json" | gsutil cp - "$CONTROL_PREFIX/current_trial.json" >/dev/null 2>&1 || true
echo "[$(date -Is)] === agent trial $idx (run ${WANDB_RUN_ID:-?}) ===" | tee -a "$LOG"
echo "[agent trial $idx] args: ${ALL_ARGS[*]}" | tee -a "$LOG"

# ---- 2. run host-0 PRIMARY training (joins the agent's sweep run) ----
HF_TOKEN="$(gcloud secrets versions access latest --secret="$SECRET_HF" 2>/dev/null || true)"
export HF_TOKEN
# torch_xla's _XLAC.so needs libpython3.12.so.1.0 from uv's managed python dir.
LIBPYTHON_DIR="$(dirname "$(find "$HOME/.local/share/uv/python" -name 'libpython3.12.so.1.0' -type f 2>/dev/null | head -1)")"

ulimit -n 1048576
DEVICE_BACKEND=tpu PJRT_DEVICE=TPU \
XLA_USE_BF16=0 XLA_DOWNCAST_BF16=0 XLA_DISABLE_FUNCTIONALIZATION=0 XLA_NO_SPECIAL_SCALARS=1 \
LIBTPU_INIT_ARGS='--megascale_grpc_enable_xor_tracer=false --xla_tpu_enable_flash_attention=false' \
PT_XLA_DEBUG_LEVEL=1 \
TPU_STRATEGY="$TPU_STRATEGY" \
LD_LIBRARY_PATH="$LIBPYTHON_DIR:${LD_LIBRARY_PATH:-}" \
PYTHONUNBUFFERED=1 \
uv run python -u scripts/train_hierarchical.py \
    --config "$CONFIG_FILE" \
    --sweep "${ALL_ARGS[@]}" 2>&1 | tee -a "$LOG"
rc=${PIPESTATUS[0]}
echo "[$(date -Is)] agent trial $idx train exited rc=$rc" | tee -a "$LOG"
exit "$rc"
