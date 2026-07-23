# WEBAPP.md — the dia experiment web app (as-built)

FastAPI app (`app/server.py`) embedding WhisperLiveKit's `TranscriptionEngine` + `AudioProcessor` in-process, with a vanilla-JS frontend (`app/static/`). Runs in `venvs/wlk`.

## Run

```bash
scripts/run_app.sh        # alles-in-één: HTTP op :8080 + HTTPS op :8443 (mobiel/LAN-microfoon)
```

Het script laadt `.env`, maakt zo nodig eenmalig het certificaat (`scripts/make_cert.sh`,
alle host-IP's in de SAN) en start de TLS-proxy op :8443 automatisch mee. Op de machine
zelf: http://localhost:8080; vanaf telefoon/LAN: **https://<machinenaam>:8443** (de microfoon
vereist HTTPS buiten localhost; http-bezoekers krijgen een banner met de juiste link).
Detached draaien: `setsid nohup bash scripts/run_app.sh > eval/results/app_server.log 2>&1 &`

Engine flags load from `app/engine_config.json` (WLK CLI flags verbatim, e.g. `"--model": "large-v3-turbo"`). The engine loads during FastAPI startup — `/health` answers only after the model is up (warm ~30 s; first ever start downloads the model).

## UI tabs

- **Live mic** *(sinds 2026-07-23 expert-only, net als Evaluatie — gebruikersbesluit: de vergadertab toont zelf al een live transcript + doorlopende samenvatting, dus Live is alleen nog een motor-test)* — MediaRecorder (webm/opus, 250 ms chunks) → WS `/asr`; live speaker-colored transcript; gray italic = un-finalized partials; lag indicator = WLK's `remaining_time_*` metrics. On stop, the session is saved automatically. Standaardgebruikers zien drie werk-tabs: Vergadering · Bestand · Archief (+ Instellingen).
- **File** — upload any ffmpeg-readable audio (**m4a/AAC included**); optional **loudness normalization** (single-pass EBU R128 `loudnorm=I=-16:TP=-1.5:LRA=11` — use for quiet/uneven phone recordings); mode: **fast** (unpaced, after-the-fact processing) or **realtime replay** (true streaming behavior, for latency-faithful experiments).
- **Evaluate** — pick a dataset sample (IFADV dev/test, FLEURS, MLS, CV), server replays it through the exact live pipeline, reference shown side-by-side, then **WER / cpWER / DER** appear (scored via dialib: jiwer + meeteval, Dutch normalizer v1). The IFADV *test* split is marked HELD OUT — don't tune on it.
- **Sessions** — every run (mic/file/eval) is stored under `data/sessions/<id>/` (`hyp.seglst.json`, `meta.json` incl. full engine config, `events.jsonl` for latency analysis). Click to review; edit speaker/text per segment; **Save correction** → `data/corrections/<id>.seglst.json` (grows the local curated set for eval/fine-tuning).
- **Config** — edit engine flags as JSON; Apply reloads the engine in-process (old engine released + `torch.cuda.empty_cache()` first; takes 10–60 s).

## WebSocket protocol (`/asr`)

Server → client:
- `{"type":"ready","session_id":...}` on connect
- `{"type":"update", status, lines:[{speaker,text,start,end}], buffer_transcription, buffer_diarization, remaining_time_*}` — WLK FrontData passthrough; `speaker:-2` = silence, cumulative `lines`
- `{"type":"replay_progress","fed":s,"duration":s}` / `{"type":"replay_done"}`
- `{"type":"session_saved","session_id":...,"segments":[SegLST]}` then `{"type":"ready_to_stop"}`

Client → server:
- binary frames: live audio (any ffmpeg-decodable container; MediaRecorder webm works)
- `{"type":"replay","source":"upload:<id>"|"eval:ifadv/DVA1A"|"eval:fleurs_nl/<utt>","speed":1.0|0}` — speed 0 = fast/unpaced
- `{"type":"stop"}`

## REST API

