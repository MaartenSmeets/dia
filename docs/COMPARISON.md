# COMPARISON.md — empirical method comparison for Dutch diarized transcription

**Date:** 2026-07-15 · **Machine:** DGX Spark (GB10) · **Data:** IFADV-dev (10 real 15-min Dutch 2-person conversations) + FLEURS-nl test (read sentences) · **Metrics/normalization:** see EVALUATION.md (normalizer v1; pooled = total errors / total ref mass) · **Raw results:** `eval/results/2026 0715-*` (each with full config for reproduction).

## Verdict (TL;DR)

1. **For who-said-what transcription, diarization is not optional — it's the difference between unusable and usable.** Plain whisper large-v3 long-form (the classic approach) achieves the best raw WER but **cpWER 87.3% / DER 46.2%** on real conversations: it structurally cannot attribute words to speakers. Adding diarization (pyannote) to the *same* ASR output halves both: **cpWER 44.7% / DER 21.4%**. That is the empirical proof requested.
2. **After-the-fact uploads (m4a etc.): use the offline pipeline** — whisper long-form + pyannote is the best quality on every axis and runs ~10× faster than realtime. Now available in the app as upload mode "offline (best quality)".
3. **Live/realtime: the WLK streaming pipeline is the only contender** (nothing else does live), and its ASR penalty vs offline is moderate (~5 WER pts on conversations). Its streaming diarization (Sortformer) is usually good (DER 12–18%) but collapsed on 1 of 2 realtime long-dialogue runs — the top tuning priority.
4. **Do NOT use unpaced "fast" streaming for long files:** feeding the streaming pipeline faster than realtime degrades ASR badly on long audio (WER 49.3% vs 35.0% paced). Kept only for functional checks.

## Results — IFADV-dev (real Dutch conversations, 2 speakers, pooled over 10 dialogues)

*(DER values rescored 2026-07-17 against timeline-corrected references — see Update 2 below.)*

| # | Method | WER ↓ | **cpWER ↓** (headline) | DER ↓ | Speed (wall/audio) | Live? |
|---|---|---|---|---|---|---|
| A | whisper large-v3 long-form (no diarization) | **30.1%** | 87.3% ✗ | 45.9% ✗ | ~0.11× | ✗ |
| D | whisper large-v3 long-form + pyannote community-1 | **30.1%** | 44.7% | 20.1% | ~0.16× | ✗ |
| C | WLK streaming pipeline, unpaced ("fast") | 49.3% | 57.3% | 25.1% | ~0.45× | ✗ |
| B | WLK streaming pipeline, realtime (N=2 dialogues!) | 35.0% | 62.5%* | 32.7%* | 1.0× (live) | ✓ |
| **B′** | **WLK realtime with large-v3-turbo (6 dialogues, 2026-07-17)** | **25.0%** | **32.2%** | **14.1%** | 1.0× (live) | ✓ |

**B′ is the new overall winner:** the live turbo pipeline beats even the offline whisper+pyannote reference (D) on speaker-attributed accuracy — per-dialogue cpWER is lower on every directly comparable dialogue (e.g. DVA1A 30.8 vs 33.4, DVA3E 27.0 vs 32.5, DVA6H 29.9 vs 30.9, DVA8K 32.1 vs 42.0).

\* B's cpWER/DER dominated by one diarization collapse: DVA1A run assigned 793 s vs 118 s to the two speakers (healthy run: 400/491 s). Its per-dialogue numbers: DVA1A cpWER 80.5%/DER 49.4% (collapsed) vs DVA3E cpWER 42.7%/DER 14.2% (healthy — competitive with offline). See "streaming diarization stability" below.

Per-dialogue offline ceiling (method D) spread: cpWER 30.9–67.7%, DER 8.4–38.2% (worst: DVA19AG — hard dialogue for every method).

## Results — FLEURS-nl (read speech, single speaker, short clips)

| Method | WER ↓ | Note |
|---|---|---|
| whisper long-form offline | **7.3%** (N=50) | Matches published large-v3 FLEURS-nl numbers → our harness/normalizer is sound |
| WLK unpaced | 16.1% (N=50) | Short-clip streaming penalty |
| WLK realtime | 22.2% (N=25) | Cold-start + forced finalization dominate a ~10 s clip — worst case for streaming policies |

## Key findings

