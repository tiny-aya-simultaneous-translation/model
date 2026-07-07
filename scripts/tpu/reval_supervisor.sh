#!/usr/bin/env bash
# Always-on SUPERVISOR for the 6-arm v0.3 reval sweep.
#
# WHY THIS EXISTS
# ---------------
# Each reval arm trains in tmux ON ITS OWN v6e-8 (workstation-independent) and
# auto-resumes from GCS on spot preemption (startup_script re-runs + --resume auto).
# What does NOT survive a workstation shutdown is the ORCHESTRATION: resubmitting a
# fully-FAILED spot QR, and tearing arms down when done. This script runs that loop
# on a tiny always-on GCE VM (NOT the workstation, NOT a TPU), so the whole reval is
# fire-and-forget. It is idempotent and safe to restart.
#
# Per poll, for each arm A..F (independent single-host jobs -- no coordinator):
#   - done (step_5000 ckpt in GCS)        -> tear the arm's QR down (frees spot capacity), mark done.
#   - QR ACTIVE + not done                -> leave it (training or auto-resuming); heartbeat.
#   - QR FAILED / missing + not done      -> delete any stale QR + resubmit that ONE arm.
#   - all six done                        -> ntfy the user (selection is a human call), idle.
#
# A describe() that errors returns UNKNOWN (treated as "wait", never destructive) so a
# network blip can't tear down or resubmit a healthy arm.
#
# Env (VM metadata / defaults): PROJECT_ID, ZONE (TPU zone), BUCKET, NTFY_TOPIC,
#   REPO_DIR, POLL_S, HEARTBEAT_EVERY, MAX_STEPS, ARMS.
set -uo pipefail

PROJECT_ID="${PROJECT_ID:-ml-pipelines-315702}"
ZONE="${ZONE:-europe-west4-a}"                 # the TPUs' zone
BUCKET="${BUCKET:-tinyaya-stage2-eu}"
REPO_DIR="${REPO_DIR:-/opt/tinyaya-sup}"
NTFY_TOPIC="${NTFY_TOPIC:-tinyaya-v6e64-e35c80e64dea}"
WANDB_URL="${WANDB_URL:-https://wandb.ai/cataluna84/tinyaya-stage2-tpu/groups/v03-5k-reval}"
POLL_S="${POLL_S:-180}"
HEARTBEAT_EVERY="${HEARTBEAT_EVERY:-10}"       # ntfy heartbeat every N polls (~30 min)
MAX_STEPS="${MAX_STEPS:-5000}"
ARMS="${ARMS:-A B C D E F}"
CKPT_PREFIX="gs://$BUCKET/checkpoints/stage2-reval-5k"

ntfy() { curl -s -H "Title: TinyAya reval" -d "$1" "https://ntfy.sh/$NTFY_TOPIC" >/dev/null 2>&1 || true; }

qr_state() {  # $1=QR name -> ACTIVE|FAILED|SUSPENDED|...|MISSING|UNKNOWN
    local s
    s=$(gcloud compute tpus queued-resources describe "$1" --project="$PROJECT_ID" --zone="$ZONE" \
        --format='value(state.state)' 2>/tmp/qr_err) || { grep -qi "NOT_FOUND\|was not found" /tmp/qr_err && echo MISSING || echo UNKNOWN; return; }
    echo "${s:-UNKNOWN}"
}

arm_done() {  # $1=letter -> 0 if the final step_MAX_STEPS checkpoint exists in GCS
    gsutil ls "$CKPT_PREFIX/arm_$1/step_${MAX_STEPS}/" >/dev/null 2>&1
}

latest_tarball() { gsutil ls "gs://$BUCKET/code/reval-*.tar.gz" 2>/dev/null | sort | tail -1; }

resubmit_arm() {  # $1=letter
    local L="$1" qr="tinyaya-reval-arm-${1,,}-qr" tb
    tb="$(latest_tarball)"
    if [ -z "$tb" ]; then ntfy "arm $L needs resubmit but NO reval tarball in gs://$BUCKET/code/"; return 1; fi
    # clear any stale FAILED/SUSPENDED QR first (idempotent), then relaunch just this arm.
    gcloud compute tpus queued-resources delete "$qr" --project="$PROJECT_ID" --zone="$ZONE" --force --quiet >/dev/null 2>&1 || true
    ( cd "$REPO_DIR" && REPO_TARBALL_GS_URI="$tb" ARMS="$L" bash scripts/tpu/launch_reval_arms.sh >/dev/null 2>&1 )
    ntfy "arm $L resubmitted (tarball $(basename "$tb"))"
}

teardown_arm() {  # $1=letter -- arm finished; free its spot capacity
    local qr="tinyaya-reval-arm-${1,,}-qr"
    gcloud compute tpus queued-resources delete "$qr" --project="$PROJECT_ID" --zone="$ZONE" --force --quiet >/dev/null 2>&1 || true
}

declare -A DONE
for L in $ARMS; do DONE[$L]=0; done

ntfy "reval supervisor started -- arms: $ARMS. $WANDB_URL"
i=0
while true; do
    i=$((i + 1))
    all_done=1
    running=""
    for L in $ARMS; do
        [ "${DONE[$L]}" = "1" ] && continue
        if arm_done "$L"; then
            DONE[$L]=1; teardown_arm "$L"; ntfy "arm $L DONE (step $MAX_STEPS) -- QR torn down."; continue
        fi
        all_done=0
        st=$(qr_state "tinyaya-reval-arm-${L,,}-qr")
        case "$st" in
            ACTIVE|READY|PROVISIONING|WAITING_FOR_RESOURCES|ACCEPTED|CREATING)
                running="$running $L($st)" ;;
            FAILED|SUSPENDED|MISSING)
                ntfy "arm $L QR=$st and not done -> resubmit"; resubmit_arm "$L" ;;
            UNKNOWN)
                : ;;  # transient describe error -- wait, never destructive
            *)
                running="$running $L($st)" ;;
        esac
    done
    if [ "$all_done" = "1" ]; then
        ntfy "ALL reval arms COMPLETE. Pick the winner (val/composite + per-CB acc). $WANDB_URL"
        sleep 3600; continue
    fi
    [ $((i % HEARTBEAT_EVERY)) -eq 0 ] && ntfy "alive: reval arms running:$running. $WANDB_URL"
    sleep "$POLL_S"
done
