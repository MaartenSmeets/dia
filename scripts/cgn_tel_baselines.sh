#!/usr/bin/env bash
# Telefoon-baselines (taak #16, callcenter): M0hfw (kale turbo) en M2w (turbo+CGN-a-LoRA)
# woordniveau-gescoord op cgn_tel_dev (comp-c/d). Wacht eerst tot de Voxtral-basisrace de
# GPU vrijgeeft. VOLLEDIGE logs per stap (les 2026-07-22: nooit foutkanalen wegfilteren).
# Markers: CGN-TEL-SCORE <tag> / CGN-TEL-FOUT / CGN-TEL DONE.
set -uo pipefail
cd "$(dirname "$0")/.."
export HF_HOME=$PWD/data/hf
PY=venvs/wlk/bin/python

stamp() { date +%H:%M:%S; }
memguard() {
  avail=$(awk '/MemAvailable/{print int($2/1048576)}' /proc/meminfo)
  if [ "$avail" -lt 25 ]; then
    echo "=== $(stamp) CGN-TEL-FOUT: slechts ${avail}GB beschikbaar vóór $1 — stop"
    exit 1
  fi
}

echo "=== $(stamp) wachten op VOXTRAL-BAKEOFF DONE (GPU-volgorde)"
# LES 2026-07-23: eerst stond hier ook |VOX-FOUT als startconditie én wees dit naar de oude
# log met een historische VOX-FOUT-regel → keten drong voor en er draaiden 3 GPU-jobs
# tegelijk (16 GiB over). Alleen op expliciet DONE in de verse log starten; bij een
# Voxtral-fout beslist de operator zelf.
until grep -q "VOXTRAL-BAKEOFF DONE" eval/results/vox_bakeoff2.log 2>/dev/null; do sleep 60; done

for pair in "M0hfw none" "M2w models/lora/M2-cgn"; do
  set -- $pair
  memguard "$1"
  echo "=== $(stamp) CGN-TEL-SCORE $1 op cgn_tel_dev (log: eval/results/cgn_tel_$1.log)"
  $PY scripts/score_lora.py --adapter "$2" --manifest cgn_tel_dev --tag "$1" \
    > "eval/results/cgn_tel_$1.log" 2>&1 \
    || { echo "=== $(stamp) CGN-TEL-FOUT: $1 faalde — zie eval/results/cgn_tel_$1.log"; exit 1; }
  grep -E "SUMMARY:" "eval/results/cgn_tel_$1.log" | tail -1
done

echo "=== $(stamp) CGN-TEL DONE"