1. **Conversational Dutch is the real problem, not Dutch per se.** Offline WER: 7.3% read speech → 30.1% spontaneous conversation (disfluencies, backchannels, overlap). Any accuracy work must be validated on IFADV/CGN, not read-speech sets (this was predicted by research — now measured).
2. **Pacing interacts with the streaming policy in opposite directions by audio length.** Long audio: unpaced ≫ worse (49.3% vs 35.0% WER — the AlignAtt policy gets starved and truncates aggressively). Short clips: unpaced slightly better (16.1% vs 22.2% — end-of-stream flush approximates offline decoding). Consequence: "fast streaming" is the wrong upload mode; offline is both faster AND better.
3. **Streaming Sortformer on Dutch: promising but unstable on long dialogues.** Healthy runs: DER 12–18% (fast mode pooled 26.9% incl. worse dialogues; best dialogues ~12%) vs offline pyannote 21.4% pooled — competitive when it works. One realtime run collapsed to near-single-speaker. Hypotheses to test: diarization latency preset (0.32 s vs 1.04 s), Sortformer v2.1, interaction with server load during realtime pacing.
4. **The word-attribution step matters:** method D's cpWER (44.7%) ≈ WER (30.1%) + ~14 pts attribution/diarization cost. Better attribution (pyannote "exclusive" mode, finer ASR segmenting before assignment) is a cheap improvement lever for the offline path.

## Decisions taken (as implemented)

- **Live mode default:** WLK streaming, whisper large-v3, `--lan nl`, Sortformer @ default preset (only live option; quality acceptable, tuning agenda below).
- **Upload mode default:** **offline pipeline (method D)** — exposed in the app's File tab as "offline (best quality)"; realtime-replay retained for latency-faithful experiments; unpaced fast mode demoted to functional checks only.
- **Benchmark anchor:** method D is the quality ceiling all streaming configs are measured against; method A is kept only as the no-diarization strawman.

## Update 2026-07-17 — config sweep results (DVA1A+DVA3E realtime unless noted; runs in `eval/results/*-wlk-stream-*-r*`)

| Config (vs day-1 default: large-v3, ft≈default, Sortformer v2) | WER | cpWER | DER |
|---|---|---|---|
| default, repeat 1 / 2 / 3 | 33.7 / 31.2 / 30.8% | 37.2 / 34.6 / 34.9% | 13.2 / 11.7 / 12.4% |
| `--frame-threshold 15` | 39.4% ✗ | 43.3% | 13.7% |
| `--frame-threshold 40` | 33.4% | 38.0% | 13.1% |
| **`--model large-v3-turbo`** | **25.1%** | **29.4%** | **10.3%** |
| turbo, FLEURS-25 streamed | 18.0% (large-v3: 22.2%) | — | — |
| Sortformer **v2.1**, repeat 1 / 2 | 29.6 / 34.8% | 33.3 / 37.5% | 11.8 / 12.7% |

**Conclusions (now implemented):**
1. **large-v3-turbo is the new live default** (`app/engine_config.json`): on the streaming path the smaller/faster model keeps up with the AlignAtt policy and wins on *every* metric on both datasets — on these 2 dialogues its streamed WER (25.1%) even edges the *offline* large-v3 (26.5–27.9%). Fuller 6-dialogue validation running. Offline uploads (method D) keep large-v3 (offline quality favors the big model: FLEURS 7.3%).
2. **Stability re-assessed:** 0 diarization collapses in 8 realtime runs → day-1 collapse is a rare event (~1-in-10), not systematic. Keep monitoring sessions; no config change warranted.
3. **Frame-threshold: leave at default.** Lower (15) clearly hurts; higher (40) is noise-level.
4. **Sortformer v2.1: no gain on Dutch dialogue** and a more restrictive license (NVIDIA Open Model License) → stay on v2 (CC-BY-4.0).
5. Run-to-run variance on identical configs is real (±3 WER pts, ±1.5 DER pts on N=2 dialogues) — differences smaller than that are noise; turbo's margin is well beyond it.

## Update 2 — 2026-07-17 (evening): turbo validated on 6 dialogues; IFADV reference-timeline bug found & fixed

1. **Turbo validation (6 IFADV-dev dialogues, realtime): WER 25.0% / cpWER 32.2% / DER 14.1% pooled** (run `20260717-1416-wlk-stream-turbo-val-ifadv_dev`). Confirms the sweep: turbo stays the live default; the live stack now beats offline method D on cpWER (44.7%).
2. **Reference bug (important for anyone re-using IFADV):** IFADV ships plain and `Shift6` annotation variants for DVA12S/DVA2C; only the **Shift6 timeline matches the audio** (measured channel-VAD agreement 0.85–0.87 vs 0.50–0.63 for plain). Our converter originally chose the plain variant → bogus DER (~0.65) for *every* method on DVA12S. Fixed in `scripts/ifadv_to_seglst.py` (Shift outranks plain), all 20 references re-audited (timeline agreement 0.75–0.87, all pass), and **all IFADV runs rescored** — DER improved 1–5 pts everywhere DVA12S was included; text metrics unchanged.
3. **DVA12S is intrinsically hard** (similar voices; every diarizer over-clusters it: 3–4 hypothesized speakers for 2). With correct references: streaming Sortformer DER **30.5%** vs offline pyannote **55.1%** — the streaming model handles it best. Combined with 0 collapses in 8 sweep repeats, the day-1 DVA1A collapse remains a single unexplained event in ~16 realtime runs.
4. Timeline audit is now part of the reference-validation protocol (converter + audit snippet in PROGRESS 2026-07-17).

