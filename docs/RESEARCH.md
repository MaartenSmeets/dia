# RESEARCH.md — Fully-local realtime Dutch transcription + speaker diarization on NVIDIA DGX Spark

**Status:** definitive research synthesis, verified against primary sources on 2026-07-15.
**Target machine:** DGX Spark (GB10 Grace Blackwell, aarch64/SBSA, sm_121, CUDA 13.0 toolkit, driver 580.159.03, 128 GB unified LPDDR5x @ ~273 GB/s, Python 3.12.3, Ubuntu-based DGX OS, docker + ffmpeg installed, ~500 GB free disk).
**Convention used throughout:** claims below are verified against primary sources unless marked **UNVERIFIED — test on machine**. Nothing marked REFUTED in verification is presented as fact.

> **ON-MACHINE VERIFICATION ADDENDUM (2026-07-15, end of day 1)** — the following UNVERIFIED items are now RESOLVED (details: PROGRESS.md, results: COMPARISON.md):
> - **R1 ✓** torch 2.11.0+cu130 aarch64 wheels run on GB10 (capability (12,1), sm_120 kernels).
> - **R2 ✓** `whisperlivekit[diarization-sortformer]==0.2.24` pip-installs natively on aarch64/py3.12 (nemo-toolkit 2.7.3); NGC container not needed for the live stack.
> - **R7 ✓(corrected)** `wlk` is a multi-command CLI; the language flag is **`--lan`**, not `--language`. Other flags as documented.
> - **R3 (measured, ongoing)** Streaming Sortformer on Dutch: healthy runs DER 12–18% per dialogue (pooled 26.9% fast mode), but **one realtime run collapsed to near-single-speaker** — stability sweep is the top live-quality experiment. Offline pyannote community-1 pooled DER 21.4% on IFADV-dev.
> - **R10 ✓** IFADV TextGrid conversion validated (channel-VAD magnitudes consistent; crosstalk makes exact channel mapping fuzzy — irrelevant for permutation-invariant metrics).
> - **R11 (measured)** Streaming-vs-offline gap for whisper large-v3 Dutch: FLEURS 22.2% vs 7.3% WER (short clips = worst case); IFADV conversations 35.0% vs 30.1% WER. Plus a new finding: **unpaced feeding degrades long-audio ASR badly** (49.3%) — see COMPARISON.md finding 2.
> - **§4 Step 0.2 note:** swap was NOT disabled (system default kept); no memory pressure observed at ~27 GiB peak usage. Revisit only if larger models are co-resident.

> **ADDENDUM 2 (2026-07-23, basisrace afgerond)** — resterende bake-off-onzekerheden gemeten
> (tabellen: COMPARISON.md Update 4):
> - **R3 ✓(afgesloten)** Sortformer-stabiliteit: 1 collapse in ~16 realtime runs (dag-1);
>   sweep 8/8 schoon → v2 definitief; escalatieregel nooit getriggerd.
> - **R4/§7 canary ✓(gemeten, verliest)** canary-1b-v2 offline: 31,5% (ifadv_dev) / 43,5%
>   (cgn_a_dev) pooled WER — de FLEURS-belofte (6,12%) draagt NIET over naar spontaan NL;
>   M2 (turbo+CGN-LoRA) wint met 6–12 punten. "Offline accuracy ceiling"-hypothese REFUTED
>   voor conversationeel Nederlands.
> - **R5 (bewust onbeslist gelaten)** Voxtral-Mini-4B-Realtime niet gemeten: offline-broer
>   Voxtral-Mini-3B verliest al ruim (32,1/40,7) én de voxtral-extra is venv-incompatibel
>   met de Sortformer-stack — verwachtingswaarde te laag (rationale COMPARISON.md Update 4).
> - **parakeet ✓(gemeten, verliest)** 28,8/43,2 pooled WER offline — zelfde les als canary.
> - **Nieuwe systeemles (OPS-LLM.md):** vLLM-prefix-caching op hybride Mamba-modellen
>   (Qwen3.6) corrumpeert deterministisch → altijd uit op deze machine.

---

## 1. Executive summary

We will build a fully-local web application for realtime (streaming, partial-results-while-speaking) transcription of **Dutch** audio with live **speaker diarization**, plus an offline evaluation harness (WER / DER / speaker-attributed WER) on downloadable Dutch reference data, so we can iterate on accuracy.

The core decision: **do not build the streaming pipeline from scratch — use WhisperLiveKit (WLK) as the engine**. WLK (Apache-2.0, v0.2.24 released 2026-07-11, 10.5k stars) is the only mature open-source project that already combines: streaming ASR with partial hypotheses (SimulStreaming/AlignAtt policy over Whisper models, plus a natively-streaming Voxtral backend), **streaming speaker diarization** (NVIDIA Streaming Sortformer, default), word→speaker attribution, a WebSocket protocol with incremental results, a bundled browser UI, and a WER/latency benchmark CLI. Its entire dependency chain is permissive (the historical SimulStreaming non-commercial license was replaced by MIT on 2025-10-22).

Concretely:

- **Live path (day 1):** WLK server on the Spark → Whisper `large-v3` with `--language nl`, SimulStreaming policy, pure-PyTorch GPU inference (official `cu130` aarch64 PyTorch wheels run on sm_121 via sm_120 binary compatibility) → Streaming Sortformer diarization at the ~1 s latency preset → bundled web UI, later a thin custom UI for experiments.
- **Accuracy upgrade path:** pilot `mistralai/Voxtral-Mini-4B-Realtime-2602` (Apache-2.0, natively streaming at 80–1200 ms delays, Dutch FLEURS WER 7.07 % @ 480 ms) — in a *separate venv* because WLK declares its `voxtral-hf` extra incompatible with the Sortformer extra. Benchmark NVIDIA `parakeet-tdt-0.6b-v3` (Dutch FLEURS 7.48 %, ~283× realtime confirmed on this exact hardware) and `canary-1b-v2` (best open Dutch WER: 6.12 % FLEURS) via the NeMo container as engine candidates / offline references.
- **Evaluation:** download **IFADV** (5 h of real Dutch two-person conversations, per-speaker transcripts, speakers on separate stereo channels → exact reference diarization) today from Zenodo; MLS-Dutch / FLEURS-nl / Common Voice-nl for clean WER; start the **CGN** license request immediately (weeks of lead time, ~99.5 h of Dutch multi-speaker conversation). Metrics via **meeteval** (cpWER *and* DER — meeteval now wraps md-eval for DER) + jiwer.

The biggest empirical unknowns (all testable on-machine within days): Sortformer's DER penalty on Dutch (it is English-trained), the real latency/accuracy curve of each ASR engine under streaming, and pip-installability of the NeMo stack natively on aarch64 (the NGC arm64 container is the guaranteed fallback).

---

## 2. Recommended stack (primary + fallback per layer)

### 2.1 Streaming ASR model + engine for Dutch