| Route | What |
|---|---|
| `POST /api/upload` (multipart `file`, `loudnorm`) | → `{id, duration}`; stores original + processed 16k mono wav under `data/uploads/<id>/` |
| `GET /api/eval/list` · `GET /api/eval/reference?id=` | datasets/items · reference SegLST |
| `POST /api/score {reference_id, hypothesis}` | WER/cpWER/DER via dialib |
| `GET /api/sessions` · `GET /api/sessions/{id}` · `POST /api/sessions/{id}/correction` | session store + corrections |
| `GET/POST /api/config` | engine flags; POST persists + reloads engine |
| `GET /api/audio/{kind}/{path}` | serve audio for playback |
| `GET /health` | `{engine_ready, engine_args}` |
| `GET/POST /api/settings` · `/autodetect` · `/test` | samenvatter-LLM-instellingen (persistent) |
| `POST /api/summarize` | samenvatting van segments/sessie (optioneel `template_id`, `roles`) |
| `GET/POST/DELETE /api/templates[/{id}]` | samenvattingssjablonen (CRUD) |
| `POST /api/roles/guess` · `GET/POST /api/roles/{kind}/{id}` | LLM-rolvoorstel · rollen opslaan/lezen (bevestigingsvlag) |
| `POST /api/resummarize {kind,id,template_id}` | nieuwe samenvatting volgens sjabloon → nieuwe versie |
| `GET/POST /api/summary/{kind}/{id}` · `POST …/restore` | versiegeschiedenis: lezen, bewerken (nieuwe versie), herstellen |
| `POST /api/meetings/start` · `GET /api/meetings[/{id}]` · `POST …/stop` · `DELETE` · `GET …/download/{artifact}` · WS `…/feed` | vergaderingen (zie §Meetings) |
| `POST /api/offline/{upload_id}` · `GET /api/offline/{session_id}` | offline "beste kwaliteit"-verwerking van uploads |
| `GET /api/uploads` · `DELETE /api/sessions/{id}` | uploadlijst · verwijderen (privacy-compleet) |

## Meetings (persistent recorder — survives client disconnects)

The **Meeting tab** records a meeting server-side: transcribe + diarize live, rolling Dutch summary every ~2.5 min, everything downloadable afterwards. Built for "leave it running during a meeting".

### Samenvattingssjablonen, sprekerrollen en versiebeheer (2026-07-23, gebruikersverzoek)

- **Sjablonen** (`data/templates.json`; beheer in Instellingen; API `/api/templates` GET/POST/
  DELETE): een sjabloon = naam + optionele instructie + secties (één per regel). Drie
  defaults: *Algemeen gespreksverslag*, *Letselschade-intakegesprek* (toedracht,
  aansprakelijkheid, letsel/klachten, behandelingen, pre-existente klachten, werk/inkomen,
  beperkingen, schadeposten-inventarisatie, verzekeringen, vervolgstappen — onderbouwd met
  branchebronnen: intake-werkwijzen Drost/Letselverhalen, schadeposten-checklists,
  pre-existentie-uitleg) en *Regelingsgesprek met de tegenpartij* (schadeposten/standpunten,
  voorschotten+slotbetaling, finale kwijting, voorbehouden/heropening, belastinggarantie,
  BGK, vaststellingsovereenkomst — bronnen: De Letselschade Raad, VSO-kennisbanken).
- **Sprekerrollen** (kaart "Samenvatting op maat" in het archiefdetail): `/api/roles/guess`
  laat de LLM per spreker (tot 6) een rol voorstellen (best-guess); de gebruiker bewerkt en
  **bevestigt**; pas dan gebruiken samenvattingen de rolnamen (ook de automatische
  nabewerking). Opslag: state.json (meeting) / meta.json (sessie), veld `speaker_roles`.
- **Hersamenvattten**: `/api/resummarize {kind,id,template_id}` maakt op basis van het
  (verfijnde) transcript een nieuw verslag volgens het gekozen sjabloon én onthoudt die
  keuze per gesprek (`template_id` in state.json/meta.json; het detail selecteert hem voor).
- **Sjabloon per gesprek** (2026-07-23): kiesbaar bij de start (Gesprek-tab, standaard
  "automatisch"); de doorlopende én definitieve verslagen gebruiken de keuze. Zonder keuze
  kiest het taalmodel in de nabewerking zelf het meest passende sjabloon op basis van het
  transcript (`suggest_template`, terugval = algemeen; keuze wordt vastgelegd en is
  achteraf altijd te wijzigen). In het Archief-detail stelt "🎯 Sjabloon voorstellen"
  hetzelfde voor zonder direct te genereren — de gebruiker beslist.
- **Versiebeheer** (`summary_versions.json` per item; `/api/summary/{kind}/{id}` GET/POST +
  `/restore`): élke wijziging — automatisch, sjabloon, handmatig bewerkt — wordt een nieuwe
  versie met tijd, bron en een LLM-beschrijving van de wijziging; een current-pointer
  bepaalt de actieve versie; **herstellen = pointer terugzetten, er gaat nooit iets
  verloren**. De actieve versie wordt gespiegeld naar de downloadartefacten
  (refined_summary.md/summary.md/state.json). De automatische nabewerking maakt een
  gebruikerssamenvatting nooit meer stilzwijgend inactief: bestaat er al een handmatige/
  sjabloonversie, dan komt de automatische alleen in de geschiedenis. Bewerken kan direct
  in het detail (✏ Bewerken → nieuwe versie); ids zijn padinjectie-gevalideerd
  (`_safe_id`); templates.json wordt atomair geschreven.

