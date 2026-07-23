#!/usr/bin/env bash
# venvs/vox — ALLEEN voor offline Voxtral-scoring (eval/score_voxtral.py --phase transcribe).
# Niet mengen met venvs/wlk (transformers-pin daar is heilig) of het toekomstige
# venvs/voxtral (gereserveerd voor de WLK voxtral-hf live-extra, zie CLAUDE.md).
# Pins geverifieerd beschikbaar op 2026-07-22 (pip index versions op deze machine).
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -x venvs/vox/bin/python ] && venvs/vox/bin/python -c "import transformers, mistral_common, librosa" 2>/dev/null; then
  echo "venvs/vox bestaat al en importeert — klaar"
  exit 0
fi

python3 -m venv venvs/vox
venvs/vox/bin/pip install --upgrade pip==25.2
# HARDE REGEL: torch alleen via de cu130-index (aarch64 + sm_121).
venvs/vox/bin/pip install --index-url https://download.pytorch.org/whl/cu130 torch==2.11.0
venvs/vox/bin/pip install \
  transformers==4.57.6 \
  "mistral-common[audio]==1.11.6" \
  accelerate==1.14.0 \
  soundfile==0.13.1 \
  librosa==0.11.0
# librosa is vereist door transformers' load_audio_as (geleerd 2026-07-22: ImportError
# pas bij de eerste transcriptie-aanroep, niet bij de modelload)

venvs/vox/bin/python - <<'EOF'
import torch, transformers, mistral_common
assert torch.cuda.is_available(), "CUDA niet beschikbaar in venvs/vox"
print("vox-venv OK: torch", torch.__version__, "cap", torch.cuda.get_device_capability(),
      "| transformers", transformers.__version__, "| mistral-common", mistral_common.__version__)
EOF
echo "VOX-VENV KLAAR"
