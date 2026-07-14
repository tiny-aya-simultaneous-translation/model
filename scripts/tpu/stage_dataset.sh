#!/bin/bash
# Dataset staging + preflight for a TPU host (extracted from startup_script.sh
# sections 6/6a so the pre-launch STAGING DRILL can exercise the EXACT code
# path that runs at boot, and so the logic is testable in isolation).
#
# Called by startup_script.sh on every boot; callable directly for drills.
#
# Env:
#   DATA_DIR              (required) e.g. /mnt/data
#   SWEEP_DATA_GS_URI     GCS tarball to stage; empty => HF-download branch
#   HF_DATASET            HF dataset repo (HF branch only)
#   EXPECTED_TRAIN_ROWS   preflight gate: min train.jsonl rows (0 = skip)
#   MIN_TEXT_COVERAGE     preflight gate: min alignment coverage % (0 = warn only)
#
# On success writes the cross-host digest to $DATA_DIR/.data_digest
# (rows/pt/al/md5) -- startup_script.sh rides it on the rendezvous marker.
# Preflight failures exit 1 BEFORE any digest/ready-marker is written.
set -euo pipefail

DATA_DIR="${DATA_DIR:?set DATA_DIR}"
SWEEP_DATA_GS_URI="${SWEEP_DATA_GS_URI:-}"
HF_DATASET="${HF_DATASET:-tiny-aya-translate/tr-hi-mimi-encoded}"
EXPECTED_TRAIN_ROWS="${EXPECTED_TRAIN_ROWS:-0}"
MIN_TEXT_COVERAGE="${MIN_TEXT_COVERAGE:-0}"
USER="${USER:-$(id -un)}"

# ----- 6. dataset to /mnt/data (resumable) -----
sudo mkdir -p "$DATA_DIR"
sudo chown "$USER:$USER" "$DATA_DIR"

if [ -n "$SWEEP_DATA_GS_URI" ]; then
    # Pre-staged GCS tarball (probe subset OR the full corpus; built by
    # scripts/tpu/stage_sweep_subset.sh and siblings). Avoids HF entirely.
    # The .unpacked marker records WHICH source it belongs to (first line):
    # a marker that doesn't match the requested SWEEP_DATA_GS_URI -- including
    # the legacy empty marker -- forces a wipe + re-stage. Without this, a
    # tarball swap (e.g. 4k probe subset -> full corpus) silently trains the
    # long-horizon run on stale data (found live 2026-07-14: all 4 hosts held
    # the 4k spoke-4 subset behind a contentless marker).
    _marker="$DATA_DIR/encoded/.unpacked"
    _staged_src="$(head -n1 "$_marker" 2>/dev/null || true)"
    if [ "$_staged_src" != "$SWEEP_DATA_GS_URI" ]; then
        if [ -e "$_marker" ] || [ -d "$DATA_DIR/encoded" ]; then
            echo "[startup] staged corpus is '${_staged_src:-<unlabeled>}' but launch wants '$SWEEP_DATA_GS_URI' -- wiping stale corpus"
            sudo rm -rf "$DATA_DIR/encoded" "$DATA_DIR/splits"
            sudo find "$DATA_DIR" -maxdepth 1 -name '*.alignments.json' -delete 2>/dev/null || true
        fi
        echo "[startup] staging corpus from $SWEEP_DATA_GS_URI"
        gcloud storage cp "$SWEEP_DATA_GS_URI" /tmp/sweep_subset.tar.gz
        sudo mkdir -p "$DATA_DIR/encoded" "$DATA_DIR/splits"
        sudo chown -R "$USER:$USER" "$DATA_DIR/encoded" "$DATA_DIR/splits"
        # Tarball lays out encoded/ + splits/ at the top level -> extract into $DATA_DIR.
        tar -xzf /tmp/sweep_subset.tar.gz -C "$DATA_DIR"
        rm -f /tmp/sweep_subset.tar.gz
        n_pt=$(find "$DATA_DIR/encoded" -maxdepth 1 -name '*.pt' | wc -l)
        echo "[startup] staged: $n_pt encoded .pt files"
        # Written LAST (set -e: a failed download/extract never writes it), and
        # AFTER extraction so an in-tar marker can't overwrite the identity.
        printf '%s\nn_pt=%s\n' "$SWEEP_DATA_GS_URI" "$n_pt" | sudo tee "$_marker" >/dev/null
    else
        echo "[startup] corpus already staged from $SWEEP_DATA_GS_URI (marker match)"
    fi