### Verbindingsbewaking + adaptieve audiokwaliteit (2026-07-23, gebruikersverzoek)

- **Zichtbaarheid:** header-pill (verschijnt alleen bij problemen): *verbinding traag · Xs
  achter* (upload-achterstand = `ws.bufferedAmount` / gemeten recorder-bitrate), *geen
  verbinding* (navigator.onLine + /health-timeout >16 s → rode banner: "opname loopt op de
  server door"), *spaarzame modus*. De vergader-statuspil toont de achterstand ook
  ("microfoon verbonden · loopt 5s achter").
- **Gedrag bij storing:** vergader-statuspoll krijgt backoff (2 s → max 12 s) en meldt
  "server niet bereikbaar — opnieuw proberen…"; de mic-feeder herverbindt met exponentiële
  backoff (2→15 s; reset pas na ≥10 s stabiele verbinding, tegen open-dan-dicht-lussen).
- **Noodoplossing kwaliteit:** opus-bitrate 32 kbit/s normaal, **12 kbit/s spaarzaam**
  (checkbox "spaarzame verbinding" op het vergadertabblad; localStorage). Bij 3×
  opeenvolgende metingen >8 s achterstand op de vergaderstream schakelt hij automatisch om
  (feeder herverbindt met nieuwe bitrate; server vult het gaatje met stilte). Automatische
  omschakeling wordt bewust NIET gepersisteerd — alleen expliciete gebruikerskeuzes.
  De server maakt van alles 16 kHz mono PCM, dus de herkenningskwaliteit lijdt nauwelijks.
- **Lifecycle-hardening (gevonden via 3 adversariële reviewrondes):** feeder-state leeft in
  de closure van `meetingStartFeeder` (niet op het globale meeting-object); teardown bij
  start/wissel/stop/serverzijdig-finished; await-race-bescherming rond getUserMedia
  (`meetingFeederStart`); wake lock met eigenaren-refcount; live-mic ruimt ook op bij
  abnormale WS-sluiting en bij Stop-vóór-open.

- **Persistence model:** the session lives in the server (`app/meetings.py`). The browser is (a) a *feeder* — streams mic audio over WS `/api/meetings/{id}/feed`, auto-reconnects every 2 s on drops, wall-clock gaps are filled with silence (≤5 min) so timestamps stay aligned; and (b) a *viewer* — polls `GET /api/meetings/{id}` every 2 s, so closing the tab/laptop changes nothing. Re-open the page later and "bekijk / heraansluiten" re-attaches your mic to the running meeting.
- **Crash-safety:** raw PCM is appended to `data/meetings/<id>/audio.raw` continuously; `state.json` snapshots every 30 s. A server restart orphans the live pipeline but audio + transcript-so-far survive (listed as "orphaned"; audio can be re-processed offline).
- **Stop & artifacts:** `POST /api/meetings/{id}/stop` finalizes: final LLM summary over the whole transcript, then downloads at `/api/meetings/{id}/download/…`: `audio.wav`, `transcript.seglst.json`, `transcript.txt` (readable, `[mm:ss] spkN:` lines), `summary.md`, `meta.json`. File-source meetings (`source: "file:<eval-id>"`, used by tests/demos) auto-finalize when the file ends.
- **Sources:** browser mic (the Spark has no capture hardware — checked) or `file:` replay. LAN mics need the HTTPS variant (`scripts/run_app.sh --ssl`).

## Testing

`venvs/wlk/bin/python tests/test_app_e2e.py` against the running server: health, uploads (wav+loudnorm, **m4a**), eval catalog/reference, live-pipeline WS replay, scoring, session persistence + corrections, summarize, meeting lifecycle (file-source auto-finalize, artifacts, empty-meeting edge case, listing). **Status 2026-07-22: 15/16 pass; the `summarize` test fails only while GPU batch jobs starve the LLM (contention, not a bug — see ops note).** The suite found and led to fixes for two real meeting bugs: file-source meetings never finalizing, and a stop-path hang on empty pipelines.

**Ops note (GB10 unified GPU):** heavy batch jobs (training, batch scoring) starve the vLLM summarizer to unresponsiveness. Schedule summarization-dependent work outside batch windows; the eval chains do this by ordering LLM steps last.

## Design notes / gotchas

- One engine at a time (unified memory!); engine reload is serialized behind a lock.
- Replay decodes via ffmpeg to s16le 16 kHz mono and sets `processor.is_pcm_input = True` (same trick as WLK's REST endpoint).
- Session persistence happens in the WS `finally` block — also on abrupt disconnect.
- The eval harness (`eval/run_eval.py`) reuses the same `/asr` replay path, so UI numbers and harness numbers are produced by the identical code path.
- WLK quirk: `Segment` times can arrive as `H:MM:SS.cc` strings — `dialib.seglst.parse_wlk_time` handles both.
