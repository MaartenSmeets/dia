#!/usr/bin/env bash
# Na de basisrace: samenvattings-herkansing (N=6) met VOLLEDIGE logging (les: geen grep-filter
# dat fouten opslokt), daarna schone E2E-run. Alles sequentieel, GPU-rustig.
set -uo pipefail
cd "$(dirname "$0")/.."
export HF_HOME=$PWD/data/hf
LOG=eval/results/mseries.log
say() { echo "=== $(date +%H:%M:%S) $*" | tee -a "$LOG"; }
until grep -q "OFFLINE-BAKEOFF DONE" "$LOG" 2>/dev/null; do sleep 60; done
say "SUMMARY-EVAL-RERUN start (volledige log: eval/results/summary_eval_rerun.log)"
venvs/wlk/bin/python eval/summary_eval.py --manifest ifadv_dev --limit 6 \
  --live-run    eval/results/20260717-1416-wlk-stream-turbo-val-ifadv_dev \
  --offline-run eval/results/20260715-1805-whisper-longform-ifadv_dev \
  --offlineD-run eval/results/20260715-1912-whisper-longform+pyannote-ifadv_dev \
  > eval/results/summary_eval_rerun.log 2>&1
rc=$?
say "SUMMARY-EVAL-RERUN klaar (exit $rc)"
say "E2E-RERUN start"
venvs/wlk/bin/python tests/test_app_e2e.py > eval/results/e2e_final.log 2>&1
say "E2E-RERUN klaar (exit $?; log eval/results/e2e_final.log)"
say "SUMMARY-EVAL-RERUN DONE"
