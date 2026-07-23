#!/usr/bin/env bash
# Start the dia app: HTTP on :8080 (localhost) + HTTPS on :8443 (LAN/mobiel — microfoon
# vereist een secure context buiten localhost). Certs: scripts/make_cert.sh (auto indien nodig).
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a
export HF_HOME="${HF_HOME:-$PWD/data/hf}"
if [ ! -f certs/dia.crt ]; then bash scripts/make_cert.sh; fi
if ! pgrep -f "https_prox[y].py" > /dev/null; then
  setsid nohup venvs/wlk/bin/python scripts/https_proxy.py > eval/results/https_proxy.log 2>&1 < /dev/null &
fi
exec venvs/wlk/bin/python app/server.py "$@"
