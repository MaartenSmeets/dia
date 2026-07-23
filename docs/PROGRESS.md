# PROGRESS.md — levend journaal (nieuwste entry EERST; lees minimaal de actuele stand + de bovenste entries)

Regels: na elke betekenisvolle stap een entry PREPENDEN direct onder het actuele-stand-blok: datum · wat gedaan · wat **geverifieerd** (echt commando/output) · wat volgt / waar het op wacht. Entries nooit verwijderen; alleen doorhalen als iets actief misleidt, met een gedateerde correctie erbij.

## Actuele stand (bijgewerkt 2026-07-23)

- **Product:** de app is feature-compleet en jurist-gericht (tabs Gesprek · Bestand · Archief · Instellingen; expertmodus voor Live/Evaluatie) met verslagsjablonen, sprekerrollen en versiebeheer. E2E-suite 30/30 groen. Repo publiek: <https://github.com/MaartenSmeets/dia>.
- **Pijplijn (gemeten — COMPARISON.md §Eindstand):** live = whisper-large-v3-turbo + streaming Sortformer v2; definitieve versie = fusie van live-sprekerbeurten × offline-M2-woorden (turbo+CGN-LoRA, NC — intern gebruik); verslagen via een lokaal OpenAI-compatibel LLM (OPS-LLM.md).
- **Meetprogramma afgerond:** basisrace (M2 wint), summary-eval v4 (sprekerlabels = ×3,5 attributie-accuratesse), telefoontransfer (−9,6 WER), woordlatentie ~1,0 s p50, hybride-vergadering (geen aparte opwaardering nodig).
- **Open:** CGN-commerciële offerte is een gebruikersactie (CGN-VALUE.md §VERDICT); benchmark NL-overheidsmodel wacht op een externe release (watch op gebruikersverzoek uitgeschakeld).

---

## 2026-07-23 (nacht) — redactionele keuring van ALLE md-docs: ~150 bevindingen verwerkt, structuur + kruisverwijzingen consistent

**Op gebruikersverzoek ("alleen relevante inhoud, geen dubbelingen, niets in het verkeerde
document; opbouw logisch, duidelijke referenties"):** twee workflowrondes (4 groepslezers +
structuurlens ≈85 bevindingen; daarna een 5-groepen-kruisanalyse, 64 bevindingen) en alles
doc-voor-doc toegepast. Hoofdlijnen:
- **Eén canonieke plek per feit**, rest verwijst: alle meetuitslagen → COMPARISON.md (nieuwe
  "Eindstand"-tabel bovenaan); machinefeiten/regels → CLAUDE.md; LLM-ops → OPS-LLM.md
  (herordend: actieve setup eerst, MoE = terugvaloptie, typo's en ~tmp-verwijzingen weg);
  datasets as-built → DATASETS.md (CGN geleverd i.p.v. besteltodo); summary-eval-runprotocol
  → SUMMARY-EVAL.md (leeswijzer bovenaan, E-conditie in de ontwerptabel, v1-restanten weg).
- **Verouderde adviezen gedateerd i.p.v. stilletjes laten staan** (nieuwe CLAUDE-regel):
  RESEARCH.md kreeg Addendum 3 (turbo=live default, fusie=productiepad, CGN-waarde, latentie,
  OOM-update) + ⚠-markers op achterhaalde rijen/secties (§2/§4/§5/§6/§7/§8); COMPARISON-proza
  herscoord (45,9/20,1/25,1), open-experimentenlijst gesloten; PLAN.md statusblok.
- **Dit journaal hersorteerd** naar nieuwste-eerst conform de nieuwe kopregel, met
  actuele-stand-blok bovenaan; correctienotities toegevoegd (fonentelling dag 1, pre-rescore-
  DER's 15-07, privérepo→publiek), gevoelige restanten geneutraliseerd (docs-intern-,
  account-/portaaldetails, concurrentieduiding).
- **WEBAPP.md**: tabset actueel (Gesprek/Bestand/Archief/Instellingen + expert), §Meetings
  herordend (persistentie eerst), stale --ssl weg, testsectie = dekking i.p.v. momentopname.
**Geverifieerd:** geautomatiseerde link-/§-verwijzingscheck over alle md's schoon (enige hit
= WLK's eigen upstream-pad); geheimen-grep schoon (geen interne hostnaam, absolute paden, ~tmp- of
docs-intern-verwijzingen meer in publieke docs). Open ter beoordeling gebruiker: OPS-LLM documenteert de as-built
modelcontainer (community-AEON-image met "Uncensored"-modelnaam) — reputationeel wellicht
liever het officiële nvidia/Qwen3.6-27B-NVFP4 op dezelfde image valideren.

## 2026-07-23 (avond, vervolg) — reproduceerbare installatie + Docker + volledige handleiding (taak #24)

**Op gebruikersverzoek "runnen makkelijker" + "dockerfile" + "gedetailleerde README":**
- `requirements/{wlk,eval,vox}.txt`: exacte pins bevroren uit de draaiende venvs (incl.
  +cu130); **geverifieerd** door volledige herbouw van venvs/vox via uv (identiek, CUDA ok)
  en schone dry-run-resolutie van wlk/eval.
- `scripts/setup.sh`: één commando voor alle omgevingen (installeert uv zelf, GPU-smoketest
  na afloop); `pyproject.toml` als projectmarker (bewust geen package: gescheiden venvs);
  `.env.example` met alle variabelen gedocumenteerd.
- **Dockerfile + docker-compose.yml**: image gebouwd (8,99 GB; build-essential nodig voor
  aarch64-sdists zoals meeteval) en **geverifieerd met GPU**: container-import torch
  2.11.0+cu130, cuda True, WLK laadt. LLM blijft bewust een externe container.
- **README volledig herschreven** als gebruikershandleiding: functionaliteit, werking
  (mermaid-schema), systeemvereisten, 3 installatieroutes, LLM-opzet met concreet
  vLLM-voorbeeld, configuratietabel (.env/Instellingen/expert), doorloopvoorbeeld
  intake→verslag, FAQ, licentie-/modellentabel, documentatiekaart.
- Opgeruimd op gebruikersverzoek: wekelijkse release-watch (cloud-routine) uitgeschakeld,
  taak #18 vervallen; alle lokale monitors waren al klaar (0 actief).

## 2026-07-23 (avond) — integrale kwaliteitskeuring: 55 bevindingen, allemaal verwerkt (E2E 30/30)

**Op gebruikersverzoek ("controleer kwaliteit en gebruikersvriendelijkheid voor de jurist"):**
audit-workflow met 5 lenzen (jurist-doorloop, consistentie, JS-robuustheid,
server-robuustheid, mobiel) → 55 bevindingen; parallel verwerkt door 3 bestandsgebonden
agents + eigen integratieronde. Hoogtepunten:
- **5 blokkerend gefixt:** /api/config kon de app permanent breken (nu valideren→laden→pas
  dan opslaan, met rollback); padtraversal-gat in delete-endpoints (id-validatie overal);
  stop-endpoint blokkeerde tot 4,5 min (nu asynchroon afronden met status "finalizing");
  tap-tooltippaneel overlapte de mobiele stopknop; race bij snel wisselen tussen
  archief-items.
- **Jurist-UX:** alle Engelse/technische teksten vertaald (states, foutmeldingen,
  downloadbestandsnamen als "definitief-gespreksverslag.md", offline-fases); zichtbare
  voortgang bij stoppen én bij de nabewerking (refine_pending/refine_failed); verslag-
  downloadlink voor sessies; vervolgknop na bestandsverwerking; nette standaardnamen;
  elke fout krijgt een Nederlandse melding i.p.v. stil falen (apiJson-helper overal).
- **Robuustheid:** per-item-lock op de versiegeschiedenis; snapshot merge+atomair (server-
  velden overleven de 30s-snapshot); streaming wav-write + to_thread (geen 230MB-reads in
  de event-loop); corrupte meta.json breekt lijsten niet meer; achtergrondtaken met
  referentie; LLM-timeouts → nette 504-melding. Verwijderen tijdens afronden geblokkeerd.