else
# We deliberately do NOT set HF_HUB_ENABLE_HF_TRANSFER here: hf_transfer isn't
# pinned in the lockfile. (The synthetic repo is ~11.7 GB across 9 batch
# tarballs; the download dominates startup but is a one-time cost per host.)
uv run huggingface-cli download "$HF_DATASET" \
    --repo-type dataset \
    --local-dir "$DATA_DIR"

# The synthetic tr-hi-mimi-encoded repo ships the encoded .pt tensors AND their
# alignment JSONs bundled in mimi_encoded_batch*.tar.gz (each with a top-level
# encoded/ dir), plus splits/{train,val}.jsonl. Extract every batch into
# $DATA_DIR so files land at $DATA_DIR/encoded/<name>.pt -- src/data/dataset.py
# _resolve() matches on the BASENAME, so no --strip-components needed.
# ~1.24M samples => ~4M small files (fits: ~12.5M inodes free on the v6e VM).
# Idempotent: skip extraction once the marker file exists.
_marker="$DATA_DIR/encoded/.unpacked"
_staged_src="$(head -n1 "$_marker" 2>/dev/null || true)"
if ls "$DATA_DIR"/mimi_encoded_batch*.tar.gz >/dev/null 2>&1 \
        && [ "$_staged_src" != "hf:$HF_DATASET" ]; then
    if [ -e "$_marker" ] || [ -d "$DATA_DIR/encoded" ]; then
        echo "[startup] staged corpus is '${_staged_src:-<unlabeled>}' but launch wants 'hf:$HF_DATASET' -- wiping stale corpus"
        sudo rm -rf "$DATA_DIR/encoded"
        sudo find "$DATA_DIR" -maxdepth 1 -name '*.alignments.json' -delete 2>/dev/null || true
    fi
    sudo mkdir -p "$DATA_DIR/encoded"
    sudo chown "$USER:$USER" "$DATA_DIR/encoded"
    for tb in "$DATA_DIR"/mimi_encoded_batch*.tar.gz; do
        echo "[startup] extracting $(basename "$tb") -> $DATA_DIR/encoded"
        tar -xzf "$tb" -C "$DATA_DIR"
    done
    n_pt=$(find "$DATA_DIR/encoded" -maxdepth 1 -name '*.pt' | wc -l)
    echo "[startup] extracted $n_pt encoded .pt files"
    # The published HF repo's own splits/{train,val}.jsonl reference a small
    # number of pt_path entries (~5%, verified 2026-07-05) whose .pt file is
    # NOT present in any of the mimi_encoded_batch*.tar.gz -- an upstream gap
    # in the dataset repo itself, not a download failure (huggingface-cli
    # reports 100% of files fetched). src/data/dataset.py's __getitem__ loads
    # pt_path unconditionally (torch.load, no existence check), so an
    # unfiltered split crashes training the moment it draws a missing row.
    # Filter once per host, in place, before training ever reads the splits.
    sudo python3 -c "
import json, os
for split in ('train', 'val'):
    p = '$DATA_DIR/splits/' + split + '.jsonl'
    kept, dropped = [], 0
    with open(p) as f:
        for line in f:
            row = json.loads(line)
            if os.path.exists(os.path.join('$DATA_DIR', row['pt_path'])):
                kept.append(line)
            else:
                dropped += 1
    with open(p, 'w') as f:
        f.writelines(kept)
    print(f'[startup] filtered {split}.jsonl: kept={len(kept)} dropped={dropped}')
