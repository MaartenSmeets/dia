#!/usr/bin/env bash
# M-series orchestrator (CGN-VALUE.md): anchor + train/score M2, M1, M3 sequentially.
# STEPS is set from the bring-up timing. Log: eval/results/mseries.log
set -uo pipefail
cd "$(dirname "$0")/.."
PY=venvs/wlk/bin/python
STEPS="${STEPS:-1200}"
LOG=eval/results/mseries.log
say() { echo "=== $(date +%H:%M:%S) $*" | tee -a "$LOG"; }

train() { # name, data args...
  local name="$1"; shift
  say "TRAIN $name (steps=$STEPS)"
  $PY scripts/train_lora.py "$@" --out "models/lora/$name" --steps "$STEPS" 2>&1 \
    | tee -a "eval/results/train_$name.out" | grep -E "TRAIN_DONE|trainable|dataset:" | tee -a "$LOG"
}
score() { # tag, adapter
  for mani in cgn_a_dev ifadv_dev; do
    say "SCORE $1 on $mani"
    $PY scripts/score_lora.py --adapter "$2" --manifest "$mani" --tag "$1" 2>&1 \
      | grep -E "SUMMARY|results ->" | tee -a "$LOG"
  done
}

say "M-SERIES START (STEPS=$STEPS)"
score M0hf none
train M2-cgn  --data data/ft/cgn_a_train.jsonl
score M2 models/lora/M2-cgn
train M1-perm --data data/ft/mls_train.jsonl --data data/ft/cv_train.jsonl
score M1 models/lora/M1-perm
train M3-both --data data/ft/cgn_a_train.jsonl --data data/ft/mls_train.jsonl
score M3 models/lora/M3-both
say "M-SERIES DONE"