| Role | Choice | Why on THIS machine |
|---|---|---|
| **Primary (integrated, day 1)** | **OpenAI Whisper `large-v3`** (MIT) served by **WhisperLiveKit's SimulStreaming (AlignAtt) policy**, pure PyTorch on GPU, `--language nl` | Works with official `torch` cu130 aarch64 wheels (sm_121 runs sm_120 binaries — confirmed by PyTorch maintainer ptrblck, Jan 2026). No CTranslate2 needed (whose PyPI aarch64 wheels are CPU-only — verified: built without `-DWITH_CUDA`). SimulStreaming was the best-performing system at IWSLT 2025 simultaneous shared task and is MIT since 2025-10-22. 3 GB fp16 model is trivial in 128 GB unified memory. Use `--disable-fast-encoder` so WLK does not try the faster-whisper/CT2 encoder path. `large-v3-turbo` (809M) is the latency-optimized variant to sweep. |
| **Primary upgrade (pilot in week 2)** | **`mistralai/Voxtral-Mini-4B-Realtime-2602`** (Apache-2.0, Feb 2026) via WLK `--backend voxtral` (HF transformers ≥5.2.0) | The only *architecturally* streaming open model with Dutch: configurable delay = any multiple of 80 ms in 80–1200 ms, plus a standalone 2400 ms value (note: discrete set, not a continuum). Dutch FLEURS WER 7.07 % at 480 ms — better than Whisper large-v3. ~4 B params (≥16 GB memory) — fine here. Constraint: WLK declares `voxtral-hf` and `diarization-sortformer` **intentionally incompatible extras** (transformers 5.2 vs NeMo's ~4.57 pin) → separate venv; live Sortformer diarization is not available in the same process (see §8, R6). vLLM serving is now viable on Spark (official vLLM blog validated `vllm/vllm-openai:cu130-nightly` on GB10, 2026-06-01) — the older "needs custom build" advice is outdated. |
| **Fallback / speed champion** | **`nvidia/parakeet-tdt-0.6b-v3`** (CC-BY-4.0, 600M) via NeMo | Confirmed running on DGX Spark GB10 at ~282.9× RTFx (NVIDIA forum + coder543/stt-bench-matrix; NGC PyTorch 25.10 container — avoid 25.12+/PyTorch 2.10 Sampler API breakage with older NeMo). Dutch: 7.48 % FLEURS / 12.78 % MLS. **Important correction:** it is *not* cache-aware streaming — the model card's streaming path is NeMo's *chunked/buffered* inference script (`speech_to_text_streaming_infer_rnnt.py`, defaults `chunk_secs=2, right_context_secs=2.0, left_context_secs=10.0` → ~4 s algorithmic latency before finalization; tunable down at an accuracy cost — **UNVERIFIED — test on machine**). Not a WLK backend → needs custom serving glue; use first in the offline eval harness, promote to live engine only if it wins the latency/WER trade-off. |
| **Offline accuracy ceiling (eval only)** | **`nvidia/canary-1b-v2`** (CC-BY-4.0, 978M) | Best open Dutch numbers found anywhere: **6.12 % FLEURS-nl / 11.27 % MLS-nl**, 749 RTFx. Offline attention encoder-decoder — no native streaming (long-form via chunking). Use as the accuracy reference every streaming config is measured against. |
| **Rejected** | Kyutai STT (no Dutch — EN/FR + EN-only models only, confirmed against live HF org listing 2026-07-15); faster-whisper GPU as primary (CT2 aarch64 wheels CPU-only; CUDA 13 support still an open request, OpenNMT/CTranslate2#1933; source build with arch `120;121` is a proven workaround, not a default); Qwen3-ASR as primary (Dutch supported but **no published Dutch WER** — pilot only; timestamps require the separate `Qwen3-ForcedAligner-0.6B`); Dutch Whisper fine-tune `yuriyvnv/whisper-large-v3-high-mixed-nl` (4.43 % on CV17-nl but **20.29 % on MLS-nl** — hard evidence of read-speech overfitting); `Jaspernl/whisper-large-v3-ft-nl` (HTTP 401 — private/inaccessible). |

### 2.2 Streaming diarization

| Role | Choice | Why |
|---|---|---|
| **Primary** | **`nvidia/diar_streaming_sortformer_4spk-v2`** (CC-BY-4.0, ungated, 117M) via NeMo, at the **1.04 s latency preset** — WLK's default diarization backend | Best published *online* DER: 13.24 % DIHARD III ≤4-spk @ 1.04 s input-buffer latency (model-card table: 13.45/13.75/13.24/13.44 % at 30.4/10/1.04/0.32 s; CALLHOME-part2 *Full* DER 9.54–11.38 %). RTF 0.002–0.180 on RTX 6000 Ada — far below realtime. Hard limits: **max 4 speakers**; trained **primarily on English** — the card explicitly warns of degradation on non-English speech, so **Dutch DER must be measured, not assumed** (§8, R3). Consider `-v2.1` (better meeting-domain DER claimed — plausible but not independently verified) — note its license is the **NVIDIA Open Model License**, not CC-BY; review before commercial use. Avoid the *offline* `diar_sortformer_4spk-v1`: **CC-BY-NC-4.0 (non-commercial)**. |
| **Fallback (>4 speakers)** | **diart 0.9.2** (MIT) — WLK `--diarization-backend diart` | Unbounded speaker count, 0.5–5 s latency, language-independent (pyannote multilingual models). Downsides: older accuracy (~28–30 % DER DIHARD III per its paper), gated pyannote HF models (accept conditions + token), and WLK's `diarization-diart` extra pins **torch<2.9** — which conflicts with the cu130/sm_121 torch this machine needs → expect CPU-only diart or a manual pin override (**UNVERIFIED — test on machine**). |
| **Offline reference (eval loop)** | **`pyannote/speaker-diarization-community-1`** (CC-BY-4.0, gated "auto") on pyannote.audio 4.0.7 (MIT) | Best open offline pipeline (DER: DIHARD-3 20.2 %, AMI-IHM 17.0 %, VoxConverse 11.2 %; multilingual-proven). Its "exclusive" (non-overlapping) output mode makes word↔speaker alignment unambiguous. No open-source streaming mode (streaming is pyannoteAI's paid cloud only). Optional second reference: DiariZen (MIT, offline SOTA-ish). |
| **Rejected** | sherpa-onnx (diarization is offline-only — `OnlineSpeakerDiarization` does not exist in the codebase); senko (batch-only); FS-EEND/LS-EEND (no license file, no turnkey checkpoints — research code). |

### 2.3 VAD

- **Primary: Silero VAD v6 (6.2.1, 2026-02-24, MIT)** — already bundled and wired into WLK (gates inference during silence). Pure-Python wheel; runs on CPU via torch or ONNX (official CPU `onnxruntime` 1.27.0 has cp312 aarch64 wheels — GPU ONNX unnecessary for VAD).
- **Fallback: `webrtcvad-wheels` 2.0.14** (cp312 aarch64 wheels; the original `webrtcvad` 2.0.10 is sdist-only from 2017).

### 2.4 Word-to-speaker attribution

- **Primary: WLK's built-in alignment** (`whisperlivekit/tokens_alignment.py`, verified in source): groups ASR tokens into punctuation/silence-delimited segments, merges consecutive same-speaker diarization segments, assigns each group the speaker with **maximum temporal overlap** (`intersection_duration` argmax), and **buffers unlabeled tokens when diarization lags ASR** (back-fills speaker labels at the live edge). This is the dominant, production-proven approach.
- **Fallback / offline refinement:** pyannote community-1 **exclusive diarization** output → word assignment becomes a direct lookup; use for the offline reference transcripts and for scoring speaker-attributed WER.

### 2.5 Serving / web layer

- **Primary: WhisperLiveKit server** (FastAPI + WebSocket `/asr` with documented JSON incremental protocol: `lines` with speaker/text/start/end, `buffer_transcription`, `buffer_diarization`, lag metrics; optional `?mode=diff` snapshot/diff protocol; per-session `?language=nl`), plus its **OpenAI-compatible REST** (`POST /v1/audio/transcriptions`) and **Deepgram-compatible WS** (`/v1/listen`) endpoints — wrapped in a thin custom FastAPI app (§3).
- **Fallback:** WLK bundled UI as-is (vanilla HTML/JS, no build toolchain, trivially forkable), or Collabora WhisperLive (MIT, v0.9.0) as an alternative engine — weaker diarization (embedding + cosine clustering), no web UI, CT2-on-GB10 friction.

---

## 3. Web interface: adapt vs. build

**Verdict: ADAPT — option (b): use WhisperLiveKit as the engine behind a thin custom FastAPI app + forked UI.** Do not adopt wholesale, do not build from scratch.

- **Why not build from scratch:** the failure-prone 20 % is exactly what WLK has refined over 31 releases: AlignAtt incremental decoding with context retention, LocalAgreement commit logic, VAD gating, FFmpeg/PCM ingestion, diarization-token alignment, multi-session engine sharing, documented WS protocol. Rebuilding = reproducing WLK minus its bug fixes.
- **Why not adopt as-is:** the bundled UI is a demo page — no reference-transcript loading, no side-by-side alignment/correction, no per-speaker WER/DER dashboards, no A/B config comparison. `wlk bench` measures WER/RTF/latency but **no DER**, and its Dutch catalog entry (MLS "dutch") has only 1 sample.
- **Plan:** pin `whisperlivekit==0.2.24`; embed via its public Python API (`TranscriptionEngine` + `AudioProcessor`; `whisperlivekit/basic_server.py` is the ~30-line template); build a small FastAPI app that adds: eval-dataset player (stream WAVs through the same WebSocket path at realtime pace), reference alignment view, per-speaker WER + DER panels, config A/B. Fork `whisperlivekit/web/live_transcription.html/.js` as the UI starting point. UX references for the correction screen: OpenTranscribe, Scriberr.
- **Alternatives surveyed and rejected:** WhisperLive (no web UI, basic diarization), RealtimeSTT (no diarization at all — confirmed), speaches (**has** pyannote diarization since 2025-12-01, but batch REST, not streaming-fused — still rejected), Vibe/Hyprnote (desktop apps), Scriberr/Speakr/OpenTranscribe/TranscriptionStream (batch upload), Vexa (meeting-bot infra), Kyutai (no Dutch). Note: "no other project combines all three" is a negative claim — unrefuted by targeted searches, but formally UNCERTAIN.

**License notes (all verified 2026-07-15):**
- WLK: **Apache-2.0** (LICENSE file + GitHub; note the PyPI classifier still incorrectly says "MIT" — the LICENSE file governs; flag in any compliance review).
- SimulStreaming (vendored in WLK): **MIT since 2025-10-22** ("MIT License, Copyright (c) 2025 Charles University"). The PolyForm-Noncommercial license applies only to checkouts at/before the `nc` release tag (2025-10-22) — **never use pre-Oct-2025 SimulStreaming or WLK ≤0.2.7** for commercial work.
- Commercial-safe: Whisper weights (MIT), Voxtral Realtime (Apache-2.0), parakeet/canary (CC-BY-4.0, attribution), Sortformer v2 (CC-BY-4.0, ungated), NeMo (Apache-2.0), Silero VAD (MIT), diart (MIT), pyannote.audio lib (MIT).
- **Watch-list:** Sortformer **v2.1** = NVIDIA Open Model License (review terms); offline Sortformer **v1** = CC-BY-NC-4.0 (do not use commercially); pyannote models CC-BY-4.0/MIT but **HF-gated** (account + accepted conditions + token); IFADV corpus = AGPL-3.0-or-later (fine for internal eval; check before redistributing derivatives); Rev reverb-diarization (in sherpa-onnx docs) = non-commercial — irrelevant since sherpa-onnx is rejected.

---

## 4. Install plan (exact commands)

> Run in order. Everything is pinned. Steps marked **[UNVERIFIED]** must be validated on-machine (see §8 for the matching test). Directory layout: `~/venvs/*` for Python envs, `~/data` for corpora, `~/src` for source builds.

### Step 0 — System prep

```bash
# 0.1 Sanity (already-verified facts; just confirm nothing changed)
nvidia-smi                        # driver 580.159.03; Memory-Usage column reads "Not Supported" on this platform — expected
python3 --version                 # 3.12.3
docker --version && ffmpeg -version | head -1

# 0.2 Unified-memory safety: on this machine GPU over-allocation causes a system-wide
# freeze ("swap death spiral"), not a clean CUDA OOM. Disabling swap converts
# "brick the box" into "job dies, OS lives".  [Community-verified mitigation — decide consciously]
sudo swapoff -a

# 0.3 Workspace
mkdir -p ~/venvs ~/data ~/src
```

### Step 1 — Environment A: main live stack (WLK + Whisper/SimulStreaming + Sortformer)

```bash
python3 -m venv ~/venvs/wlk && source ~/venvs/wlk/bin/activate
pip install --upgrade pip

# 1.1 PyTorch stack — official CUDA-13 aarch64 wheels.
# Pin 2.11.0: torchaudio's cu130 aarch64 wheels top out at 2.11.0 (torchaudio is in
# maintenance mode), and pyannote.audio 4.0.7 needs torch>=2.8/torchaudio>=2.8/torchcodec>=0.7.
pip install torch==2.11.0 torchaudio==2.11.0 torchcodec==0.14.0 \
    --index-url https://download.pytorch.org/whl/cu130

# 1.2 GPU smoke test  [UNVERIFIED — run this first, §8 R1]
python -c "import torch; print(torch.__version__, torch.cuda.is_available(), \
torch.cuda.get_arch_list(), torch.cuda.get_device_capability()); \
import torch as t; x=t.randn(1024,1024,device='cuda'); print((x@x).sum().item())"
# Expect: is_available=True, 'sm_120' in arch list (sm_121 not listed — that is fine),
# capability (12, 1), and a finite matmul result.

# 1.3 WhisperLiveKit + Sortformer diarization extra
# (pulls nemo-toolkit[asr]>2.4 → resolves to nemo_toolkit 2.7.3, pure-Python wheel;
#  extra requires Python <3.13 — OK on 3.12.3)
pip install "whisperlivekit[diarization-sortformer]==0.2.24"   # [UNVERIFIED — aarch64 transitive-dep resolution of nemo_toolkit[asr], §8 R2]

# 1.4 Launch the live server (downloads whisper large-v3 + Sortformer v2 on first run)
wlk --model large-v3 --language nl \
    --diarization --diarization-backend sortformer \
    --disable-fast-encoder \
    --host 0.0.0.0 --port 8000
# --backend-policy simulstreaming is the default; 'simulstreaming' is a POLICY, not a --backend value.
# --disable-fast-encoder: avoid the faster-whisper/CT2 encoder path (CPU-only CT2 wheels on aarch64).
# Verify exact flag names with `wlk --help` before scripting.  [UNVERIFIED — flag spellings, §8 R7]
# Open http://<spark-ip>:8000 in a browser → speak Dutch → partial results + speaker colors.
```

### Step 2 — Environment B: Voxtral realtime pilot (separate venv — extras conflict)

```bash
python3 -m venv ~/venvs/voxtral && source ~/venvs/voxtral/bin/activate
pip install --upgrade pip
pip install torch==2.13.0 --index-url https://download.pytorch.org/whl/cu130
pip install "whisperlivekit[voxtral-hf]==0.2.24"    # transformers>=5.2 + mistral-common[audio]
# NOTE: voxtral-hf × diarization-sortformer are DECLARED-INCOMPATIBLE extras (transformers pin clash).
# This env serves ASR only; see §8 R6 for the diarization-sidecar question.
wlk --backend voxtral --language nl --host 0.0.0.0 --port 8001   # [UNVERIFIED — Voxtral throughput/memory on GB10 via transformers, §8 R5]
```

Optional higher-throughput Voxtral serving via vLLM (validated on Spark by the official vLLM blog, 2026-06-01 — no custom build needed):

```bash
docker pull vllm/vllm-openai:cu130-nightly    # pin a validated digest for reproducibility
# Alternative: NGC vLLM container (nvcr.io/nvidia/vllm) / NVIDIA playbook build.nvidia.com/spark/vllm
# [UNVERIFIED — Voxtral-Realtime specifically under this image on GB10, §8 R5]
```

### Step 3 — Environment C: NeMo offline eval engines (parakeet / canary / Sortformer presets)

Guaranteed path — NGC arm64 container (verified multi-arch: nemo:26.06 arm64 18.2 GB built 2026-06-22):

```bash
docker pull nvcr.io/nvidia/nemo:26.06
docker run --gpus all -it --rm --ipc=host -v $HOME/data:/data -v $HOME/src:/src \
    nvcr.io/nvidia/nemo:26.06
# Inside: python -c "import nemo.collections.asr as a; \
# m=a.models.ASRModel.from_pretrained('nvidia/parakeet-tdt-0.6b-v3'); print(m)"
```

Native-pip alternative **[UNVERIFIED — §8 R2]**:

```bash
python3 -m venv ~/venvs/nemo && source ~/venvs/nemo/bin/activate
pip install torch==2.11.0 torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/cu130
pip install "nemo_toolkit[asr]==2.7.3"
# Note: the NEW split package 'nemo-toolkit-asr' has ONLY pre-releases (2.8.0rc2) — plain
# `pip install nemo-toolkit-asr` resolves to nothing without --pre. Prefer classic nemo_toolkit[asr].
sudo apt-get install -y libsndfile1   # if not present
```

### Step 4 — Environment D: offline diarization reference (pyannote) + metrics

```bash
python3 -m venv ~/venvs/eval && source ~/venvs/eval/bin/activate
pip install torch==2.11.0 torchaudio==2.11.0 torchcodec==0.14.0 \
    --index-url https://download.pytorch.org/whl/cu130
pip install pyannote.audio==4.0.7 meeteval jiwer datasets soundfile praatio zenodo-get
# pyannote model is HF-gated (gated:"auto"): visit
# https://huggingface.co/pyannote/speaker-diarization-community-1 , accept conditions, then:
hf auth login        # (or: huggingface-cli login)
python - <<'EOF'
from pyannote.audio import Pipeline
p = Pipeline.from_pretrained("pyannote/speaker-diarization-community-1")
import torch; p.to(torch.device("cuda"))
print("pyannote OK")
EOF
```

### Step 5 — whisper.cpp GPU baseline (optional, quick sanity engine)

```bash
cd ~/src && git clone https://github.com/ggml-org/whisper.cpp && cd whisper.cpp   # current release v1.9.1 (2026-06-19)
cmake -B build -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES="120;121" -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
# CRITICAL: arch "120" alone produces a GB10-incompatible binary (compiles sm_120a) —
# "120;121" is mandatory (NVIDIA forum, 2026-05-30, whisper.cpp v1.8.4 on GB10).
# Prebuilt release arm64 binaries exist since v1.8.7 but are CPU-only — source build required for GPU.
```

### Step 6 — CTranslate2 GPU source build (ONLY if faster-whisper-GPU is ever needed)

```bash
# PyPI ctranslate2 aarch64 wheels contain NO CUDA at all (verified from CT2's own wheel-build CI script).
# CUDA 13 support is an open request (OpenNMT/CTranslate2#1933). Community-proven build (CT2 4.6.0
# on a DGX Spark, Oct 2025); 4.8.x same recipe [UNVERIFIED for 4.8.x — §8 R9]:
cd ~/src && git clone --recursive https://github.com/OpenNMT/CTranslate2 && cd CTranslate2
cmake -B build -DWITH_CUDA=ON -DWITH_CUDNN=ON -DWITH_MKL=OFF -DWITH_OPENBLAS=ON \
      -DOPENMP_RUNTIME=NONE -DCMAKE_CUDA_ARCHITECTURES="120;121"
cmake --build build -j && sudo cmake --install build && sudo ldconfig
cd python && pip install .        # into whichever venv needs GPU faster-whisper
```

### Things to NOT install

- `flash-attn` (pulls CUDA-12 libs, breaks on Spark; native SDPA is faster on Blackwell).
- `onnxruntime-gpu` from PyPI (zero aarch64 wheels through 1.27.0). If GPU ONNX is ever needed: community wheel `onnxruntime_gpu-1.24.0-cp312-linux_aarch64.whl` from `https://pypi.jetson-ai-lab.io/sbsa/cu130` (community-built — pin hashes).
- Any cu126/cu128/cu129 torch wheels (CUDA-12-based → `libcudart.so.12` failures on this CUDA-13-only system).
- Pre-Oct-2025 SimulStreaming / WLK ≤0.2.7 (non-commercial license era).

---

## 5. Dutch evaluation data plan

### Download today (in this order)

**1. IFADV — IFA Dialog Video corpus (PRIMARY conversational eval: DER + speaker-attributed WER).**
Zenodo record 14906857 (live, HTTP 200 on 2026-07-15). License: **GNU AGPL-3.0-or-later** (Zenodo record; publication metadata says 2008 v1 — the "re-published 2025" date is unverified). Content: 20 annotated dyadic free conversations × 15 min = **5 h** (24 recorded / 6 h total, 20 fully annotated), ~34 native speakers. **Stereo: subject A = left channel, subject B = right channel** → exact per-speaker ground truth. Annotations: Praat TextGrids — `.ort` (orthographic per speaker), `.awd` (word+phoneme alignment → word timestamps), plus POS.

```bash
source ~/venvs/eval/bin/activate
cd ~/data && mkdir ifadv && cd ifadv
zenodo_get 14906857 -g "Annotations.zip"       # 12.5 MB
zenodo_get 14906857 -g "AudioWAV.zip"          # 5.8 GB (or AudioFLAC.zip, 3.2 GB)
# fallback: wget "https://zenodo.org/records/14906857/files/Annotations.zip?download=1"
unzip Annotations.zip && unzip AudioWAV.zip
```

Use: reference RTTM + per-speaker reference transcripts (parse `.ort`/`.awd` with `praatio`; cross-check against the channel split) → **DER, cpWER, speaker-attributed WER** on real Dutch conversation. This conversion is our own code — spot-check in Praat (§8 R10).

**2. MLS Dutch (clean WER + largest free fine-tuning corpus).**
`facebook/multilingual_librispeech`, config `"dutch"`, ungated, **CC-BY-4.0**. Train **1,554.24 h** / dev 12.76 h / test 12.76 h; FLAC 16 kHz mono; fields `text`, `speaker_id`.

```python
from datasets import load_dataset
mls_test = load_dataset("facebook/multilingual_librispeech", "dutch", split="test")
```

**3. FLEURS Dutch (tiny standard benchmark — comparability with published numbers).**
`google/fleurs`, config `nl_nl`, CC-BY-4.0; ~1509/150/350 train/dev/test read sentences. Every headline Dutch WER quoted in §2/§9 (canary 6.12, Voxtral 7.07, parakeet 7.48) is FLEURS-based — this anchors our numbers to the literature.

```python
fleurs_test = load_dataset("google/fleurs", "nl_nl", split="test")
```

**4. Common Voice Dutch (clean WER, crowd-read).**
Official Mozilla releases moved to the **Mozilla Data Collective** in Oct 2025; the HF `mozilla-foundation/*` repos froze at v17.0 (residual gating of v17 files on HF: unconfirmed). Scriptable route: ungated CC0 community mirror **`fsicoli/common_voice_22_0`**, config `nl` (Dutch hour count not broken out on the card — confirm after download).

```python
cv_test = load_dataset("fsicoli/common_voice_22_0", "nl", split="test")
```

**5. VoxPopuli Dutch (formal-domain WER + long-form non-overlapping diarization probe).**
`facebook/voxpopuli`, config `nl`, CC0: 53 transcribed hours, 221 speakers, per-speaker paragraphs split into ≤20 s utterances with `speaker_id`.

### Request now (lead time: days–weeks)

**6. CGN — Corpus Gesproken Nederlands.** ~900 h / 9 M words of spoken Dutch (NL+Flanders); **comp-a = ~925 face-to-face spontaneous conversations, 2–5 speakers, ~99.5 h** — the gold-standard Dutch conversational eval + fine-tuning material. Free of charge but requires a signed license via INT Taalmaterialen (order form at `https://taalmaterialen.ivdnt.org/download/tstc-corpus-gesproken-nederlands/` — loads in a browser; automated fetch gets 403). Separate research vs. commercial editions — request the correct one. **Action: file the request on day 1.**

**7. JASMIN-CGN (optional robustness/fine-tune: children, elderly, non-native Dutch).** Academic license via corpus developers/INT; benchmark scaffolding: `github.com/syfengcuhk/jasmin`; related FT paper arXiv:2502.17284.

### Synthesize when needed

**8. "DutchMix" synthetic overlap set (controllable-overlap DER with exact ground truth).** Build 2–3-speaker mixtures from MLS-Dutch `speaker_id` clips. **Not turnkey**: LibriMix/SparseLibriMix document LibriSpeech inputs only and emit no RTTM natively — adapting metadata CSVs is an integration task. Prefer **lhotse** (`cut.mix()` / meeting simulation) which emits supervision segments we can export as RTTM directly.

### Usage matrix

| Dataset | WER | DER | SA-WER/cpWER | Fine-tune | License | Instant? |
|---|---|---|---|---|---|---|
| IFADV | ✓ (conversational) | ✓ | ✓ | – | AGPL-3.0-or-later | ✓ Zenodo |
| MLS-nl | ✓ (headline clean) | – | – | ✓ (1,554 h) | CC-BY-4.0 | ✓ HF |
| FLEURS nl_nl | ✓ (lit. comparability) | – | – | – | CC-BY-4.0 | ✓ HF |
| CV-nl (fsicoli v22) | ✓ | – | – | ✓ (caution: read speech) | CC0 | ✓ HF |
| VoxPopuli-nl | ✓ (formal) | probe (no overlap) | – | ✓ | CC0 | ✓ HF |
| CGN comp-a | ✓ (spontaneous) | ✓ | ✓ | ✓ | signed license (free) | ✗ weeks |
| JASMIN-CGN | robustness | – | – | ✓ | academic license | ✗ |
| DutchMix (lhotse) | – | ✓ (controllable overlap) | ✓ | – | inherits MLS CC-BY-4.0 | build it |
| N-Best 2008 | — rejected: ELRA-channel only, no self-service download | | | | | ✗ |

---

## 6. Evaluation methodology

**Headline metrics (in priority order):**
1. **cpWER** (concatenated-minimum-permutation WER) on IFADV — the single number that captures "right words attributed to the right speaker" for the whole system. Engine: **meeteval**.
2. **WER** on MLS-nl test + FLEURS nl_nl test (clean ASR quality, literature-comparable). Engine: jiwer / meeteval.
3. **DER** on IFADV (and DutchMix) — **meeteval now computes DER too** (it wraps `md-eval-22.pl` like dscore; the earlier claim that meeteval lacks DER is REFUTED). Use collar 0.25 s, report with-overlap. Cross-check with `pyannote.metrics` if desired (should match — same md-eval core).
4. **Latency**: per-word emission lag and finalization lag (below).

**Canonical data format: SegLST** (meeteval's native "Segment-wise Long-form Speech Transcription" JSON: one record per segment with `session_id`, `speaker`, `start_time`, `end_time`, `words`). Everything converts to/from it: IFADV TextGrids → SegLST (via `praatio`); WLK's WebSocket `lines` output → SegLST (fields map 1:1: speaker/text/start/end); SegLST → RTTM for DER tooling. Keep RTTM as the interchange for diarization-only tools.

**Text normalization (fixed, versioned, applied to both reference and hypothesis before WER):** lowercase; strip punctuation; NFC unicode; collapse whitespace; consistent number policy (recommend: spell out via a fixed Dutch num2words pass, or strip digit-only tokens — pick one and never change it mid-project). Whisper's English normalizer is not suitable for Dutch — implement a small Dutch normalizer and commit it with tests.

**Latency measurement:**
- Feed eval WAVs through the **same WebSocket path as the live UI** at realtime pace (sleep-paced 16 kHz PCM chunks), not via batch API — measures the true streaming behavior.
- Metrics: (a) **partial-word latency** = wall-clock first emission of a word − word's audio end time (needs reference word timestamps — IFADV `.awd` has them); (b) **finalization latency** = time a word enters `lines` (committed) − audio end; (c) p50/p95 of both; (d) RTF. `wlk bench` already produces WER/RTF/avg/p95-latency per sample — reuse its harness, add DER + SegLST export.
- Report every config as a point on the **latency-vs-WER plane**; decisions are made on the curve, not single numbers.

**Protocol hygiene:** fixed eval manifests (file lists + hashes) checked into the repo; every run logs model id + revision, WLK version, all flags, GPU env; never tune on IFADV test dialogues — hold out at least 10 of 20 dialogues as the untouched test split.

---

## 7. Accuracy improvement roadmap (ordered, with expected impact)

1. **Establish baselines (week 1).** WLK + whisper large-v3 + Sortformer@1.04 s on IFADV/MLS/FLEURS; offline canary-1b-v2 + pyannote community-1 as ceilings. *Impact: defines the gap we're closing; zero risk.*
2. **ASR engine bake-off (week 2).** Voxtral-Realtime (480 ms) vs whisper large-v3/turbo (SimulStreaming, `--frame-threshold` sweep) vs parakeet-tdt-0.6b-v3 (chunk sweep 0.5–2 s in NeMo). Expected: Voxtral or parakeet beats streamed Whisper on the latency/WER curve (offline evidence: 7.07/7.48 vs Whisper ~8–10 % Dutch). *Impact: likely 1–3 WER points and/or 2–4× latency reduction.*
3. **Diarization bake-off on Dutch.** Sortformer v2 vs v2.1 vs diart (CPU) vs pyannote-offline on IFADV. Sortformer's English-training penalty on Dutch is the single biggest unknown; if DER is bad, diart (language-independent) may win despite worse English benchmarks. *Impact: unknown until measured — potentially the largest DER lever.*
4. **Latency preset tuning.** Sortformer 0.32 s vs 1.04 s presets; Voxtral 240/480/960 ms; AlignAtt frame threshold. *Impact: UX-defining; small WER cost per step, measure the curve.*
5. **Domain data: CGN comp-a once licensed.** Re-baseline on true spontaneous Dutch; expect WER substantially worse than read-speech numbers (disfluencies, overlap) — this is the number that matters for the product.
6. **Fine-tuning (only after 1–5).** LoRA fine-tune Whisper (WLK supports `--lora-path`) or parakeet (NeMo) on MLS-nl train + CGN (+ JASMIN for robustness). **Anti-pattern to avoid (evidence-backed):** Common-Voice-only fine-tunes — `yuriyvnv/whisper-large-v3-high-mixed-nl` scores 4.43 % on CV17-nl but **20.29 % on MLS-nl** (worse than vanilla). Validate any FT on IFADV/CGN spontaneous speech. `pevers/whisperd-nl` (CGN-trained, handles disfluencies) is worth benchmarking for the conversational domain. *Impact: potentially large in-domain, high overfit risk.*
7. **Attribution refinement.** If word→speaker errors dominate cpWER: post-hoc re-attribution with pyannote exclusive mode on finalized segments; tune WLK's punctuation-segment grouping. *Impact: moderate, cheap.*
8. **Pilot Qwen3-ASR-1.7B** (Apache-2.0, Dutch supported, no published Dutch WER) via `qwen3-streaming` backend — cheap to test once the harness exists.

---

## 8. Risks & open questions → concrete on-machine tests

| # | Risk / unknown | Concrete test |
|---|---|---|
| R1 | **torch cu130 aarch64 wheel actually runs on sm_121** (rests on maintainer statement + community guides; wheels ship sm_120 SASS) | Step 1.2 smoke test: `torch.cuda.is_available()`, `get_arch_list()` contains `sm_120`, capability `(12,1)`, matmul finite. Also run a 30 s Whisper transcription and check `nvidia-smi` process table shows the python process. |
| R2 | **`nemo_toolkit[asr]` pip-installs natively on aarch64/py3.12** (pure-Python wheel, but 42 transitive deps incl. lhotse, lightning≤2.4, texterrors, sox≤1.5 — never end-to-end verified) | `pip install --dry-run "nemo_toolkit[asr]==2.7.3"` in a fresh venv; if any sdist fails to build → use `nvcr.io/nvidia/nemo:26.06` container (guaranteed arm64). |
| R3 | **Sortformer Dutch DER penalty** (trained primarily English; card warns of non-English degradation) | Run Sortformer v2 @1.04 s and @0.32 s on all 20 IFADV dialogues → DER via meeteval vs the channel-derived reference; compare against pyannote community-1 (offline) and diart-CPU on the same RTTMs. Decision rule: if Sortformer DER > pyannote DER + 10 points absolute, escalate diart/alternatives. |
| R4 | **Parakeet chunked-streaming latency** (~4 s algorithmic at documented defaults; NOT cache-aware — how low can chunk/right-context go before Dutch WER collapses?) | In NeMo container, sweep `chunk_secs ∈ {0.5,1,2}` × `right_context_secs ∈ {0.5,1,2}` on FLEURS-nl + 2 IFADV dialogues; plot WER vs (chunk+right-context). |
| R5 | **Voxtral-Mini-4B-Realtime on GB10**: transformers-path throughput (needs >12.5 tok/s) and memory-bandwidth-bound behavior on 273 GB/s; vLLM cu130-nightly path unproven for this exact model | Env B: stream a 5-min Dutch WAV at realtime pace; log tokens/s, end-to-end word latency at 480 ms delay setting, memory via `free -h`. Repeat under `vllm/vllm-openai:cu130-nightly`. |
| R6 | **No Sortformer diarization in the Voxtral venv** (declared-incompatible extras) | (a) Try `pip install "whisperlivekit[voxtral-hf,diarization-sortformer]"` and observe the resolver conflict (document it); (b) test running diarization as a separate process/service feeding the same audio, merging streams by timestamp in our wrapper app. |
| R7 | **WLK flag spellings/behavior drift** (project releases fast; e.g. `simulstreaming` policy-vs-backend confusion) | `wlk --help` after install; assert the flags used in §4 exist; pin 0.2.24 and record `--help` output in the repo. |
| R8 | **Unified-memory OOM = system freeze** | Keep swap off (Step 0.2); before long eval runs, `watch free -h`; cap eval concurrency to 1 model per GPU-heavy env; never co-run Voxtral + NeMo eval simultaneously without checking headroom. |
| R9 | **CT2 4.8.x source build on CUDA 13/Spark unconfirmed** (4.6.0 proven Oct 2025) | Only if faster-whisper-GPU is wanted: run Step 6; success = `python -c "import ctranslate2; print(ctranslate2.get_cuda_device_count())"` → 1. Low priority — primary stack avoids CT2. |
| R10 | **IFADV TextGrid → RTTM/SegLST conversion correctness** (our own code; DER garbage-in otherwise) | Convert 1 dialogue; open in Praat alongside audio; verify 10 random turns' speaker/timing; cross-check RTTM speech time per speaker ≈ per-channel VAD speech time (Silero on left/right channels separately). |
| R11 | **Streamed-vs-offline WER gap for whisper large-v3 Dutch** (AlignAtt degradation at low thresholds) | `wlk bench` with Dutch samples (extend beyond the catalog's single MLS-nl sample) at 3 frame-threshold settings vs offline transcription of the same files. |
| R12 | **Browser audio path on the LAN** (MediaRecorder/WebM vs `--pcm-input` AudioWorklet; ffmpeg decode jitter) | A/B the two ingestion modes from a laptop browser; compare p95 word latency; note ws:// vs wss:// (mic capture requires secure context except on localhost — plan a self-signed cert or reverse proxy if used off-box). |
| R13 | **Qwen3-ASR Dutch quality unknown** (no published Dutch WER) | After harness exists: run `Qwen/Qwen3-ASR-1.7B` on FLEURS-nl/MLS-nl offline; only consider streaming integration if it beats the incumbent. |
| R14 | **Open ASR Leaderboard multilingual track freshness** (multilingual evals refreshed less rigorously; UI Dutch filter unrendered in verification) | Periodically re-check https://huggingface.co/spaces/hf-audio/open_asr_leaderboard for new Dutch-capable entrants; treat as tip-off, re-verify on our own eval set. |

---

## 9. Comparison tables

### 9.1 ASR models for Dutch (all figures from model cards / papers, verified 2026-07-15)

| Model (HF id) | Params | Dutch WER FLEURS | Dutch WER MLS | Streaming | License | DGX Spark status |
|---|---|---|---|---|---|---|
| `nvidia/canary-1b-v2` | 978M | **6.12 %** | **11.27 %** | ✗ offline enc-dec (chunked long-form only) | CC-BY-4.0 | NeMo path; same container as parakeet (no explicit Spark confirmation) |
| `mistralai/Voxtral-Mini-4B-Realtime-2602` | ~4B (3.4B LM + 0.97B enc) | 7.07 % @480 ms delay | n/a | ✓ **native** (delays: multiples of 80 ms in 80–1200 ms, + 2400 ms) | Apache-2.0 | transformers≥5.2 path OK; vLLM via cu130-nightly image (validated on Spark, model-specific run UNVERIFIED) |
| `nvidia/parakeet-tdt-0.6b-v3` | 600M | 7.48 % | 12.78 % | ✓ chunked/buffered (NOT cache-aware; ~4 s algorithmic at defaults, tunable) | CC-BY-4.0 | **Confirmed** ~282.9× RTFx on GB10 (NGC PyTorch 25.10) |
| `openai/whisper-large-v3` (+ SimulStreaming) | 1.55B | ~8–10 % (varies by benchmark; Canary paper cross-avg ~9.9 %) | — | via AlignAtt/LocalAgreement wrapper | MIT | ✓ pure-PyTorch cu130; WLK Spark issues #276/#284 were wheel-selection problems, closed |
| `openai/whisper-large-v3-turbo` | 809M | slightly worse than large-v3 | — | same wrappers | MIT | same |
| `Qwen/Qwen3-ASR-1.7B` / `-0.6B` | 1.7B/0.6B | **no published Dutch WER** | — | ✓ causal/streaming backends in WLK | Apache-2.0 | vLLM variant OK via cu130-nightly; timestamps need separate ForcedAligner model |
| `pevers/whisperd-nl` (CGN FT) | 1.55B | — (16.42 % on own disfluency-rich eval) | — | via wrappers | (check card) | as whisper |
| `yuriyvnv/whisper-large-v3-high-mixed-nl` | 1.55B | — | **20.29 %** (vs 4.43 % CV17) | via wrappers | (check card) | **avoid** — read-speech overfit |
| `Jaspernl/whisper-large-v3-ft-nl` | — | — | — | — | — | **HTTP 401 — private/unavailable** |
| Kyutai STT (`stt-1b-en_fr`, `stt-2.6b-en`) | — | **no Dutch** | — | ✓ native | CC-BY-4.0 | rejected on language |

### 9.2 Diarization options

| Option | Streaming | Latency | Published DER | Max spk | Dutch/lang-independence | License | Spark/aarch64 |
|---|---|---|---|---|---|---|---|
| `nvidia/diar_streaming_sortformer_4spk-v2` | ✓ native | 0.32–30.4 s configurable | 13.24 % DIHARD-III ≤4spk @1.04 s; CALLHOME-p2 Full 9.54–11.38 % | **4** | English-primary training — **measure on Dutch** | CC-BY-4.0, ungated | ✓ NeMo (container or pip R2) |
| `nvidia/diar_streaming_sortformer_4spk-v2.1` | ✓ | same knobs | meeting-domain improvement claimed (plausible, not independently verified) | 4 | same | **NVIDIA Open Model License** | same |
| diart 0.9.2 | ✓ | 0.5–5 s | ~28–30 % DIHARD-III (paper) | unbounded (cfg 20) | ✓ language-independent | MIT (pyannote models gated) | torch<2.9 pin friction → likely CPU-only here |
| pyannote `speaker-diarization-community-1` | ✗ offline | n/a | 20.2 % DIHARD-3 / 17.0 % AMI / 11.2 % VoxConverse | unbounded | ✓ multilingual-proven | CC-BY-4.0, gated "auto" | ✓ plain PyTorch cu130 |
| `nvidia/diar_sortformer_4spk-v1` (offline) | ✗ | n/a | — | 4 | — | **CC-BY-NC-4.0 — do not use commercially** | — |
| DiariZen | ✗ offline | n/a | near-SOTA offline | unbounded | ✓ | MIT | secondary reference |
| sherpa-onnx / senko / FS-EEND | ✗ / ✗ / research | — | — | — | — | Apache-2.0 / MIT / **no license** | rejected |

### 9.3 Datasets

| Dataset | Size (Dutch) | Type | Per-speaker refs | Word timestamps | License | Access |
|---|---|---|---|---|---|---|
| IFADV | 5 h annotated (20×15 min) | dyadic free conversation | ✓ (TextGrids + stereo channel split) | ✓ (`.awd`) | AGPL-3.0-or-later | instant, Zenodo 14906857 |
| CGN comp-a | ~99.5 h (of ~900 h total) | 2–5-spk face-to-face spontaneous | ✓ (speaker turns) | segment-level (+phonetic) | free, signed license | INT order, days–weeks |
| MLS Dutch | 1,554 h train / 12.76 h dev / 12.76 h test | read audiobooks, 1 spk/clip | speaker_id | ✗ | CC-BY-4.0 | instant, HF ungated |
| FLEURS nl_nl | ~1509/150/350 sentences | read sentences | ✗ | ✗ | CC-BY-4.0 | instant, HF |
| Common Voice nl (fsicoli v22 mirror) | TBD (confirm post-download) | crowd read speech | client_id | ✗ | CC0 | instant, HF ungated |
| VoxPopuli nl | 53 h transcribed, 221 speakers | EU-Parliament formal | speaker_id, per-speaker paragraphs | ✗ (≤20 s utterances) | CC0 | instant, HF |
| JASMIN-CGN | — | children/elderly/non-native | ✓ | — | academic license | contact INT/developers |
| DutchMix (lhotse-built) | as generated | synthetic overlap | ✓ exact | ✓ exact | inherits CC-BY-4.0 | build (integration task) |
| N-Best 2008 | — | broadcast+telephone benchmark | — | — | ELRA channels | **not self-service — rejected** |

---

## 10. Sources

**Models (Hugging Face):**
- https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3
- https://huggingface.co/nvidia/canary-1b-v2 (+ /blob/main/README.md)
- https://huggingface.co/mistralai/Voxtral-Mini-4B-Realtime-2602
- https://huggingface.co/Qwen/Qwen3-ASR-1.7B
- https://huggingface.co/openai/whisper-large-v3
- https://huggingface.co/nvidia/diar_streaming_sortformer_4spk-v2
- https://huggingface.co/nvidia/diar_streaming_sortformer_4spk-v2.1
- https://huggingface.co/nvidia/diar_sortformer_4spk-v1 (CC-BY-NC — avoid)
- https://huggingface.co/pyannote/speaker-diarization-community-1
- https://huggingface.co/yuriyvnv/whisper-large-v3-high-mixed-nl
- https://huggingface.co/pevers/whisperd-nl
- https://huggingface.co/kyutai (via https://kyutai.org/stt/)

**Papers:**
- arXiv:2509.14128 (parakeet multilingual), arXiv:2602.11298 (Voxtral Realtime), arXiv:2601.21337 (Qwen3-ASR), arXiv:2507.18446 (Streaming Sortformer), arXiv:2506.17077 (SimulStreaming/IWSLT-2025), arXiv:2510.06961 (Open ASR Leaderboard), arXiv:2410.06670 (LS-EEND), arXiv:2502.17284 (JASMIN Whisper FT), arXiv:2205.12446 (FLEURS), arXiv:2409.00819 (LibriheavyMix)

**Engines / apps / libraries:**
- https://github.com/QuentinFuxa/WhisperLiveKit (+ docs/API.md, whisperlivekit/tokens_alignment.py, whisperlivekit/benchmark/, pyproject.toml; issues #276, #284)
- https://github.com/ufal/SimulStreaming (MIT since 2025-10-22; tag `nc` = last noncommercial)
- https://github.com/ufal/whisper_streaming
- https://github.com/SYSTRAN/faster-whisper (issue #1431, closed as redirect)
- https://github.com/OpenNMT/CTranslate2 (issue #1933 open; python/tools/prepare_build_environment_linux.sh)
- https://github.com/Mekopa/whisperx-blackwell
- https://github.com/m-bain/whisperX
- https://github.com/ggml-org/whisper.cpp
- https://github.com/juanmc2005/diart
- https://github.com/pyannote/pyannote-audio
- https://github.com/snakers4/silero-vad
- https://github.com/k2-fsa/sherpa-onnx (+ https://k2-fsa.github.io/sherpa/onnx/speaker-diarization/index.html)
- https://github.com/narcotic-sh/senko , https://github.com/Audio-WestlakeU/FS-EEND , https://github.com/BUTSpeechFIT/DiariZen
- https://github.com/collabora/WhisperLive , https://github.com/KoljaB/RealtimeSTT , https://github.com/speaches-ai/speaches (issue #620) , https://github.com/thewh1teagle/vibe , https://github.com/rishikanthc/Scriberr , https://github.com/fastrepl/hyprnote , https://github.com/Vexa-ai/vexa , https://github.com/davidamacey/OpenTranscribe , https://github.com/kyutai-labs/delayed-streams-modeling
- https://github.com/fgnt/meeteval (DER via md-eval wrapper — confirmed in README)
- https://github.com/JorisCos/LibriMix , https://github.com/popcornell/SparseLibriMix , https://lhotse.readthedocs.io
- https://github.com/QwenLM/Qwen3-ASR

**DGX Spark / platform:**
- https://download.pytorch.org/whl/cu130 (+ /torch/, /torchaudio/ index listings)
- https://pypi.org/pypi/torch/2.13.0/json , https://pypi.org/pypi/pyannote.audio/json , https://pypi.org/pypi/whisperlivekit/json , https://pypi.org/pypi/nemo-toolkit/json , https://pypi.org/pypi/nemo-toolkit-asr/json , https://pypi.org/pypi/ctranslate2/4.8.1/json , https://pypi.org/pypi/silero-vad/json , https://pypi.org/project/webrtcvad-wheels/ , https://pypi.org/project/onnxruntime-gpu/
- https://discuss.pytorch.org/t/dgx-spark-gb10-cuda-13-0-python-3-12-sm-121/223744 (ptrblck: sm_121 binary-compat with sm_120)
- https://forums.developer.nvidia.com/t/running-parakeet-speech-to-text-on-spark/356353 (+ https://github.com/coder543/stt-bench-matrix)
- https://forums.developer.nvidia.com/t/running-whisper-cpp-stt-server-on-dgx-spark-gb10-arm64-cuda-13-via-docker/371803 (arch "120;121" mandatory)
- https://github.com/vllm-project/vllm/issues/36821 (open) , issue #31128 (closed completed 2025-12-23) , https://vllm.ai/blog/2026-06-01-vllm-dgx-spark , https://build.nvidia.com/spark/vllm
- https://catalog.ngc.nvidia.com/orgs/nvidia/containers/nemo (+ NGC API: nemo:26.06 arm64, pytorch:26.06-py3 arm64)
- https://github.com/NVIDIA/dgx-spark-playbooks , https://github.com/natolambert/dgx-spark-setup (swap death spiral), https://github.com/assix/ctranslate2-aarch64-cuda13-binaries
- https://pypi.jetson-ai-lab.io/sbsa/cu130 (community onnxruntime-gpu/torch/flash-attn aarch64 wheels)
- https://docs.nvidia.com/nemo/speech/nightly/starthere/install.html , https://github.com/NVIDIA-NeMo/Speech

**Datasets & eval:**
- https://zenodo.org/records/14906857 (IFADV) , https://www.fon.hum.uva.nl/IFA-SpokenLanguageCorpora/IFADVcorpus/
- https://taalmaterialen.ivdnt.org/download/tstc-corpus-gesproken-nederlands/ (CGN)
- https://huggingface.co/datasets/facebook/multilingual_librispeech , https://huggingface.co/datasets/google/fleurs , https://huggingface.co/datasets/facebook/voxpopuli , https://huggingface.co/datasets/fsicoli/common_voice_22_0 , https://huggingface.co/datasets/mozilla-foundation/common_voice_17_0 (Mozilla Data Collective migration notice)
- https://github.com/syfengcuhk/jasmin (JASMIN access model)
- https://link.springer.com/chapter/10.1007/978-3-642-30910-6_15 (N-Best 2008)
- https://huggingface.co/spaces/hf-audio/open_asr_leaderboard (+ https://github.com/huggingface/open_asr_leaderboard)