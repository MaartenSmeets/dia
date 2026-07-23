#!/usr/bin/env bash
# dia — één-commando-installatie van alle Python-omgevingen (uv, exact gepind).
#
#   scripts/setup.sh          # bouwt venvs/wlk + venvs/eval (kern; venvs/vox = optioneel)
#   scripts/setup.sh --all    # ook venvs/vox (alleen nodig voor de Voxtral-basisrace)
#
# Bron van waarheid: requirements/{wlk,eval,vox}.txt — bevroren uit de draaiende,
# geverifieerde omgevingen (as-built). HARDE REGEL (CLAUDE.md): torch komt uitsluitend
# van de cu130-index (aarch64 + GB10/sm_121); de +cu130-pins in de freeze-bestanden
# garanderen dat de juiste wheels gekozen worden.
set -euo pipefail
cd "$(dirname "$0")/.."

CU_INDEX="https://download.pytorch.org/whl/cu130"

if ! command -v uv >/dev/null 2>&1; then
  echo ">> uv niet gevonden — installeren (astral.sh)…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
echo ">> uv $(uv --version | awk '{print $2}')"

build() {
  local naam="$1"
  echo ">> venvs/$naam bouwen uit requirements/$naam.txt…"
  uv venv "venvs/$naam" --python 3.12 --allow-existing
  uv pip install --python "venvs/$naam/bin/python" \
    -r "requirements/$naam.txt" --extra-index-url "$CU_INDEX" --index-strategy unsafe-best-match
}

build wlk
build eval
if [ "${1:-}" = "--all" ]; then build vox; fi

echo ">> GPU-smoketest (venvs/wlk)…"
venvs/wlk/bin/python - <<'EOF'
import torch
assert torch.cuda.is_available(), "CUDA niet beschikbaar — controleer driver/wheels (cu130!)"
cap = torch.cuda.get_device_capability()
x = (torch.randn(256, 256, device="cuda") @ torch.randn(256, 256, device="cuda")).sum().item()
assert x == x, "GPU-matmul gaf NaN"
print(f"GPU OK: capability {cap}, matmul eindig")
EOF

echo
echo "Klaar. Vervolgstappen:"
echo "  1. kopieer .env.example naar .env en vul HF_TOKEN in (nodig voor het gated pyannote-model)"
echo "  2. scripts/run_app.sh   → http://localhost:8080 (HTTPS voor mobiel: :8443)"
