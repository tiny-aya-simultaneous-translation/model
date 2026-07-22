#!/bin/bash
# TPU VM startup script.
# Runs as the default user on every host of the Queued Resource at boot.
# Idempotent: safe to re-run after a host reboot or `gcloud ... ssh ... -- 'sudo reboot'`.

set -euo pipefail
exec > >(tee -a /tmp/startup.log) 2>&1

# Metadata startup-script context can run with HOME unset (root, no login shell).
# Set it explicitly so `set -u` doesn't trip on $HOME later.
export HOME="${HOME:-/root}"
export USER="${USER:-$(id -un)}"

echo "=== [$(date -Is)] startup_script.sh begin on $(hostname) ==="

# ----- repo / branch knobs (override via VM metadata if needed) -----
REPO_URL="${REPO_URL:-https://github.com/tiny-aya-simulatenous-translation/tinyaya-stage2-scale.git}"
REPO_BRANCH="${REPO_BRANCH:-feat/tpu-support}"
REPO_DIR="${REPO_DIR:-/opt/tinyaya}"
PYTHON_VERSION="${PYTHON_VERSION:-3.12.13}"
# v0.3: the SYNTHETIC FLORES/OPUS/conversational corpus (1.24M Mimi-encoded
# pairs). NOTE: this is the non-`fleurs-` repo. v0.1 trained on this; v0.2
# regressed to the `fleurs-` sibling by accident -- see the model cards.
HF_DATASET="${HF_DATASET:-tiny-aya-translate/tr-hi-mimi-encoded}"
DATA_DIR="${DATA_DIR:-/mnt/data}"
SECRET_HF="${SECRET_HF:-hf-token}"
SECRET_WANDB="${SECRET_WANDB:-wandb-api-key}"
TMUX_SESSION="${TMUX_SESSION:-train}"
# Optional: GCS path to a tarball that overlays the cloned repo with locally
# uncommitted files (pyproject.toml, uv.lock, new configs). Useful when the
# launch infra is being iterated on and we don't want to push every change.
OVERLAY_GS_URI="${OVERLAY_GS_URI:-}"

read_meta() {
    local key=$1 default=$2
    curl -fsS -H 'Metadata-Flavor: Google' \
        "http://metadata.google.internal/computeMetadata/v1/instance/attributes/$key" \
        2>/dev/null || echo "$default"
}
# Training config path (relative to repo root) is read from VM
# metadata so canary vs full run share the same image.
CONFIG_FILE="$(read_meta config-file configs/tpu/stage2_tpu_v6e16_full_v03.yaml)"
# Optional GCS overlay path (see OVERLAY_GS_URI section below).
OVERLAY_GS_URI="$(read_meta overlay-gs-uri '')"
# Optional full-repo tarball in GCS. When set, replaces the `git clone` step
# entirely (private repo without GitHub credentials on the VM).
REPO_TARBALL_GS_URI="$(read_meta repo-tarball-gs-uri '')"
# Sharding strategy passed through to TPUBackend. See src/backend/tpu_backend.py
# for the full list (replicated / fsdpv2 / fsdpv2_lora / auto).
TPU_STRATEGY_META="$(read_meta tpu-strategy auto)"
# When set to 1, run scripts/tpu/probe_strategies.py before the real training
# and dump results to /tmp/probe-results.json. Useful for canary runs to pick
# the optimal strategy.
PROBE_FIRST="$(read_meta probe-first 0)"
# launch_spot.sh stamps `is-spot=1` into the QR metadata so this script can
# tell preemptible runs from on-demand. We use it to set WANDB_RESUME=allow
# so a preempt resumes the same wandb run instead of forking a new one.
IS_SPOT="$(read_meta is-spot 0)"
# Phase E sweep fleet: when `sweep-id` is set this host runs a `wandb agent`
# (one independent trial stream) instead of a single-config training run, and
# pulls the small pre-staged sweep subset from `sweep-data-gs-uri` (GCS) instead
# of the full corpus from HF. Both empty for a normal training run.
SWEEP_ID="$(read_meta sweep-id '')"
SWEEP_DATA_GS_URI="$(read_meta sweep-data-gs-uri '')"
# Flash attention: OFF historically (v4 correctness). Opt-in on v6e via the
# `flash-attention` metadata flag; Phase E validates speed/HBM/correctness.
if [ "$(read_meta flash-attention 0)" = "1" ]; then _FA=true; else _FA=false; fi
LIBTPU_ARGS="--megascale_grpc_enable_xor_tracer=false --xla_tpu_enable_flash_attention=${_FA}"
echo "[startup] CONFIG_FILE=$CONFIG_FILE"
echo "[startup] SWEEP_ID=${SWEEP_ID:-<unset>} SWEEP_DATA_GS_URI=${SWEEP_DATA_GS_URI:-<unset>}"
echo "[startup] OVERLAY_GS_URI=${OVERLAY_GS_URI:-<unset>}"
echo "[startup] REPO_TARBALL_GS_URI=${REPO_TARBALL_GS_URI:-<unset>}"
echo "[startup] TPU_STRATEGY=$TPU_STRATEGY_META PROBE_FIRST=$PROBE_FIRST IS_SPOT=$IS_SPOT"
if [ "$IS_SPOT" = "1" ]; then
    export WANDB_RESUME=allow
    echo "[startup] spot mode: WANDB_RESUME=allow"
