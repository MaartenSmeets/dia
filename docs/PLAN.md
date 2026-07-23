# PLAN.md — build plan, phases, acceptance criteria

Decisions and rationale live in [RESEARCH.md](RESEARCH.md). This is the execution plan. Status of each phase is tracked in [PROGRESS.md](PROGRESS.md).

## Requirements (from the user, 2026-07-15)

- Realtime diarization + transcription of **Dutch** audio, fully local on the DGX Spark.
- Optimized for **meetings/conversations with 2–4 speakers**.
- **Balanced latency:** partial words ≈2 s, finalized speaker-attributed text a few seconds behind.
- Audio inputs: **browser mic on the machine**, **browser mic from LAN devices** (needs HTTPS/self-signed cert for getUserMedia off-localhost), and **uploaded files replayed as-if-live** (also feeds the eval loop).
- Web interface to experiment; curated Dutch data with per-speaker reference transcriptions; measure and iterate on accuracy.
- Gated HF models allowed (token in `.env`).

## Phase 0 — Environment (R1, R2, R7)  ✅ acceptance criteria

1. `venvs/wlk`: torch 2.11.0 cu130 aarch64 → `torch.cuda.is_available() == True`, matmul on GPU finite.
2. `whisperlivekit[diarization-sortformer]==0.2.24` installs cleanly on aarch64/py3.12 (else fall back per RESEARCH §4 step 3: NGC NeMo container).
3. `wlk --help` output recorded in SETUP.md; flags used in scripts verified to exist.

## Phase 1 — Data (R10)

1. IFADV downloaded + unzipped; inventory matches: 20 annotated dyadic dialogues, stereo WAV (A=left, B=right), `.ort`/`.awd` TextGrids.
2. HF sets cached locally: FLEURS-nl test, MLS-nl test/dev, CV-nl test (fsicoli v22), VoxPopuli-nl sample.
3. `scripts/ifadv_to_seglst.py` converts TextGrids → SegLST + RTTM; validation: per-speaker speech-time vs per-channel VAD agree within tolerance; 10 random turns spot-checked.
4. Fixed splits committed: `eval/manifests/ifadv_dev.json` (10 dialogues), `eval/manifests/ifadv_test.json` (10 dialogues, **held out — never tune on it**).
5. CGN license request instructions delivered to user (docs/DATASETS.md §CGN) — user action.

## Phase 2 — Live pipeline go/no-go (R3 partially, R7, R12)

1. WLK server runs: `--model large-v3 --language nl --diarization --diarization-backend sortformer --disable-fast-encoder`.
2. An IFADV WAV streamed over the WebSocket at realtime pace produces sensible Dutch partials + speaker labels; no crash over a full 15-min dialogue.
3. Browser mic works on localhost with the bundled UI.
4. GPU/unified memory usage recorded (`free -h` before/during).

## Phase 3 — Experiment web app

FastAPI app (`app/`) embedding WLK's `TranscriptionEngine`/`AudioProcessor` (template: WLK `basic_server.py`), custom frontend. Features, in build order:
1. **Live mode:** mic capture → WebSocket → live transcript, speaker-colored, partial (gray) vs finalized text; session save to SegLST.
2. **File mode:** upload → realtime-paced replay through the same path (this is the eval transport too). Accept any ffmpeg-decodable format — **m4a/AAC explicitly required** (user 2026-07-15), plus wav/flac/mp3/ogg/webm. Ingest = ffmpeg decode → 16 kHz mono PCM, with an optional **loudness normalization** toggle (ffmpeg `loudnorm`, EBU R128, two-pass for files) because phone/meeting m4a recordings are often too quiet/uneven for VAD+ASR.
3. **Eval mode:** pick IFADV/FLEURS sample → play + live hypothesis; on completion show reference alignment (per-speaker), WER/cpWER/DER, latency stats.
4. **Config panel:** model, language, diarization backend/latency preset, AlignAtt frame threshold → restart engine with chosen config; every run logged with full config.
5. **Correction mode:** edit hypothesis segments (text + speaker), save as corrected SegLST → grows a local curated set for future fine-tuning (`data/corrections/`).
6. **LAN access:** self-signed TLS (script + docs) so getUserMedia works from other devices.

Acceptance: all six features demonstrated; app documented in WEBAPP.md; survives a 30-min live session.

## Phase 4 — Evaluation harness + baselines (R11)

1. `eval/run_eval.py`: manifest in → stream via WS at realtime pace → SegLST out → meeteval cpWER + DER (collar 0.25, with overlap), jiwer WER with `eval/normalizer.py` (Dutch, versioned, tested) → latency percentiles (partial-word + finalization, needs IFADV `.awd` word times).
2. Baselines on IFADV-dev + FLEURS-nl test:
   - WLK + whisper large-v3 + Sortformer@1.04s (the day-1 stack)
   - WLK + whisper large-v3-turbo (latency point)
   - Offline ceilings: canary-1b-v2 transcription (NeMo container), pyannote community-1 diarization
3. Results table in EVALUATION.md; every run reproducible from `eval/results/*/config.json`.

## Phase 5 — Bake-offs & accuracy iteration (R3, R4, R5, R6, R13)  ✅ AFGEROND 2026-07-23

Uitkomsten (bewijs in COMPARISON.md, CGN-VALUE.md, SUMMARY-EVAL.md):
1. **ASR bake-off ✅:** live = **large-v3-turbo** (won de sweep, Update 1/2); offline refine =
   **turbo+CGN-LoRA (M2)** — versloeg canary-1b-v2, parakeet-tdt-0.6b-v3 én Voxtral-Mini-3B
   met 6–12 punten pooled WER op ifadv/cgn_a dev (Update 4). Voxtral-4B-Realtime bewust
   overgeslagen (venv-incompatibel + offline-broer verliest ruim).
2. **Diarization ✅:** Sortformer v2 blijft (beslisregel nooit getriggerd; op moeilijke
   dialogen wint Sortformer juist van pyannote); **fusie (live-Sortformer-beurten ×
   offline-M2-woorden) = productstandaard** voor de definitieve versie (Update 3).
3. **Latency ✅:** presets gekozen (frame-threshold sweep); woordniveau-emissielatentie
   gemeten (EVALUATION.md §Latency).
4. **Attribution ✅:** bevestigd als dé bottleneck (cpWER-analyse + SUMMARY-EVAL v4:
   labels = ×3,5 attributie-accuratesse in samenvattingen); fusie is de gekozen remedie.
5. **CGN-LoRA ✅:** M-serie compleet; CGN = werkzaam bestanddeel (−7 WER; draagt over naar
   telefoonspraak −9,6); VERDICT + per-use-case-waardetabel in CGN-VALUE.md.

Rest-experimenten: hybride-meeting per-spreker-audiobehandeling (taak #20, gepland);
benchmark van het NL-overheidsspraakinitiatief bij release (taak #18, wekelijkse watch; details docs-intern/).

## Phase 6 — Consolidation

- SETUP.md complete as-built; PROGRESS.md summary entry; RESEARCH.md UNVERIFIED flags resolved (verified ✓ / refuted with note).
- Final recommended default config written into the app as the startup preset.

## Standing decision rules

- Prefer the boring, verified path (RESEARCH-confirmed) over novel options mid-build; new-model tips go into a "later" list in PROGRESS.md.
- Any deviation from RESEARCH.md's recommendations must be recorded in PROGRESS.md with the evidence that forced it.
- If an install fails twice on aarch64, stop patching and use the documented fallback (usually the NGC container) — do not yak-shave source builds unless the plan says so.
