#!/bin/bash
# ON-HOST launcher for the pre-launch hardening probes (run as root on every
# worker of the v6e-16 slice; the local box pushes + invokes it over SSH).
#
# Mirrors _remote_redeploy.sh's INNER + startup_script.sh's trainer env, plus
# the probe-specific extras:
#   - LIBTPU flash-attention toggle (FLASH_ATTN=true/false -> LIBTPU_INIT_ARGS)
#   - persistent XLA compile cache at /mnt/data/xla_cache (XLA_CACHE=1)
#   - profiler server port 9012 (Probe 3 captures xp.trace against it)
#   - HF_HUB_OFFLINE=1 (backbones are verified-cached on this fleet)
#
# Env:
#   CONFIG_FILE            (required) repo-relative config
#   FLASH_ATTN             true|false (default false -- the validated default)
#   XLA_CACHE              1|0 (default 1)
#   RESUME                 auto|none (default auto)
#   WANDB_RENDEZVOUS_URI   (required for multi-host; SAME value on all hosts)
#   TMUX_SESSION           default train
set -euo pipefail

CONFIG_FILE="${CONFIG_FILE:?set CONFIG_FILE}"
FLASH_ATTN="${FLASH_ATTN:-false}"
XLA_CACHE="${XLA_CACHE:-1}"
RESUME="${RESUME:-auto}"
TMUX_SESSION="${TMUX_SESSION:-train}"
REPO_DIR="${REPO_DIR:-/opt/tinyaya}"
WANDB_RENDEZVOUS_URI="${WANDB_RENDEZVOUS_URI:?set WANDB_RENDEZVOUS_URI (same on all hosts)}"

# uv binary (installed as root by startup_script.sh)
UV_BIN=""
for candidate in /root/.local/bin/uv /root/.cargo/bin/uv; do
    [ -x "$candidate" ] && { UV_BIN="$candidate"; break; }
done
[ -n "$UV_BIN" ] || { echo "[probe] ERROR: uv not found"; exit 2; }

# stop whatever is running
tmux kill-session -t "$TMUX_SESSION" 2>/dev/null || true
pkill -9 -f 'python.*train_hierarchical' 2>/dev/null || true
sleep 2

_libpython="$(find /root/.local/share/uv/python -name 'libpython3.12.so.1.0' -type f 2>/dev/null | head -1)"
[ -n "$_libpython" ] || { echo "[probe] ERROR: libpython not found"; exit 2; }
LIBPYTHON_DIR="$(dirname "$_libpython")"

HF_TOKEN="$(gcloud secrets versions access latest --secret=hf-token)"
WANDB_API_KEY="$(gcloud secrets versions access latest --secret=wandb-api-key 2>/dev/null || echo '')"

LIBTPU_ARGS="--megascale_grpc_enable_xor_tracer=false --xla_tpu_enable_flash_attention=${FLASH_ATTN}"
XLA_CACHE_DIR=""
if [ "$XLA_CACHE" = "1" ]; then
    XLA_CACHE_DIR=/mnt/data/xla_cache
    mkdir -p "$XLA_CACHE_DIR"
fi

echo "[probe] host=$(hostname) config=$CONFIG_FILE flash_attn=$FLASH_ATTN xla_cache=${XLA_CACHE_DIR:-off} resume=$RESUME"

INNER=/tmp/probe_loop.sh
cat > "$INNER" <<INNEREOF
#!/bin/bash
set -e
cd "$REPO_DIR"
echo "[\$(date -Is)] hardening probe: $CONFIG_FILE (fa=$FLASH_ATTN cache=${XLA_CACHE_DIR:-off})" | tee -a /tmp/train.log
HOME=/root \
DEVICE_BACKEND=tpu PJRT_DEVICE=TPU \
XLA_DISABLE_FUNCTIONALIZATION=0 \
XLA_NO_SPECIAL_SCALARS=1 \
LIBTPU_INIT_ARGS='$LIBTPU_ARGS' \
${XLA_CACHE_DIR:+XLA_PERSISTENT_CACHE_PATH=$XLA_CACHE_DIR} \
PT_XLA_DEBUG_LEVEL=1 \
XLA_PROFILER_PORT=9012 \
TPU_STRATEGY=auto \
LD_LIBRARY_PATH="$LIBPYTHON_DIR:\${LD_LIBRARY_PATH:-}" \
HF_TOKEN='$HF_TOKEN' \
WANDB_API_KEY='$WANDB_API_KEY' \
WANDB_RENDEZVOUS_URI='$WANDB_RENDEZVOUS_URI' \
HF_HOME=/root/.cache/huggingface \
HF_HUB_OFFLINE=1 \
HF_HUB_ENABLE_HF_TRANSFER=0 \
PYTHONUNBUFFERED=1 \
"$UV_BIN" run python -u scripts/train_hierarchical.py \
    --config '$CONFIG_FILE' \
    --resume $RESUME 2>&1 | tee -a /tmp/train.log
echo "[\$(date -Is)] probe exited with status \$?" | tee -a /tmp/train.log
INNEREOF
chmod +x "$INNER"
tmux new-session -d -s "$TMUX_SESSION" "bash $INNER"
echo "[probe] tmux '$TMUX_SESSION' started"