fi

# ----- 1. system deps -----
# Dpkg::Lock::Timeout=600 lets apt wait for unattended-upgrades (which
# routinely holds the dpkg lock right after first boot) instead of failing.
APT_OPTS=(-o Dpkg::Lock::Timeout=600)
sudo DEBIAN_FRONTEND=noninteractive apt-get "${APT_OPTS[@]}" update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get "${APT_OPTS[@]}" install -y -qq \
    tmux git curl ca-certificates build-essential

# ----- 2. uv (with pip fallback if astral.sh is unreachable) -----
if ! command -v uv >/dev/null 2>&1; then
    if ! curl -fLsS https://astral.sh/uv/install.sh -o /tmp/uv-install.sh; then
        echo "[startup] curl install of uv failed, falling back to pip"
        python3 -m pip install --user uv
    else
        sh /tmp/uv-install.sh
    fi
fi
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
uv --version

# ----- 3. fetch repo: tarball-from-GCS (preferred for private repos) or git clone -----
sudo mkdir -p "$(dirname "$REPO_DIR")"
sudo chown "$USER:$USER" "$(dirname "$REPO_DIR")"
if [ -n "$REPO_TARBALL_GS_URI" ]; then
    echo "[startup] fetching repo tarball from $REPO_TARBALL_GS_URI"
    sudo rm -rf "$REPO_DIR"
    sudo mkdir -p "$REPO_DIR"
    sudo chown "$USER:$USER" "$REPO_DIR"
    gcloud storage cp "$REPO_TARBALL_GS_URI" /tmp/repo.tar.gz
    tar -xzf /tmp/repo.tar.gz -C "$REPO_DIR"
    rm -f /tmp/repo.tar.gz
else
    if [ ! -d "$REPO_DIR/.git" ]; then
        git clone "$REPO_URL" "$REPO_DIR"
    fi
    cd "$REPO_DIR"
    git fetch --all --prune
    git checkout "$REPO_BRANCH"
    git pull --ff-only
fi

cd "$REPO_DIR"

# ----- 3.5. optional overlay of locally-modified files from GCS -----
# The infra files (pyproject.toml, uv.lock, configs/stage2_tpu*.yaml) may not
# be in the cloned commit yet. If OVERLAY_GS_URI metadata is set, fetch and
# unpack on top of the cloned repo before `uv sync`.
if [ -n "$OVERLAY_GS_URI" ]; then
    echo "[startup] fetching code overlay from $OVERLAY_GS_URI"
    gcloud storage cp "$OVERLAY_GS_URI" /tmp/overlay.tar.gz
    tar -xzvf /tmp/overlay.tar.gz -C "$REPO_DIR"
    rm -f /tmp/overlay.tar.gz
fi

# ----- 4. python + deps via uv (frozen lockfile) -----
uv python install "$PYTHON_VERSION"
uv sync --frozen --extra eval

# ----- 5. secrets from Secret Manager -----
HF_TOKEN="$(gcloud secrets versions access latest --secret="$SECRET_HF")"
export HF_TOKEN
if WANDB_API_KEY="$(gcloud secrets versions access latest --secret="$SECRET_WANDB" 2>/dev/null)"; then
    export WANDB_API_KEY
fi