## Update 3 — 2026-07-22: de fusie-methode wint (productstandaard "definitieve versie")

**Live-sprekerbeurten × offline-M2-woorden** (dialib/fuse.py; experiment eval/merge_live_offline.py), gemeten op dezelfde opnames:

| Methode | IFADV (n=6) WER/cpWER/DER | CGN (n=4) WER/cpWER/DER |
|---|---|---|
| Live (turbo+Sortformer) | 25,0 / 32,2 / 14,1% | 35,1 / 44,5 / 20,1% |
| Offline M2 + pyannote-attributie | 22,9* / 41,6 / 17,8% | 31,3* / 49,2 / 19,4% |
| **Fusie (live-beurten × M2-woorden)** | **21,9 / 33,8 / 13,7%** | **28,1 / 41,3 / 14,5%** |

→ Fusie combineert offline-woordkwaliteit met live-sprekerkwaliteit en is op CGN op álle drie de maten de beste. Geïmplementeerd als automatische nabewerking van vergaderingen/live-sessies (refined_*-artefacten); pyannote-attributie blijft fallback voor kale uploads. (*WER-getallen offline-runs over alle items; overige cellen op de gemeenschappelijke subset.)

Licentie-implicatie: in deze productpijplijn haalt M2 (CGN-getraind) de ≥3-punts-cpWER-regel op het vergaderdomein — zie CGN-VALUE.md VERDICT.

## Update 4 — 2026-07-22 (late avond): offline-motor-basisrace — NeMo-kandidaten verliezen, M2 blijft

Gepubliceerde FLEURS-cijfers beloofden een stapverandering (canary-1b-v2: 6,1% FLEURS-nl). Gemeten op onze eigen conversationele dev-sets (score_nemo.py, 30 s-vensters, zelfde normalizer v1 + referenties als alle andere rijen):

| Model (offline) | ifadv_dev pooled WER | cgn_a_dev pooled WER |
|---|---|---|
| **M2w = large-v3-turbo + CGN-LoRA (woordniveau)** | **22,9%** | **31,3%** |
| parakeet-tdt-0.6b-v3 | 28,8% | 43,2% |
| Voxtral-Mini-3B-2507 | 32,1% | 40,7% |
| canary-1b-v2 | 31,5% | 43,5% |

Runs: `eval/results/20260722-{2058,2107}-nemo-canary-*`, `20260722-{2117,2119}-nemo-parakeet-*`,
`20260722-2149-voxtral-{ifadv_dev,cgn_a_dev}` (venvs/vox, 30s-vensters — zelfde methodologie
als de NeMo-rijen), M2w: `20260722-1333-lora-M2w-ifadv_dev`, `20260722-1215-lora-M2w-cgn_a_dev`.

**Conclusies (basisrace compleet, 2026-07-23 01:52):**
1. **M2 blijft de refine-motor** van de "definitieve versie"-pijplijn; de fusie-methode (Update 3) blijft er bovenop staan. Alle vier de serieuze publieke kandidaten zijn nu op onze eigen conversationele sets gemeten — **de claim "best beschikbare openbare model + beste dataset, gemeten" is hiermee gedekt**.
2. **canary+CGN-FT-route vervalt**: het baseline-gat (6–12 punten) is te groot om met een fine-tune te dichten, en trainen zou dagen kosten voor een naar verwachting slechter resultaat. Zelfde redenering geldt a fortiori voor parakeet/Voxtral-FT.
3. Wéér bevestigd: **voorgelezen-spraak-benchmarks voorspellen spontaan Nederlands niet** (Voxtral claimt whisper-v3 te verslaan op meertalige benchmarks; hier 9 punten achter M2 en zelfs achter kale parakeet op IFADV). Meten is weten.
4. **Voxtral-Mini-4B-Realtime (live-variant) niet gemeten, bewust**: vereist de WLK `voxtral-hf`-extra (venv-incompatibel met Sortformer-diarization, zie CLAUDE.md) én de offline-broer verliest al met 9+ punten — live-condities zijn strikter, dus de verwachtingswaarde van die meting is te laag om het venv-risico te rechtvaardigen. Heropenen alleen als een nieuwe Voxtral-versie met sterk betere NL-cijfers verschijnt.

