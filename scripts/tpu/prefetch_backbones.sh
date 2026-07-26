#!/bin/bash
# Prefetch the three HF model backbones the trainer loads into the host HF
# cache. PRIMARY: direct download from huggingface.co with default transports.
# FALLBACK: Cloudflare WARP SOCKS proxy + plain downloader.
# Idempotent: a no-op when the cache is already complete.
#
# ROUTE HISTORY (TPU-for-GPU-engineers note): the composite model loads three
# US-region HF repos at build time -- CohereLabs/tiny-aya-base (backbone,
# 6.7 GB), kmhf/hf-moshiko (depth decoder, 15.6 GB 4-shard bf16 set),
# kyutai/mimi (audio monitor, 385 MB). On 2026-07-14 these pulls STALLED on
# GCP-EU hosts at ~0 MB/s across every transport: HF geo-routed GCP-origin EU
# traffic to the congested US gateway us.gcp.cdn.hf.co. Workaround was WARP
# proxy mode (AMS edge, ~50 MB/s). On 2026-07-15 the route was FIXED upstream:
# the redirect now resolves to cas-bridge.xethub.hf.co and direct default-
# transport (Xet) downloads measured 146-219 MB/s from the same hosts. So
# DIRECT is primary again; WARP stays as the fallback because route
# regressions of this class recur and a fresh boot must never be blocked.
#
# A fresh boot (initial provision or QR-death recovery) pays this once
# (~2-4 min direct; ~8 min if the WARP fallback engages); a warm reboot with a
# persisted boot disk skips it entirely.
set -uo pipefail

export HF_HOME="${HF_HOME:-$HOME/.cache/huggingface}"
export HF_HUB_CACHE="${HF_HUB_CACHE:-$HF_HOME/hub}"
PROXY_PORT=40000
PROXY="socks5h://127.0.0.1:${PROXY_PORT}"

_moshiko="$HF_HUB_CACHE/models--kmhf--hf-moshiko"
_tinyaya="$HF_HUB_CACHE/models--CohereLabs--tiny-aya-base"
_mimi="$HF_HUB_CACHE/models--kyutai--mimi"

# /tmp/hf_backbones_ready gates HF_HUB_OFFLINE=1 in the trainer env
# (startup_script.sh): only set when this script has VERIFIED the cache.
rm -f /tmp/hf_backbones_ready

# ----- 0. skip when already complete (warm reboot) -----
_is_cached() {
    local nm na ni
    nm=$(find "$_moshiko/snapshots" -name 'model-*-of-00004.safetensors' 2>/dev/null | wc -l)
    na=$(find "$_tinyaya/snapshots" -name 'model-*-of-00002.safetensors' 2>/dev/null | wc -l)
    ni=$(find "$_mimi/snapshots" -name '*.safetensors' 2>/dev/null | wc -l)
    [ "$nm" -eq 4 ] && [ "$na" -eq 2 ] && [ "$ni" -ge 1 ] \
        && [ -z "$(find "$_moshiko" "$_tinyaya" "$_mimi" -name '*.incomplete' 2>/dev/null)" ]
}
if _is_cached; then
    echo "[prefetch] backbones already cached; skipping"
    touch /tmp/hf_backbones_ready
    exit 0
fi

# The download job is identical for both paths; only the env differs.
# Skip Moshiko's 31 GB -of-00007 fp32 set -- the index references the 4-shard
# bf16 set. main revision (no pin) so this always matches from_pretrained.
_download_py() {
    cat <<'PY'
import glob, os, sys
from huggingface_hub import snapshot_download

jobs = [
    ("CohereLabs/tiny-aya-base", None),
    ("kmhf/hf-moshiko", ["*-of-00007.safetensors"]),
    ("kyutai/mimi", None),
]
mw = int(os.environ.get("PREFETCH_MAX_WORKERS", "4"))
for repo, ignore in jobs:
    snapshot_download(repo_id=repo, ignore_patterns=ignore, max_workers=mw,
                      token=os.environ.get("HF_TOKEN"))

base = os.environ["HF_HUB_CACHE"]
nm = len(glob.glob(os.path.join(base, "models--kmhf--hf-moshiko",
                                 "snapshots", "*", "model-*-of-00004.safetensors")))
na = len(glob.glob(os.path.join(base, "models--CohereLabs--tiny-aya-base",
                                 "snapshots", "*", "model-*-of-00002.safetensors")))
print(f"[prefetch] moshiko={nm}/4 tinyaya={na}/2", flush=True)
sys.exit(0 if (nm == 4 and na == 2) else 3)
PY
}