"
    sudo chown "$USER:$USER" "$DATA_DIR/splits/train.jsonl" "$DATA_DIR/splits/val.jsonl"
    printf 'hf:%s\nn_pt=%s\n' "$HF_DATASET" "$n_pt" | sudo tee "$DATA_DIR/encoded/.unpacked" >/dev/null
fi
fi  # end SWEEP_DATA_GS_URI branch

# ----- 6a. dataset preflight (guards two SILENT failure modes) -----
# (1) Row-count gate: metadata `expected-train-rows` (0 = skip). Catches a
#     stale/wrong corpus that the marker logic somehow let through -- without
#     it a 110k-step run can burn days on a 4k probe subset with no error.
# (2) Text-coverage gate: src/data/dataset.py falls back to ZERO text when an
#     alignment JSON is missing (no crash) -- exactly how the arm-era runs
#     silently under-trained text. metadata `min-text-coverage` (percent,
#     0 = warn only). The long-horizon launch sets both gates.
# The digest (rows/pt/al/md5) also rides the rendezvous ready-marker so hosts
# can refuse to launch on divergent splits (DistributedSampler shards by index:
# different per-host datasets silently corrupt the global batch).
TRAIN_ROWS=$(wc -l < "$DATA_DIR/splits/train.jsonl" 2>/dev/null || echo 0)
VAL_ROWS=$(wc -l < "$DATA_DIR/splits/val.jsonl" 2>/dev/null || echo 0)
N_PT=$(find "$DATA_DIR/encoded" -maxdepth 1 -name '*.pt' 2>/dev/null | wc -l)
N_TGT_AL=$(find "$DATA_DIR" -maxdepth 1 -name '*.tgt.alignments.json' 2>/dev/null | wc -l)
SPLIT_MD5=$(md5sum "$DATA_DIR/splits/train.jsonl" 2>/dev/null | awk '{print $1}' || echo none)
_coverage=0
[ "$N_PT" -gt 0 ] && _coverage=$(( N_TGT_AL * 100 / N_PT ))
echo "[preflight] train_rows=$TRAIN_ROWS val_rows=$VAL_ROWS n_pt=$N_PT n_tgt_align=$N_TGT_AL text_coverage=${_coverage}% split_md5=$SPLIT_MD5"
df -h "$DATA_DIR" | tail -1 | awk '{print "[preflight] disk: used "$3" of "$2", "$4" free"}'
if [ "$EXPECTED_TRAIN_ROWS" -gt 0 ] && [ "$TRAIN_ROWS" -lt "$EXPECTED_TRAIN_ROWS" ]; then
    echo "[preflight] FATAL: train.jsonl has $TRAIN_ROWS rows, expected >= $EXPECTED_TRAIN_ROWS (expected-train-rows metadata). Refusing to launch on the wrong corpus."
    exit 1
fi
if [ "$_coverage" -lt "${MIN_TEXT_COVERAGE:-0}" ]; then
    echo "[preflight] FATAL: text-alignment coverage ${_coverage}% < required ${MIN_TEXT_COVERAGE}% -- training would silently run (near-)audio-only. Refusing to launch."
    exit 1
fi
if [ "$_coverage" -lt 99 ]; then
    echo "[preflight] WARNING: text-alignment coverage is ${_coverage}% (dataset.py zero-fills text for uncovered rows -- verify this is intended)"
fi
DATA_DIGEST="rows=$TRAIN_ROWS pt=$N_PT al=$N_TGT_AL md5=$SPLIT_MD5"
printf '%s\n' "$DATA_DIGEST" | sudo tee "$DATA_DIR/.data_digest" >/dev/null
echo "[preflight] digest written: $DATA_DIGEST"