## Update 5 — 2026-07-23: hybride vergaderingen (1 spreker "online") — schade gemeten, opwaardering helpt niet

Gebruikersvraag: moet een gesprek met 1 naveld-spreker + 1 online-deelnemer (ander
kanaalkarakter) een andere audio-opwaarderingsaanpak krijgen? **Meting vóór aanname**
(taak #20, fase 1). Synthetische set uit IFADV-stereo (1 kanaal per spreker):
kanaal 2 door 300–3400 Hz + 8 kHz-omweg + compressie + roze ruis ("telefoon/online"),
daarna mono gemixt — het producttypische invoerformaat. Bouw: `scripts/make_hybrid_ifadv.py`;
sets in `data/hybrid/{clean,deg,fix}/`; runs `eval/results/*-lora-M2w-hybrid_*_dev`.

| Variant (3 dialogen, M2w offline) | pooled WER |
|---|---|
| clean — beide sprekers naveld | 21,0% |
| deg — spreker 2 gedegradeerd | 21,3% |
| fix — deg + goedkope DSP-reparatie (afftdn+speechnorm) | 22,0% |

**Conclusies (fase 1):**
1. **De ASR-schade van een smalband-"online"-spreker is verwaarloosbaar (+0,3 pt)** —
   consistent met de sterke cgn_tel-overdracht (CGN-VALUE.md): whisper-turbo+CGN-LoRA is
   al robuust voor smalbandspraak. Aparte opwaardering per spreker is voor
   wóórdnauwkeurigheid dus geen hefboom op dit degradatieniveau.
2. **Domme DSP-opwaardering is contraproductief (−0,7 pt t.o.v. niets doen):**
   denoise/normalisatie-artefacten kosten de ASR meer dan ze opleveren. Niet inzetten
   zonder meting; dit generaliseert vermoedelijk naar "audio eerst even opschonen"-reflexen.
3. **Fase 2 (diarization-effect, gemeten):** live-pijplijn op de hybride mix vs schoon
   (zelfde 3 dialogen, runs `*-wlk-stream-hybdeg-*` vs `*-wlk-stream-wordlat-*`):

   | live-pijplijn | clean | deg (hybride) |
   |---|---|---|
   | WER pooled | 25,2% | 26,1% |
   | cpWER pooled | 29,8% | 30,1% |
   | DER pooled | 10,6% | 10,3% |

   **Sortformer is ongevoelig voor het kanaalkarakterverschil** (ΔDER binnen ruis; het
   andere klankkarakter maakt sprekers in elk geval niet minder scheidbaar).

**EINDANTWOORD op de gebruikersvraag (gemeten): nee — een aparte
audio-opwaarderingsaanpak per spreker is op dit (telefoonachtige) degradatieniveau niet
nodig.** ASR-schade minimaal (+0,3 offline / +0,9 live), diarization onaangetast, en
naïeve opwaardering is contraproductief. De hefboom voor hybride vergaderingen blijft
dezelfde als overal: fusie + M2. Kanttekening: zwaardere degradaties (slechte VoIP met
dropouts, galm/ver-veld) zijn niet getest — de synthetische-set-generator
(`scripts/make_hybrid_ifadv.py`) staat klaar om die escalatie te meten zodra er
aanleiding is.

## Open experiments (ordered by expected impact — tracked in PLAN.md Phase 5)

1. Streaming-diarization stability: 5× repeat runs on IFADV-dev, both Sortformer latency presets, v2 vs v2.1 → pick stable config (biggest live-quality lever).
2. AlignAtt `--frame-threshold` sweep + `large-v3-turbo` → close the live 35%→30% WER gap / cut latency.
3. Voxtral-Mini-4B-Realtime pilot (natively streaming, Dutch FLEURS 7.07% claimed) — potential step-change for live WER.
4. canary-1b-v2 offline (NeMo container) — potential step-change for the offline ceiling (6.12% FLEURS-nl claimed; expect the conversational gap to persist but shrink).
5. Word-emission latency measurement on IFADV `.awd` word timestamps (harness logs are already captured per session).
6. After CGN license: re-baseline + LoRA fine-tune on spontaneous Dutch.

## Caveats (read before quoting these numbers)

- Single runs (except DVA1A twice); realtime method on only 2 dialogues so far; no significance testing. Repeat-run variance is demonstrably nonzero (finding 3).
- WER on overlapping conversation is order-ambiguous (time-sorted concatenation); cpWER is the metric that matters on IFADV.
- pyannote ran blind (no `num_speakers=2` hint) for fairness vs Sortformer; giving the hint would likely improve method D further on known-2-speaker audio.
- All numbers use normalizer v1 (fillers/backchannel tokens stripped from both sides; digits→Dutch words). Different normalization = incomparable numbers.
