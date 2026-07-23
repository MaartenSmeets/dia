# SUMMARY-EVAL.md — does diarization (and offline quality) improve summaries?

> **Leeswijzer: de geldige uitslag staat in §Results v4** (labels = ×3,5 attributie-
> accuratesse). v1–v3 blijven staan als gemarkeerde meetprotocol-historie — niet citeren.

**User questions (2026-07-21):** for the call-center use case —
1. Live rolling summarization vs summarizing offline afterwards: how big is the quality difference?
2. Is a summary of a **diarized** transcript more accurate than one from a transcript **without** diarization?

## Experiment design (implemented: `eval/summary_eval.py`)

Per dialogue (IFADV-dev; de cgn_tel-referenties bestaan inmiddels maar zijn hier nog niet
gedraaid), six transcript
conditions feed the **same summarizer LLM with the same prompt**:

| Cond | Transcript source | Speaker labels | Answers |
|---|---|---|---|
| A | live streaming pipeline (existing wlk-stream results) | ✓ | live+diar |
| B | same live text, labels stripped | ✗ | isolates diarization at fixed ASR quality |
| C | offline whisper+pyannote (existing method-D results) | ✓ | offline+diar |
| D | offline whisper long-form (existing results) | ✗ | classic no-diar baseline |
| E | fusie: live-sprekerbeurten × offline-M2-woorden (het productiepad) | ✓ | meet de productie-samenvatting direct |
| R | gold reference transcript | ✓ | ceiling |

A−B and C−D isolate **the diarization effect** (same words, ± labels). A−C isolates **live-vs-offline
transcript quality** at fixed diarization. All transcripts already exist from prior eval runs — the
experiment only costs LLM calls.

## Measurement

- **Attribution accuracy (primary):** the judge LLM generates who-said/agreed-to-what questions
  from the GOLD transcript (answer = a speaker), then answers each question *using only the summary*.
  Expectation: conditions without labels can't attribute commitments ("customer agreed to X") —
  precisely the failure that matters in call-center summaries.
- **Coverage / factuality / hallucination count (secondary):** rubric scores vs the gold transcript.
- Conditions are anonymized and order-shuffled for the judge.

## Caveats (read before quoting results)

- LLM-as-judge with the same local model that writes summaries → self-preference bias possible;
  set `JUDGE_URL/JUDGE_MODEL` in `.env` to a different (stronger) model when available. Treat
  **deltas between conditions** as the signal, never absolute rubric scores.
- Attribution questions derive from gold; if question generation is poor the primary metric gets
  noisy — inspect `eval/results/*summary-eval*/<item>.json` spot-wise.
- Dutch throughout (prompts + judging).

## How to run

```bash
# Vereist een lokaal OpenAI-compatibel LLM (SUMMARIZER_URL in .env of app-instellingen).
# LET OP: de LLM-server MOET zonder prefix-caching draaien (OPS-LLM.md VALKUIL 2) —
# anders deterministische degeneratie (gemeten, zie Results v3).
# v4-protocol: labelhernoeming (A/C/E) + degeneratie-guards zitten in het script.
venvs/wlk/bin/python eval/summary_eval.py --manifest ifadv_dev --limit 6 \
  --live-run    eval/results/20260717-1416-wlk-stream-turbo-val-ifadv_dev \
  --offline-run eval/results/20260715-1805-whisper-longform-ifadv_dev \
  --offlineD-run eval/results/20260715-1912-whisper-longform+pyannote-ifadv_dev \
  --fused-run   eval/results/20260722-2023-merged-liveturns-offwords-ifadv_dev
```

## Results v1 — 2026-07-22 ⚠️ VERVUILD DOOR GEMETEN RECHTER-ARTEFACT — niet citeren

**Artefact (bewezen met een swap-probe, 2026-07-23 00:05):** de rechter ankert op
sprekerlabelNAMEN ondanks de semantische instructie — dezelfde E-samenvatting met
Spk1↔Spk2 geswapt flipte het oordeel 'fout'→'correct'. Gevolg: voor elke gelabelde
machineconditie is de attributiescore per item een muntworp (loopt de labelnummering
toevallig met goud mee of niet). Alleen R_gold is schoon. **Fix (uitgevoerd — zie v4):**
gelabelde condities (A/C/E) krijgen vóór het samenvatten een globale labelhernoeming naar
de gouden namen via tijdsoverlap (`remap_speakers_to_ref`); echte attributiefouten blijven
gewoon fout tellen. De v1-tabel hieronder blijft alleen staan als bewijsstuk van het
artefact; de v4-tabel verderop is de geldige meting.

Oude kop: N=6 (ifadv_dev), rechter+samenvatter = qwen36 (AEON 27B NVFP4)

Run: `eval/results/20260722-2121-summary-eval-ifadv_dev` (volledige logging; de eerdere stille
dood was een opgeslokte traceback + verhongerd NGC-LLM — beide verholpen). Per item kregen
**alle condities exact dezelfde 6 attributievragen** (geverifieerd), dus binnen-run-vergelijking
is geldig. 36 vragen per conditie.

