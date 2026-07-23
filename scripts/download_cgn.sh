#!/usr/bin/env bash
# Download CGN_2.0.3.zip (93 GiB) from the INT-provided pCloud link, resumable.
# pCloud direct URLs expire -> re-resolve via the public API on every retry.
set -uo pipefail
cd "$(dirname "$0")/.."
# Persoonlijke leverlink: zet CGN_PCLOUD_CODE en CGN_PCLOUD_FILEID in .env
# (die krijg je van INT na ondertekening van de licentie; nooit committen).
set -a; source .env 2>/dev/null; set +a
CODE="${CGN_PCLOUD_CODE:?zet CGN_PCLOUD_CODE in .env (uit de INT-leverlink)}"
FILEID="${CGN_PCLOUD_FILEID:?zet CGN_PCLOUD_FILEID in .env}"
SIZE="${CGN_SIZE:-99648401751}"
TARGET=data/cgn/CGN_2.0.3.zip
mkdir -p data/cgn

while true; do
  have=$(stat -c%s "$TARGET" 2>/dev/null || echo 0)
  if [ "$have" -ge "$SIZE" ]; then echo "COMPLETE ($have bytes)"; break; fi
  echo "=== $(date +%H:%M:%S) have $have / $SIZE — resolving fresh link"
  url=$(curl -s "https://eapi.pcloud.com/getpublinkdownload?code=$CODE&fileid=$FILEID&forcedownload=1" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print('https://'+d['hosts'][0]+d['path']) if d.get('result')==0 else sys.exit('resolve failed: '+str(d))")
  [ -z "$url" ] && { echo "resolve failed, retry in 60s"; sleep 60; continue; }
  wget -c -q --show-progress --progress=dot:giga -O "$TARGET" "$url" && true
  sleep 5
done
echo "=== verifying zip listing"
unzip -l "$TARGET" > data/cgn/zip_contents.txt 2>&1 && echo "LISTING OK: $(wc -l < data/cgn/zip_contents.txt) lines" || echo "LISTING FAILED"
tail -3 data/cgn/zip_contents.txt
echo CGN_DOWNLOAD_DONE