# ----- 6. dataset staging + preflight (scripts/tpu/stage_dataset.sh) -----
# Extracted to its own script so the pre-launch staging DRILL exercises the
# EXACT boot code path. Marker-identity re-staging, the two preflight gates
# (expected-train-rows / min-text-coverage metadata), and the cross-host
# digest all live there; a preflight failure exits nonzero here (set -e) so
# this host never writes its rendezvous ready-marker on a bad corpus.
DATA_DIR="$DATA_DIR" \
SWEEP_DATA_GS_URI="$SWEEP_DATA_GS_URI" \
HF_DATASET="$HF_DATASET" \
EXPECTED_TRAIN_ROWS="$(read_meta expected-train-rows 0)" \
MIN_TEXT_COVERAGE="$(read_meta min-text-coverage 0)" \
bash "$REPO_DIR/scripts/tpu/stage_dataset.sh"
DATA_DIGEST="$(cat "$DATA_DIR/.data_digest" 2>/dev/null || echo '')"

# ----- 6b. model backbones via WARP proxy (route around GCP-EU -> HF CDN stall) -----
# The composite model loads three US-region HF repos (tiny-aya-base, hf-moshiko,
# mimi) at build time; on a GCP-EU host these large pulls stall on the congested
# transatlantic route to us.gcp.cdn.hf.co. Prefetch them through a Cloudflare WARP
# SOCKS proxy BEFORE the rendezvous barrier so no host launches (or writes its
# ready-marker) without its backbones present. Idempotent -- skips when the boot
# disk already holds them. See scripts/tpu/prefetch_backbones.sh.
# Opt out with metadata prefetch-backbones=0.
if [ "$(read_meta prefetch-backbones 1)" = "1" ]; then
    echo "[startup] prefetching model backbones via WARP proxy"
    chmod +x "$REPO_DIR/scripts/tpu/prefetch_backbones.sh" 2>/dev/null || true
    bash "$REPO_DIR/scripts/tpu/prefetch_backbones.sh" 2>&1 | tee -a /tmp/prefetch.log \
        || echo "[startup] backbone prefetch returned nonzero (non-fatal)"
fi
# With a verified-complete HF cache the trainer runs fully OFFLINE: no etag
# HEADs at model build, immune to HF outages / the CDN route for the whole
# multi-day run. prefetch_backbones.sh drops the marker only after verifying
# all three snapshots; without it we stay online (cache-first fallback).
_HF_OFFLINE=0
[ -f /tmp/hf_backbones_ready ] && _HF_OFFLINE=1
echo "[startup] HF_HUB_OFFLINE=$_HF_OFFLINE"

# ----- 7. launch training with auto-restart in tmux -----
# torch_xla's _XLAC.so dynamically links libpython3.12.so.1.0, which uv keeps
# inside its managed-Python directory rather than on the standard linker path.
LIBPYTHON_DIR="$(dirname "$(find "$HOME/.local/share/uv/python" -name 'libpython3.12.so.1.0' -type f 2>/dev/null | head -1)")"
echo "[startup] LIBPYTHON_DIR=$LIBPYTHON_DIR"

# Persistent XLA compile cache: OPT-IN via `xla-cache-gs-uri` metadata.
# History: #8930/#9094 (TPU v4 + torch_xla 2.9) fail "deserialize executable:
# UNIMPLEMENTED" with the cache on. That bug is v4-SPECIFIC; on a long v6e-16
# SPOT run every preemption reboot otherwise pays a full ~20-min cold recompile
# of the scan-collapsed graph. So we make it opt-in + GCS-backed so the cache
# survives the reboot: restore from GCS at boot on ALL hosts (identical SPMD
# program => identical graph keys), host 0 syncs new entries back every 10 min.
# Phase E verifies it actually works on v6e before production turns it on.
XLA_CACHE_GS_URI="$(read_meta xla-cache-gs-uri '')"
if [ -n "$XLA_CACHE_GS_URI" ]; then
    _cache_dir="$DATA_DIR/xla_cache"
    mkdir -p "$_cache_dir"
    echo "[startup] restoring XLA compile cache from $XLA_CACHE_GS_URI"
    gsutil -m rsync -r "$XLA_CACHE_GS_URI" "$_cache_dir" 2>/dev/null || true
    export XLA_PERSISTENT_CACHE_PATH="$_cache_dir"
    echo "[startup] XLA_PERSISTENT_CACHE_PATH=$_cache_dir (entries: $(find "$_cache_dir" -type f 2>/dev/null | wc -l))"
    # Only host 0 pushes back (all hosts compile the same graphs, one uploader
    # avoids GCS write races). Backgrounded; dies with the VM on preemption.
    if [ "$(hostname | grep -oP 'w-\K[0-9]+' || echo 0)" = "0" ]; then
        ( while true; do sleep 600; gsutil -m rsync -r "$_cache_dir" "$XLA_CACHE_GS_URI" 2>/dev/null || true; done ) &
        echo "[startup] host 0 XLA-cache sync-up loop started (600s)"
    fi
