#!/bin/bash
# Prefetch the three HF model backbones the trainer loads into the host HF cache,
# routing around the GCP-EU -> HF CDN route congestion with a Cloudflare WARP
# SOCKS proxy. Idempotent: a no-op when the cache is already complete.
#
# WHY (TPU-for-GPU-engineers note): the composite model loads three US-region HF
# repos at build time -- CohereLabs/tiny-aya-base (backbone, 6.7 GB),
# kmhf/hf-moshiko (depth decoder, 15.6 GB 4-shard bf16 set), kyutai/mimi (audio
# monitor, 385 MB). On a GCP-EU host these large pulls STALL at tens-hundreds of
# MB, ~0 MB/s, across every transport (Xet / hf_transfer / plain) -- proven live
# 2026-07-14. Root cause is the network route, not auth/limit/transport: HF
# geo-routes GCP-origin EU traffic to the US CDN gateway us.gcp.cdn.hf.co over a
# congested transatlantic path (fast.hf.co = 3.8 KB/s). There is NO EU GCP
# gateway, and the CDN edge is chosen server-side by the repo's storage region,
# so no client env override exists. Cloudflare WARP in *proxy mode* egresses via
# Cloudflare's Amsterdam edge (the request no longer looks GCP-origin) -> HF stops
# using the US gateway and throughput jumps to ~50 MB/s. hf_transfer and the Xet
# client ignore SOCKS proxies, so we use the plain, proxy-honoring downloader
# (HF_HUB_DISABLE_XET=1 + HF_HUB_ENABLE_HF_TRANSFER=0). Proxy mode does NOT touch
# the default route, so training's GCS/DCN/metadata stay on the internal EU route.
# Full write-up: docs/v0.3-mh-hf-cdn-unblock.md.
#
# A fresh boot (initial provision or QR-death recovery) pays this once (~8 min);
# a warm reboot with a persisted boot disk skips it entirely.
set -uo pipefail

export HF_HOME="${HF_HOME:-$HOME/.cache/huggingface}"
export HF_HUB_CACHE="${HF_HUB_CACHE:-$HF_HOME/hub}"
PROXY_PORT=40000
PROXY="socks5h://127.0.0.1:${PROXY_PORT}"

_moshiko="$HF_HUB_CACHE/models--kmhf--hf-moshiko"
_tinyaya="$HF_HUB_CACHE/models--CohereLabs--tiny-aya-base"
_mimi="$HF_HUB_CACHE/models--kyutai--mimi"

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
    exit 0
fi

# ----- 1. Cloudflare WARP proxy (idempotent) -----
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

# ----- 2. download the 3 backbones via the proxy (plain, resumable) -----
# Pre-warm PySocks over the NORMAL route so uv's own package fetch isn't itself
# sent through the SOCKS proxy.
uv run --with pysocks python -c "import socks" >/dev/null 2>&1 || true

for _try in 1 2 3 4 5 6; do
    HF_HUB_DISABLE_XET=1 HF_HUB_ENABLE_HF_TRANSFER=0 HF_HUB_DOWNLOAD_TIMEOUT=20 \
    ALL_PROXY="$PROXY" HTTPS_PROXY="$PROXY" HTTP_PROXY="$PROXY" \
    uv run --with pysocks python - <<'PY'
import glob, os, sys
from huggingface_hub import snapshot_download

# main revision (no pin) so this always matches what from_pretrained resolves;
# skip Moshiko's 31 GB -of-00007 fp32 set -- the index references the 4-shard set.
jobs = [
    ("CohereLabs/tiny-aya-base", None),
    ("kmhf/hf-moshiko", ["*-of-00007.safetensors"]),
    ("kyutai/mimi", None),
]
for repo, ignore in jobs:
    snapshot_download(repo_id=repo, ignore_patterns=ignore, max_workers=1,
                      token=os.environ.get("HF_TOKEN"))

base = os.environ["HF_HUB_CACHE"]
nm = len(glob.glob(os.path.join(base, "models--kmhf--hf-moshiko",
                                 "snapshots", "*", "model-*-of-00004.safetensors")))
na = len(glob.glob(os.path.join(base, "models--CohereLabs--tiny-aya-base",
                                 "snapshots", "*", "model-*-of-00002.safetensors")))
print(f"[prefetch] moshiko={nm}/4 tinyaya={na}/2", flush=True)
sys.exit(0 if (nm == 4 and na == 2) else 3)
PY
    rc=$?
    if [ "$rc" -eq 0 ]; then echo "[prefetch] backbones ready"; exit 0; fi
    echo "[prefetch] attempt ${_try} incomplete (rc=${rc}); retrying"
    sleep 5
done

# Non-fatal: let the trainer attempt its own load (and the QR auto-retry recover)
# rather than blocking boot forever.
echo "[prefetch] WARNING: backbone prefetch did not complete after retries"
exit 0
