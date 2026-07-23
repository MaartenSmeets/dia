# EVALUATION.md — methodology + results

## Metrics (what we measure and why)

| Metric | Tool | Used on | Meaning |
|---|---|---|---|
| **cpWER** (headline) | meeteval `cpwer` | IFADV (multi-speaker) | Word errors under the best speaker permutation — "the right words attributed to the right speaker". The single number that captures the whole diarized-transcription task. |
| WER | jiwer | all sets | Speaker-agnostic word errors over time-sorted concatenated text. On overlapping conversation the concatenation order is ambiguous — treat IFADV WER as indicative only; FLEURS/MLS WER is exact. |
| **DER** | meeteval `md_eval_22`, collar 0.25 s, all regions (overlap included) | IFADV | Diarization quality alone (missed + false-alarm + confused speaker time) / scored speech time. |
| Latency | session `events.jsonl` + WLK lag fields | streaming runs | Partial/finalization lag; full word-emission latency analysis uses IFADV `.awd` word timestamps (planned). |

**Normalization:** both reference and hypothesis pass through `dialib/normalizer.py` (**v1**, tests in `tests/test_normalizer.py`): lowercase, NFKC, punctuation stripped (Dutch clitic apostrophes kept: `'k`, `d'r`), digits→Dutch words (num2words), hesitation fillers + IFADV non-lexical tokens (`xxx`, `ggg`) removed from both sides. Never change silently — bump the version and re-run baselines (`eval/rescore.py` re-scores stored hypotheses without re-running pipelines).

**Formats:** canonical = SegLST JSON (meeteval-native). References in `eval/references/`, run outputs in `eval/results/<stamp>-<method>-<manifest>/` with `config.json` (engine flags, model, normalizer version) for reproducibility.

**Splits:** IFADV dev (10 dialogues) for tuning; IFADV **test (10 dialogues) is held out — never tune on it**. Fixed manifests in `eval/manifests/`.

## Methods compared (see docs/COMPARISON.md for the verdict)

1. `wlk-stream` — the live pipeline at realtime pace: whisper large-v3 (SimulStreaming/AlignAtt) + streaming Sortformer diarization. What a live meeting user experiences.
2. `wlk-fast` — same pipeline, unpaced. The "after-the-fact upload" mode (m4a etc.). Quality ≈ wlk-stream, wall-clock ≈ 0.45× audio duration on this machine.
3. `whisper-longform` — classic offline whisper large-v3 sequential long-form decode, **no diarization** (the user's requested baseline). Cannot answer who-said-what: cpWER degenerates (all words on one speaker).
4. `whisper-longform+pyannote` — offline ASR + pyannote community-1 offline diarization + max-overlap word attribution. The offline quality ceiling for diarized transcription. *Blocked until the HF gating for pyannote is accepted.*
5. (Planned) parakeet-tdt-0.6b-v3 / canary-1b-v2 via NeMo container — RESEARCH.md §7.2.

## Results

**See [COMPARISON.md](COMPARISON.md) for the full method comparison and verdict** (2026-07-15 baselines). Headlines: offline whisper+pyannote is the quality ceiling (IFADV-dev pooled WER 30.1% / cpWER 44.7% / DER 21.4%); the live streaming pipeline costs ~5 WER pts vs offline on conversations; diarization-free long-form whisper fails the who-said-what task (cpWER 87.3%); conversational Dutch is ~4× harder than read speech (30.1% vs 7.3% offline WER); unpaced "fast" streaming degrades long-audio ASR (demoted to functional checks — uploads use the offline pipeline instead).

## Latency — woordniveau-emissielatentie (gemeten 2026-07-23)

**Definitie:** tijd tussen het uitgesproken zijn van een woord (IFADV .awd-woordtijdstempel,
orthografische tier) en het moment dat het woord in de GECOMMITTEERDE live-transcripttekst
verschijnt (audio_fed-positie, gepaced replay op speed 1.0). Meting: `eval/word_latency.py`
op sessies met tekst-delta-events (app logt die sinds 2026-07-23). Matching is bewust
conservatief (alleen genormaliseerd-uniek in een 30s-venster, woorden ≥3 letters → ~50%
dekking met hoge precisie).

| Dialoog | p50 | p90 | n gematcht |
|---|---|---|---|
| DVA1A | 1,05 s | 1,35 s | 1164 |
| DVA3E | 1,03 s | 1,32 s | 1049 |
| DVA6H | 1,04 s | 1,33 s | 1157 |

**Conclusie: de live-pijplijn (turbo+Sortformer, huidige defaults) committeert woorden met
~1,0 s mediane / ~1,35 s p90 latentie — ruim binnen de producteis van ~2 s partials.**
De spreiding tussen dialogen is verwaarloosbaar (±0,02 s). Run:
`eval/results/20260723-0207-word-latency/`; replays: `*-wlk-stream-wordlat-*`.

Voetnoot bij de oude proxy-meting (`eval/latency_report.py`, finalisatie-achterstand): die
bleek een meetbias te hebben (negatieve medianen door committed-eindtijd vs audio_fed-
vergelijking) en is vervangen door deze directe woordmeting.

**Bugfix onderweg gevonden:** de IFADV `.words.json`-referenties bevatten vóór 2026-07-23
FONEN i.p.v. woorden (awd-bestanden hebben 3 tier-paren met identieke namen; een
dict-comprehension hield stilletjes de laatste = fonentier — `ifadv_to_seglst.py` gefixt,
alle 20 regenerated). SegLST/RTTM/WER-referenties komen uit de ort-bestanden en waren
NIET geraakt.

## How to run

```bash
venvs/wlk/bin/python eval/run_eval.py --method <method> --manifest <ifadv_dev|ifadv_test|cgn_a_dev|cgn_tel_dev|fleurs_nl|mls_nl> [--limit N]
venvs/wlk/bin/python eval/rescore.py eval/results/<run-dir>     # after metric changes
scripts/run_baselines.sh                                        # the full comparison queue

# Basisrace-kandidaten offline (allemaal 30s-vensters, zelfde normalizer — COMPARISON.md Update 4):
venvs/wlk/bin/python eval/score_nemo.py --model nvidia/canary-1b-v2 --manifest ifadv_dev --tag canary
bash scripts/vox_bakeoff.sh                                     # Voxtral: 2 fasen (venvs/vox + venvs/wlk), hervat-baar
venvs/wlk/bin/python scripts/score_lora.py --adapter models/lora/M2-cgn --manifest cgn_tel_dev --tag M2w

# Samenvattings-eval (SUMMARY-EVAL.md; v4-protocol = labelhernoeming + degeneratie-guards;
# LLM-server MOET zonder prefix-caching draaien, zie OPS-LLM.md VALKUIL 2):
venvs/wlk/bin/python eval/summary_eval.py --manifest ifadv_dev --limit 6 \
  --live-run <wlk-stream-run> --offline-run <longform-run> --offlineD-run <longform+pyannote-run> \
  --fused-run <merged-liveturns-offwords-run>
```
