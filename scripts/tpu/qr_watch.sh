#!/usr/bin/env bash
# QR babysitter for long-horizon spot runs. Run on the LOCAL workstation in a
# detached tmux for the duration of a multi-day run.
#
# WHY THIS EXISTS
# ---------------
# Spot PREEMPTION reboots the slice's VMs and self-heals (startup_script.sh
# re-runs; the trainer resumes via --resume auto). But when the QUEUED RESOURCE
# itself dies (state FAILED / SUSPENDED -- e.g. capacity reclaim tears the
# slice down for good), nothing recreates it: a 2.4-day run silently stalls
# until a human notices. This watcher closes that gap: it polls the QR, and on
# a dead state captures the full describe JSON (failedData included) to the
# log, deletes the dead QR, and resubmits the IDENTICAL launch env.
#
# Sweep-orchestration lessons applied (PR #10 ed3bdcf + 61d4a6a):
#   - never false-complete: the loop only ends on operator stop, quota-abort,
#     or the resubmit budget running out -- always with a loud final line
#   - deterministic identity: the same QR_NAME/NODE_ID every resubmit
#   - coordinator-only relaunch: THIS process is the only resubmitter; if the
#     QR is MISSING (operator deleted it), we exit instead of fighting them
#
# Usage:
#   1. Save the exact launch env to a file (one KEY=VALUE per line), e.g.
#        TRC_PROFILE=v6e-16-eu
#        CONFIG_FILE=configs/tpu/stage2_tpu_v6e16_full_v03_mh.yaml
#        REPO_TARBALL_GS_URI=gs://tinyaya-stage2-eu/code/<sha>.tar.gz
#        SWEEP_DATA_GS_URI=gs://tinyaya-stage2-eu/data/full-corpus-ta-20260708.tar.gz
#        XLA_CACHE_GS_URI=gs://tinyaya-stage2-eu/xla-cache/v03-mh
#   2. tmux new -d -s qrwatch \
#        "QR_NAME=tinyaya-stage2-spot-v6e16-eu-qr ZONE=europe-west4-a \
#         LAUNCH_ENV_FILE=launch.env bash scripts/tpu/qr_watch.sh \
#         2>&1 | tee -a /tmp/qr_watch.log"
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

QR_NAME="${QR_NAME:?set QR_NAME}"
ZONE="${ZONE:?set ZONE}"
PROJECT_ID="${PROJECT_ID:-ml-pipelines-315702}"
LAUNCH_ENV_FILE="${LAUNCH_ENV_FILE:?set LAUNCH_ENV_FILE (saved launch env)}"
POLL_SECONDS="${POLL_SECONDS:-300}"
MAX_RESUBMITS="${MAX_RESUBMITS:-20}"
# Minimum seconds between two recovery actions (anti-flap).
COOLDOWN_SECONDS="${COOLDOWN_SECONDS:-120}"

[ -f "$LAUNCH_ENV_FILE" ] || { echo "[qr_watch] FATAL: no env file $LAUNCH_ENV_FILE"; exit 2; }

_ts() { date -Is; }

_describe() {
    gcloud compute tpus queued-resources describe "$QR_NAME" \
        --zone="$ZONE" --project="$PROJECT_ID" --format=json 2>/dev/null
}

_state() {
    gcloud compute tpus queued-resources describe "$QR_NAME" \
        --zone="$ZONE" --project="$PROJECT_ID" \
        --format='value(state.state)' 2>/dev/null
}

_resubmit() {
    echo "[qr_watch $(_ts)] resubmitting via launch_spot.sh (env: $LAUNCH_ENV_FILE)"
    (
        set -a
        # shellcheck disable=SC1090
        source "$LAUNCH_ENV_FILE"
        set +a
        QR_NAME="$QR_NAME" ZONE="$ZONE" bash "$SCRIPT_DIR/launch_spot.sh"
    )
}

echo "[qr_watch $(_ts)] watching QR=$QR_NAME zone=$ZONE poll=${POLL_SECONDS}s max_resubmits=$MAX_RESUBMITS"
resubmits=0
last_action=0

while true; do
    state="$(_state)"
    now=$(date +%s)

    case "$state" in
        ACTIVE|PROVISIONING|ACCEPTED|CREATING|WAITING_FOR_RESOURCES)
            echo "[qr_watch $(_ts)] state=$state ok"
            ;;
        SUSPENDING|SUSPENDED|FAILED)
            echo "[qr_watch $(_ts)] state=$state -- QR is DEAD, starting recovery"
            if [ $(( now - last_action )) -lt "$COOLDOWN_SECONDS" ]; then
                echo "[qr_watch] within cooldown; waiting"
            elif [ "$resubmits" -ge "$MAX_RESUBMITS" ]; then
                echo "[qr_watch $(_ts)] ABORT: resubmit budget ($MAX_RESUBMITS) exhausted. Manual intervention required."
                exit 1
            else
                # 1. capture forensics BEFORE deleting (failedData etc.)
                echo "[qr_watch] --- describe snapshot (pre-delete) ---"
                _fd="$(_describe)"
                echo "$_fd"
                echo "[qr_watch] --- end snapshot ---"
                if echo "$_fd" | grep -qi 'quota'; then
                    echo "[qr_watch $(_ts)] ABORT: failedData mentions quota -- resubmitting would loop forever. Manual intervention required."
                    exit 1
                fi
                # 2. delete the dead QR (same-name create fails until gone)
                gcloud compute tpus queued-resources delete "$QR_NAME" \
                    --zone="$ZONE" --project="$PROJECT_ID" --quiet --force || true
                for _i in $(seq 1 60); do
                    [ -z "$(_state)" ] && break
                    sleep 10
                done
                # 3. resubmit the identical launch
                if _resubmit; then
                    resubmits=$(( resubmits + 1 ))
                    last_action=$(date +%s)
                    echo "[qr_watch $(_ts)] resubmit #$resubmits accepted; back to watching"
                else
                    echo "[qr_watch $(_ts)] WARNING: resubmit FAILED (see above); will retry next poll"
                    last_action=$(date +%s)
                fi
            fi
            ;;
        DELETING)
            echo "[qr_watch $(_ts)] state=DELETING (operator or recovery in progress); waiting"
            ;;
        "")
            echo "[qr_watch $(_ts)] QR not found -- assuming OPERATOR deletion (coordinator-only relaunch rule). Exiting without resubmit."
            exit 0
            ;;
        *)
            echo "[qr_watch $(_ts)] state=$state (unrecognized; treating as ok)"
            ;;
    esac
    sleep "$POLL_SECONDS"
done
