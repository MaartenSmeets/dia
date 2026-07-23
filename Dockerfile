# dia — containerimage voor de app (live ASR + diarization + verslagpijplijn).
# LET OP: vereist een NVIDIA-GPU-runtime (--gpus all) en aarch64 met CUDA 13-driver
# (ontwikkeld op DGX Spark GB10). Het LLM voor verslagen draait BUITEN deze container
# (eigen vLLM-container; koppelen via SUMMARIZER_URL of autodetectie op de host).
FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl build-essential \
    && rm -rf /var/lib/apt/lists/*
# build-essential: enkele pakketten (o.a. meeteval) hebben geen aarch64-wheel en
# compileren bij installatie hun eigen extensie
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /opt/dia
# eerst alleen de pins → docker-laagcache: codewijzigingen triggeren geen herinstallatie
COPY requirements/wlk.txt requirements/eval.txt requirements/
RUN uv venv /opt/dia/venvs/wlk --python 3.12 && \
    uv pip install --python /opt/dia/venvs/wlk/bin/python -r requirements/wlk.txt \
      --extra-index-url https://download.pytorch.org/whl/cu130 --index-strategy unsafe-best-match && \
    uv venv /opt/dia/venvs/eval --python 3.12 && \
    uv pip install --python /opt/dia/venvs/eval/bin/python -r requirements/eval.txt \
      --extra-index-url https://download.pytorch.org/whl/cu130 --index-strategy unsafe-best-match && \
    uv cache clean

COPY app/ app/
COPY scripts/ scripts/
COPY dialib/ dialib/
COPY eval/ eval/

ENV HF_HOME=/opt/dia/data/hf
EXPOSE 8080
CMD ["/opt/dia/venvs/wlk/bin/python", "app/server.py", "--port", "8080"]
