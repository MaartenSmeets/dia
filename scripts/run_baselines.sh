#!/usr/bin/env bash
# Sequential baseline/comparison queue (GPU jobs must not overlap — unified memory).
# Prereq: app server running with the day-1 config (large-v3 + sortformer + lan nl).
set -uo pipefail
cd "$(dirname "$0")/.."
PY=venvs/wlk/bin/python
LOG=eval/results/baseline_queue.log
run() { echo "=== $(date +%H:%M:%S) $*" | tee -a "$LOG"; $PY eval/run_eval.py "$@" 2>&1 | grep -v "^WARNING" | tee -a "$LOG"; }

run --method wlk-fast         --manifest fleurs_nl --limit 50
run --method whisper-longform --manifest fleurs_nl --limit 50
run --method wlk-stream       --manifest fleurs_nl --limit 25
run --method wlk-fast         --manifest ifadv_dev
run --method whisper-longform --manifest ifadv_dev
run --method wlk-stream       --manifest ifadv_dev --limit 2
echo "=== $(date +%H:%M:%S) QUEUE DONE" | tee -a "$LOG"
