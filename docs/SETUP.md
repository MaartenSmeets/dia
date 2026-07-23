# SETUP.md — installatie (as-built)

## Snelle route (aanbevolen): uv + bevroren pins

```bash
scripts/setup.sh          # bouwt venvs/wlk + venvs/eval uit requirements/*.txt (uv, exact gepind)
scripts/setup.sh --all    # ook venvs/vox (alleen voor de Voxtral-basisrace nodig)
cp .env.example .env      # HF_TOKEN invullen (gated pyannote-model)
scripts/run_app.sh        # app op :8080 (+ HTTPS :8443 voor mobiel)
```

`requirements/{wlk,eval,vox}.txt` zijn bevroren uit de draaiende, geverifieerde omgevingen
(pip freeze, incl. de verplichte `+cu130`-torch-pins). Geverifieerd 2026-07-23: volledige
herbouw van venvs/vox via dit mechanisme → identieke omgeving, CUDA werkend; wlk/eval
lossen volledig op tegen dezelfde indexen. Alternatief: `docker compose up -d --build`
(zie Dockerfile; GPU-runtime vereist).

Machinefacts en harde platformregels (cu130-only wheels, unified memory): zie
[CLAUDE.md](../CLAUDE.md).

## Historisch: oorspronkelijke handmatige opbouw van venvs/wlk en venvs/eval

*(vervangen door de requirements-freeze hierboven; bewaard omdat de verificatie-output en
lessen nergens anders staan — Environment C en alles daaronder is gewoon actueel)*

### Environment A — live stack (`venvs/wlk`)

```bash
python3 -m venv venvs/wlk
venvs/wlk/bin/pip install --upgrade pip
venvs/wlk/bin/pip install torch==2.11.0 torchaudio==2.11.0 torchcodec==0.14.0 \
    --index-url https://download.pytorch.org/whl/cu130
# verified: torch 2.11.0+cu130, cuda_available=True, capability (12,1),
#           arch_list [sm_80..sm_120] (sm_121 absent is EXPECTED), GPU matmul OK

venvs/wlk/bin/pip install "whisperlivekit[diarization-sortformer]==0.2.24"
# verified: installs cleanly on aarch64/py3.12 — nemo-toolkit 2.7.3, transformers 4.57.6,
# faster-whisper 1.2.1 (ctranslate2 4.8.1 wheel is CPU-only -> we run --disable-fast-encoder),
# onnxruntime 1.27.0 (CPU), lightning 2.4.0, numpy 2.4.6

venvs/wlk/bin/pip install python-dotenv meeteval num2words openai-whisper
# meeteval 0.4.3 builds an aarch64 wheel from sdist successfully
# openai-whisper reuses the same ~/.cache/whisper/large-v3.pt as WLK's simulstreaming backend
```

### Environment B — metrics/offline reference (`venvs/eval`)

```bash
python3 -m venv venvs/eval
venvs/eval/bin/pip install --upgrade pip
venvs/eval/bin/pip install torch==2.11.0 torchaudio==2.11.0 torchcodec==0.14.0 \
    --index-url https://download.pytorch.org/whl/cu130
venvs/eval/bin/pip install "pyannote.audio==4.0.7" meeteval jiwer datasets soundfile praatio zenodo-get python-dotenv
# verified: pyannote.audio 4.0.7, meeteval 0.4.3, jiwer 4.0.0, datasets 5.0.0, torch cuda True
```

**pyannote gated model (user action, once):** log in on huggingface.co as the token's account, open
https://huggingface.co/pyannote/speaker-diarization-community-1 and accept the conditions ("gated: auto" → instant).
Until then `Pipeline.from_pretrained(...)` returns 403 (verified). Token lives in `.env` (`HF_TOKEN=`, mode 600).

## Environment C — Voxtral offline scoring (`venvs/vox`, as-built 2026-07-23)

Alleen voor `eval/score_voxtral.py --phase transcribe` (basisrace-kandidaat). Aangemaakt via
`scripts/setup_vox_venv.sh`; geverifieerd: torch 2.11.0+cu130 cap (12,1), transformers 4.57.6,
mistral-common 1.11.6, librosa 0.11.0.

```bash
bash scripts/setup_vox_venv.sh   # idempotent; pins staan in het script
```
- **Les:** `librosa` is een verplichte runtime-dep van transformers' `load_audio_as` maar
  faalt pas bij de EERSTE transcriptie-aanroep, niet bij modelload — hij zit daarom in de
  pinlijst én in de venv-herkenningscheck van het script.
- Niet verwarren met het (nog niet bestaande) `venvs/voxtral` voor de WLK `voxtral-hf`
  live-extra (CLAUDE.md); de score-fase draait in `venvs/wlk` (twee-fasen-ontwerp, zie
  docstring van eval/score_voxtral.py).

## Models (auto-downloaded on first use; pre-pull to avoid startup stalls)

```bash
set -a; source .env; set +a; export HF_HOME=$PWD/data/hf
venvs/wlk/bin/wlk pull large-v3                      # whisper large-v3
venvs/wlk/bin/python -c "from huggingface_hub import snapshot_download; \
print(snapshot_download('nvidia/diar_streaming_sortformer_4spk-v2'))"
# NOTE: the app server's engine ALSO loads openai-whisper's ~/.cache/whisper/large-v3.pt (2.88 GB);
# first engine start downloads it if missing. Engine load: ~13 min cold (download), ~20-60 s warm.
```

## Data

```bash
# IFADV downloaden: commando's en licentie staan canoniek in DATASETS.md §Priority 1
python3 scripts/ifadv_to_seglst.py   # na download: TextGrids -> SegLST/RTTM-referenties
# -> eval/references/ifadv/*.{seglst.json,rttm,words.json} (20 dialogues), manifests dev/test 10/10

# HF eval sets (FLEURS-nl full test 364 utts + MLS-nl test) — verified
set -a; source .env; set +a; export HF_HOME=$PWD/data/hf
venvs/eval/bin/python scripts/download_hf_datasets.py
# KNOWN ISSUE: CommonVoice (fsicoli/common_voice_22_0) fails on datasets 5.0
# ("Dataset scripts are no longer supported") — not blocking; retry via a parquet revision later.
```

## Run the app

```bash
scripts/run_app.sh    # alles-in-één: HTTP :8080 + HTTPS :8443 (cert wordt zo nodig gemaakt)
```

## Run evaluations

```bash
venvs/wlk/bin/python eval/run_eval.py --method wlk-stream --manifest ifadv_dev
# volledige methode- en manifestlijst + alle meetcommando's: EVALUATION.md §How to run
```

## Verified quirks (save yourself the debugging)

- `wlk` CLI language flag is `--lan`, **not** `--language`.
- `AudioProcessor.is_pcm_input` must be set **before** `create_tasks()` — after that the ffmpeg
  input path is already started and raw PCM input hangs with "FFmpeg read timeout".
- WLK clients must wait for `ready_to_stop` — our server sends it when the results generator
  is exhausted (after end-of-stream `b""`), while the socket is still open.
- `nvidia-smi` shows "Not Supported" for memory on GB10 — use `free -h` (unified memory).
- Background pkill patterns: quote like `"serve[r].py"` or you kill your own shell command.
