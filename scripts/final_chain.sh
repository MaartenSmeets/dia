#!/usr/bin/env bash
# Final chain, strictly sequential: word-level rescore of all M variants ->
# pyannote attribution (valid cpWER) -> extended summary eval retry (N=6).
set -uo pipefail
cd "$(dirname "$0")/.."
export HF_HOME=$PWD/data/hf
PY=venvs/wlk/bin/python
LOG=eval/results/mseries.log
say() { echo "=== $(date +%H:%M:%S) $*" | tee -a "$LOG"; }

memguard() {  # abort loudly if available memory is low (freeze prevention)
  avail=$(awk '/MemAvailable/{print int($2/1048576)}' /proc/meminfo)
  if [ "$avail" -lt 25 ]; then
    say "FINAL_CHAIN_DONE (ABORTED: only ${avail}GB available before $1)"
    exit 1
  fi
}

for pair in "M0hfw none" "M1w models/lora/M1-perm" "M2w models/lora/M2-cgn" "M3w models/lora/M3-both"; do
  set -- $pair
  for mani in cgn_a_dev ifadv_dev; do
    memguard "$1/$mani"
    say "WORDSCORE $1 on $mani"
    $PY scripts/score_lora.py --adapter "$2" --manifest "$mani" --tag "$1" 2>&1 | grep -E "SUMMARY|results ->" | tee -a "$LOG"
  done
done
for d in $(ls -d eval/results/*-lora-M*w-cgn_a_dev eval/results/*-lora-M*w-ifadv_dev 2>/dev/null); do
  say "ATTRIBUTE $d"
  venvs/eval/bin/python scripts/attribute_with_pyannote.py --from-run "$d" 2>&1 | grep -E "SUMMARY|results ->" | tee -a "$LOG"
done
say "SUMMARY-EVAL retry (N=6)"
$PY eval/summary_eval.py --manifest ifadv_dev --limit 6 \
  --live-run    eval/results/20260717-1416-wlk-stream-turbo-val-ifadv_dev \
  --offline-run eval/results/20260715-1805-whisper-longform-ifadv_dev \
  --offlineD-run eval/results/20260715-1912-whisper-longform+pyannote-ifadv_dev 2>&1 | grep -E "SUMMARY|results ->" | tee -a "$LOG"
say "FINAL_CHAIN_DONE"
