#!/usr/bin/env bash
# Voxtral-Mini-3B offline meten op ifadv_dev + cgn_a_dev (laatste kandidaat basisrace, taak #13).
# Draait detached; log via de aanroeper. Markers: VOX-SETUP / VOX-TRANSCRIBE / VOX-SCORE / VOXTRAL-BAKEOFF DONE / VOX-FOUT.
set -uo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a

stamp() { date +%H:%M:%S; }
memguard() {  # >= 20 GiB beschikbaar vereist vóór modelload (unified memory, CLAUDE.md)
  avail_gb=$(free -g | awk '/^Mem:/{print $7}')
  if [ "$avail_gb" -lt 20 ]; then
    echo "=== $(stamp) VOX-FOUT: slechts ${avail_gb}G beschikbaar (<20G) — stop voor systeemveiligheid"
    exit 1
  fi
}

echo "=== $(stamp) VOX-SETUP venv"
bash scripts/setup_vox_venv.sh || { echo "=== $(stamp) VOX-FOUT: venv-setup faalde"; exit 1; }

echo "=== $(stamp) VOX-SETUP modeldownload (mistralai/Voxtral-Mini-3B-2507)"
venvs/vox/bin/python - <<'EOF' || { echo "=== $(date +%H:%M:%S) VOX-FOUT: download faalde"; exit 1; }
from huggingface_hub import snapshot_download
p = snapshot_download("mistralai/Voxtral-Mini-3B-2507")
print("model in cache:", p)
EOF

D=$(date -u +%Y%m%d-%H%M)
for MAN in ifadv_dev cgn_a_dev; do
  # hervat een bestaande run-map als die er is (per-item skip-logica in score_voxtral.py)
  OUT=$(ls -d eval/results/*-voxtral-${MAN} 2>/dev/null | tail -1)
  [ -n "$OUT" ] || OUT="eval/results/${D}-voxtral-${MAN}"
  memguard
  echo "=== $(stamp) VOX-TRANSCRIBE ${MAN} -> ${OUT}"
  # --max-single-s 0 = altijd 30s-vensters: zelfde methodologie als de NeMo-rijen
  # (eerlijke modelvergelijking); heel-bestand-modus blijft beschikbaar voor een naexperiment.
  venvs/vox/bin/python eval/score_voxtral.py --phase transcribe --manifest "$MAN" --out-dir "$OUT" \
    --max-single-s 0 \
    || { echo "=== $(stamp) VOX-FOUT: transcribe ${MAN} faalde"; exit 1; }
  echo "=== $(stamp) VOX-SCORE ${MAN}"
  venvs/wlk/bin/python eval/score_voxtral.py --phase score --manifest "$MAN" --out-dir "$OUT" \
    || { echo "=== $(stamp) VOX-FOUT: score ${MAN} faalde"; exit 1; }
done

echo "=== $(stamp) VOXTRAL-BAKEOFF DONE"