**Git + GitHub (gebruikersakkoord "doe maar"):** `git init`, daarna repo
https://github.com/MaartenSmeets/dia aangemaakt en gepusht (MIT-licentie, publieksgerichte
README; geheimen-scan vooraf schoon). `.gitignore` houdt bewust buiten de repo: geheimen
(.env, .ivdnt.json, certs/), gelicenseerde/grote data (data/ incl. CGN-NC, eval/references/,
eval/audio/), modellen, venvs en eval/results (samengevat in docs/). Initieel privé;
later dezelfde avond op gebruikersverzoek ("maak maar openbaar") publiek gemaakt na een
extra gevoeligheids- en licentiescan.

## 2026-07-23 (avond) — gebruikersvraag "rol bevestigd maar zie spk1": weergave verbeterd

Diagnose op de data: het VERSLAG gebruikte de bevestigde rol wél correct ("Tester: …",
bron "met bevestigde rollen") — wat de gebruiker als spk1 zag was het transcript-paneel/
de correctie-editor, die bewust de technische code tonen. UX-verbetering doorgevoerd:
**na bevestiging tonen transcriptweergave en editor-dropdowns de rolnamen** (weergavelaag
via `display_name`; opgeslagen data houdt spk-codes zodat correcties/evaluaties stabiel
blijven; sprekerkleuren blijven aan de code gekoppeld). WEBAPP §Run geactualiseerd
(run_app.sh = alles-in-één incl. HTTPS :8443; oude --ssl-instructie weg). E2E 30/30.

## 2026-07-23 (einde middag) — sjabloon per gesprek + LLM-sjabloonvoorstel (taak #23)

**Verslagsjabloon is nu een eigenschap van het individuele gesprek:** kiesbaar bij de start
(default "automatisch"), gebruikt door de doorlopende én definitieve verslagen, onthouden
bij hersamenvattten, voorgeselecteerd in het Archief-detail en daar altijd te wijzigen
(wijzigen = verslag opnieuw genereren uit het transcript, als nieuwe versie). **Zonder
gebruikerskeuze kiest het taalmodel in de nabewerking zelf het meest passende sjabloon**
op basis van het transcript (default/terugval: algemeen; bron/wijziging vermelden wie
koos). Nieuw endpoint `/api/templates/suggest` + 🎯-knop in het detail. **E2E 30/30**
(nieuwe checks: keuze-persistentie + geldig LLM-voorstel).

## 2026-07-23 (namiddag, vervolg) — privacy-verwijdercheck ving registry-bug; terminologie jurist-proof

**Gebruikerspunt "let bij verwijderen ook op de verslagversies":** beide verwijderroutes
doen rmtree op de hele itemmap (versies+rollen zitten daarin) — maar de nieuwe E2E-check
die dat op bestandssysteemniveau bewijst ving direct een échte bug: **een afgerond gesprek
bleef in reg.active hangen en gaf 409 bij verwijderen tot serverherstart**. Gefixt (alleen
state=="recording" blokkeert; registry-pop bij delete). **E2E nu 28/28.**

**Terminologie (gebruikersbesluit):** UI spreekt nu van **"Gesprek"** (i.p.v. Vergadering)
en **"Gespreksverslag"** (i.p.v. Samenvatting) — tabs, knoppen, tooltips, archieflinks,
meldingen; technische ids/API-paden ongewijzigd (meeting-endpoints etc. blijven stabiel).

## 2026-07-23 (namiddag) — sjablonen, sprekerrollen en samenvattings-versiebeheer (taak #22)

**Gebruikersfeature in 3 lagen (details WEBAPP.md §Sjablonen):** (1) samenvattingssjablonen
CRUD via Instellingen met 3 web-onderzochte defaults (algemeen, letselschade-intake,
regelingsgesprek-tegenpartij incl. finale kwijting/voorbehouden/BGK/belastinggarantie);
(2) LLM-sprekerrolvoorstel (tot 6 sprekers, best-guess) → gebruiker bewerkt en bevestigt →
pas dan gebruiken alle samenvattingen (ook de automatische nabewerking) de rolnamen;
(3) hersamenvattten met gekozen sjabloon + **versiebeheer**: elke wijziging (auto/sjabloon/
handmatig) = nieuwe versie met LLM-wijzigingsbeschrijving, current-pointer, herstellen
zonder verlies; de automatische nabewerking respecteert een actieve gebruikersversie.
Adversariële review ving vooraf o.a. padinjectie via body-id (→ `_safe_id` overal),
de auto-refine-overschrijfrace (→ opgelost door het versiemodel), niet-atomaire
templates.json-writes en een stale-response-race. **E2E uitgebreid 18→27 checks: 27/27
groen** (CRUD, rollen, hersamenvattten met LLM, versie bewerken/herstellen, padinjectie
geweigerd).

## 2026-07-23 (middag) — WORTELOORZAAK "alleen ruis"/geen live transcript: PCM-byteverschuiving op verbindingsgrenzen — GEFIXT + opname gered

