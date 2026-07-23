#!/usr/bin/env bash
# Offline-motor-bake-off (draait NA de M-serie-keten): canary-1b-v2 en parakeet-tdt-0.6b-v3
# vs turbo/M2 op ifadv_dev + cgn_a_dev. Bepaalt de motor van de "definitieve versie"-pass.
set -uo pipefail
cd "$(dirname "$0")/.."
export HF_HOME=$PWD/data/hf
LOG=eval/results/mseries.log
say() { echo "=== $(date +%H:%M:%S) $*" | tee -a "$LOG"; }
until grep -q "FINAL_CHAIN_DONE" "$LOG" 2>/dev/null; do sleep 60; done
say "OFFLINE-BAKEOFF start (canary/parakeet)"
for m in "nvidia/canary-1b-v2 canary" "nvidia/parakeet-tdt-0.6b-v3 parakeet"; do
  set -- $m
  for mani in ifadv_dev cgn_a_dev; do
    say "NEMO-SCORE $2 op $mani"
    venvs/wlk/bin/python eval/score_nemo.py --model "$1" --manifest "$mani" --tag "$2" 2>&1 \
      | grep -E "SUMMARY|results ->|Error|error" | tee -a "$LOG"
  done
done
say "OFFLINE-BAKEOFF DONE"
