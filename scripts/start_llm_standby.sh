#!/usr/bin/env bash
# Wissel naar het standby-LLM: nvidia/Qwen3.6-27B-NVFP4 (dense, officieel) — stabieler
# decode-pad dan de 35B-A3B MoE op de GB10 marlin-FP4-fallback. Zelfde poort (8000) en
# zelfde served-model-name (qwen36) → de app hoeft NIETS te weten van de wissel.
# Terugdraaien: docker stop vllm-qwen36-dense && docker start vllm-qwen36-moe
set -euo pipefail

OLD="${OLD:-vllm-qwen36-moe}"
NAME="${NAME:-vllm-qwen36-dense}"
MODEL_DIR="${MODEL_DIR:-$HOME/models/Qwen3.6-27B-NVFP4}"
UTIL="${GPU_MEMORY_UTILIZATION:-0.40}"

[ -f "$MODEL_DIR/config.json" ] || { echo "FOUT: model niet (volledig) gedownload in $MODEL_DIR"; exit 1; }

if docker inspect "$OLD" >/dev/null 2>&1 && [ "$(docker inspect -f '{{.State.Running}}' "$OLD")" = "true" ]; then
  echo "Stop $OLD..."
  docker stop "$OLD" >/dev/null
fi

if docker inspect "$NAME" >/dev/null 2>&1; then
  docker start "$NAME"
else
  docker run -d --name "$NAME" \
    --gpus all --ipc=host \
    -p 127.0.0.1:8000:8000 \
    -v "$HOME/models:/models" \
    --restart unless-stopped \
    nvcr.io/nvidia/vllm:26.06-py3 \
    vllm serve "/models/$(basename "$MODEL_DIR")" \
      --served-model-name qwen36 \
      --quantization modelopt \
      --gpu-memory-utilization "$UTIL" \
      --max-model-len 32768 \
      --host 0.0.0.0 --port 8000
fi
echo "Wachten op endpoint (modelload duurt enkele minuten)..."
for i in $(seq 1 90); do
  curl -sf -m 3 http://localhost:8000/v1/models 2>/dev/null | grep -q '"id"' && { echo "STANDBY ACTIEF"; exit 0; }
  sleep 10
done
echo "endpoint niet opgekomen binnen 15 min — check: docker logs $NAME"
exit 1