Gebruikersmelding "stop lijkt niet te werken + geen live transcript + audio is alleen ruis"
bleek één worteloorzaak: **een feeder-verbinding kan eindigen op een HALF 16-bit-sample**
(gekapte per-verbinding-ffmpeg). Alles wat daarna in audio.raw komt is 1 byte verschoven =
statische ruis — in het bestand ÉN in de live-engine (verklaart de 0 transcriptie-aanroepen
en de whisper-hallucinatie "TV GELDERLAND 2021" uit de nabewerking). Bewezen met een
ruwheidsanalyse: echte spraak zat op offset 1 (uitgelijnd=10137, verschoven=383).
**Fixes:** (1) meetings.py `align_pcm()` — op elke verbindingsgrens (detach + vóór
stiltevulling) wordt een oneven bytepositie met één nulbyte hersteld, ook richting de
engine-pijplijn; bytepositie overleeft serverherstart; stiltevulling altijd hele samples;
(2) wav-schrijver rondt af op hele samples (eerdere fix); (3) offline_job decodeert
tolerant via soundfile (eerdere fix); (4) client-feeder geeft definitief op bij sluitcode
4404 (vergadering klaar) of 10 snelle fouten op rij — geen eeuwige 403-herverbindlus meer.
**Opname van de gebruiker gered**: spraak op offset 1 teruggehaald ("hallo hallo. dit is
een test...") → nabewerking + samenvatting opnieuw gedraaid, definitieve versie in Archief.
"Stop & rond af" bleek overigens correct te werken (state finished + refined); het "werkt
niet"-gevoel kwam door de doorlopende herverbindlus/mic-indicator. App herstart; E2E 18/18.

## 2026-07-23 (late ochtend) — gebruikersincident "geen transcript": 2 oorzaken gevonden, 1 structureel gefixt

Gebruikerstest 10:49 ("Test", 13 s, luide spraak) had géén live-transcript én geen definitieve
versie. Diagnose: (1) **live**: engine deed 0 transcriptie-aanroepen (SESSION_METRICS
n_transcription_calls: 0) — transiente singleton-klem na twee snel opeenvolgende teststarts;
engine-probe daarna weer gezond. Bekende WLK-kwetsbaarheid, vangnet = nabewerking. (2) **dat
vangnet crashte**: audio.raw eindigde op een HALF 16-bit-sample (415671 bytes, oneven — ffmpeg
mid-sample gestopt) → audio.wav met oneven payload → torchcodec (torchaudio-backend in
offline_job) weigert het hele bestand ("Invalid data found"). **Fixes:** meetings.py rondt de
wav-payload af op hele samples; offline_job.py decodeert nu tolerant één keer via soundfile en
geeft de array door aan ASR én pyannote (padpaden verwijderd). Opname van de gebruiker
gerepareerd + handmatig nabewerkt (refined_transcript/summary aanwezig, state.refined=true).
App herstart met de fix; E2E **18/18**. Open punt (klein): de singleton-klem zelf — vangnet
dekt hem nu af; structurele serialisatie van processor-instanties is een latere verbetering.

## 2026-07-23 (ochtend) — UI-dag: mobiel + leesbaarheid, verbindingsbewaking, spaarzame modus, Live→expert (taak #21)

**Drie gebruikersverzoeken in één verbouwing van app/static/ (workflow-gestuurd: 3
analyse-lenzen → implementatie → 3 adversariële verificatierondes → E2E):**
1. **Leesbaarheid/mobiel:** rem/clamp-typografie op de root (16→18px fluïde, browserzoom/
   OS-voorkeur werkt), transcript 1.06rem/1.65 met 75ch-regellengte, inputs overal ≥16px
   (iOS-zoomval), tap-targets ≥44px, sticky tabbalk, vaste duimbereikbare stopknop tijdens
   opname (body.meeting-live, geen :has()), archief-items wrappen, correctie-editor-grid
   mobiel, dvh+safe-area, WCAG-fixes (muted-contrast, sprekerkleur oranje→donkeroranje),
   tooltips: op touch tikbaar (bottom-sheet), op desktop ook via toetsenbordfocus,
   [hidden]-!important-fix. Desktop behouden (breakpoints 700/900/980, focus-visible).
2. **Verbindingsbewaking (gebruikersverzoek):** header-pill goed/traag/offline met
   achterstand in seconden (ws.bufferedAmount/bitrate), offline-banner, poll- en
   feeder-backoff. 3. **Spaarzame modus (gebruikersverzoek):** 12 vs 32 kbit/s opus,
   checkbox + automatische noodomschakeling bij aanhoudende achterstand (details WEBAPP.md).
   **Live-tab → expert-only (gebruikersbesluit):** vergadertab toont zelf al live transcript.

**De verificatierondes vingen 30+ echte fouten vóór de gebruiker ze zag**, waaronder een
BESTAANDE ernstige: microfoon ging niet uit na "Stop & rond af" (feeder-referentie zoek bij
heraansluiten) — nu closure-based feeder-state + teardown-discipline + await-race-guard +
wake-lock-refcount. Metriek-af: E2E na elke ronde **18/18**; node --check schoon.

## 2026-07-23 (ochtendschemer, ~05:10) — hybride-vergadering-vraag BEANTWOORD (taak #20 dicht); takenbord LEEG op overheidsmodel-wacht na

**Taak #20 gemeten en beantwoord (COMPARISON.md Update 5):** synthetische hybride-set uit
IFADV-stereo (kanaal 2 telefoonachtig gedegradeerd: 300–3400 Hz + 8 kHz-omweg + compressie
+ roze ruis; mono gemixt; `scripts/make_hybrid_ifadv.py`, sets in `data/hybrid/`,
manifests `hybrid_{clean,deg,fix}_dev`, resolver-uitbreidingen in run_eval + app-server).
Uitkomsten: **ASR-schade minimaal** (M2w offline 21,0→21,3%; live 25,2→26,1%),
**Sortformer-DER onaangetast** (10,6→10,3%), **naïeve DSP-opwaardering contraproductief**
(afftdn+speechnorm: 22,0% — slechter dan niets doen). **Eindantwoord op de
gebruikersvraag: nee, aparte audio-opwaardering per spreker is op dit degradatieniveau
niet nodig**; escalatie (VoIP-dropouts, galm/ver-veld) kan later met dezelfde generator.

**Takenbord:** #1–#17, #19, #20 ✅; alleen #18 (benchmark overheidsmodel) wacht op externe release
(wekelijkse cloud-watch actief). Onderweg ook: harness-kill-les opnieuw bevestigd (lange
achtergrondtaken ALTIJD setsid+monitor), app-herstartrecept gevalideerd (engine warm in
~30 s), en de nachtelijke replays reproduceerden de turbo-validatie (±0,3 pt).

## 2026-07-23 (einde nacht, ~04:45) — woordlatentie GEMETEN: ~1,0 s mediaan; woordtier-bug gefixt; taak #14 dicht

**Woordniveau-emissielatentie live-pijplijn: p50 1,03–1,05 s / p90 1,32–1,35 s** over 3
IFADV-dialogen (>1000 conservatief gematchte woorden elk, spreiding ±0,02 s) — **ruim binnen
de ~2 s-producteis**. Methode + tabel: EVALUATION.md §Latency; rapport
`eval/results/20260723-0207-word-latency/`. Nieuw: app logt tekst-delta's per result-event
(app/server.py), analyse in `eval/word_latency.py`; replays reproduceerden en passant de
turbo-validatie (pooled 25,2 WER / 29,8 cpWER / 10,6 DER, n=3).

**Referentiebug gevonden+gefixt:** `.words.json` bevatte FONEN, geen woorden — awd-bestanden
hebben 3 tier-paren met identieke namen (woorden/fonemisch/fonen) en een dict-comprehension
hield stilletjes de laatste; dag-1-notitie "~9,5k–14,7k woorden per dialoog" waren dus
foontellingen (echt: ~3-4k woorden). Converter gefixt (eerste-wint + commentaar), alle 20
regenerated. SegLST/RTTM (alle WER/cpWER/DER-resultaten) komen uit ort-bestanden — NIET geraakt.

**Datakeuze:** VoxPopuli-NL bewust vervallen (rationale in DATASETS.md — beslist niets meer).
**Docs-consolidatie:** PLAN.md Fase 5 ✅ met uitkomsten; README-stack geactualiseerd;
RESEARCH.md Addendum 2 (canary-plafondhypothese REFUTED voor conversationeel NL; R5 bewust
onbeslist); SETUP.md venvs/vox; EVALUATION.md basisrace+summary-eval-commando's. Taak #14 dicht.

## 2026-07-23 (diepe nacht, 03:00) — SUMMARY-EVAL v4 DEFINITIEF: diarization = ×3,5 attributie-accuratesse

**v4 compleet en geldig** (run `20260723-0025-summary-eval-ifadv_dev`, N=6, alle drie de
artefacten verholpen): **gelabelde condities 0,56–0,69 attributie-acc / 11–14% misattributie
tegen 0,17–0,19 / 50–58% zonder labels; goud 0,75 / 2,8%.** Kernvraag van de gebruiker
("is een samenvatting mét diarization accurater?") definitief beantwoord: **ja, ×3,5** —
schoonste bewijs: A vs B is identieke tekst met alleen de labels weg. Gelabelde bronnen
(live-Sortformer / pyannote-hernoemd / fusie) clusteren onderling binnen ruis; goud wint op
hallucinaties (1,7 vs 3,7–5,8) → transcriptkwaliteit = resterende hefboom. Volledige tabel
+ meetprotocol-lessen in SUMMARY-EVAL.md Results v4. Taak #16 (callcenter-spoor) hiermee
compleet: telefoonbaselines gemeten (M2w 24,0 vs M0 33,6), live-samenvatting zit in de app,
samenvattingskwaliteit met/zonder diarization gemeten.

## 2026-07-23 (na middernacht) — E2E 18/18; rechter-artefact ONTDEKT & BEWEZEN; summary-eval v2 met labelhernoeming

**E2E-EINDRUN 18/18 GROEN** (eval/results/e2e_final.log, 23:56) — incl. summarize tegen het
snelle LLM, live-webm-route en alle vergaderchecks. Taak #17 (vergadermodus) gesloten.

**Samenvattings-herkansing N=6 liep uit (exit 0, alle 36 vragen × 5 condities) — maar de
uitslag bleek vervuild:** gold haalde maar 50% attributie en de fusieconditie (E, via nieuwe
`--add-fused`-modus met hergebruik van vragen) scoorde absurd slecht ondanks een inhoudelijk
goede samenvatting met consistent-geswapte labels. **Swap-probe (1 gerichte rechter-aanroep,
00:05): zelfde samenvatting, alleen Spk1↔Spk2 hernoemd → oordeel flipt 'fout'→'correct'.
De rechter ankert dus op labelnamen, niet op inhoud** — attributiescores van gelabelde
machinecondities waren per item een muntworp. Fix geïmplementeerd (`remap_speakers_to_ref`
in eval/summary_eval.py): gelabelde condities (A/C/E) krijgen vóór het samenvatten een
globale labelhernoeming naar de gouden namen via tijdsoverlap; echte attributiefouten
blijven fout. **v2-run gestart ~00:15** (6 condities incl. E_fused geïntegreerd, verse
vragen, volledige log eval/results/summary_eval_v2.log). v1 blijft in SUMMARY-EVAL.md staan
als bewijsstuk, gemarkeerd NIET CITEREN.

**Ops-incidenten (leerzaam, schade beperkt):**
- cgn_tel-keten drong voor (wachtconditie matchte de historische VOX-FOUT-regel in de
  hergebruikte log) → even 3 GPU-jobs naast het LLM, 16 GiB over → keten gestopt,
  wachtconditie strakker (alleen expliciet DONE, verse log vox_bakeoff2.log), opnieuw in de rij.
- Bij het stoppen wéér een zelfmatch-kill (4e keer, exit 144: patroontekst in eigen commando)
  én ontdekt dat de waakhond-monitor om dezelfde reden nooit kon afgaan. **Regel aangescherpt:
  procesgroepen doden op PGID-nummer, pgrep-patronen ALTIJD met [x]-klasse-truc.** Nevenschade:
  het vox-ouderscript stierf; python-transcriptie liep door (hervat-wachter gewapend,
  run-map-hergebruik + per-item-skip in vox_bakeoff.sh ingebouwd → niets gaat verloren).

**Voxtral-voortgang:** librosa ontbrak in de pinlijst (ImportError pas bij eerste aanroep —
gepind op 0.11.0, setup-script + les bijgewerkt); transcriptie ifadv_dev loopt ~2,7× realtime.

**Basisrace DEFINITIEF compleet (01:52): Voxtral-Mini-3B 32,1 (ifadv_dev) / 40,7 (cgn_a_dev)
pooled WER** — verliest net als canary/parakeet ruim van M2w (22,9/31,3). Alle vier de
serieuze publieke kandidaten nu zelf gemeten; **M2 = eindkeuze refine-motor**, taak #13
gesloten. Voxtral-4B-Realtime bewust niet gemeten (rationale in COMPARISON.md Update 4).
Basisrace-methodologie-noot: alle kandidaten 30s-vensters, zelfde normalizer v1 + referenties.

**DERDE artefact OPGELOST — degeneratie was prefix-cache-corruptie (02:30):** v3 kreeg
degeneratie op nóg een conditie (DVA3E/A), op alle temperaturen → server verdacht. LLM
herstart met `--no-enable-prefix-caching` (na één mislukte start: KV-init faalde terwijl
turbo-scoring de GPU bezette — OPS-LLM VALKUIL 3), daarna probes: **beide trigger-prompts
schoon op de cache-vrije server** → bewezen. Oorzaak: vLLM-prefix-caching is experimenteel
op hybride Mamba-architecturen (Qwen3.6); opstartlog waarschuwde er zelf voor. Blijvend uit
(OPS-LLM VALKUIL 2). **v4 = definitieve summary-eval** (remap + guards + cache-vrije server)
gestart ~02:35, log eval/results/summary_eval_v4.log.

**Telefoonbaselines (taak #16) GEMETEN (02:14): M2w 24,0 vs M0hfw 33,6 pooled WER op
cgn_tel_dev (n=8) — de comp-a-getrainde CGN-LoRA draagt vol over naar telefoonspraak
(−9,6 pt) zonder telefoontraining.** Callcenter-rij in CGN-VALUE.md-waardetabel nu gemeten
i.p.v. verwacht. (cpWER-kolom hier betekenisloos: scoring zonder attributie, zoals bij alle
lora-runs.)

**TWEEDE meetartefact (v2 → v3, ~00:40):** op DVA1A/E degenereerde de samenvatter tot 700
uitroeptekens en **de rechter gaf die garbage 6/6 attributie + feitelijkheid 5 + 0
hallucinaties** — rechters zijn niet robuust tegen gedegenereerde invoer. Fixes:
`is_degenerate()` + `summarize_robust()` (herkansing temp 0,2→0,5→0,8) + rechter-bypass
(alles 'absent' + bodemscores + vlag). v3 gestart met beide reparaties; eerste v2-datapunten
waren verder al bemoedigend (gold 6/6, C 5/6 na hernoeming — het remap-mechanisme werkt).

## 2026-07-22 (late avond) — LLM-wissel naar native FP4 gelukt; basisrace beslist: M2 blijft refine-motor

**LLM-wissel (gebruikerswaarschuwing: NGC-image ≠ volledig NVFP4, BF16-fallback → traag; officieel NVIDIA-model géén harde eis meer):**
- Eerste poging (officiële MoE op AEON-image) stierf direct: **AEON-image heeft entrypoint `/bin/bash`** → bash voerde het python-script `/usr/local/bin/vllm` uit (`import: command not found`, exit 2). Fix: `--entrypoint vllm`. Valkuil gedocumenteerd in OPS-LLM.md.
- Definitieve setup = bewezen config van 11 dagen terug, aangepast aan coexistentieregels: container `vllm-qwen36-fast` (AEON-image v0.24.0+sm121a.dflash) met **Qwen3.6-27B-AEON NVFP4 + dflash speculatieve decode** (12 spec-tokens), util **0.40**, ctx 32k, poort 8000, naam `qwen36` → app merkt niets.
- **Geverifieerd:** log toont `Using FlashInferCutlassNvFp4LinearKernel for NVFP4 GEMM` (native FP4, geen marlin) + `DFlashDraftModel` geladen; endpoint op na ~580 s; engine-doorvoer **~12–19 tok/s** bij 2 gelijktijdige requests (NGC-MoE haalde <10 tokens in 30 s). Dense-27B op GB10 (~273 GB/s bandbreedte) zit hiermee nabij het hardwareplafond — prima voor batch-samenvatting. Geheugen na load: 39 GiB beschikbaar.
- Terugvalopties: (1) `docker start vllm-qwen36-moe`; (2) officiële `nvidia/Qwen3.6-27B-NVFP4` (21 GB) staat compleet in `~/models` (`scripts/start_llm_standby.sh`).

**Basisrace (offline_bakeoff.sh) compleet — pooled WER dev, zelfde normalizer/suite:** canary-1b-v2 **31,5** (ifadv) / **43,5** (cgn_a); parakeet-tdt-0.6b-v3 **28,8 / 43,2**; tegenover **M2w (turbo+CGN-LoRA, woordniveau) 22,9 / 31,3**. **Uitslag: M2 wint met 6–12 punten op beide conversationele sets → blijft de refine-motor; canary+CGN-FT-route vervalt** (baseline-gat te groot om met een FT te dichten; gepubliceerde benchmarks — voorgelezen spraak — bleken wéér niet voorspellend voor spontaan NL). Tabel in COMPARISON.md Update 4.

**Samenvattings-herkansing gestart 23:21** met volledige logging (`eval/results/summary_eval_rerun.log`), nu tegen het snelle LLM; daarna schone E2E-run (after_bakeoff.sh).

**Volgende (vannacht):** Voxtral-Mini-3B offline meten (laatste ontbrekende kandidaat voor de claim "best beschikbare openbare model", eigen venv, gepind) → daarna cgn_tel-baselines (taak #16).

## 2026-07-22 (nacht) — VERDICT geschreven; fusie-doorbraak; nachtwachtrij

**M-serie compleet + geattribueerd + VERDICT in CGN-VALUE.md** (incl. use-case-waardetabel): CGN-data −7 WER (werkzaam bestanddeel, M3≈M2); cpWER-regel via pyannote-route NIET gehaald (attributie-bottleneck DER 18–24%), via **productpijplijn (fusie) WEL op vergaderdomein** (−5,0 cpWER, n=4). Aanbeveling: offerte opvragen; tekenen na herbevestiging op testsplit.

**FUSIE-DOORBRAAK (dialib/fuse.py, gemeten in eval/merge_live_offline.py):** live-Sortformer-beurten × offline-M2-woorden = beste van beide (IFADV: 21,9 WER/33,8 cpWER/13,7 DER; CGN: wint op alle maten). Geïmplementeerd als productstandaard in de vergader-nabewerking (refined_*); pyannote-attributie = fallback voor kale uploads.

**Samenvattings-herbeoordeling N=6 stierf stil** (29 min, 0 items; foutmelding opgeslokt door grep-filter in de keten — LES: nooit foutkanalen wegfilteren in ketenstappen). Herkansing met volledige logging gepland ná de basisrace (scripts/after_bakeoff.sh) + aansluitend schone E2E-run.

**Basisrace draait** (canary-1b-v2 eerst, dan parakeet; op ifadv_dev+cgn_a_dev, zelfde suite — meten is weten, uitslag bepaalt de refine-motor en evt. canary+CGN-FT morgen; NeMo-manifest met CGN-data staat klaar: data/ft/nemo_cgn_a_train.json).

## 2026-07-22 (middag/avond) — productdag: jurist-UX, HTTPS, live-bugfix, tweede-pass-architectuur

**Mandaat gebruiker: volledig autonoom doorwerken tot eindproduct incl. MD's optimaal is.**

- **UI-onderzoek (3-lens workflowpanel) → "Archief"-ontwerp**: één lijst voor alles (badges Vergadering/Bestand/Live), tabvolgorde op jurist-gebruiksfrequentie (Vergadering·Bestand·Archief·Live·Instellingen, Vergadering = startscherm), Sessies-jargon weg, verwijderen (privacy-compleet: audio+transcript+samenvatting+upload+correcties) met bevestiging; systeem-/testitems standaard verborgen (interne vlag + eval-bron-filter; `?all=1` voor experts).
- **Smart defaults**: LLM-autodetectie (startup + knop; pakt eerste model op lokale poorten — gevonden qwen36@8000), loudnorm standaard aan, expertmodus verbergt Evaluatie/engine-config.
- **HTTPS voor mobiel**: TLS-proxy :8443 (alle host-IP's in SAN incl. Tailscale), run_app start hem mee; http-banner verwijst mobiele http-bezoekers door. run_app --ssl-bug gefixt.
- **KRITIEKE LIVE-BUG (gevonden via gebruikerstest, bewezen gefixt)**: MediaRecorder startte vóór WS-open → eerste chunk (WebM-header!) weg bij trage TLS/LAN-handshake → geen transcript én onleesbare opname. Fix: start na ws.onopen; audio-only sessies blijven nu ook bewaard; conversiefouten gelogd; **nieuwe E2E-tests voor de live-WebM-route: 17/18 groen** (alleen summarize rood door GPU-verzadiging tijdens meetketen).
- **NL-overheidsspraakinitiatief nagetrokken**: er bestaat alleen een intentieverklaring (3 juli 2026), nog géén model — mocht er ooit een model verschijnen, dan gewoon meenemen in de bake-off-systematiek. (Release-watch later op gebruikersverzoek uitgeschakeld, zie 2026-07-23 avond.)
- **Tweede-pass-architectuur (user req: live bijhouden + beste kwaliteit achteraf)**: vergaderingen krijgen na afloop automatisch een offline "definitieve versie" (refined_* artefacten NAAST live-versie): offline_job.py nu HF-turbo + optionele LoRA (default REFINE_ADAPTER=models/lora/M2-cgn — **NC-licentie: intern ok, commercieel pas na CGN-commercieel**) + pyannote + definitieve samenvatting; zichtbaar in Archief als "definitief transcript/samenvatting". **Motorkeuze wordt gemeten**: offline bake-off (canary-1b-v2, parakeet) staat gepland direct na de M-keten (`scripts/offline_bakeoff.sh`, wacht op FINAL_CHAIN_DONE); wint canary op conversatie, dan wordt die de refine-motor (NeMo zit al in wlk-venv).

## 2026-07-22 (daytime) — meeting mode shipped + tested; word-cpWER chain grinding

**Meeting mode implemented and E2E-tested (task #17, user req):** persistent server-side meetings (app/meetings.py + Meeting tab) — reconnecting mic feeder w/ silence gap-fill, stateless polling viewers, continuous PCM+state persistence, rolling+final qwen summaries, downloadable artifacts (wav/seglst/txt/summary.md/meta). **E2E suite (tests/test_app_e2e.py): 15/16 pass** — only `summarize` fails DURING GPU batch windows (qwen starvation; contention, not code). Suite caught 2 real bugs pre-user: file-source meetings never finalized (no EOS signal) and stop() hang on empty pipelines — both fixed (bounded waits, EOS on EOF, empty-summary skip). Orphaned-on-restart meetings now labeled in listings. WEBAPP.md updated (Meetings + Testing + GB10 ops note).

**Word-cpWER chain (final_chain.sh, detached+monitored):** M0hfw validated word-level ≈ chunk-level WER (41.1 vs 40.5 CGN); batch 2→4 speedup for remaining passes after the near-OOM fix (batch 8 incident: ~9 GB/slot alignment buffers). Then pyannote attribution → summary-eval N=6 retry. Three monitors: milestones, crash signatures, silent-death watchdog.

**Incident log:** near-OOM caught at 0.5 GB free during batch-8 word scoring (killed in time, box saved); 2 harmless zombies inside qwen container (vLLM unreaped workers); repeated lesson recorded — never put a pkill pattern in the same shell command as text matching it (3 self-kills).

## 2026-07-21/22 (overnight, autonomous) — night plan

User asleep; standing orders: continue autonomously. In flight / queued, notification-driven:
1. `nvidia/Qwen3.6-35B-A3B-NVFP4` downloading → on completion: serve via **official NGC image** `nvcr.io/nvidia/vllm:26.06-py3`, `--quantization modelopt --served-model-name qwen36 --gpu-memory-utilization 0.40` (coexistence per user's own script convention), 127.0.0.1:8000 → smoke test (`enable_thinking:false`).
2. M-series chain: M1 finishing → score → M3 → score → (docker-start neutralized by guard; user's old container was removed anyway) → auto-rejudge summaries if :8000 answers.
3. After chain: pyannote attribution on M0hf/M1/M2/M3 cgn_a_dev+ifadv_dev scoring runs → **cpWER for the ≥3-pt decision rule** → write CGN-VALUE.md verdict + SUMMARY-EVAL.md results.
4. **cgn_tel built** (this entry): comp-c/d telephone references — 1,230 recordings, audit-filtered dev/test 8+8 (dyadic, 8 kHz A-law stereo = caller-per-channel). Converter generalized: `cgn_to_seglst.py --components c,d --out-name cgn_tel`; run_eval handles any `cgn*` manifest. Baselines on cgn_tel queued after the M-chain frees the GPU.

## 2026-07-21 (late night) — OOM incident: vLLM vs training; recovery chain running

**Incident:** user's Qwen3.6-27B vLLM container (default gpu_memory_utilization ≈0.9 → tried ~109 GiB of the 121 GiB unified memory) crashed once under judge load, auto-restarted, and its re-allocation **OOM-killed the M1 LoRA training (step ~1020/1500) and the background task shells** (12 GiB available at intervention). Rule + incident recorded in CLAUDE.md: one big model at a time, or cap vLLM to ~0.3.

**Recovery (automated chain `mseries_continue.sh`, running):** stopped the vLLM container (reversible; auto `docker start` at chain end) → **fresh M1 retrain** (identical uninterrupted recipe as M2 for fairness; partial ckpts discarded) → score M1 → train M3 → score M3 → restart qwen container → wait for endpoint → rejudge summary experiment (semantic attribution protocol — first attempt used brittle label matching, fixed; misattribution_rate now reported separately). ETA ≈ 5 h.

**Landed before the incident:** M2 scores (WER 30.2% CGN-dev / 23.8% IFADV-dev, −10.4/−7.6 vs M0hf — above the researched prior range); summarization live in app (Qwen3.6, `enable_thinking:false` required — Qwen3.x returns null content otherwise); summary experiment summaries generated (judging redo pending).

## 2026-07-21 (night 2) — call-center use case: telephone data + summarization layer (task #16)

**Use case declared by user: call-center live summarization/diarization/transcription.** Implications logged in CGN-VALUE (a call-center product is commercial → CGN-trained adapters shipping there need the commercial license, sharpening the M-experiment stakes).

- **CGN comp-c+d (telephone dialogues, 1,230 recordings, 12.8 GB) extracted** — the call-center acoustic proxy (narrowband 2-speaker). Next: adapt cgn converter for comp-c/d layout → `cgn_tel_dev/test` splits → baseline live stack + M-adapters on telephone audio.
- **Summarization layer implemented in the app:** `POST /api/summarize` → any local OpenAI-compatible endpoint (`SUMMARIZER_URL`/`SUMMARIZER_MODEL` in .env). Live tab: rolling summary button + 60 s auto; Sessions tab: summarize stored sessions. Dutch call-center prompt. NOTE: app not restarted yet (M-series owns the GPU) — restart to activate routes.
- **Summary-quality experiment designed + implemented** (`docs/SUMMARY-EVAL.md`, `eval/summary_eval.py`): answers two user questions — live-vs-offline transcript as summary input, and **diarized vs non-diarized transcript → summary accuracy** (attribution-question judging against gold). Uses EXISTING eval transcripts (A/B/C/D/R conditions); runs when GPU is free + LLM endpoint up.

## 2026-07-21 (night) — M-series fine-tuning launched (task #15)

**Training data built:** `data/ft/` — CGN comp-a windows 80.2 h/11,038 (mixed-audio ≤28 s windows, time-ordered all-speaker verbatim text, eval recordings excluded); MLS-nl train 60 h/14,451 (HF streaming, no full download); CV22-nl train 20 h/16,067 (legacy venv). M1=MLS+CV, M2=CGN, M3=CGN+MLS per CGN-VALUE.md.

**Two training bugs found & fixed in `scripts/train_lora.py`:** (1) DataLoader forked workers wedge on this platform → `num_workers=0` (the 1-hour silent bring-up hang); (2) reentrant gradient checkpointing double-backwards under autocast+LoRA → `use_reentrant=False` + `enable_input_require_grads()`. After fixes: **bs=8 ≈ 2.5 s/step, bs=16 ≈ 5.1 s/step** (GB10, bf16, grad ckpt, LoRA r=32 q/k/v/out).

**Launched:** `STEPS=1500 scripts/run_m_series.sh` (background; log `eval/results/mseries.log`): score M0hf anchor (same HF-chunked scorer as all variants — do NOT compare against openai-whisper sequential numbers) → train+score M2-cgn → M1-perm → M3-both; each ~2 h train + ~40 min scoring on cgn_a_dev+ifadv_dev. Adapters → `models/lora/<name>` (servable live via WLK `--lora-path` later). ETA full matrix: ~10 h.

## 2026-07-21 (evening) — CGN ingested end-to-end; M0 anchors measured

**CGN comp-a fully ingested:** 1,537 recordings converted (`scripts/cgn_to_seglst.py` — same short-TextGrid format as IFADV; CGN token markers stripped; BACKGROUND/COMMENT tiers skipped, UNKNOWN kept); audit-filtered splits `cgn_a_dev`/`cgn_a_test` (12+12 NL, 2–4 spk, 3 timeline-suspect recordings auto-excluded); wired into run_eval (+`--whisper-model` flag), app eval tab, and pyannote attribution (cgn_a branches). Fixes en route: run_eval passed `eval:cgn_a_dev/..` vs resolver's `eval:cgn_a/..`.

**M0 anchors (cgn_a_dev, table in CGN-VALUE.md):** live turbo+Sortformer **WER 35.1 / cpWER 44.5 / DER 20.1%** (4-rec subset); offline v3+pyannote 40.5/57.3/30.9 (12); offline turbo 37.7% WER beats v3 40.5% (ordering settled). CGN is much harder than IFADV (cpWER 44.5 vs 32.2) → real eval value under NC. 35–40% zero-shot zone = the headroom M1–M3 fine-tunes compete over. WER-above-bracket investigated: genuine domain difficulty, not a bug (transcript inspection documented in session).

## 2026-07-21 (later) — CGN-VALUE priors researched; zoekterm-initiatief not found; sanity flags for M0

Web-research pass (workflow, partially verified — UNCERTAIN flags inline) added to **CGN-VALUE.md**: published-WER table for CGN/spontaneous Dutch; predicted **M2−M1 ≈ +2..+8 WER pts (central 3–5), cpWER +1.5..+6 (central 2.5–4) — right AT the ≥3 cpWER decision threshold**, so measurement genuinely decides. Key finds: whisperd-nl 16.42% is VERBATIM-scored (not comparable to our cleaned normalizer — plan: score it on comp-a both ways to calibrate the offset); Bălan/CLIN34: **large-v3 can regress vs large-v2 on conversational Dutch (hallucination)**; Welzijn.AI: turbo WORSE than v3 offline on spontaneous elderly Dutch — contradicts our streamed ordering → M0 must compare turbo vs v3 under identical conditions; no published zero-shot WER on comp-a exists (our M0 = novel data point; expect 25–35% cleaned, outside that = bug). **het gezochte initiatief als dialect-fine-tune: NOT FOUND** on GitHub/HF (only an unrelated voice-conversion model); nearest real artifacts: Frisian whisper-small FTs (polixonrio/Rijgersberg whisper-small-fy-NL). Ask user for more clues if it matters.

## 2026-07-21 — CGN delivered; download in progress

User signed the NC license via the local /sign page (2026-07-18) and mailed it; INT replied with a pCloud link. `CGN_2.0.3.zip` (92.8 GiB; leverlink-parameters in `.env`) downloading via `scripts/download_cgn.sh` (re-resolving resumable loop) → `data/cgn/`. Disk before: 438 GB free — extract SELECTIVELY (comp-a conversations + annotations only), not the whole corpus. On completion: `data/cgn/zip_contents.txt` has the listing; next steps = extract comp-a (nl+vl) audio + ort annotations, build SegLST/RTTM references (new converter — CGN ort format, likely gzipped Praat TextGrids; verify against listing), timeline-audit like IFADV, then re-baseline live turbo stack + offline method D on a CGN dev split. Remember: NON-COMMERCIAL license — evaluation only, no shipping fine-tunes trained on it (DATASETS.md §CGN).

## 2026-07-17 (evening) — turbo validated; IFADV reference-timeline bug fixed; all runs rescored

**Turbo 6-dialogue realtime validation: WER 25.0 / cpWER 32.2 / DER 14.1% pooled — turbo stays live default; the LIVE stack now beats offline whisper+pyannote (cpWER 44.7%) on speaker-attributed accuracy** (per-dialogue wins on all 4 direct comparisons). Full story in COMPARISON.md Update 2.

**Reference bug found via an apparent "collapse" on DVA12S (DER 0.65 for every method, WER normal):** IFADV's plain vs `Shift6` annotation variants differ in timeline; only Shift6 matches the audio (channel-VAD agreement 0.85 vs 0.50). Converter now prefers Shift variants; **all 20 references re-audited (0.75–0.87, pass) and every IFADV run rescored** (rescore.py; DER improved 1–5 pts where DVA12S was included; text metrics unchanged). Timeline audit code is in this entry's session; promote it into the converter if references are ever regenerated.

**DVA12S post-fix:** intrinsically hard dialogue (similar voices) — all diarizers over-cluster; streaming Sortformer best (DER 30.5% vs pyannote 55.1%). Day-1 DVA1A collapse = 1 unexplained event in ~16 realtime runs; keep monitoring.

## 2026-07-17 (afternoon) — sweep results: turbo wins, stability OK, defaults updated

Sweep completed (9 runs, ~4.5 h; table in COMPARISON.md "Update 2026-07-17"). Verdicts: **large-v3-turbo promoted to live default** (WER 25.1 / cpWER 29.4 / DER 10.3 on DVA1A+3E realtime — beats large-v3 on every metric incl. FLEURS 18.0 vs 22.2); **no diarization collapse in 8 runs** (day-1 event ≈ rare); frame-threshold default stays; **Sortformer v2 stays** (v2.1 no gain + stricter license). Server restarted on turbo config; **6-dialogue turbo validation running** (`--tag=-turbo-val`, ~3.2 h). Run-to-run variance measured: ±3 WER / ±1.5 DER pts — treat smaller deltas as noise. Task #12 closed; #13 remains open for the Voxtral/canary/parakeet bake-off.

## 2026-07-17 — engine-reload bug found+fixed; config sweep running; license prefilled; latency first-look

**CRITICAL BUG FIXED:** WLK's `TranscriptionEngine` is a hard singleton — re-instantiating returns the OLD engine and silently ignores new config ("engine loaded in 0.0s" symptom). The app's `/api/config` reload (and Config tab) had therefore been a NO-OP. Fixed via the official `TranscriptionEngine.reset()` in `EngineManager.load` (app/server.py); verified reloads now really load (10–14 s warm) and flags take effect. **No prior results are tainted** — all COMPARISON.md baselines ran on the startup config.

**Config sweep running** (`scripts/run_sweep.py`, log `eval/results/sweep_queue.log`, ~5 h): stability 3× repeats (realtime, DVA1A+DVA3E) → frame-threshold 15/40 → large-v3-turbo (+FLEURS-25) → Sortformer v2.1 2× repeats. Driver reconfigures the engine via `/api/config` per stage, restores default at the end, aborts if available memory <20 GB. Gotchas encountered: argparse needs `--tag=-x` form for tags starting with “-”; `app/engine_config.json` only exists after first config POST (driver falls back to `/health`).

**Latency first-look** (`eval/latency_report.py`, from existing realtime IFADV sessions): result cadence ~10–12 Hz; finalization lag (line-level) p50 ≈ −0.5–0 s, p90 ≈ 5–8 s. Word-level emission latency vs `.awd` still open (#14). Short FLEURS clips give degenerate lag samples — use long dialogues only.

**CGN license prep:** `data/cgn/order/Licentie-NC_CGN_INGEVULD.docx` prefilled (organisatie, e-mail, Bijlage-2 onderzoeksomschrijving) via `scripts/fill_cgn_license.py` (fills FORMTEXT display runs in-place; structure verified with python-docx). Remaining user fields + steps: `data/cgn/order/TODO_SIGNING.md`; email body: `MAIL_DRAFT.txt`. Signature must be the user's own.

**CommonVoice-nl:** parquet revision doesn't exist for fsicoli v22 / mozilla v17 → legacy route worked: `venvs/cvdl` (datasets==2.21.0) + `scripts/download_cv_legacy.py` → 1000 utts / 1.36 h exported (manifest `cv22_nl_test.json`).

## 2026-07-15 (late) — CGN order kit retrieved; license process + NC restriction documented

Downloaded via the user's taalmaterialen.ivdnt.org account: the CGN **order kit** (`data/cgn/order/`): order instructions + NC license (NL+EN docx). Verified process: user signs license → scan to servicedesk@ivdnt.org → INT sends the download link for BP_CGN_NC.zip (~96 GB, v2.0.3). **License is NON-COMMERCIAL, personal-research, no-public-derivatives** — full analysis in DATASETS.md §CGN; commercial edition exists separately.

## 2026-07-15 (night) — baselines complete, COMPARISON.md written, offline upload mode shipped

**pyannote gating accepted by user → method D unlocked and verified** (community-1 loads on CUDA in ~7 s; short-clip caveat: on a 60 s test clip it underclustered to 1 speaker — fine on full 15-min dialogues: 220–360 turns, DER 8–17% on the best dialogues).

**All baselines done** (`scripts/run_baselines.sh` + chained `scripts/attribute_with_pyannote.py`; full tables + verdict in **COMPARISON.md**). IFADV-dev pooled: whisper-longform 30.1/87.3/46.2 (WER/cpWER/DER %), +pyannote 30.1/**44.7**/**21.4**, wlk-fast 49.3/57.3/26.9, wlk-stream (N=2) 35.0/62.5/32.7. *(Annotatie 2026-07-23: DER-cijfers hier zijn van vóór de referentie-timelinefix van 2026-07-17 — canonieke, herscoorde tabellen in COMPARISON.md.)* FLEURS-nl: offline 7.3% (matches literature → harness validated), wlk-fast 16.1%, wlk-stream 22.2%.

**Decisions implemented:**
- Upload default = **offline pipeline** (whisper long-form + pyannote): new `scripts/offline_job.py` (eval venv subprocess), app endpoints `POST/GET /api/offline/*`, File-tab mode selector updated. Verified end-to-end with a 60 s **m4a + loudnorm** upload (job pipeline asr→diarize→attribute, ~50 s wall). Sessions from offline jobs appear in the Sessions tab (mode "offline") for correction.
- Unpaced "fast" streaming demoted to functional checks (COMPARISON finding 2: 49.3% vs 35.0% WER on long audio).

**Key open issue found:** streaming Sortformer collapsed to near-single-speaker in 1 of 2 realtime long-dialogue runs (DVA1A: 793/118 s split; healthy fast-mode run: 400/491 s). Top next experiment: 5× repeat stability sweep across Sortformer latency presets + v2.1.

**Gotchas fixed today (already folded into SETUP.md):** eval venv needed num2words (dialib import) + openai-whisper for offline jobs.

**Next up (ordered, see COMPARISON.md open experiments):** diarization stability sweep → frame-threshold/turbo sweep → Voxtral-Realtime pilot (separate venv) → canary-1b-v2 offline (NeMo container) → latency analysis from events.jsonl + IFADV .awd → CV-nl via parquet route → CGN when license arrives.

## 2026-07-15 (evening) — END-TO-END PIPELINE WORKING; app built; first real metrics

**New user requirements folded in today:** (1) uploads must support **m4a** + optional loudness normalization (implemented: ffmpeg ingest accepts anything, single-pass EBU R128 `loudnorm` toggle); (2) both **realtime streaming** and **after-the-fact upload** processing available (implemented: replay speed=1.0 vs speed=0 fast/unpaced); (3) an **empirical methods comparison document** incl. classic whisper-large long-form baseline, proving what the diarized pipeline adds → docs/COMPARISON.md (task #11), harness supports methods: wlk-stream / wlk-fast / whisper-longform / whisper-longform+pyannote.

**Built and verified:**
- `dialib/` — normalizer (Dutch, v1, tests pass), seglst helpers, metrics (jiwer WER + meeteval cpWER/DER; meeteval returns per-session dicts → combined; md-eval Decimals → float; inverted WLK intervals clamped).
- `app/` — full experiment server + UI (see WEBAPP.md): live mic, file upload (m4a/loudnorm/fast-or-realtime), eval tab w/ side-by-side reference + WER/cpWER/DER, sessions + corrections editor, config tab w/ in-process engine reload. Server runs on :8080.
- `eval/run_eval.py` harness + `eval/rescore.py`; results under eval/results/.
- Engine load: cold 784 s (incl. 2.9 GB whisper download), warm ~20-60 s. Memory with engine resident: ~23 GiB / 121 GiB.
- **Bugs found & fixed:** (1) `AudioProcessor.is_pcm_input` must be set before `create_tasks()` (else "FFmpeg read timeout" hang); (2) `ready_to_stop` must be sent when the results generator ends, not after client disconnect (deadlock with waiting clients); (3) WLK emits occasional end<start segments → clamped in dialib.
- **IFADV audio complete** (5.6 GB, 48 wavs = 24 dialogues × DVA/DVB views, 48 kHz stereo 15:00). R10 validation: per-channel energy-VAD speech time consistent with reference magnitudes; exact channel↔speaker mapping fuzzy due to mic crosstalk (fine — metrics are permutation-invariant).
- **First real numbers** (details in eval/results/):
  - FLEURS-nl (2 samples, sanity): wlk-stream WER 10.3% pooled vs whisper-longform offline 6.9% — expected streaming penalty visible.
  - IFADV DVA1A (15-min real conversation, fast mode): **WER 52.4% / cpWER 55.3% / DER 18.0%** — conversational Dutch is the real challenge (backchannels/overlap); DER 18% from English-trained streaming Sortformer on Dutch is decent. Transcript quality qualitatively good; WER on overlapping dialogue is order-ambiguous → cpWER is the headline metric.
- HF eval sets: FLEURS-nl test (364) + MLS-nl test exported (wav + SegLST + manifests). CommonVoice blocked by datasets-5.0 script removal (parked; not blocking).

**In flight:** `scripts/run_baselines.sh` background queue (~2.5 h): {wlk-fast, whisper-longform, wlk-stream} × {FLEURS-nl, IFADV-dev} → COMPARISON.md.

**User actions still needed:**
1. Accept pyannote gating: open https://huggingface.co/pyannote/speaker-diarization-community-1 (logged in as the .env token account) and accept conditions → unlocks method D (offline diarization reference).
2. CGN license request (docs/DATASETS.md §CGN).
3. Try the UI: http://localhost:8080 (mic on localhost); for LAN mic: scripts/make_cert.sh + run with --ssl.

## 2026-07-15 (later) — environment A verified, IFADV references built

**R1 CONFIRMED (GPU on GB10 via pip wheels):** `venvs/wlk` = torch 2.11.0+cu130 / torchaudio 2.11.0+cu130 / torchcodec 0.14.0+cu130 (aarch64). `torch.cuda.is_available()==True`, `get_device_capability()==(12,1)`, arch list `[sm_80…sm_120]` (sm_121 absent is expected — sm_120 binaries run), GPU matmul finite. Note: install order left numpy out until WLK stage — harmless warning.

**R2 CONFIRMED (native aarch64 pip install of the full chain):** `whisperlivekit[diarization-sortformer]==0.2.24` installed cleanly, no source-build failures. Key resolved versions: nemo-toolkit 2.7.3, transformers 4.57.6, faster-whisper 1.2.1 (+ctranslate2 4.8.1 wheel = CPU-only, irrelevant — we run `--disable-fast-encoder`), onnxruntime 1.27.0 (CPU), lightning 2.4.0, numpy 2.4.6, fastapi 0.139.0. NGC NeMo container fallback NOT needed for the live stack.

**R7 PARTIALLY RESOLVED (flag drift found):** `wlk` is now a multi-command CLI (`serve|listen|run|transcribe|bench|diagnose|models|pull|rm|check`). **The language flag is `--lan`, NOT `--language`** — RESEARCH.md §4 command corrected here:
`wlk serve --model large-v3 --lan nl --diarization --diarization-backend sortformer --disable-fast-encoder --host 0.0.0.0 --port 8000`
Also available & relevant: `--backend-policy simulstreaming` (default policy), `--frame-threshold` (AlignAtt knob), `--beams/--decoder`, `--init-prompt/--static-init-prompt` (domain hotwords), `--ssl-certfile/--ssl-keyfile` (LAN mic), `--pcm-input`, `--api-token`, `--warmup-file`, `--min-chunk-size`, `--vac-chunk-size`, `--buffer_trimming`.

**IFADV annotations converted (task #7 code done, validation pending audio):** `scripts/ifadv_to_seglst.py` (self-contained short-TextGrid parser incl. Praat trigraph decoding; variant selection Corr > plain > Shift > ORIGINAL/nodia, matches awd convention). All 20 dialogues → `eval/references/ifadv/{ID}.seglst.json,.rttm,.words.json`, zero warnings; 502–792 segments and ~~9.5k–14.7k words~~ per dialogue *(correctie 2026-07-23: dit waren fonen-tellingen; echte woordaantallen ~3–4k — zie entry 2026-07-23 einde nacht)*; per-speaker speech times plausible (high overlap is normal in free dialogue). Splits: `eval/manifests/ifadv_dev.json` (DVA1A,3E,6H,8K,10O,12S,14W,16AA,19AG,22AL) / `ifadv_test.json` (DVA2C,4C,7B,9M,11Q,13U,15Y,17AC,20AI,24AK — HELD OUT). Dialogue numbering has gaps (no 5,18,21,23) = 20-of-24-annotated, expected. Remaining validation once audio lands: channel-VAD cross-check + Praat spot-check (R10).

**In flight:** IFADV AudioWAV.zip download (Zenodo is slow, wget -c resumable); `venvs/eval` pip install (task #4).

## 2026-07-15 — project start: research, decisions, environment bring-up

**Requirements fixed with user:** Dutch, fully local on DGX Spark; meetings 2–4 speakers; balanced latency (partials ≈2 s); inputs = browser mic (localhost + LAN), uploaded files incl. **m4a** (→ ffmpeg ingest + optional EBU R128 `loudnorm`); HF gated models OK (token in `.env`, mode 600).

**Research done (12-agent verified web research, see RESEARCH.md + verification appendix):**
- Stack decision: WhisperLiveKit 0.2.24 engine (Apache-2.0) + whisper large-v3 `--language nl` (SimulStreaming policy) + NVIDIA Streaming Sortformer v2 diarization (ungated CC-BY-4.0, ≤4 spk) as day-1 live pipeline; Voxtral-Mini-4B-Realtime / parakeet-tdt-0.6b-v3 / canary-1b-v2 as bake-off candidates; pyannote community-1 as offline diarization reference; meeteval+jiwer metrics, SegLST canonical format; IFADV as primary conversational eval corpus.
- Platform facts: torch **cu130** aarch64 wheels are the only correct pip path (cp312 wheels exist up to torch 2.13.0 / torchaudio 2.11.0 / torchcodec 0.15.0 — checked the index directly today); CT2/faster-whisper aarch64 wheels are CPU-only; `nvidia-smi` memory column reads "Not Supported" on this platform (normal).
- Known risk list R1–R14 in RESEARCH.md §8 — treat as the test checklist.
- Gap: the "evaluation & metrics" research agent crashed (structured-output failure); its ground is mostly covered by §5/§6 of RESEARCH.md, but when building the eval harness, do a small focused check on: jiwer/meeteval exact APIs, Dutch normalizer details, whisper LoRA recipes. Noted as backfill work in Phase 4.

**Machine verified:** GB10, aarch64, driver 580.159.03, CUDA 13.0, py3.12.3, docker+ffmpeg+node24, ~528 GB free, internet OK, venv creation OK.

**In flight (background):**
- `venvs/wlk` creation: torch==2.11.0+torchaudio==2.11.0+torchcodec==0.14.0 (cu130) + GPU smoke test, then `whisperlivekit[diarization-sortformer]==0.2.24`. (R1/R2/R7)
- IFADV download from Zenodo (Annotations.zip + AudioWAV.zip 5.8 GB) → `data/ifadv/`.

**Done today:** project skeleton; docs: README, CLAUDE.md, PLAN, DATASETS, RESEARCH (+appendix), this journal; HF token → `.env`.

**Next:** finish env A install → GPU smoke test result recorded here → wlk --help verify flags → unzip+inventory IFADV → eval env (task #4) → HF datasets (task #5) → end-to-end go/no-go (task #6).
