# CLAUDE.md — how to continue this project

This file is for any AI model (or human) continuing work here. Follow it strictly; the project was designed so a less capable model can execute the remaining steps.

## First actions in any new session

1. Read `docs/PROGRESS.md` — the single source of truth for current state and next steps.
2. Read `docs/PLAN.md` for where the current step fits.
3. Only consult `docs/RESEARCH.md` when you need the *why* or hit a decision RESEARCH already settled — do not re-research settled questions.

## Hard rules (violating these bricks or breaks the machine/project)

- **PyTorch:** ONLY `--index-url https://download.pytorch.org/whl/cu130` wheels (aarch64 + CUDA 13 + GB10/sm_121). NEVER cu126/cu128/cu129, NEVER `flash-attn`, NEVER `onnxruntime-gpu` from PyPI (no aarch64 wheels).
- **Memory:** 128 GB is *unified* (CPU+GPU). Over-allocating GPU memory can freeze the entire system, not just the process. Before loading a new large model: `free -h` and make sure no other big model is resident. One GPU-heavy process at a time.
  - **INCIDENT 2026-07-21:** the user's vLLM container (default `gpu_memory_utilization` ≈0.9 → ~109 GiB on unified memory) OOM-killed a running LoRA training + background shells. If vLLM must coexist with anything, the container needs `--gpu-memory-utilization` ≤ 0.40 (canonical rule: docs/OPS-LLM.md §Vuistregels); otherwise run strictly one-at-a-time (docker stop/start around training).
- **venvs are single-purpose, do not mix:**
  - `venvs/wlk` — live stack (WhisperLiveKit + Sortformer + torch 2.11 cu130). No transformers>=5 here.
  - `venvs/eval` — metrics + pyannote + datasets. Keep pyannote's torch pins intact.
  - `venvs/vox` — offline Voxtral-scoring only (`eval/score_voxtral.py`); never merge with `venvs/wlk`.
  - `venvs/voxtral` (WLK `voxtral-hf` live-extra) — route afgewezen na de gemeten basisrace (PLAN fase 5 / COMPARISON.md Update 4); mocht hij herleven: **declared incompatible** met de sortformer-extra, nooit mengen met `venvs/wlk`.
  - NeMo experiments — prefer docker `nvcr.io/nvidia/nemo:26.06` (arm64), not pip, unless PROGRESS.md says the pip path was verified.
- **Secrets:** `HF_TOKEN` lives in `.env` in the repo root (mode 600). Never print it, never commit it. Load with `set -a; source .env; set +a` or `python-dotenv`.
- **Never tune on the held-out IFADV test split** (dialogues listed in `eval/manifests/ifadv_test.json`; idem `cgn_a_test`/`cgn_tel_test`). Tuning happens on the dev split only.
- **Licenses:** offline `nvidia/diar_sortformer_4spk-v1` is CC-BY-NC (non-commercial) — do not add it. WhisperLiveKit ≤0.2.7 contained non-commercially-licensed SimulStreaming — never downgrade below 0.2.24 pin without checking `docs/RESEARCH.md` §3.

## Conventions

- **Docs are as-built:** `docs/SETUP.md` may only contain commands that were actually run successfully on this machine, with their key outputs. Anything speculative stays in RESEARCH.md marked UNVERIFIED.
- **Journal discipline:** after completing any meaningful step, add an entry to `docs/PROGRESS.md` — **newest entry FIRST (prepend, direct onder het actuele-stand-blok)**: date, what was done, what was verified (with the actual command/output), what's next. Convert relative dates to absolute. Houd het actuele-stand-blok bovenaan kloppend.
- **Canonical transcript format: SegLST** (meeteval JSONL: `session_id, speaker, start_time, end_time, words`). All converters emit it; RTTM only as derived interchange for diarization tools.
- **Every eval result** goes to `eval/results/<date>-<config-slug>/` with a `config.json` (model id+revision, WLK version, all flags, dataset manifest hash) so runs are reproducible and comparable.
- **Dutch text normalization** for WER lives in ONE place (`dialib/normalizer.py`), versioned, with tests. Never change it silently — old results become incomparable; if it must change, bump its version and re-run baselines.
- Pin every package version in setup scripts. `pip install <pkg>` without a version is forbidden in scripts.

## Machine facts (verified 2026-07-15)

DGX Spark: GB10 Grace Blackwell, aarch64, sm_121 (`torch.cuda.get_device_capability()` → `(12, 1)`; sm_120 binaries run on it), driver 580.159.03, CUDA 13.0, DGX OS (Ubuntu-based, kernel 6.17.0-1026-nvidia), Python 3.12.3, docker + ffmpeg + node24 present, ~500 GB free on `/`. `nvidia-smi` shows "Not Supported" for memory usage — expected on this platform; use `free -h` (unified memory).

## Where things run

- App (web-UI + engine in-proces): port **8080** (`scripts/run_app.sh`, `venvs/wlk`)
- HTTPS/TLS-proxy (mobiele microfoon): port **8443** (start automatisch mee met run_app.sh)
- Samenvattings-LLM (externe vLLM-container): port **8000** — runbook: `docs/OPS-LLM.md`
- Anything else: document the port here when you add it.

## Standing decision rules (verplaatst uit PLAN.md)

- Prefer the boring, verified path (RESEARCH-confirmed) over novel options mid-build; new-model tips go into a "later" list in PROGRESS.md.
- Any deviation from RESEARCH.md's recommendations must be recorded in PROGRESS.md with the evidence that forced it.
- If an install fails twice on aarch64, stop patching and use the documented fallback (usually the NGC container) — do not yak-shave source builds unless the plan says so.
- Bij elk nieuw Update-/addendumblok in een doc: de weersproken oudere passage direct dateren + doorverwijzen ("stand 2026-07-15; actueel: Update 3") — append-only mag nooit misleidend worden.
