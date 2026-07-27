#!/bin/bash
# Durable run watcher -- runs ON TPU host 0 in tmux, survives any workstation.
# Watches /tmp/train.log for completion AND errors; publishes status to GCS so
# any session (or a browser via the console) can check without SSH:
#   gs://$BUCKET/watch/$RUN_TAG-status.txt   (heartbeat, overwritten)
#   gs://$BUCKET/watch/$RUN_TAG-errors.txt   (appended on error)
# Stale-log guard: terminal/exit markers only count with a timestamp >= START_DAY
# (an append-mode log can still contain a previous leg's ending).
#
# BUCKET/RUN_TAG/START_DAY/TARGET_STEP are per-run and MUST be set for your own
# run; the defaults below are the v0.3 anneal leg's values, kept as a worked
# example. (That run's bucket was decommissioned after release.)
set -u
LOG=/tmp/train.log
BUCKET="${BUCKET:-tinyaya-stage2-eu}"
RUN_TAG="${RUN_TAG:-anneal-r2}"
STATUS="gs://${BUCKET}/watch/${RUN_TAG}-status.txt"
ERRFILE="gs://${BUCKET}/watch/${RUN_TAG}-errors.txt"
START_DAY="${START_DAY:-2026-07-20}"
TARGET_STEP="${TARGET_STEP:-76250}"
last_err_sig=""

publish () {  # $1 = state line
  {
    echo "state: $1"
    echo "updated: $(date -Is)"
    echo "last_step_line: $(tail -n 200 $LOG | grep -aE '^step +[0-9]+ \|' | tail -1)"
    echo "last_val_line: $(tail -n 400 $LOG | grep -a 'val/composite=' | tail -1)"
  } > /tmp/watch_status.txt
  gcloud storage cp -q /tmp/watch_status.txt "$STATUS" 2>/dev/null
}

while true; do
  # --- error detection (Traceback, FATAL, OOM, non-finite, kills) ---
  err=$(tail -n 80 $LOG | grep -aiE "Traceback|FATAL: |non-finite train loss|RESOURCE_EXHAUSTED|Killed|core dumped" | tail -3)
  if [ -n "$err" ] && [ "$err" != "$last_err_sig" ]; then
    last_err_sig="$err"
    { echo "=== ERROR detected $(date -Is) ==="; echo "$err";
      echo "--- 40-line context ---"; tail -n 40 $LOG; } > /tmp/watch_err.txt
    gcloud storage cp -q /tmp/watch_err.txt "$ERRFILE" 2>/dev/null
    publish "ERROR (see anneal-r2-errors.txt)"
  fi
  # --- completion detection (fresh markers only) ---
  done_marker=$(grep -a "canonical final save complete" $LOG | tail -1)
  exit_marker=$(grep -a "training exited" $LOG | grep -aE "$START_DAY|2026-07-2[1-9]" | tail -1)
  laststep=$(tail -n 200 $LOG | grep -aoE "^step +[0-9]+" | awk '{print $2}' | tail -1)
  if [ -n "$exit_marker" ]; then
    if [ -n "$laststep" ] && [ "$laststep" -ge $TARGET_STEP ]; then
      publish "DONE (reached $laststep; $exit_marker)"
    else
      publish "EXITED EARLY at step ${laststep:-?} ($exit_marker) -- investigate"
    fi
    exit 0
  fi
  # --- heartbeat ---
  # tmux 'train' gone but no exit marker = process died hard (host OOM/kill)
  if ! tmux has-session -t train 2>/dev/null; then
    publish "TRAIN TMUX GONE without exit marker at step ${laststep:-?} -- investigate"
    exit 0
  fi
  publish "RUNNING (step ${laststep:-?}/$TARGET_STEP)"
  sleep 120
done
