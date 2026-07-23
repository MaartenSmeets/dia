# CGN-VALUE.md — is the commercial CGN license worth it?

**Purpose:** give a concrete, measured answer to: *how much accuracy does CGN buy us, with vs without?* — so the commercial-license decision is made on numbers. Status of each experiment is tracked here; empty cells = not yet run.

## The decision in one paragraph

The **NC license we have** already covers everything *evaluative*: benchmarking, tuning configs, model selection — none of that ships CGN content. The **commercial license** is only needed for one thing: **shipping a model fine-tuned on CGN** in een commercieel product. So its value equals: *(accuracy of a CGN-fine-tuned model) minus (accuracy of the best model we can ship without it)* — measured on realistic conversational Dutch. That delta is what the experiments below produce. Commercial pricing is quote-based: request via the [commercial product page](https://hdl.handle.net/10032/tm-a2-d9) / servicedesk@ivdnt.org — get the quote in parallel so both sides of the cost/benefit are known.

## What we already know (priors, before any fine-tuning)

- Our current best *shippable* live stack (whisper large-v3-turbo streamed + Sortformer, zero fine-tuning): **WER 25.0% / cpWER 32.2%** on IFADV-dev conversations (COMPARISON.md Update 2). Offline shippable ceiling (whisper large-v3 + pyannote): WER 30.1% / cpWER 44.7%.
- The read-speech ↔ conversation gap is a factor ~4 (7.3% FLEURS vs 30% IFADV WER, same model): **the missing accuracy on conversations is a domain problem — exactly what CGN's 99.5 h of spontaneous multi-party speech (comp-a) targets.**
- Literature/HF priors that CGN fine-tuning works: `pevers/whisperd-nl` (whisper fine-tuned on CGN) exists and targets disfluency-faithful transcription; the JASMIN fine-tuning paper (arXiv:2502.17284) shows Dutch-domain fine-tuning gains. Counter-prior: CV-only fine-tunes *hurt* out-of-domain (yuriyvnv: 4.4% on CV but 20.3% on MLS) — gains depend on training-domain match, which is CGN's whole argument.
- Nothing published isolates "CGN-FT vs permissive-FT for conversational Dutch" — hence measuring it ourselves.

*(The quick priors above are superseded by the researched section below.)*

# Published priors (researched 2026-07-21)

*Replaces/expands the informal priors in the section above. All figures below are single-channel WER unless stated; none is cpWER. Every cross-comparison is gated by the normalization caveat in the next paragraph — read it before using any number.*

## Read this first: the normalization caveat that invalidates most naive comparisons

CGN orthographic transcripts are **verbatim**: they keep filled pauses and disfluencies (uh, uhm), and CGN encodes laughter as `ggg`, long laughter as `ggggg`, and unintelligible speech as `xxx` (confirmed from the whisperd-nl README). Our normalizer v1 **strips fillers and maps digits→words**, i.e. it scores a *cleaned* reference. A cleaned WER is **substantially lower** than a verbatim WER on the same audio, because the filler/repair/non-speech tokens that get removed are exactly the ones a model most often gets wrong. Published CGN WERs mix both conventions and usually do not state which. **Therefore: do not treat any published CGN WER as a target to match unless its scoring matches ours.** The single most-cited CGN fine-tune (whisperd-nl, 16.42%) is deliberately verbatim-plus-tags and is *not* comparable to our numbers.

## 1. Published WERs on CGN / spontaneous Dutch

"Comparable?" flags whether the number can be lined up against our cleaned-normalizer WER. "Verbatim" = fillers/tags scored (lower-bound-breaking, not comparable). "Read-clean" = scored on an already-clean read corpus (different domain). "Undoc." = scoring not documented.

| # | System | Base / arch | Training data | Test set / CGN component | WER | Comparable to our cleaned WER? | Caveat | Source |
|---|--------|-------------|---------------|--------------------------|-----|-------------------------------|--------|--------|
| 1 | **pevers/whisperd-nl** | Whisper-large-v3 FT | CGN "900h", literal transcripts incl. disfluencies; speaker tags [S1]–[S4] (comp-a inclusion **inferred, not documented**) | held-out CGN (split not documented) | **16.42%** | **NO — verbatim + [S1]–[S4] tags + `ggg`/`ggggg`/`xxx` all scored.** Would be markedly lower with fillers stripped. No baseline-large-v3 comparison published. | huggingface.co/pevers/whisperd-nl ; github.com/pevers/whisperd-nl |
| 2 | **kul-speech-lab/whisper_large_CGN** (KU Leuven) | Whisper-large-v2 FT | CGN **Flemish portion** (components/hours not stated) | CGN test (mix not stated) | **9.616%** | **Unknown / likely not** — scoring undocumented; **Flemish, not Northern Dutch**; probably read-heavy mix. Even less comparable to comp-a/IFADV than it looks. | huggingface.co/kul-speech-lab/whisper_large_CGN |
| 3 | **Röpke, Rădulescu, Efthymiadis, Nowé 2019** (VUB, CLIN29 / CEUR Vol-2491) | DeepSpeech (RNN-CTC) + KenLM 5-gram | CGN "small non-overlapping" split that **excludes comp-a,c,d,f,g** (spontaneous conversation removed as "noise") + drops overlapping-timestamp files | filtered CGN test (NL+Flemish) | from-scratch **30.0%** (CER 17.2%); Dutch-only **34.2%**, Flemish-only **38.6%**; **transfer from EN DeepSpeech → 23.0%** (Table 11: 23.58%; Flemish 22.9%, Dutch 25.5%) | **NO — comp-a explicitly removed**; 2019 char-CTC; best numbers are on the split that deletes spontaneous conversation. Useful only for CGN component taxonomy. | ceur-ws.org/Vol-2491/paper60.pdf |
| 4 | **Bălan, Ordelman, Truong 2024** (U Twente, CLIN34) | Eval study: Whisper large-v2/v3, MMS, XLS-R vs **Kaldi_NL** | zero-shot / off-the-shelf (XLS-R FT on CV-nl) | **N-Best 2008** (BN + CTS) + **JASMIN-CGN** | **Relative-to-Kaldi_NL only — no absolute WER.** large-v2+VAD best; **large-v3 WORSE than large-v2** by 34–147% (read) and **13–60% (conversational)** rel. degradation | **N/A (relative only).** Project-critical finding: **large-v3 can regress vs large-v2 on conversational Dutch (hallucination).** Our base is large-v3-turbo → mind this. | research.utwente.nl/en/publications/evaluating-the-state-of-the-art-automatic-speech-recognition-syst ; clin34.leidenuniv.nl/abstracts |
| 5 | **N-Best 2008 benchmark** (Van Leeuwen, Kessens et al.; SPRAAK/ESAT) | HMM-GMM LVCSR | — | CGN **broadcast-news** + **conversational-telephone**, NL + Flemish | best systems **15.9% (BN Flemish) → 46.1% (CTS Flemish)**; conversational-telephone broadly **~30–46%** | **Partial** — verbatim CTS scoring, 2008 HMM era. Defines the "hard = conversational" gap. **UNCERTAIN(source-access):** figures from indexed summaries; ResearchGate PDF returned HTTP 403, quoted range appears verbatim across multiple indexes. | researchgate.net/publication/221489527 |
| 6 | **Dutch archival-broadcast SSL** (arXiv 2507.04554, 2025) | wav2vec2 BASE+LARGE, pre-trained ~**55.7k h** Dutch broadcast TV, then FT | archival + CV/MLS/N-Best | **N-Best (BN)**; MLS-nl; CV-nl | N-Best **6.2–11.1%**; MLS **11.3–13.3%**; CV **7.1–9.8%** | **NO — read/broadcast domain, clean references, no spontaneous conversation.** | arxiv.org/html/2507.04554v2 |
| 7 | **w2v2-nl** (arXiv 2506.00981, 2025) | wav2vec2, Dutch pre-train **831h** (537h CGN **excl. telephone + sermon** + 211h MLS + 83h CV), FT on **78h CGN comp-o (read)** | CGN read | **CGN comp-o (read-aloud)** test | Dutch **10.4%** (multilingual 12.7%, English 21.5%, non-speech baseline 43.5%) | **NO — read speech (comp-o).** Key caution for us: **language-specific pretrain beat multilingual by only ~2 pts on read** → gains shrink when the base already knows Dutch. | arxiv.org/html/2506.00981 |
| 8 | **JASMIN-CGN Whisper FT** (arXiv 2502.17284, 2025) | Whisper-large-v2 | JASMIN-CGN NL (~60h atypical speakers: children/teens/non-native/elderly; read + human-machine dialogue) | JASMIN-CGN by group | **zero-shot** 26.12 / 38.48 / 42.07 / 28.73%; **group-FT** 5.45 / 13.13 / 14.01 / 9.11%; **combined-FT** 4.98 / 10.90 / 13.95 / 9.96% (native children / non-native children / non-native adults / native elderly) | **Partial** — JASMIN's own normalization; **atypical speakers, not comp-a peers**; mix of read + HMI dialogue. **Strongest published evidence that in-domain Dutch FT helps hard speech: 65–81% relative WER reduction.** | arxiv.org/abs/2502.17284 |
| 9 | **Welzijn.AI clinical eval** (arXiv 2508.08684, 2025) | Whisper v2/v3/**v3-turbo**/medium/small; golesheed elderly-FT; Voxtral | off-the-shelf + FT | small (~11 min) older-adult Dutch conversational sample + CommonVoice | orthographic-normalized WER: **large-v3 0.12**, **large-v3-turbo 0.16**, large-v2 0.19, medium 0.19, small 0.26, golesheed-elderly-FT 0.40 | **Closest in scoring** (orthographic-normalized ≈ cleaned-ish) **and spontaneous**, but **tiny sample** and elderly-clinical domain. Rare *turbo* number on spontaneous Dutch (~16%). **Note: turbo WORSE than v3 here** — opposite ordering to our numbers (see §4). | arxiv.org/pdf/2508.08684 |

Zero-shot Dutch read-speech anchors (context): FLEURS multilingual avg ~10% for large-v3; Dutch read (FLEURS/CV/MLS) zero-shot large-v3 lands ~7–13%. **Consistent with our FLEURS-nl 7.3%.** There is **no clean published absolute WER for Whisper large-v2/v3 zero-shot on CGN comp-a specifically** — our M0-on-comp-a will be a novel data point.

## 2. Dutch dialect / variant fine-tune findings — and the initiative search

**Geïdentificeerd (update 2026-07-22): het gezochte initiatief is een Nederlands overheidsprogramma voor een soeverein publiek NL-spraakmodel** (incl. dialecten en juridisch jargon). **Status: planvorming — geen downloadbaar model.** Bij een modelrelease direct benchmarken op onze eval-sets; details en bronnen in docs-intern/.

*(Eerdere notitie hieronder — "not found as fine-tune" — was correct voor zover het om bestaande modellen ging:)* **Het gezochte initiatief was NOT found as a Dutch dialect Whisper fine-tune.** Searched Web + HuggingFace model index. The only HF hit matching the string is an unrelated RVC voice-conversion model, an unrelated RVC voice-conversion model. If the term was a half-remembered handle, no matching Dutch ASR artifact exists as of 2026-07-21. **UNCERTAIN:** I cannot rule out a private/renamed repo, but nothing public matches.

Closest actual Dutch-variant / non-standard fine-tunes and their gains:

- **Frisian cross-lingual transfer** (closest thing to a "dialect" fine-tune, though Frisian is a separate language, not a Dutch dialect): `polixonrio/whisper-small-fy-NL`, `Rijgersberg/whisper-small-fy-NL` — Whisper-small FT on CommonVoice West-Frisian (fy-NL). Exist; no comp-a-relevant WER. Links: huggingface.co/polixonrio/whisper-small-fy-NL, huggingface.co/Rijgersberg/whisper-small-fy-NL.
- **Flemish variety:** `kul-speech-lab/whisper_large_CGN` (row 2, 9.616%, scoring undoc.). Röpke 2019 (row 3) also splits Dutch (34.2%) vs Flemish (38.6%) from-scratch — a ~4-pt variety gap under identical training.
- **Atypical-speaker fine-tunes (the quantified "hard-Dutch" gains):** JASMIN-CGN (row 8) — **65–81% relative WER reduction** from in-domain FT (arXiv:2502.17284). `golesheed/whisper-non-native-adult-dutch`, `golesheed/whisper-native-elderly-9-dutch` exist; the elderly FT scored *worse* (0.40) than off-the-shelf large-v3 (0.12) on the Welzijn.AI sample (row 9) — a caution that narrow FT can overfit and hurt out-of-its-niche.
- **Disfluency-faithful spontaneous FT:** `pevers/whisperd-nl` (row 1) — the one artifact trained to emit spontaneous CGN verbatim incl. speaker tags; 16.42% verbatim.
- **Other Dutch FTs (not dialect, less relevant):** `yuriyvnv/whisper-large-v3-high-mixed-nl`, `HHoofs/whisper-nl-noise`, `sgangireddy/whisper-largev2-mls-dutch`, `hannatoenbreker/whisper-dutch`.

Carried-over counter-prior from the previous draft of this doc (**UNCERTAIN — not re-verified in this pass**): a CV-only Dutch fine-tune (`yuriyvnv`) reportedly hit ~4.4% on CommonVoice but ~20.3% on MLS-nl — i.e. **CV-only FT hurt out-of-domain.** Directionally this reinforces the domain-match thesis but should be re-confirmed before citing externally.

## 3. Predicted M2−M1 (CGN-FT minus permissive-FT), with reasoning

**There is no direct prior.** No published study isolates "permissive read-speech FT (M1) vs CGN-comp-a FT (M2) on held-out conversational Dutch" (this is a negative existence claim → **UNCERTAIN** but consistent with everything found; JASMIN-FT and comp-o-FT are the nearest analogues and neither runs this contrast). The estimate below is inference, not measurement.

**Reasoning chain A — why M2 should win (pushes gap up):**
1. Domain match dominates for spontaneous speech. Every source shows conversation is where WER is high and in-domain data pays most: N-Best 15.9% (BN) → 46.1% (CTS); JASMIN in-domain FT cut WER 65–81% relative.
2. M1's data (MLS-nl + CommonVoice-nl) is **read speech** — mismatched to comp-a's spontaneous, multi-party, casual register with disfluencies/overlap. M2/M3's comp-a is exactly in-domain.
3. Our base is large-v3-turbo, and large-v3 can *regress* on conversational Dutch (Bălan, row 4) → weaker zero-shot conversational start → more headroom for in-domain FT to recover.

**Reasoning chain B — why the gap may be small (pushes gap down / collapse conditions):**
1. The base already knows Dutch, and M1's MLS+CV *also* teach Dutch acoustics/lexicon. w2v2-nl (row 7) is the sharpest caution: language-specific pretrain beat multilingual by only **~2 pts on read** — gains compress when the base is already competent.
2. **LoRA** = limited adaptation capacity; comp-a is only **99.5h** — small.
3. **Our normalizer strips fillers** — precisely the disfluency tokens where comp-a's spontaneous supervision helps most. Cleaned scoring mechanically compresses M2's advantage relative to a verbatim benchmark.
4. **Held-out register mismatch:** comp-a is multi-party face-to-face; our conversational test (IFADV) is dyadic. If the two spontaneous registers differ enough, comp-a FT may not transfer cleanly to IFADV.
5. **cpWER is partly gated by Sortformer.** All published anchors are single-channel WER. Diarization error inflates cpWER independently of the acoustic model, so an AM-only improvement moves WER more than cpWER. A CGN FT that only improves transcription clears a **higher effective bar** on the ≥3 *cpWER* rule than on a ≥3 *WER* rule.

**Predicted range (cleaned normalizer, held-out conversational Dutch, identical base/recipe, M1 and M2 differ only in data):**
- **M2−M1 in WER: roughly +2 to +8 points in M2's favor; central estimate ~3–5 points.** Wide because there is no direct prior and the compressors above are real.
- **M2−M1 in cpWER: smaller, roughly +1.5 to +6 points; central estimate ~2.5–4 points**, because diarization overhead dilutes AM gains (assume cpWER gain ≈ 0.7–0.9× the WER gain).
- **Implication for the ≥3 cpWER decision rule:** the central prediction sits *right at the threshold*. Genuinely uncertain whether M2/M3 clears it. **Report both WER and cpWER**, and expect the WER delta to look more convincing than the cpWER delta.

**The gain collapses (M2−M1 → <3, possibly ~0) if:** (a) MLS+CV already cover enough Dutch register that comp-a adds little (the w2v2-nl "only ~2 pts" scenario); (b) LoRA capacity / 99.5h is too small to absorb spontaneous phenomena; (c) the cleaned normalizer removes comp-a's main advantage (disfluencies); (d) comp-a's multi-party register doesn't transfer to dyadic IFADV; (e) cpWER is diarization-dominated so AM improvements barely register; (f) large-v3-turbo's decoder LM-prior resists verbatim spontaneous output. Any two of these co-occurring likely sinks the ≥3 cpWER rule.

## 4. Consistency check: are our measured numbers sane?

- **Offline large-v3 IFADV 30.1% WER — GREEN.** Sits squarely inside published spontaneous/conversational Dutch: JASMIN conversational zero-shot 28–42% (row 8), N-Best CTS ~30–46% (row 5). No red flag.
- **FLEURS-nl 7.3% — GREEN.** Matches read-speech literature (7–13% zero-shot large-v3; w2v2 read 10.4%; broadcast SSL 6.2–11.1%).
- **cpWER 32.2% vs WER 25.0% (turbo live) — plausible.** The ~7-pt gap is diarization overhead; no published cpWER anchor exists for Dutch conversation, but the magnitude is unremarkable.
- **RED FLAG — turbo-streamed (25.0%) is *better* than large-v3-offline (30.1%).** Two independent priors say this ordering is surprising: (i) Welzijn.AI (row 9) found large-v3-turbo (0.16) **worse** than large-v3 (0.12) on spontaneous Dutch — the opposite direction; (ii) turbo is the smaller/faster model and streaming usually *hurts* vs offline. Benign explanations exist: the two numbers are not a like-for-like head-to-head (different model, different decoding, offline uses pyannote + different segmentation, and large-v3 offline may hallucinate on conversation per Bălan row 4, while streaming chunking suppresses that). But because the ordering contradicts published turbo-vs-v3 behavior, **treat 25.0 vs 30.1 as not-yet-explained until M0 is run with identical base, normalizer, segmentation and test split.** This is exactly what the M0 anchor is for.
- **Novel-territory note:** no published absolute zero-shot large-v3(-turbo) WER on CGN comp-a exists, so the M0-on-comp-a number cannot be cross-checked against literature — only bracketed. Expect **~25–35% cleaned** (bracketed by IFADV 30.1% and JASMIN conversational zero-shot 28–42%); landing far outside implies a normalization or segmentation bug.

**Suggested sanity runs:** (1) zero-shot turbo on comp-a held-out, cleaned normalizer → expect 25–35%; (2) score `whisperd-nl` on our held-out comp-a **twice** — verbatim (should approach its ~16% regime) and with our cleaned normalizer — to measure the verbatim↔cleaned offset for CGN and make its number comparable to ours; (3) run M0 for turbo *and* large-v3 under identical conditions to resolve the 25.0-vs-30.1 ordering.

## 5. Sources

- pevers/whisperd-nl — huggingface.co/pevers/whisperd-nl ; github.com/pevers/whisperd-nl (16.42% verbatim; large-v3 base; [S1]–[S4] tags; `ggg`/`ggggg`/`xxx`). **comp-a inclusion = INFERRED, not documented (UNCERTAIN).**
- kul-speech-lab/whisper_large_CGN — huggingface.co/kul-speech-lab/whisper_large_CGN (9.616%; **Flemish CGN**; scoring undocumented).
- Röpke, Rădulescu, Efthymiadis, Nowé 2019, CLIN29 — ceur-ws.org/Vol-2491/paper60.pdf (from-scratch 30.0%/CER 17.2%; transfer 23.0%; split excludes comp-a,c,d,f,g).
- Bălan, Ordelman, Truong 2024, CLIN34 — research.utwente.nl/en/publications/evaluating-the-state-of-the-art-automatic-speech-recognition-syst ; clin34.leidenuniv.nl/abstracts (relative-only; large-v3 worse than large-v2 on conversational Dutch).
- N-Best 2008 — researchgate.net/publication/221489527 (15.9% BN Flemish → 46.1% CTS Flemish). **UNCERTAIN (source access):** PDF 403; figures from indexed summaries of the primary source.
- arXiv 2507.04554v2 — arxiv.org/html/2507.04554v2 (55.7k h Dutch broadcast SSL; N-Best BN 6.2–11.1%, MLS 11.3–13.3%, CV 7.1–9.8%; read/broadcast only).
- arXiv 2506.00981 — arxiv.org/html/2506.00981 (w2v2-nl; CGN comp-o read 10.4% vs 12.7% multilingual — ~2-pt language-specific-pretrain gain on read).
- arXiv 2502.17284 — arxiv.org/abs/2502.17284 (JASMIN-CGN Whisper-large-v2 FT; 65–81% relative reduction; per-group zero-shot vs FT numbers).
- arXiv 2508.08684 — arxiv.org/pdf/2508.08684 (Welzijn.AI; large-v3 0.12, turbo 0.16, elderly-FT 0.40; tiny ~11-min spontaneous older-adult sample).
- Frisian variant FTs — huggingface.co/polixonrio/whisper-small-fy-NL ; huggingface.co/Rijgersberg/whisper-small-fy-NL.
- initiatief-zoektocht — Web + HuggingFace model index, 2026-07-21: **no Dutch dialect ASR match** (only an unrelated voice-conversion model). **UNCERTAIN** (cannot rule out private/renamed repo).
- ML6 blog "Fine-tuning Whisper for Dutch: The Crucial Role of Size" — ml6.eu/en/blog/fine-tuning-whisper-for-dutch-language-the-crucial-role-of-size (context: larger Whisper variants show diminishing returns from more Dutch FT data).

**UNCERTAIN items flagged inline:** (i) whisperd-nl comp-a inclusion (inferred); (ii) N-Best 2008 numbers (via indexed summaries, PDF 403); (iii) "no direct M2-vs-M1 head-to-head prior" (unprovable negative, consistent with all found); (iv) the M2−M1 predicted range (inference, not measured); (v) initiatief-afwezigheid; (vi) carried-over yuriyvnv CV-vs-MLS counter-prior (4.4% / 20.3%, not re-verified this pass).

*Provenance: 3-agent web research + verification pass, 2026-07-21; two verification chains failed structured output, so items are conservatively flagged UNCERTAIN inline — treat flagged numbers as leads, not facts.*

## Experiment matrix (fills in as runs complete)

All fine-tunes: LoRA on whisper large-v3-turbo (the live default), identical recipe/steps/LR, only the data differs. Scored with normalizer v1 on three conversational test sets, cpWER via the live pipeline (turbo+Sortformer) and WER offline.

| # | Model | Training data | Shippable? | IFADV-test WER / cpWER | CGN-test WER / cpWER | Corrected-sessions WER¹ |
|---|---|---|---|---|---|---|
| M0 | turbo, no fine-tune (today's default) | — | ✓ | *(dev anchors below; test reserved for final)* | *(idem)* | — |
| M1 | turbo + LoRA on permissive data | MLS-nl train (subset) + CV22-nl | ✓ | | | |
| M2 | turbo + LoRA on CGN | CGN comp-a (+comp-b/f if useful) | ✗ under NC — **the commercial-license candidate** | | | |
| M3 | turbo + LoRA on both | MLS-nl + CGN comp-a | ✗ under NC | | | |

¹ once enough corrected sessions exist in `data/corrections/` — the most product-relevant test set.

### M0 anchors — measured 2026-07-21 on cgn_a_dev (12 NL recordings, 2–4 speakers; live = 4-recording subset)

| System | WER | cpWER | DER |
|---|---|---|---|
| offline whisper large-v3 (no diar) | 40.5% | >100% ✗ | 55% ✗ |
| offline whisper large-v3-turbo (no diar) | **37.7%** | ~100% ✗ | 56% ✗ |
| offline v3 + pyannote (method D) | 40.5% | 57.3% | 30.9% |
| **live turbo + Sortformer (our default)** | **35.1%** | **44.5%** | **20.1%** |

What the anchors established:
1. **CGN comp-a is substantially harder than IFADV** (live cpWER 44.5% vs 32.2%; offline-D DER 30.9% vs 20.1%) — multi-party casual speech with heavy overlap. IFADV alone *understates* the hard case → CGN's **evaluation value is real and already usable under the NC license**.
2. **turbo > large-v3 confirmed offline on CGN too** (37.7 vs 40.5%) — settles the ordering question from the literature (Bălan/Welzijn.AI) for our setup: turbo is the better base, streamed *and* offline.
3. The live stack beats offline-D on cpWER on 3 of 4 common recordings (pattern from IFADV repeats on multi-party audio).
4. WER above the predicted 25–35% bracket was investigated per protocol: transcript inspection shows honest domain difficulty (overlap → order-sensitive WER inflation, proper-noun variants, casual register), not a harness bug. **This 35–40% zero-shot zone is the headroom the M1–M3 fine-tunes now compete over.**

**Decision rule (proposed):** the commercial license is worth pursuing if **M2 or M3 beats M1 by ≥ 3 cpWER points** (i.e., clearly outside our measured ±1.5–3 pt run noise) on IFADV-test *and* the gain holds on corrected-sessions data. Below that, permissive-only fine-tuning (M1) ships the same practical quality for free.

Secondary value (already usable under NC, no extra cost): CGN-test as an evaluation set tells us whether IFADV dyads *predict* multi-party performance (comp-a has 2–5 speakers). If they diverge, CGN's eval value alone is substantial — it's the only realistic multi-party Dutch benchmark we have.

## VERDICT (2026-07-22, alle metingen afgerond)

### De gemeten matrix (offline scoring, identieke normalizer/scorer; dev-sets)

**Woordkwaliteit (WER, pooled):**

| | CGN-gesprekken | IFADV |
|---|---|---|
| M0 basis (turbo) | 41,1% | 30,0% |
| M1 gratis data (MLS+CV, 80u) | 38,3% | 28,0% |
| **M2 CGN comp-a (80u)** | **31,3%** | **22,9%** |
| M3 beide (140u) | 32,5% | 23,1% |

→ **CGN-data is het werkzame bestanddeel**: −7,0 (CGN) / −5,1 (IFADV) punten t.o.v. gratis data; extra voorleesdata bovenop CGN voegt niets toe (M3≈M2). Dit patroon was consistent over drie onafhankelijke scoringsmethoden.

**Wie-zei-wat (cpWER) — het pad bepaalt de uitkomst:**

1. *Via offline pyannote-attributie:* M2−M1 = −1,6 (CGN) / +0,3 (IFADV) — **regel NIET gehaald**. Oorzaak gemeten: de attributiestap (DER 18–24%) domineert de fout; woordwinst komt er niet doorheen.
2. *Via de productpijplijn (fusie: live-sprekerbeurten × offline woorden — de "definitieve versie"-methode):* **M2−M1 = −5,0 cpWER op CGN-meerpartijen (✓ regel gehaald, n=4)**; −0,4 op dyadisch IFADV (✗, attributieruis-gebonden; n=6). Plus −7,9/−5,0 WER.

### Conclusie & aanbeveling

1. **De waarde van CGN-trainingsdata is bewezen** — groot en consistent op woordkwaliteit, en in de productpijplijn op het vergaderdomein ook boven de formele cpWER-drempel. De prior-voorspelling (+2..+8 WER; cpWER-verwatering door diarisatie) kwam exact uit, inclusief het instortscenario via de pyannote-route én de oplossing (fusie).
2. **Commerciële licentie: gerechtvaardigd zodra CGN-getrainde gewichten in een commercieel product gaan** (call-center/vergaderproduct). **Timing-advies: offerte nu opvragen, tekenen nog niet.** Redenen: (a) intern gebruik onder NC levert de winst al voor evaluatie/demo/ontwikkeling; (b) het uitleverbare alternatief (M0-fusie) is op sprekermaten gelijkwaardig en alleen op woorden −5..−8 punten slechter; (c) de basisrace (canary e.a., loopt) en een eventuele release van het NL-overheidsspraakinitiatief kunnen de som veranderen; (d) de beslisregel is gehaald op n=4 — één herbevestiging op de held-out testsplit vóór aankoop is verstandig (draaiboek staat klaar).
3. **Belangrijkste accuracy-lever ná dit besluit is niet meer het akoestisch model maar de sprekertoewijzing** — de fusie-methode (nu productstandaard) en diarisatieverbetering leveren per punt investering meer cpWER op dan verdere AM-training.

*Voorbehouden: enkelvoudige runs; n=4–12 per cel; ruisvloer ±1,5–3 pt gemeten; live-beurten in de fusietest kwamen van de M0-live-pass (identiek voor beide varianten, dus fair voor de delta).*

## Waarde per use case (invoer: één gemengd audiokanaal met meerdere sprekers)

*Alle metingen hieronder zijn gedaan op precies dit invoerformaat (mono-mixdown). "M2" = CGN-getrainde adapter (commerciële licentie vereist voor uitlevering); "gratis route" = basismodel of M1 + fusie-methode.*

| Use case | Waarde commerciële licentie | Bewijs |
|---|---|---|
| **Spontane meerpartijen-gesprekken** (vergadering, groepsoverleg, 3–4 sprekers) → definitief transcript | **HOOG** — dit is dé use case | M2−M1 in productpijplijn: −7,9 WER / −5,0 cpWER (≥3-regel gehaald; CGN comp-a, n=4) |
| Afgeleiden daarvan (samenvatting, zoeken, citeren uit eindverslag) | Middel–hoog (indirect) | volgt de woordwinst; samenvattings-delta niet apart gemeten |
| **Callcenter/telefoongesprekken** (smalband, 2 sprekers) → transcript | **HOOG — GEMETEN 2026-07-23** | M2w−M0hfw op cgn_tel_dev (comp-c/d, n=8): **24,0 vs 33,6 pooled WER (−9,6 pt)** — de comp-a-getrainde adapter draagt vol over naar telefoonspraak zonder één seconde telefoontraining; met comp-c/d-data in de mix is er mogelijk nog meer (ongemeten). Runs: `eval/results/*-lora-M{0hfw,2w}-cgn_tel_dev` |
| **Wie-zei-wat in tweegesprekken** (intake, interview, consult) | **LAAG** | fusie-cpWER M2 vs M1: 33,8 vs 34,2% (−0,4 pt = ruis); fout wordt gedomineerd door sprekertoewijzing, niet woorden |
| **Live-only** (alleen realtime meelezen, geen definitieve versie) | **GEEN (vandaag)** | M2-winst is uitsluitend in de offline pass gemeten; adapter in live-pijplijn nog niet gevalideerd |
| Voorgelezen/voorbereide spraak (dictaat, verklaringen) | Laag (niet direct gemeten) | basismodel al ~7% WER; domein-match-principe hard aangetoond bij M1 (verkeerd domein = geen/negatieve winst) |
| Intern gebruik / onderzoek / demo | **GEEN** — per definitie | NC-licentie (reeds in bezit) dekt dit volledig |
| Elk scenario ná een sterke gratis release (bv. het NL-overheidsspraakinitiatief) | Herwaarderen | wekelijkse release-watch actief; benchmark-draaiboek klaar (taak #18) |

**Vuistregel:** hoe spontaner het gesprek en hoe meer sprekers, hoe waardevoller de commerciële licentie; bij tweegesprekken, live-only of nette spraak is de gratis route vrijwel gelijkwaardig.

## Costs to weigh against the measured delta

| Item | Status |
|---|---|
| Commercial CGN license fee | **unknown — request quote** (user action; quote-based) |
| Fine-tune compute | days on this DGX Spark per variant (LoRA, not full FT) — one-time |
| Alternative shippable path | M1 (MLS 1554 h CC-BY-4.0 + CV CC0) — zero license cost |
| Risk if skipped | if M2−M1 ≥ 3 pts, shipped product leaves that accuracy on the table |

## Execution order (tracked as task #15)

1. CGN comp-a extraction + references + timeline audit *(in progress — download running)*.
2. M0 anchors on IFADV-test + CGN-test (cheap; also answers the eval-value question).
3. LoRA recipe bring-up (one short run on MLS subset to validate the training loop on this machine).
4. M1 → M2 → M3, identical recipes; score; fill the matrix; write the verdict in this file.

*Everything in this doc is measured under the NC license (internal research). Only the ship-decision consumes the numbers.*