| Conditie | attributie-acc | **misattributie** | dekking (1-5) | feitelijkheid (1-5) | hallucinaties (#) |
|---|---|---|---|---|---|
| R_gold (goud transcript+labels) | 0,50 | **0,083** | 3,67 | 2,50 | 1,83 |
| A_live_diar (turbo+Sortformer) | 0,28 | **0,278** | 3,00 | 2,00 | 4,17 |
| B_live_nodiar (zelfde tekst, labels weg) | 0,33 | **0,333** | 3,00 | 2,17 | 4,17 |
| C_off_diar (longform+pyannote) | 0,17 | **0,583** | 3,17 | 2,00 | 3,33 |
| D_off_nodiar (longform kaal) | 0,14 | **0,528** | 2,83 | 2,00 | 5,83 |
| E_fused_diar (productiepad: fusie) | *(v1-meting afgebroken: labels anti-uitgelijnd → artefact maximaal)* | | | | |

## Results v2 — afgebroken: tweede meetartefact gevonden (samenvatter-degeneratie)

Tijdens v2 bleek op DVA1A/E de "samenvatting" uit 700 uitroeptekens te bestaan (zeldzame
degeneratie van de samenvatter; v1 had 30 nette samenvattingen van hetzelfde model) — en
**de rechter gaf die garbage 6/6 attributie + feitelijkheid 5 + 0 hallucinaties**. Rechters
zijn dus niet robuust tegen gedegenereerde invoer. Fixes (beide in eval/summary_eval.py):
`is_degenerate()`-detectie + `summarize_robust()` (herkansing op temp 0,2→0,5→0,8) en een
rechter-bypass die gedegenereerde samenvattingen zonder LLM-aanroep alles 'absent' +
bodemscores geeft (met `degenerate: true`-vlag in de uitvoer).

## Results v3 — afgebroken: degeneratie bleek prefix-cache-corruptie in de LLM-server

v3 draaide met remap + guards, maar twee cellen (DVA1A/E, DVA3E/A) degenereerden op ALLE
temperaturen — temperatuuronafhankelijkheid wees naar de server, niet naar sampling.
**Bewijs (probes 02:30):** exact dezelfde twee trigger-prompts op een verse server ZONDER
prefix-caching → beide schoon. Oorzaak: vLLM-prefix-caching is experimenteel op hybride
Mamba-architecturen (Qwen3.6) en vergiftigde het cachevoorvoegsel. Server draait sinds
02:20 permanent met `--no-enable-prefix-caching` (OPS-LLM.md VALKUIL 2).

## Results v4 — DE GELDIGE METING (2026-07-23, N=6 ifadv_dev, 36 vragen/conditie)

Run: `eval/results/20260723-0025-summary-eval-ifadv_dev`. Alle drie de gemeten artefacten
verholpen: labelhernoeming (A/C/E), degeneratie-guards, én LLM-server zonder prefix-caching.
Rechter+samenvatter = qwen36 (AEON 27B NVFP4). Zelfde 6 vragen per item voor alle condities.

| Conditie | attributie-acc | misattributie | dekking (1-5) | feitelijkheid (1-5) | hallucinaties (#) |
|---|---|---|---|---|---|
| R_gold (goud transcript+labels) | **0,75** | **0,028** | 4,00 | 2,67 | 1,67 |
| A_live_diar (turbo+Sortformer) | 0,69 | 0,111 | 2,83 | 1,83 | 4,50 |
| C_off_diar (longform+pyannote, hernoemd) | 0,61 | 0,139 | 3,50 | 2,33 | 3,67 |
| E_fused_diar (productiepad: fusie) | 0,56 | 0,111 | 2,83 | 2,00 | 5,83 |
| B_live_nodiar (zelfde tekst als A, labels weg) | 0,19 | 0,583 | 2,67 | 2,00 | 4,50 |
| D_off_nodiar (longform kaal) | 0,17 | 0,500 | 2,83 | 2,00 | 5,67 |

**HOOFDCONCLUSIE — het antwoord op de kernvraag van dit experiment:** een samenvatting van
een transcript MÉT sprekerlabels is dramatisch beter in wie-zei-wat: **attributie-accuratesse
×3,5 (0,61–0,69 vs 0,17–0,19) en misattributie ×4–5 lager (11–14% vs 50–58%)** — het
zuiverste bewijs in dit project dat diarization geen nice-to-have is maar een voorwaarde
voor bruikbare gespreksverslagen. (A vs B is de schoonste vergelijking: identieke tekst,
alleen de labels verschillen.)

**Verdere bevindingen:**
1. De drie gelabelde machinecondities (A/C/E) clusteren op attributie (0,56–0,69; deltas
   < 0,15 zijn ruis bij N=6) — de labelBRON maakt minder uit dan het HEBBEN van labels.
2. Goud blijft duidelijk beter op misattributie (2,8% vs 11–14%) en vooral hallucinaties
   (1,7 vs 3,7–5,8): **transcriptkwaliteit is de resterende hefboom** voor feitelijke
   betrouwbaarheid, consistent met de fusie/CGN-VALUE-bevindingen.
3. Het productiepad (E, fusie) presteert gelijkwaardig aan de beste gelabelde condities op
   attributie; zijn hallucinatie-uitschieter komt uit de 2 zwaarste dialogen (DVA10O/12S).
4. v1's conclusie ("labels helpen een beetje") onderschatte het effect grof — het
   labelnaam-artefact drukte juist de gelabelde condities omlaag. Meetprotocol-lessen
   (hieronder en in PROGRESS.md) zijn blijvend in het script verwerkt.

**Meetprotocol-lessen (hard bewezen deze nacht, alle drie met probe/bewijs):**
- Rechters ankeren op labelNAMEN ondanks semantische instructie → hernoem hyp-labels naar
  goud via tijdsoverlap vóór het samenvatten.
- Rechters zijn niet robuust tegen gedegenereerde samenvattingen (gaven "!!!…" 6/6 correct)
  → detecteer en bypass.
- vLLM-prefix-caching op hybride Mamba-modellen corrumpeert deterministisch → uit.

## Live summarization in the app (implemented)

In de app: de Gesprek-tab toont een doorlopend gespreksverslag tijdens de opname; het
Archief-detail maakt verslagen per sjabloon (met rollen en versiebeheer — zie WEBAPP.md).
Backend: `POST /api/summarize` → `SUMMARIZER_URL` (OpenAI-compatibel).