else
    echo "[startup] XLA persistent cache disabled (set xla-cache-gs-uri to enable)"
fi

tmux kill-session -t "$TMUX_SESSION" 2>/dev/null || true

# ----- multi-host rendezvous barrier -----
# GCP runs this startup script per-host at boot; hosts finish (apt / uv sync /
# data staging) at DIFFERENT wall-clock times, so torch_xla's SliceBuilder gRPC
# mesh (:8471) races and every trainer dies unless all launch within a tight
# window (proven fatal on v5e-64 and re-confirmed on this v6e-16). Gate the
# trainer launch: each host writes a GCS ready-marker, all wait until NUM_HOSTS
# markers exist, then launch near-simultaneously. Host count is read from the
# TPU's own worker endpoint list (topology-truthful for any accelerator); a
# time-bucketed dir isolates a preemption reboot from the previous boot's stale
# markers, and per-boot WANDB_RENDEZVOUS_URI avoids a stale shared run-id.
_endpoints="$(read_meta worker-network-endpoints '')"
if [ -n "$_endpoints" ]; then
    NUM_HOSTS=$(printf '%s' "$_endpoints" | tr ',' '\n' | grep -c . || echo 1)
else
    NUM_HOSTS="$(read_meta num-hosts 1)"
fi
_slice_id="$(hostname | sed 's/-w-[0-9]*$//')"
_bucket=$(( $(date +%s) / 600 ))
export WANDB_RENDEZVOUS_URI="gs://tinyaya-stage2-eu/wandb-rendezvous/${_slice_id}-${_bucket}.id"
if [ "${NUM_HOSTS:-1}" -gt 1 ]; then
    _wid="$(hostname | grep -oP 'w-\K[0-9]+' || echo 0)"
    _barrier="gs://tinyaya-stage2-eu/rendezvous/${_slice_id}/${_bucket}"
    echo "[startup] rendezvous: host ${_wid}/${NUM_HOSTS} barrier=${_barrier}"
    # The ready-marker carries this host's dataset digest (section 6a) so the
    # slice can refuse to launch on divergent per-host corpora.
    printf 'ready %s %s\n' "$(date -Is)" "${DATA_DIGEST:-}" | gsutil -q cp - "${_barrier}/host-${_wid}" || true
    _rdv_passed=0
    for _i in $(seq 1 240); do  # up to 20 min for the slowest host's startup
        _cnt=$(gsutil ls "${_barrier}/" 2>/dev/null | grep -c 'host-' || true)
        _cnt="${_cnt:-0}"
        if [ "${_cnt}" -ge "${NUM_HOSTS}" ]; then
            echo "[startup] rendezvous barrier PASSED (${_cnt}/${NUM_HOSTS} hosts)"
            _rdv_passed=1
            break
        fi
        [ $(( _i % 6 )) -eq 0 ] && echo "[startup] waiting at barrier: ${_cnt}/${NUM_HOSTS}"
        sleep 5
    done
    if [ "$_rdv_passed" = "1" ]; then
        # Cross-host dataset-digest check: DistributedSampler shards by index,
        # so hosts with different (rows, files, split md5) silently corrupt the
        # global batch. All markers must agree before any trainer launches.
        _uniq=$(gsutil cat "${_barrier}/host-"* 2>/dev/null | grep -o 'rows=.*' | sort -u | grep -c . || true)
        if [ "${_uniq:-0}" -gt 1 ]; then
            echo "[startup] FATAL: dataset digests DIVERGE across hosts -- refusing to launch:"
            gsutil cat "${_barrier}/host-"* 2>/dev/null || true
            exit 1
        fi
        echo "[startup] cross-host dataset digest MATCH (${DATA_DIGEST:-<none>})"
    fi
fi

