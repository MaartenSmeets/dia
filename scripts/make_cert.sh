#!/usr/bin/env bash
# Self-signed TLS cert so browsers on the LAN allow microphone access (getUserMedia
# requires a secure context off-localhost). Browsers will show a warning once — accept it.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p certs
IPS=$(hostname -I)
SAN="DNS:$(hostname),DNS:localhost,IP:127.0.0.1"
for ip in $IPS; do SAN="$SAN,IP:$ip"; done
openssl req -x509 -newkey rsa:2048 -sha256 -days 825 -nodes \
  -keyout certs/dia.key -out certs/dia.crt \
  -subj "/CN=dia.local" \
  -addext "subjectAltName=${SAN}"
echo "cert written to certs/dia.crt (SAN: ${SAN})"
echo "HTTPS runs on port 8443 via scripts/https_proxy.py (started by run_app.sh)"