# Stale-lock sweep: huggingface_hub serializes per-blob downloads with .lock
# files; a killed/zombie downloader leaves them behind and a NEW download then
# blocks on the lock FOREVER (observed live on w-1, 2026-07-15: 22 h-old
# zombie held a moshiko blob lock; the fresh download froze at 6/13 files
# with the network perfectly healthy). At boot/prefetch time nothing else may
# legitimately be downloading, so clearing is always safe here.
find "$HF_HUB_CACHE" -name '*.lock' -delete 2>/dev/null || true

# ----- 1. PRIMARY: direct from HF, default transports (Xet on), no proxy -----
# Hard wall-clock cap: a route regression must FAIL FAST into the WARP
# fallback, never hang the boot (the 2026-07-14 stall mode was silent 0 MB/s).
echo "[prefetch] attempting DIRECT download (default transports)"
for _try in 1 2; do
    _download_py | timeout 900 env \
        HF_HUB_DOWNLOAD_TIMEOUT=30 \
        PREFETCH_MAX_WORKERS=4 \
        uv run python -
    rc=$?
    if [ "$rc" -eq 0 ]; then
        echo "[prefetch] backbones ready (direct)"
        touch /tmp/hf_backbones_ready
        exit 0
    fi
    echo "[prefetch] direct attempt ${_try} incomplete (rc=${rc}); retrying"
    sleep 5
done
echo "[prefetch] DIRECT path failed twice -- falling back to WARP proxy"

# ----- 2. FALLBACK: Cloudflare WARP proxy (idempotent) -----
if ! command -v warp-cli >/dev/null 2>&1; then
    echo "[prefetch] installing cloudflare-warp"
    curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg \
        | gpg --yes --dearmor -o /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg 2>/dev/null
    # shellcheck disable=SC1091
    . /etc/os-release
    echo "deb [signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] https://pkg.cloudflareclient.com/ ${UBUNTU_CODENAME:-jammy} main" \
        > /etc/apt/sources.list.d/cloudflare-client.list
    apt-get update -qq 2>/dev/null || true
    apt-get install -y -qq cloudflare-warp 2>/dev/null || true
fi
systemctl enable --now warp-svc 2>/dev/null || true
sleep 3
# register + SOCKS proxy mode + connect (support both new/old CLI syntax)
warp-cli --accept-tos registration new >/dev/null 2>&1 || warp-cli --accept-tos register >/dev/null 2>&1 || true
warp-cli --accept-tos mode proxy       >/dev/null 2>&1 || warp-cli --accept-tos set-mode proxy >/dev/null 2>&1 || true
warp-cli --accept-tos connect          >/dev/null 2>&1 || true
sleep 5
_warp=$(curl -s --max-time 10 --proxy "$PROXY" https://api.cloudflare.com/cdn-cgi/trace 2>/dev/null | grep -E '^warp=|^colo=' | tr '\n' ' ')
echo "[prefetch] WARP proxy: ${_warp:-UNAVAILABLE}"

# hf_transfer and the Xet client ignore SOCKS proxies, so the fallback uses
# the plain, proxy-honoring downloader. Pre-warm PySocks over the NORMAL
# route so uv's own package fetch isn't itself sent through the proxy.
uv run --with pysocks python -c "import socks" >/dev/null 2>&1 || true

for _try in 1 2 3 4 5 6; do
    _download_py | HF_HUB_DISABLE_XET=1 HF_HUB_ENABLE_HF_TRANSFER=0 HF_HUB_DOWNLOAD_TIMEOUT=20 \
        PREFETCH_MAX_WORKERS=1 \
        ALL_PROXY="$PROXY" HTTPS_PROXY="$PROXY" HTTP_PROXY="$PROXY" \
        uv run --with pysocks python -
    rc=$?
    if [ "$rc" -eq 0 ]; then
        echo "[prefetch] backbones ready (WARP fallback)"
        touch /tmp/hf_backbones_ready
        exit 0
    fi
    echo "[prefetch] WARP attempt ${_try} incomplete (rc=${rc}); retrying"
    sleep 5
done

# Non-fatal: let the trainer attempt its own load (and the QR auto-retry
# recover) rather than blocking boot forever.
echo "[prefetch] WARNING: backbone prefetch did not complete after retries"
exit 0