# Optional pre-flight probe of sharding strategies on the live mesh.
if [ "$PROBE_FIRST" = "1" ]; then
    echo "[startup] running probe_strategies.py before training"
    DEVICE_BACKEND=tpu PJRT_DEVICE=TPU \
    XLA_DISABLE_FUNCTIONALIZATION=0 \
    LD_LIBRARY_PATH="$LIBPYTHON_DIR:${LD_LIBRARY_PATH:-}" \
    uv run python scripts/tpu/probe_strategies.py \
        --strategies replicated fsdpv2_lora fsdpv2 \
        --steps 5 --hidden 1024 \
        --out /tmp/probe-results.json \
        2>&1 | tee /tmp/probe.log || echo "[startup] probe failed (non-fatal, continuing)"
fi

if [ -n "$SWEEP_ID" ]; then
    # Phase E sweep fleet: this host runs an independent wandb agent (single-host
    # v6e-8 trials pulled from the shared sweep). The agent's child processes
    # inherit the exported TPU env below.
    echo "[startup] sweep mode: launching wandb agent $SWEEP_ID"
    tmux new-session -d -s "$TMUX_SESSION" "
        set -uo pipefail
        ulimit -n 1048576
        cd '$REPO_DIR'
        echo \"[\$(date -Is)] launching wandb agent $SWEEP_ID\" | tee -a /tmp/train.log
        export DEVICE_BACKEND=tpu PJRT_DEVICE=TPU
        export XLA_USE_BF16=0 XLA_DOWNCAST_BF16=0 XLA_DISABLE_FUNCTIONALIZATION=0 XLA_NO_SPECIAL_SCALARS=1
        export LIBTPU_INIT_ARGS='$LIBTPU_ARGS'
        export TPU_STRATEGY='$TPU_STRATEGY_META'
        export LD_LIBRARY_PATH='$LIBPYTHON_DIR:\${LD_LIBRARY_PATH:-}'
        export HF_TOKEN='$HF_TOKEN' WANDB_API_KEY='${WANDB_API_KEY:-}'
        export HF_HUB_OFFLINE='$_HF_OFFLINE'
        export PYTHONUNBUFFERED=1 TOKENIZERS_PARALLELISM=false
        uv run wandb agent $SWEEP_ID 2>&1 | tee -a /tmp/train.log
        echo \"[\$(date -Is)] wandb agent exited with status \$?\" | tee -a /tmp/train.log
    "
else
    tmux new-session -d -s "$TMUX_SESSION" "
        set -euo pipefail
        ulimit -n 1048576
        cd '$REPO_DIR'
        echo \"[\$(date -Is)] launching train_hierarchical.py\" | tee -a /tmp/train.log
        DEVICE_BACKEND=tpu PJRT_DEVICE=TPU \
        XLA_USE_BF16=0 \
        XLA_DOWNCAST_BF16=0 \
        XLA_DISABLE_FUNCTIONALIZATION=0 \
        XLA_NO_SPECIAL_SCALARS=1 \
        LIBTPU_INIT_ARGS='$LIBTPU_ARGS' \
        PT_XLA_DEBUG_LEVEL=1 \
        XLA_PROFILER_PORT=9012 \
        TPU_STRATEGY='$TPU_STRATEGY_META' \
        LD_LIBRARY_PATH='$LIBPYTHON_DIR:\${LD_LIBRARY_PATH:-}' \
        HF_TOKEN='$HF_TOKEN' \
        WANDB_API_KEY='${WANDB_API_KEY:-}' \
        WANDB_RENDEZVOUS_URI='${WANDB_RENDEZVOUS_URI:-}' \
        HF_HUB_OFFLINE='$_HF_OFFLINE' \
        PYTHONUNBUFFERED=1 \
        HF_HUB_DISABLE_PROGRESS_BARS=1 \
        TRANSFORMERS_VERBOSITY=error \
        ABSL_MIN_LOG_LEVEL=2 \
        uv run python -u scripts/train_hierarchical.py \
            --config '$CONFIG_FILE' \
            --resume auto 2>&1 | tee -a /tmp/train.log
        echo \"[\$(date -Is)] training exited with status \$?\" | tee -a /tmp/train.log
    "
fi
# NOTE: 'while true' supervisor loop intentionally removed.
# GCP spot TPU preemption tears down the VM, not the python process,
# so a process-level supervisor cannot recover. The QR's spot lifecycle
# triggers a host reboot, after which this startup_script.sh re-runs
# (idempotent) and re-launches training fresh. Process-level supervision
# was hiding compile-time errors as transient failures and burning quota.

echo "=== [$(date -Is)] startup_script.sh complete on $(hostname) ==="
echo "Tail logs with: tmux attach -t $TMUX_SESSION   OR   tail -f /tmp/train.log"
