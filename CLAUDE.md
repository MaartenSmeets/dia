# CLAUDE.md — how to continue this project

This file is for any AI model (or human) continuing work here. Follow it strictly; the project was designed so a less capable model can execute the remaining steps.

## First actions in any new session

1. Read `docs/PROGRESS.md` — the single source of truth for current state and next steps.
2. Read `docs/PLAN.md` for where the current step fits.
3. Only consult `docs/RESEARCH.md` when you need the *why* or hit a decision RESEARCH already settled — do not re-research settled questions.

## Hard rules (violating these bricks or breaks the machine/project)

- **PyTorch:** ONLY `--index-url https://download.pytorch.org/whl/cu130` wheels (aarch64 + CUDA 13 + GB10/sm_121). NEVER cu126/cu128/cu129, NEVER `flash-attn`, NEVER `onnxruntime-gpu` from PyPI (no aarch64 wheels).
- **Memory:** 128 GB is *unified* (CPU+GPU). Over-allocating GPU memory can freeze the entire system, not just the process. Before loading a new large model: `free -h` and make sure no other big model is resident. One GPU-heavy process at a time.
  - **INCIDENT 2026-07-21:** the user's vLLM container (default `gpu_memory_utilization` ≈0.9 → ~109 GiB on unified memory) OOM-killed a running LoRA training + background shells. If vLLM must coexist with anything, the container needs `--gpu-memory-utilization 0.3`-ish; otherwise run strictly one-at-a-time (docker stop/start around training).
- **venvs are single-purpose, do not mix:**
  - `venvs/wlk` — live stack (WhisperLiveKit + Sortformer + torch 2.11 cu130). No transformers>=5 here.
  - `venvs/eval` — metrics + pyannote + datasets. Keep pyannote's torch pins intact.
  - `venvs/voxtral` (future) — WLK `voxtral-hf` extra; **declared incompatible** with the sortformer extra; never merge with `venvs/wlk`.
  - NeMo experiments (future) — prefer docker `nvcr.io/nvidia/nemo:26.06` (arm64), not pip, unless PROGRESS.md says the pip path was verified.
- **Secrets:** `HF_TOKEN` lives in `/home/maarten/dia/.env` (mode 600). Never print it, never commit it. Load with `set -a; source .env; set +a` or `python-dotenv`.
- **Never tune on the held-out IFADV test split** (dialogues listed in `eval/manifests/ifadv_test.json` once created). Tuning happens on the dev split only.
- **Licenses:** offline `nvidia/diar_sortformer_4spk-v1` is CC-BY-NC (non-commercial) — do not add it. WhisperLiveKit ≤0.2.7 contained non-commercially-licensed SimulStreaming — never downgrade below 0.2.24 pin without checking `docs/RESEARCH.md` §3.

## Conventions

- **Docs are as-built:** `docs/SETUP.md` may only contain commands that were actually run successfully on this machine, with their key outputs. Anything speculative stays in RESEARCH.md marked UNVERIFIED.
- **Journal discipline:** after completing any meaningful step, append to `docs/PROGRESS.md`: date, what was done, what was verified (with the actual command/output), what's next. Convert relative dates to absolute (today is in the journal header of each entry).
- **Canonical transcript format: SegLST** (meeteval JSONL: `session_id, speaker, start_time, end_time, words`). All converters emit it; RTTM only as derived interchange for diarization tools.
- **Every eval result** goes to `eval/results/<date>-<config-slug>/` with a `config.json` (model id+revision, WLK version, all flags, dataset manifest hash) so runs are reproducible and comparable.
- **Dutch text normalization** for WER lives in ONE place (`eval/normalizer.py` once created), versioned, with tests. Never change it silently — old results become incomparable; if it must change, bump its version and re-run baselines.
- Pin every package version in setup scripts. `pip install <pkg>` without a version is forbidden in scripts.

## Machine facts (verified 2026-07-15)

DGX Spark "raika": GB10 Grace Blackwell, aarch64, sm_121 (`torch.cuda.get_device_capability()` → `(12, 1)`; sm_120 binaries run on it), driver 580.159.03, CUDA 13.0, DGX OS (Ubuntu-based, kernel 6.17.0-1026-nvidia), Python 3.12.3, docker + ffmpeg + node24 present, ~500 GB free on `/`. `nvidia-smi` shows "Not Supported" for memory usage — expected on this platform; use `free -h` (unified memory).

## Where things run

- WLK live server: port **8000** (`venvs/wlk`)
- Experiment web app: port **8080** (`app/`, uses `venvs/wlk`)
- Anything else: document the port here when you add it.
