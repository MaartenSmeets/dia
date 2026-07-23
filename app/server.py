"""dia experiment server — wraps WhisperLiveKit for live Dutch transcription+diarization
plus evaluation/replay/correction features. See docs/WEBAPP.md.

Run:  scripts/run_app.sh   (uses venvs/wlk; loads .env; port 8080 by default)

Endpoints:
  GET  /                       web UI
  WS   /asr                    audio in (mic bytes OR one JSON replay command), results out
  POST /api/upload             multipart file (any ffmpeg format, m4a OK) + loudnorm flag
  GET  /api/eval/list          datasets + items available for replay/eval
  GET  /api/eval/reference     ?id=ifadv/DVA1A -> reference SegLST
  POST /api/score              {"reference_id": ..., "hypothesis": [segments]} -> metrics
  GET  /api/audio/{source}     serve audio (uploads + eval sets) for browser playback
  GET  /api/sessions           list saved sessions;  GET /api/sessions/{id} -> detail
  POST /api/sessions/{id}/correction   save corrected SegLST
  GET/POST /api/config         engine config view / update+reload
  GET  /health
"""
from __future__ import annotations

import asyncio
import gc
import json
import logging
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect  # noqa: E402
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from dialib import metrics  # noqa: E402
from dialib.seglst import load_seglst, save_seglst, wlk_lines_to_seglst  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("dia")

CONFIG_PATH = ROOT / "app/engine_config.json"
UPLOADS = ROOT / "data/uploads"
SESSIONS = ROOT / "data/sessions"
CORRECTIONS = ROOT / "data/corrections"
for d in (UPLOADS, SESSIONS, CORRECTIONS):
    d.mkdir(parents=True, exist_ok=True)

SR = 16000
BYTES_PER_SEC = SR * 2  # s16le mono
CHUNK_SEC = 0.25


# --------------------------------------------------------------------- engine

class EngineManager:
    """Holds the WLK TranscriptionEngine; supports reload with new args."""

    def __init__(self) -> None:
        self.engine = None
        self.args: dict = {}
        self.lock = asyncio.Lock()

    def _parse_config(self, args: dict):
        """args: {"--model": "large-v3", "--diarization": true, ...} -> WLK config namespace."""
        from whisperlivekit.parse_args import parse_args
        argv = []
        for k, v in args.items():
            if v is False or v is None:
                continue
            argv.append(k)
            if v is not True:
                argv.append(str(v))
        old = sys.argv
        try:
            sys.argv = ["wlk"] + argv
            return parse_args()
        finally:
            sys.argv = old

    async def load(self, args: dict) -> None:
        from whisperlivekit import TranscriptionEngine
        async with self.lock:
            if self.engine is not None:
                logger.info("releasing previous engine")
                self.engine = None
                # TranscriptionEngine is a hard singleton: without reset(), a new
                # construction silently returns the OLD engine and ignores the new
                # config ("engine loaded in 0.0s" symptom).
                TranscriptionEngine.reset()
                gc.collect()
                try:
                    import torch
                    torch.cuda.empty_cache()
                except Exception:
                    pass
            config = self._parse_config(args)
            logger.info("loading engine: %s", args)
            t0 = time.time()
            self.engine = await asyncio.to_thread(TranscriptionEngine, config=config)
            self.args = args
            logger.info("engine loaded in %.1fs", time.time() - t0)


manager = EngineManager()


def default_args() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {
        "--model": "large-v3",
        "--lan": "nl",
        "--diarization": True,
        "--diarization-backend": "sortformer",
        "--disable-fast-encoder": True,
        "--backend-policy": "simulstreaming",
    }


# --------------------------------------------------------------------- app

app = FastAPI(title="dia — Dutch realtime diarized transcription")
app.mount("/static", StaticFiles(directory=ROOT / "app/static"), name="static")


@app.on_event("startup")
async def startup() -> None:
    # smart default: if no summarizer configured (or it moved), find one automatically
    if not os.environ.get("SUMMARIZER_URL"):
        await autodetect_summarizer()
    else:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=3) as c:
                (await c.get(os.environ["SUMMARIZER_URL"].rstrip("/") + "/models")).raise_for_status()
        except Exception:
            logger.info("configured summarizer unreachable — re-detecting")
            await autodetect_summarizer()
    await manager.load(default_args())


@app.get("/")
async def index():
    return HTMLResponse((ROOT / "app/static/index.html").read_text(encoding="utf-8"))


@app.get("/health")
async def health():
    return {"status": "ok", "engine_ready": manager.engine is not None, "engine_args": manager.args}


# ------------------------------------------------------------------ audio sources

def resolve_source(source: str) -> Path:
    """'upload:<id>' | 'eval:ifadv/DVA1A' | 'eval:fleurs_nl/fleurs_00001' -> wav path."""
    kind, _, rest = source.partition(":")
    if kind == "upload":
        p = UPLOADS / rest / "processed.wav"
        if p.exists():
            return p
        raise HTTPException(404, f"upload {rest} not found")
    if kind == "eval":
        ds, _, utt = rest.partition("/")
        if ds == "ifadv":
            hits = sorted((ROOT / "data/ifadv").rglob(f"{utt}*.wav"))
            if hits:
                return hits[0]
            raise HTTPException(404, f"IFADV audio for {utt} not found (audio still downloading?)")
        if ds in ("cgn_a", "cgn_tel"):
            cat = json.loads((ROOT / f"eval/references/{ds}/catalog.json").read_text())
            for e in cat:
                if e["id"] == utt:
                    return ROOT / e["wav"]
            raise HTTPException(404, f"{ds} recording {utt} not in catalog")
        if ds.startswith("hybrid_"):  # hybrid_<variant>_dev/<ID> -> data/hybrid/<variant>/<ID>.wav
            variant = ds.removeprefix("hybrid_").removesuffix("_dev")
            p = ROOT / "data/hybrid" / variant / f"{utt}.wav"
            if p.exists():
                return p
            raise HTTPException(404, f"hybride audio {variant}/{utt} not found")
        p = ROOT / "eval/audio" / ds / f"{utt}.wav"
        if p.exists():
            return p
        raise HTTPException(404, f"eval audio {rest} not found")
    raise HTTPException(400, f"unknown source kind {kind}")


async def decode_to_pcm(path: Path, loudnorm: bool = False) -> bytes:
    """ffmpeg: any format -> s16le 16k mono, optional single-pass EBU R128 loudnorm."""
    af = ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11"] if loudnorm else []
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-i", str(path), *af,
        "-f", "s16le", "-acodec", "pcm_s16le", "-ar", str(SR), "-ac", "1",
        "-loglevel", "error", "pipe:1",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise HTTPException(400, f"ffmpeg failed: {err.decode()[:400]}")
    return out


@app.post("/api/upload")
async def upload(file: UploadFile = File(...), loudnorm: bool = Form(default=False)):
    uid = uuid.uuid4().hex[:10]
    d = UPLOADS / uid
    d.mkdir(parents=True)
    suffix = Path(file.filename or "audio").suffix or ".bin"
    orig = d / f"original{suffix}"
    orig.write_bytes(await file.read())
    pcm = await decode_to_pcm(orig, loudnorm=loudnorm)
    # store processed as proper wav for later playback
    import struct
    wav_header = (b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " +
                  struct.pack("<IHHIIHH", 16, 1, 1, SR, BYTES_PER_SEC, 2, 16) +
                  b"data" + struct.pack("<I", len(pcm)))
    (d / "processed.wav").write_bytes(wav_header + pcm)
    duration = len(pcm) / BYTES_PER_SEC
    meta = {"id": uid, "filename": file.filename, "loudnorm": loudnorm,
            "duration": round(duration, 2), "created": time.strftime("%Y-%m-%d %H:%M:%S")}
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return meta


@app.get("/api/uploads")
async def list_uploads():
    out = []
    for m in sorted(UPLOADS.glob("*/meta.json")):
        try:
            out.append(json.loads(m.read_text()))
        except Exception:
            logger.warning("meta.json onleesbaar, upload overgeslagen: %s", m)
    return out


@app.get("/api/audio/{kind}/{rest:path}")
async def serve_audio(kind: str, rest: str):
    return FileResponse(resolve_source(f"{kind}:{rest}"))


# ------------------------------------------------------------------ eval data

@app.get("/api/eval/list")
async def eval_list():
    datasets = []
    mdir = ROOT / "eval/manifests"
    for split in ("dev", "test"):
        p = mdir / f"ifadv_{split}.json"
        if p.exists():
            m = json.loads(p.read_text())
            datasets.append({"id": f"ifadv_{split}", "kind": "conversation",
                             "items": [{"id": f"ifadv/{d}", "label": d} for d in m["dialogues"]],
                             "held_out": split == "test"})
        for ds in ("cgn_a", "cgn_tel"):
            p = mdir / f"{ds}_{split}.json"
            if p.exists():
                m = json.loads(p.read_text())
                datasets.append({"id": f"{ds}_{split}", "kind": "conversation",
                                 "items": [{"id": f"{ds}/{it['utt']}",
                                            "label": f"{it['utt']} ({it['n_speakers']}spk, {int(it['duration'])}s)"}
                                           for it in m["items"]],
                                 "held_out": split == "test"})
    for p in sorted(mdir.glob("*_test.json")):
        if p.name.startswith(("ifadv", "cgn")):
            continue
        m = json.loads(p.read_text())
        items = [{"id": f"{m['dataset']}/{it['utt']}", "label": f"{it['utt']} ({it['duration']}s)",
                  "duration": it["duration"]} for it in m["items"][:200]]
        datasets.append({"id": m["dataset"], "kind": "single-speaker", "n_total": m["n"], "items": items})
    return datasets


def reference_for(ref_id: str) -> list[dict]:
    ds, _, utt = ref_id.partition("/")
    if ds in ("ifadv", "cgn_a", "cgn_tel"):
        p = ROOT / "eval/references" / ds / f"{utt}.seglst.json"
        if not p.exists():
            raise HTTPException(404, f"no reference for {ref_id}")
        return load_seglst(p)
    p = ROOT / "eval/references" / f"{ds}.seglst.json"
    if not p.exists():
        raise HTTPException(404, f"no reference file for dataset {ds}")
    segs = [s for s in load_seglst(p) if s["session_id"] == utt]
    if not segs:
        raise HTTPException(404, f"utt {utt} not in {ds} references")
    return segs


@app.get("/api/eval/reference")
async def eval_reference(id: str):
    return reference_for(id)


@app.post("/api/score")
async def score(payload: dict):
    ref_id = payload.get("reference_id")
    hyp = payload.get("hypothesis") or []
    if not ref_id:
        raise HTTPException(400, "reference_id required")
    ref = reference_for(ref_id)
    # align session ids so meeteval matches them
    sid = ref[0]["session_id"]
    for s in hyp:
        s["session_id"] = sid
    result = metrics.score_all(ref, hyp)
    result["reference_id"] = ref_id
    result["n_ref_segments"] = len(ref)
    result["n_hyp_segments"] = len(hyp)
    return JSONResponse(result)


# ------------------------------------------------------------------ summarization (call-center use case)
# Uses any local OpenAI-compatible endpoint (vLLM etc.). Configure in .env:
#   SUMMARIZER_URL=http://localhost:8000/v1   SUMMARIZER_MODEL=<served model name>

import os


# ------------------------------------------------------------------ external services settings
# Configurable via the web UI (Config tab) and persistent across restarts.
# Precedence: app/settings.json (UI-managed) > .env > unset.

SETTINGS_PATH = ROOT / "app/settings.json"
SETTINGS_KEYS = ("SUMMARIZER_URL", "SUMMARIZER_MODEL", "JUDGE_URL", "JUDGE_MODEL",
                 "REFINE_ADAPTER")  # LoRA voor de offline "definitieve versie"; leeg = basismodel


def load_settings() -> dict:
    if SETTINGS_PATH.exists():
        try:
            s = json.loads(SETTINGS_PATH.read_text())
            for k in SETTINGS_KEYS:
                if s.get(k):
                    os.environ[k] = s[k]
            return s
        except Exception:
            logger.warning("settings.json unreadable — ignored")
    return {}


load_settings()

AUTODETECT_PORTS = (8000, 8001, 5000, 11434, 30000)


async def autodetect_summarizer() -> dict:
    """Find a local OpenAI-compatible LLM and select its first model automatically.
    Used at startup and on demand, so a jurist never has to configure anything."""
    import httpx
    async with httpx.AsyncClient(timeout=3) as client:
        for port in AUTODETECT_PORTS:
            try:
                r = await client.get(f"http://localhost:{port}/v1/models")
                r.raise_for_status()
                models = [m.get("id") for m in r.json().get("data", []) if m.get("id")]
                if models:
                    os.environ["SUMMARIZER_URL"] = f"http://localhost:{port}/v1"
                    os.environ["SUMMARIZER_MODEL"] = models[0]
                    current = {k: os.environ.get(k, "") for k in SETTINGS_KEYS}
                    SETTINGS_PATH.write_text(json.dumps({**current, "_autodetected": True}, indent=1),
                                             encoding="utf-8")
                    logger.info("summarizer auto-detected: %s on :%s", models[0], port)
                    return {"ok": True, "url": os.environ["SUMMARIZER_URL"], "model": models[0]}
            except Exception:
                continue
    return {"ok": False, "detail": "geen lokaal taalmodel gevonden (poorten "
                                   + ", ".join(map(str, AUTODETECT_PORTS)) + ")"}


@app.post("/api/settings/autodetect")
async def settings_autodetect():
    return await autodetect_summarizer()


@app.get("/api/settings")
async def get_settings():
    return {k: os.environ.get(k, "") for k in SETTINGS_KEYS}


@app.post("/api/settings")
async def set_settings(payload: dict):
    current = {k: os.environ.get(k, "") for k in SETTINGS_KEYS}
    for k in SETTINGS_KEYS:
        if k in payload:
            v = (payload[k] or "").strip()
            current[k] = v
            if v:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)
    SETTINGS_PATH.write_text(json.dumps(current, indent=1), encoding="utf-8")
    return {"saved": True, **current}


@app.get("/api/settings/test")
async def test_settings():
    """Server-side reachability probe of the configured LLM endpoint (avoids CORS)."""
    base = os.environ.get("SUMMARIZER_URL", "").rstrip("/")
    if not base:
        return {"ok": False, "detail": "SUMMARIZER_URL niet ingesteld"}
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{base}/models")
            r.raise_for_status()
            models = [m.get("id") for m in r.json().get("data", [])]
        return {"ok": True, "models": models}
    except Exception as e:
        return {"ok": False, "detail": str(e)[:200] or "endpoint antwoordt niet"}


# ------------------------------------------------------------------ samenvattingssjablonen

TEMPLATES_PATH = ROOT / "data/templates.json"

# Letselschade-secties onderbouwd met branchebronnen (intake-werkwijzen van
# letselschadebureaus + schadeposten-checklists; zie docs/WEBAPP.md §Sjablonen).
DEFAULT_TEMPLATES = [
    {"id": "algemeen", "naam": "Algemeen gespreksverslag", "instructie": "",
     "secties": ["Onderwerp", "Kernpunten per spreker", "Afspraken en acties",
                 "Openstaande punten"]},
    {"id": "letselschade-intake", "naam": "Letselschade-intakegesprek",
     "instructie": ("Dit is een juridisch intakegesprek. Noteer feitelijk; neem datums, "
                    "bedragen en namen letterlijk uit het gesprek over; markeer "
                    "onzekerheden en tegenstrijdigheden expliciet."),
     "secties": [
         "Betrokkenen en rolverdeling in het gesprek",
         "Toedracht van het ongeval of voorval (datum, plaats, omstandigheden)",
         "Aansprakelijkheid (tegenpartij, verzekeraar, aansprakelijkstelling of erkenning, getuigen en bewijs)",
         "Letsel en huidige klachten",
         "Al uitgevoerde en lopende medische behandelingen (behandelaars, diagnoses, vervolgtraject)",
         "Medische voorgeschiedenis en pre-existente klachten",
         "Werk en inkomen (beroep, verzuim, arbeidsongeschiktheid, re-integratie)",
         "Beperkingen in het dagelijks leven (huishouden, zelfwerkzaamheid, gezin, hobby's)",
         "Inventarisatie schadeposten (medische kosten, reiskosten, huishoudelijke hulp, verlies van verdienvermogen, studievertraging, smartengeld, overige)",
         "Verzekeringen en voorzieningen (eigen verzekeringen, rechtsbijstand, uitkeringen)",
         "Afspraken en vervolgstappen (plan van aanpak, op te vragen stukken, machtigingen)",
     ]},
    {"id": "regelingsgesprek", "naam": "Regelingsgesprek met de tegenpartij",
     "instructie": ("Dit is een onderhandelings-/afwikkelingsgesprek met de tegenpartij of "
                    "diens verzekeraar. Onderscheid per punt duidelijk de standpunten van "
                    "beide partijen en wat er daadwerkelijk is afgesproken versus wat open "
                    "staat. Neem bedragen, percentages en termijnen letterlijk over."),
     "secties": [
         "Betrokkenen en rolverdeling (belangenbehartiger, verzekeraar/schaderegelaar, cliënt)",
         "Stand van het dossier en aanleiding voor het regelingsgesprek",
         "Besproken schadeposten en bedragen (per post: standpunt van beide partijen)",
         "Verstrekte voorschotten en verrekening; hoogte en termijn van de slotbetaling",
         "Voorstel eindregeling en verloop van de onderhandeling",
         "Finale kwijting (reikwijdte: welke schade valt er wel en niet onder)",
         "Voorbehouden en voorwaarden voor heropening (o.a. medisch voorbehoud bij verslechtering, termijnen)",
         "Belastinggarantie en fiscale afspraken",
         "Buitengerechtelijke kosten (BGK): standpunten en afspraken over vergoeding",
         "Vaststellingsovereenkomst (wie stelt op, teken- en bedenktermijn)",
         "Afspraken, actiepunten en termijnen",
     ]},
]


def load_templates() -> list[dict]:
    if not TEMPLATES_PATH.exists():
        TEMPLATES_PATH.write_text(json.dumps(DEFAULT_TEMPLATES, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
    try:
        tpls = json.loads(TEMPLATES_PATH.read_text(encoding="utf-8"))
        if isinstance(tpls, list) and tpls:
            return tpls
    except Exception:
        logger.warning("templates.json onleesbaar — defaults gebruikt")
    return [dict(t) for t in DEFAULT_TEMPLATES]


def get_template(tid: str | None) -> dict:
    tpls = load_templates()
    for t in tpls:
        if t.get("id") == tid:
            return t
    for t in tpls:  # standaard = vast id, niet bestandsvolgorde
        if t.get("id") == "algemeen":
            return t
    return tpls[0]


async def summarize_segments_llm(segments: list[dict], prev: str = "", final: bool = False,
                                 template: dict | None = None,
                                 roles: dict | None = None) -> str:
    """Shared summarizer core (API endpoint + meeting rolling/final summaries).
    template: sjabloon-dict (None = eerste/standaardsjabloon). roles: ALLEEN meegeven
    wanneer de gebruiker de sprekerrollen heeft bevestigd — dan vult de samenvatting
    rolnamen in plaats van spk-codes in."""
    base = os.environ.get("SUMMARIZER_URL", "").rstrip("/")
    model_name = os.environ.get("SUMMARIZER_MODEL", "")
    if not base:
        raise HTTPException(503, "Geen taalmodel ingesteld — ga naar Instellingen en klik "
                                 "'Automatisch detecteren'.")
    prev = (prev or "").strip()
    transcript = "\n".join(f"[{s.get('speaker', '?')}] {s.get('words', '')}" for s in segments[-400:])
    tpl = template or get_template(None)
    secties = "\n".join(f"{i+1}) {s}" for i, s in enumerate(tpl.get("secties", [])))
    rol_txt = ""
    if roles:
        rol_txt = ("\nDoor de gebruiker bevestigde sprekerrollen: "
                   + "; ".join(f"{k} = {v}" for k, v in roles.items() if v)
                   + ". Gebruik in de samenvatting deze rolnamen in plaats van de spk-codes.")
    system = (f"Je bent een assistent die Nederlandse gesprekken samenvat volgens het sjabloon "
              f"'{tpl.get('naam', 'verslag')}'. Vul de volgende onderdelen beknopt en zakelijk "
              f"in het Nederlands in, met korte bullets per onderdeel. Sla geen onderdeel over; "
              f"schrijf 'niet besproken' bij onderdelen zonder informatie. Verzin niets.\n"
              f"{secties}\n{tpl.get('instructie', '')}{rol_txt}")
    if final:
        lead = ("Maak de DEFINITIEVE samenvatting van het afgeronde gesprek. "
                + (f"Werksamenvatting tot nu toe:\n{prev}\n\n" if prev else ""))
    elif prev:
        lead = (f"Bestaande samenvatting tot nu toe:\n{prev}\n\n"
                "Werk de samenvatting bij met het onderstaande nieuwe transcriptdeel.\n\n")
    else:
        lead = "Vat het volgende (lopende) gesprek samen.\n\n"
    import httpx
    async with httpx.AsyncClient(timeout=180) as client:
        r = await client.post(f"{base}/chat/completions", json={
            "model": model_name or "default",
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": lead + f"Transcript:\n{transcript}"}],
            "temperature": 0.2, "max_tokens": 900,
            # Qwen3.x reasoning models: without this, content comes back null
            "chat_template_kwargs": {"enable_thinking": False}})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"] or ""


@app.post("/api/summarize")
async def summarize(payload: dict):
    segments = payload.get("segments")
    if not segments and payload.get("session_id"):
        p = SESSIONS / payload["session_id"] / "hyp.seglst.json"
        if not p.exists():
            raise HTTPException(404, "session not found")
        segments = load_seglst(p)
    if not segments:
        raise HTTPException(400, "segments or session_id required")
    import httpx
    template = get_template(payload.get("template_id")) if payload.get("template_id") else None
    roles = payload.get("roles") if payload.get("roles_confirmed") else None
    try:
        summary = await summarize_segments_llm(segments, payload.get("previous_summary", ""),
                                               final=bool(payload.get("final")),
                                               template=template, roles=roles)
    except (httpx.TimeoutException, httpx.ConnectError) as e:  # vóór HTTPError: subklassen
        logger.warning("samenvatten: taalmodel onbereikbaar (%s)", e)
        raise HTTPException(504, "Het taalmodel reageert niet — controleer bij Instellingen "
                                 "of het model draait en probeer het opnieuw.")
    except httpx.HTTPError as e:
        logger.warning("samenvatten: taalmodelfout (%s)", e)
        raise HTTPException(502, "Het taalmodel gaf een fout — probeer het opnieuw of "
                                 "controleer de verbinding onder Instellingen.")
    return {"summary": summary, "n_segments": len(segments)}


# ------------------------------------------------------------------ sjablonen + rollen

import re as _re


def _safe_id(s: str) -> str:
    """Id-validatie voor alles wat in een pad belandt (padinjectie-verdediging)."""
    if not isinstance(s, str) or not _re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}", s) or ".." in s:
        raise HTTPException(400, "ongeldig id")
    return s


def _item_dir(kind: str, item_id: str) -> Path:
    _safe_id(item_id)
    if kind == "meeting":
        d = ROOT / "data/meetings" / item_id
    elif kind == "session":
        d = SESSIONS / item_id
    else:
        raise HTTPException(400, "kind moet meeting of session zijn")
    if not d.exists():
        raise HTTPException(404, f"{kind} {item_id} niet gevonden")
    return d


def _atomic_json(path: Path, obj) -> None:
    import tempfile
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


@app.get("/api/templates")
async def templates_list():
    return {"templates": load_templates()}


@app.post("/api/templates")
async def templates_save(payload: dict):
    naam = (payload.get("naam") or "").strip()
    secties = [s.strip() for s in (payload.get("secties") or []) if s and s.strip()]
    if not naam or not secties:
        raise HTTPException(400, "naam en minimaal één sectie vereist")
    if TEMPLATES_PATH.exists():
        try:
            json.loads(TEMPLATES_PATH.read_text(encoding="utf-8"))
        except Exception:
            # NIET stilzwijgend defaults terugschrijven — dat zou eigen sjablonen wissen
            raise HTTPException(500, "templates.json is beschadigd — herstel het bestand eerst")
    tpls = load_templates()
    tid = _safe_id((payload.get("id") or "").strip() or ("tpl-" + uuid.uuid4().hex[:8]))
    entry = {"id": tid, "naam": naam, "instructie": (payload.get("instructie") or "").strip(),
             "secties": secties}
    for i, t in enumerate(tpls):
        if t.get("id") == tid:
            tpls[i] = entry
            break
    else:
        tpls.append(entry)
    _atomic_json(TEMPLATES_PATH, tpls)
    return {"saved": True, "template": entry}


@app.delete("/api/templates/{tid}")
async def templates_delete(tid: str):
    tpls = load_templates()
    keep = [t for t in tpls if t.get("id") != tid]
    if len(keep) == len(tpls):
        raise HTTPException(404, "sjabloon niet gevonden")
    if not keep:
        raise HTTPException(400, "het laatste sjabloon kan niet worden verwijderd")
    _atomic_json(TEMPLATES_PATH, keep)
    return {"deleted": tid}


def _roles_store(kind: str, item_id: str):
    """Sleutelbestand voor sprekerrollen: vergadering → state.json, sessie → meta.json."""
    d = _item_dir(kind, item_id)
    p = d / ("state.json" if kind == "meeting" else "meta.json")
    if not p.exists():
        raise HTTPException(404, f"{kind} {item_id} niet gevonden")
    return p


# ------------------------------------------------------------------ samenvattingsversies
# Elke wijziging (automatisch, sjabloon, handmatig) wordt een NIEUWE versie in
# summary_versions.json; een current-pointer bepaalt de actieve versie. Niets wordt ooit
# overschreven; herstellen = pointer terugzetten. De actieve tekst wordt gespiegeld naar
# de bestaande downloadartefacten (refined_summary.md / summary.md / state.json).

SUMVER = "summary_versions.json"
USER_BRONNEN = ("handmatig", "sjabloon")  # bronnen die als gebruikerswerk tellen
# per (kind, item_id): read-modify-write op summary_versions.json serialiseren
_sum_locks: dict[tuple, asyncio.Lock] = {}


def _sum_load(kind: str, d: Path) -> dict:
    p = d / SUMVER
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("summary_versions.json onleesbaar in %s", d)
    data = {"versions": [], "current": 0}
    # bestaande samenvatting van vóór het versiebeheer lui inladen als versie 1
    legacy = None
    for name in ("refined_summary.md", "summary.md"):
        if (d / name).exists():
            legacy = _re.sub(r"^# .*\n+", "", (d / name).read_text(encoding="utf-8")).strip()
            break
    if legacy:
        data["versions"].append({"v": 1, "tijd": time.strftime("%Y-%m-%d %H:%M"),
                                 "bron": "bestaand gespreksverslag", "wijziging": "eerste versie",
                                 "tekst": legacy})
        data["current"] = 1
    return data


def _sum_mirror(kind: str, d: Path, tekst: str, titel: str) -> None:
    """Actieve versie doorspiegelen naar de artefacten die downloads/weergave gebruiken."""
    inhoud = f"# {titel}\n\n{tekst}\n"
    if kind == "meeting":
        target = "refined_summary.md" if (d / "refined_transcript.seglst.json").exists() else "summary.md"
        (d / target).write_text(inhoud, encoding="utf-8")
        sp = d / "state.json"
        if sp.exists():  # detailweergave zonder refined leest state.json
            st = json.loads(sp.read_text())
            st["summary"] = tekst
            _atomic_json(sp, st)
    else:
        (d / "summary.md").write_text(inhoud, encoding="utf-8")


async def _describe_change(oud: str, nieuw: str) -> str:
    """Eén korte LLM-zin over wat er inhoudelijk veranderde (met nette terugval)."""
    if not (oud or "").strip():
        return "eerste versie"
    base = os.environ.get("SUMMARIZER_URL", "").rstrip("/")
    if not base:
        return "bijgewerkt"
    import httpx
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            r = await client.post(f"{base}/chat/completions", json={
                "model": os.environ.get("SUMMARIZER_MODEL", "") or "default",
                "messages": [
                    {"role": "system", "content":
                     "Beschrijf in ÉÉN korte Nederlandse zin (max 15 woorden) het inhoudelijke "
                     "verschil tussen de oude en nieuwe tekst. Alleen de zin, niets anders."},
                    {"role": "user", "content": f"OUD:\n{oud[:4000]}\n\nNIEUW:\n{nieuw[:4000]}"}],
                "temperature": 0.0, "max_tokens": 60,
                "chat_template_kwargs": {"enable_thinking": False}})
            r.raise_for_status()
            zin = (r.json()["choices"][0]["message"]["content"] or "").strip()
            return zin[:160] or "bijgewerkt"
    except Exception:
        return "bijgewerkt"


async def summary_append(kind: str, item_id: str, tekst: str, bron: str, titel: str,
                         make_current: bool = True, wijziging: str | None = None) -> dict:
    d = _item_dir(kind, item_id)
    async with _sum_locks.setdefault((kind, item_id), asyncio.Lock()):
        data = _sum_load(kind, d)
        huidige = next((v["tekst"] for v in data["versions"] if v["v"] == data["current"]), "")
        if wijziging is None:
            wijziging = await _describe_change(huidige, tekst)
        nv = (data["versions"][-1]["v"] + 1) if data["versions"] else 1
        data["versions"].append({"v": nv, "tijd": time.strftime("%Y-%m-%d %H:%M"),
                                 "bron": bron, "wijziging": wijziging, "tekst": tekst})
        data["versions"] = data["versions"][-50:]  # ruime cap; v-nummers blijven stabiel
        if make_current:
            data["current"] = nv
            _sum_mirror(kind, d, tekst, titel)
        _atomic_json(d / SUMVER, data)
        return {"v": nv, "current": data["current"]}


@app.get("/api/summary/{kind}/{item_id}")
async def summary_get(kind: str, item_id: str):
    d = _item_dir(kind, item_id)
    data = _sum_load(kind, d)
    cur = next((v for v in data["versions"] if v["v"] == data["current"]), None)
    try:
        tpl_id = json.loads(_roles_store(kind, item_id).read_text()).get("template_id") or ""
    except Exception:
        tpl_id = ""
    return {"current": data["current"], "tekst": cur["tekst"] if cur else "",
            "template_id": tpl_id,
            "versions": [{k: v[k] for k in ("v", "tijd", "bron", "wijziging")}
                         for v in reversed(data["versions"])],
            "teksten": {str(v["v"]): v["tekst"] for v in data["versions"]}}


@app.post("/api/summary/{kind}/{item_id}")
async def summary_edit(kind: str, item_id: str, payload: dict):
    tekst = (payload.get("tekst") or "").strip()
    if not tekst:
        raise HTTPException(400, "tekst vereist")
    # wijziging vast meegeven: geen LLM-aanroep laten blokkeren op een handmatige opslag
    res = await summary_append(kind, item_id, tekst, "handmatig bewerkt", "Gespreksverslag",
                               wijziging="handmatig bewerkt")
    return {"saved": True, **res}


@app.post("/api/summary/{kind}/{item_id}/restore")
async def summary_restore(kind: str, item_id: str, payload: dict):
    d = _item_dir(kind, item_id)
    async with _sum_locks.setdefault((kind, item_id), asyncio.Lock()):
        data = _sum_load(kind, d)
        v = payload.get("v")
        ver = next((x for x in data["versions"] if x["v"] == v), None)
        if not ver:
            raise HTTPException(404, "versie niet gevonden")
        data["current"] = v  # herstellen = pointer terug; geschiedenis blijft intact
        _atomic_json(d / SUMVER, data)
        _sum_mirror(kind, d, ver["tekst"], "Gespreksverslag")
        return {"restored": v, "tekst": ver["tekst"]}


@app.get("/api/roles/{kind}/{item_id}")
async def roles_get(kind: str, item_id: str):
    p = _roles_store(kind, item_id)
    d = json.loads(p.read_text())
    return d.get("speaker_roles") or {"rollen": {}, "bevestigd": False}


@app.post("/api/roles/{kind}/{item_id}")
async def roles_save(kind: str, item_id: str, payload: dict):
    p = _roles_store(kind, item_id)
    d = json.loads(p.read_text())
    d["speaker_roles"] = {"rollen": {k: (v or "").strip() for k, v in (payload.get("rollen") or {}).items()},
                          "bevestigd": bool(payload.get("bevestigd"))}
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"saved": True, **d["speaker_roles"]}


@app.post("/api/roles/guess")
async def roles_guess(payload: dict):
    """Best-guess sprekerrollen door de LLM (daarna door de gebruiker te bewerken;
    pas ná bevestiging gebruikt de samenvatting ze)."""
    segments = payload.get("segments") or []
    if not segments:
        raise HTTPException(400, "segments required")
    speakers = []
    for s in segments:
        spk = s.get("speaker")
        if spk and spk not in speakers:
            speakers.append(spk)
    speakers = speakers[:6]  # praktijkgrens: tot ~5-6 deelnemers
    transcript = "\n".join(f"[{s.get('speaker', '?')}] {s.get('words', '')}" for s in segments[:400]
                           if s.get("speaker") in speakers)
    base = os.environ.get("SUMMARIZER_URL", "").rstrip("/")
    if not base:
        raise HTTPException(503, "Geen taalmodel ingesteld — ga naar Instellingen en klik "
                                 "'Automatisch detecteren'.")
    import httpx
    system = ("Je bepaalt de rol van elke spreker in een Nederlands gesprek (bijv. "
              "letselschadejurist/belangenbehartiger, cliënt/slachtoffer, partner van cliënt, "
              "schaderegelaar verzekeraar, tolk, arts). Antwoord ALLEEN met een JSON-object "
              "dat elke sprekerscode op een korte Nederlandse rolnaam afbeeldt; gebruik "
              "'onbekend' als het niet uit het gesprek blijkt.")
    user = f"Sprekers: {', '.join(speakers)}\n\nTranscript:\n{transcript[:12000]}"
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(f"{base}/chat/completions", json={
                "model": os.environ.get("SUMMARIZER_MODEL", "") or "default",
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}],
                "temperature": 0.0, "max_tokens": 200,
                "chat_template_kwargs": {"enable_thinking": False}})
            r.raise_for_status()
            txt = r.json()["choices"][0]["message"]["content"] or "{}"
    except (httpx.TimeoutException, httpx.ConnectError) as e:  # vóór HTTPError: subklassen
        logger.warning("rollen raden: taalmodel onbereikbaar (%s)", e)
        raise HTTPException(504, "Het taalmodel reageert niet — controleer bij Instellingen "
                                 "of het model draait en probeer het opnieuw.")
    except httpx.HTTPError as e:
        logger.warning("rollen raden: taalmodelfout (%s)", e)
        raise HTTPException(502, "Het taalmodel gaf een fout — probeer het opnieuw of "
                                 "controleer de verbinding onder Instellingen.")
    try:
        guessed = json.loads(txt[txt.index("{"): txt.rindex("}") + 1])
    except Exception:
        guessed = {}
    return {"rollen": {spk: str(guessed.get(spk, "onbekend"))[:60] for spk in speakers}}


async def suggest_template(segments: list[dict]) -> dict:
    """LLM kiest het waarschijnlijk relevantste sjabloon op basis van het transcript;
    default/terugval = het algemene sjabloon (gebruikersbesluit)."""
    tpls = load_templates()
    fallback = {"template_id": get_template("algemeen").get("id", tpls[0]["id"]),
                "motivatie": "standaardkeuze (algemeen verslag)"}
    base = os.environ.get("SUMMARIZER_URL", "").rstrip("/")
    if not base or not segments:
        return fallback
    keuzes = "\n".join(
        f"- {t['id']}: {t['naam']} (onderdelen: {', '.join(t.get('secties', [])[:4])}…)"
        for t in tpls)
    transcript = "\n".join(f"[{s.get('speaker', '?')}] {s.get('words', '')}"
                           for s in segments[:300])[:8000]
    import httpx
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            r = await client.post(f"{base}/chat/completions", json={
                "model": os.environ.get("SUMMARIZER_MODEL", "") or "default",
                "messages": [
                    {"role": "system", "content":
                     "Kies uit de sjabloonlijst het meest passende verslagsjabloon voor dit "
                     "Nederlandse gesprek. Twijfel je, kies dan 'algemeen'. Antwoord ALLEEN "
                     'met JSON: {"template_id": "...", "motivatie": "één korte zin"}.'},
                    {"role": "user", "content": f"Sjablonen:\n{keuzes}\n\nTranscript:\n{transcript}"}],
                "temperature": 0.0, "max_tokens": 120,
                "chat_template_kwargs": {"enable_thinking": False}})
            r.raise_for_status()
            txt = r.json()["choices"][0]["message"]["content"] or "{}"
        d = json.loads(txt[txt.index("{"): txt.rindex("}") + 1])
        if any(t.get("id") == d.get("template_id") for t in tpls):
            return {"template_id": d["template_id"],
                    "motivatie": str(d.get("motivatie", ""))[:200] or "gekozen door het taalmodel"}
    except Exception as e:
        logger.warning("sjabloonvoorstel mislukt (%s) — algemeen gebruikt", e)
    return fallback


def _load_item_segments(kind: str, item_id: str) -> list[dict]:
    d = _item_dir(kind, item_id)
    if kind == "meeting":
        seg_p = d / "refined_transcript.seglst.json"
        if not seg_p.exists():
            seg_p = d / "transcript.seglst.json"
    else:
        seg_p = d / "hyp.seglst.json"
    if not seg_p.exists():
        raise HTTPException(404, "geen transcript gevonden")
    return load_seglst(seg_p)


def _set_item_template(kind: str, item_id: str, template_id: str) -> None:
    """Onthoud de sjabloonkeuze per gesprek (state.json/meta.json)."""
    p = _roles_store(kind, item_id)
    d = json.loads(p.read_text())
    d["template_id"] = template_id
    _atomic_json(p, d)


@app.post("/api/templates/suggest")
async def templates_suggest(payload: dict):
    segments = payload.get("segments")
    if not segments and payload.get("kind") and payload.get("id"):
        segments = _load_item_segments(payload["kind"], payload["id"])
    if not segments:
        raise HTTPException(400, "segments of kind+id vereist")
    return await suggest_template(segments)


@app.post("/api/resummarize")
async def resummarize(payload: dict):
    """Hersamenvattten van een afgeronde vergadering of sessie met een gekozen sjabloon;
    bevestigde sprekerrollen worden meegenomen. Resultaat wordt als artefact opgeslagen."""
    kind, item_id = payload.get("kind"), payload.get("id")
    template = get_template(payload.get("template_id"))
    segments = _load_item_segments(kind, item_id)
    if not segments:
        raise HTTPException(400, "transcript is leeg")
    sr = json.loads(_roles_store(kind, item_id).read_text()).get("speaker_roles") or {}
    roles = sr.get("rollen") if sr.get("bevestigd") else None
    import httpx
    try:
        summary = await summarize_segments_llm(segments, final=True, template=template, roles=roles)
    except (httpx.TimeoutException, httpx.ConnectError) as e:  # vóór HTTPError: subklassen
        logger.warning("hersamenvatten: taalmodel onbereikbaar (%s)", e)
        raise HTTPException(504, "Het taalmodel reageert niet — controleer bij Instellingen "
                                 "of het model draait en probeer het opnieuw.")
    except httpx.HTTPError as e:
        logger.warning("hersamenvatten: taalmodelfout (%s)", e)
        raise HTTPException(502, "Het taalmodel gaf een fout — probeer het opnieuw of "
                                 "controleer de verbinding onder Instellingen.")
    naam = template.get("naam", "Gespreksverslag")
    res = await summary_append(kind, item_id, summary, f"sjabloon: {naam}", naam,
                               wijziging=f"nieuw verslag volgens sjabloon ‘{naam}’"
                                         + (" met bevestigde rollen" if roles else ""))
    _set_item_template(kind, item_id, template.get("id", ""))  # keuze per gesprek onthouden
    return {"summary": summary, "template": naam, "version": res["v"]}


# ------------------------------------------------------------------ meetings (persistent)

sys.path.insert(0, str(ROOT / "app"))
import meetings as _meetings_mod  # noqa: E402

def enqueue_meeting_refine(meeting_id: str, meeting_dir):
    """Automatische nabewerking na een vergadering: offline beste-kwaliteit transcript
    (turbo + optionele CGN-adapter + pyannote) + definitieve samenvatting, als
    refined_* artefacten NAAST de live-versie (vergelijking blijft mogelijk).
    LET OP licentie: een CGN-adapter (M2/M3) is NC — intern gebruik, niet commercieel
    uitleveren zonder commerciële CGN-licentie (docs/CGN-VALUE.md)."""
    adapter = os.environ.get("REFINE_ADAPTER", "models/lora/M2-cgn")
    if adapter and not (ROOT / adapter).exists():
        logger.warning("REFINE_ADAPTER %s bestaat niet — nabewerking met basismodel", adapter)
        adapter = ""
    # status voor de UI: nabewerking loopt (weg bij succes; refine_failed bij mislukken)
    sp0 = Path(meeting_dir) / "state.json"
    if sp0.exists():
        try:
            st0 = json.loads(sp0.read_text())
            st0["refine_pending"] = True
            st0.pop("refine_failed", None)
            _atomic_json(sp0, st0)
        except Exception:
            logger.warning("nabewerking %s: refine_pending niet gezet", meeting_id)

    async def run():
        proc = await asyncio.create_subprocess_exec(
            str(ROOT / "venvs/eval/bin/python"), str(ROOT / "scripts/offline_job.py"),
            "--audio", str(meeting_dir / "audio.wav"), "--session-id", meeting_id,
            "--out-dir", str(Path(meeting_dir).relative_to(ROOT)), "--prefix", "refined_",
            *(["--adapter", adapter] if adapter else []),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, cwd=str(ROOT))
        out, _ = await proc.communicate()
        if proc.returncode != 0:
            logger.error("nabewerking %s mislukt: %s", meeting_id, out.decode()[-300:])
            fp = meeting_dir / "state.json"
            if fp.exists():
                try:
                    st = json.loads(fp.read_text())
                    st["refine_failed"] = True
                    st.pop("refine_pending", None)
                    _atomic_json(fp, st)
                except Exception:
                    pass
            return
        # FUSIE (gemeten winnaar): live sprekerbeurten × offline woorden — offline-WER
        # met live-sprekerkwaliteit. Pyannote-attributie uit offline_job blijft fallback
        # wanneer er geen bruikbare live-structuur is.
        try:
            from dialib.fuse import fuse, live_turns
            live_p = meeting_dir / "transcript.seglst.json"
            ref_p = meeting_dir / "refined_transcript.seglst.json"
            live_segs = load_seglst(live_p) if live_p.exists() else []
            if len({s["speaker"] for s in live_segs}) >= 2:
                refined = load_seglst(ref_p)
                fused = fuse(refined, live_turns(live_segs))
                save_seglst(fused, ref_p)
                lines_txt = []
                for s in fused:
                    mm, ss = divmod(int(s["start_time"]), 60)
                    lines_txt.append(f"[{mm:02d}:{ss:02d}] {s['speaker']}: {s['words']}")
                (meeting_dir / "refined_transcript.txt").write_text("\n".join(lines_txt), encoding="utf-8")
                mp = meeting_dir / "refined_meta.json"
                if mp.exists():
                    m = json.loads(mp.read_text())
                    m["method"] = m.get("method", "") + "+livefusie"
                    mp.write_text(json.dumps(m, indent=1), encoding="utf-8")
                logger.info("nabewerking %s: live-fusie toegepast", meeting_id)
        except Exception as e:
            logger.warning("nabewerking %s: fusie overgeslagen (%s)", meeting_id, e)
        # definitieve samenvatting over het verfijnde transcript — via het versiebeheer:
        # als de gebruiker al een eigen (sjabloon-/handmatige) samenvatting actief heeft,
        # blijft die actief en komt de automatische alleen in de geschiedenis
        try:
            segs = load_seglst(meeting_dir / "refined_transcript.seglst.json")
            st_now = json.loads((Path(meeting_dir) / "state.json").read_text())
            sr = st_now.get("speaker_roles") or {}
            roles = sr.get("rollen") if sr.get("bevestigd") else None
            # sjabloon: gebruikerskeuze per gesprek; anders LLM-voorstel (default algemeen)
            tpl_id = st_now.get("template_id") or ""
            gekozen_door = "gebruiker"
            if not tpl_id:
                sug = await suggest_template(segs)
                tpl_id, gekozen_door = sug["template_id"], "taalmodel"
                _set_item_template("meeting", meeting_id, tpl_id)
            tpl = get_template(tpl_id)
            summary = await summarize_segments_llm(segs, "", final=True, template=tpl, roles=roles)
            data = _sum_load("meeting", Path(meeting_dir))
            cur = next((v for v in data["versions"] if v["v"] == data["current"]), None)
            user_current = bool(cur and str(cur.get("bron", "")).startswith(USER_BRONNEN))
            await summary_append("meeting", meeting_id, summary,
                                 "automatische definitieve versie",
                                 tpl.get("naam", "Definitief gespreksverslag"),
                                 make_current=not user_current,
                                 wijziging=f"automatische nabewerking (sjabloon ‘{tpl.get('naam')}’, "
                                           f"gekozen door {gekozen_door})")
            if user_current:
                logger.info("nabewerking %s: gebruikerssamenvatting blijft actief; "
                            "auto-versie in geschiedenis", meeting_id)
        except Exception as e:
            logger.warning("nabewerking %s: samenvatting mislukt: %s", meeting_id, e)
        # status bijwerken zodat de UI de definitieve versie toont
        sp = meeting_dir / "state.json"
        if sp.exists():
            st = json.loads(sp.read_text())
            st["refined"] = True
            st.pop("refine_pending", None)
            sp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
        logger.info("nabewerking %s gereed (adapter=%s)", meeting_id, adapter or "geen")

    t = asyncio.create_task(run())
    _BG_TASKS.add(t)
    t.add_done_callback(_BG_TASKS.discard)


# referenties op achtergrondtaken: zonder referentie mag de GC een lopende taak opruimen
_BG_TASKS: set = set()


async def _meeting_summarize(segments, prev="", final=False, template_id=None):
    """Samenvatter voor de vergadermodule: respecteert het per-gesprek gekozen sjabloon."""
    return await summarize_segments_llm(
        segments, prev, final,
        template=get_template(template_id) if template_id else None)


MEETINGS = _meetings_mod.register(
    app, ROOT,
    get_engine=lambda: manager.engine,
    resolve_source=resolve_source,
    lines_to_seglst=wlk_lines_to_seglst,
    summarize_fn=_meeting_summarize,
    refine_cb=enqueue_meeting_refine,
)


# ------------------------------------------------------------------ CGN license signing (LAN page: /sign)

CGN_ORDER = ROOT / "data/cgn/order"


@app.get("/sign")
async def sign_page():
    return HTMLResponse((ROOT / "app/static/sign.html").read_text(encoding="utf-8"))


@app.post("/api/sign")
async def sign_license(payload: dict):
    """Overlay the remaining fields + user-drawn signature onto the prefilled license PDF."""
    import base64

    import fitz  # PyMuPDF
    src = CGN_ORDER / "Licentie-NC_CGN_INGEVULD.pdf"
    if not src.exists():
        raise HTTPException(404, "prefilled license PDF missing")
    sig_b64 = (payload.get("signature") or "").split(",", 1)
    if len(sig_b64) != 2:
        raise HTTPException(400, "signature (png dataURL) required")
    sig_png = base64.b64decode(sig_b64[1])

    fields = {  # label -> (value, dx from label right edge)
        "Naam Licentienemer:": payload.get("naam", ""),
        "Woonachtig te:": payload.get("woonplaats", ""),
        "Datum:": payload.get("datum", ""),
        "Postadres:": payload.get("postadres", ""),
        "Telefoonnummer:": payload.get("telefoon", ""),
    }
    doc = fitz.open(src)
    sig_page = None
    for page in doc:
        for label, value in fields.items():
            if not value:
                continue
            for r in page.search_for(label)[:1]:
                page.insert_text((r.x1 + 8, r.y1 - 1), value, fontsize=10, fontname="helv")
        for r in page.search_for("Handtekening:")[:1]:
            rect = fitz.Rect(r.x1 + 10, r.y0 - 4, r.x1 + 230, r.y0 + 60)
            page.insert_image(rect, stream=sig_png, keep_proportion=True)
            sig_page = page.number
    if sig_page is None:
        raise HTTPException(500, "Handtekening label not found in PDF")
    out = CGN_ORDER / "Licentie-NC_CGN_ONDERTEKEND.pdf"
    doc.save(out)
    pix = doc[sig_page].get_pixmap(dpi=110)
    pix.save(CGN_ORDER / "signed_preview.png")
    doc.close()
    logger.info("signed license written to %s", out)
    return {"pdf": "/api/sign/file/Licentie-NC_CGN_ONDERTEKEND.pdf",
            "preview": "/api/sign/file/signed_preview.png"}


@app.get("/api/sign/file/{name}")
async def sign_file(name: str):
    if name not in ("Licentie-NC_CGN_ONDERTEKEND.pdf", "signed_preview.png",
                    "Licentie-NC_CGN_INGEVULD.pdf"):
        raise HTTPException(404, "unknown file")
    p = CGN_ORDER / name
    if not p.exists():
        raise HTTPException(404, "not generated yet")
    return FileResponse(p)


# ------------------------------------------------------------------ offline jobs (COMPARISON.md method D)

OFFLINE_JOBS: dict = {}


@app.post("/api/offline/{upload_id}")
async def start_offline(upload_id: str):
    """Best-quality after-the-fact processing: whisper long-form + pyannote (eval venv subprocess)."""
    wav = UPLOADS / upload_id / "processed.wav"
    if not wav.exists():
        raise HTTPException(404, f"upload {upload_id} not found")
    session_id = "offline-" + time.strftime("%Y%m%d-%H%M%S") + "-" + upload_id[:6]
    proc = await asyncio.create_subprocess_exec(
        str(ROOT / "venvs/eval/bin/python"), str(ROOT / "scripts/offline_job.py"),
        "--audio", str(wav), "--session-id", session_id,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, cwd=str(ROOT))
    job = {"session_id": session_id, "upload_id": upload_id, "stage": "starting",
           "done": False, "ok": None, "log_tail": []}
    OFFLINE_JOBS[session_id] = job

    async def watch():
        async for raw in proc.stdout:
            line = raw.decode(errors="replace").strip()
            if line.startswith("STAGE "):
                job["stage"] = line[6:]
            job["log_tail"] = (job["log_tail"] + [line])[-5:]
        rc = await proc.wait()
        job["done"], job["ok"], job["stage"] = True, rc == 0, ("done" if rc == 0 else "failed")

    t = asyncio.create_task(watch())
    _BG_TASKS.add(t)
    t.add_done_callback(_BG_TASKS.discard)
    return {"job": session_id}


@app.get("/api/offline/{session_id}")
async def offline_status(session_id: str):
    job = OFFLINE_JOBS.get(session_id)
    if not job:
        raise HTTPException(404, "unknown job")
    out = dict(job)
    if job["done"] and job["ok"]:
        out["segments"] = load_seglst(SESSIONS / session_id / "hyp.seglst.json")
    return out


# ------------------------------------------------------------------ sessions

def save_session(session_id: str, lines: list[dict], meta: dict) -> None:
    d = SESSIONS / session_id
    d.mkdir(parents=True, exist_ok=True)
    seglst = wlk_lines_to_seglst(lines, session_id)
    save_seglst(seglst, d / "hyp.seglst.json")
    (d / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")


def _is_user_session(meta: dict) -> bool:
    """Hide system-generated entries (eval-harness replays, e2e tests) from the UI.
    User content = live mic, file uploads (upload:*), offline jobs."""
    if meta.get("internal"):
        return False
    src = meta.get("source") or ""
    if isinstance(src, str) and src.startswith("eval:"):
        return False
    return True


@app.get("/api/sessions")
async def list_sessions(all: int = 0):
    out = []
    for m in sorted(SESSIONS.glob("*/meta.json"), reverse=True):
        try:
            meta = json.loads(m.read_text())
        except Exception:
            logger.warning("meta.json onleesbaar, sessie overgeslagen: %s", m)
            continue
        meta["has_summary"] = (m.parent / "summary.md").exists()
        if all or _is_user_session(meta):
            out.append(meta)
    return out[:100]


@app.get("/api/sessions/{sid}")
async def get_session(sid: str):
    d = SESSIONS / sid
    if not (d / "meta.json").exists():
        raise HTTPException(404, "session not found")
    summary_p = d / "summary.md"
    return {"meta": json.loads((d / "meta.json").read_text()),
            "segments": load_seglst(d / "hyp.seglst.json"),
            "summary": summary_p.read_text(encoding="utf-8") if summary_p.exists() else None}


@app.get("/api/sessions/{sid}/download/{artifact}")
async def session_download(sid: str, artifact: str):
    d = SESSIONS / sid
    if artifact == "audio.wav" and (d / "audio.wav").exists():
        return FileResponse(d / "audio.wav", filename=f"{sid}-audio.wav")
    if artifact == "summary.md" and (d / "summary.md").exists():
        return FileResponse(d / "summary.md", filename=f"{sid}-samenvatting.md")
    if artifact == "transcript.seglst.json" and (d / "hyp.seglst.json").exists():
        return FileResponse(d / "hyp.seglst.json", filename=f"{sid}-transcript.seglst.json")
    if artifact == "transcript.txt":
        p = d / "hyp.seglst.json"
        if p.exists():
            segs = load_seglst(p)
            lines = []
            for s in segs:
                mm, ss = divmod(int(s["start_time"]), 60)
                lines.append(f"[{mm:02d}:{ss:02d}] {s['speaker']}: {s['words']}")
            from fastapi.responses import PlainTextResponse
            return PlainTextResponse("\n".join(lines), headers={
                "Content-Disposition": f'attachment; filename="{sid}-transcript.txt"'})
    raise HTTPException(404, "artifact not available for this session")


@app.delete("/api/sessions/{sid}")
async def delete_session(sid: str):
    """Volledige verwijdering: sessie + correcties + onderliggende upload (privacy)."""
    import shutil
    d = SESSIONS / _safe_id(sid)
    if not d.exists():
        raise HTTPException(404, "sessie niet gevonden")
    meta = {}
    if (d / "meta.json").exists():
        try:
            meta = json.loads((d / "meta.json").read_text())
        except Exception:
            pass  # verwijderen moet ook bij corrupt meta.json lukken
    src = meta.get("source") or ""
    if isinstance(src, str) and src.startswith("upload:"):
        shutil.rmtree(UPLOADS / src.split(":", 1)[1], ignore_errors=True)
    for c in CORRECTIONS.glob(f"{sid}*"):
        c.unlink(missing_ok=True)
    shutil.rmtree(d)
    logger.info("session %s deleted (incl. corrections/upload)", sid)
    return {"deleted": True}


@app.post("/api/sessions/{sid}/correction")
async def save_correction(sid: str, payload: dict):
    segs = payload.get("segments") or []
    if not segs:
        raise HTTPException(400, "segments required")
    save_seglst(segs, CORRECTIONS / f"{sid}.seglst.json")
    meta_p = SESSIONS / sid / "meta.json"
    meta = json.loads(meta_p.read_text()) if meta_p.exists() else {"session_id": sid}
    meta["corrected"] = time.strftime("%Y-%m-%d %H:%M:%S")
    (CORRECTIONS / f"{sid}.meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return {"saved": True, "path": f"data/corrections/{sid}.seglst.json"}


# ------------------------------------------------------------------ config

@app.get("/api/config")
async def get_config():
    return {"engine_args": manager.args, "ready": manager.engine is not None}


@app.post("/api/config")
async def set_config(payload: dict):
    args = payload.get("engine_args")
    if not isinstance(args, dict) or not args:
        raise HTTPException(400, "engine_args dict required")
    for k in args:
        if not k.startswith("--"):
            raise HTTPException(400, f"keys must be wlk flags starting with --, got {k}")
    # EERST valideren zonder bijwerkingen: ongeldige flags mochten voorheen de config
    # wegschrijven en de oude engine al loslaten → app permanent stuk tot handmatig herstel
    try:
        manager._parse_config(args)
    except (SystemExit, Exception) as e:
        raise HTTPException(400, f"ongeldige engine-instellingen: {e}")
    oud = dict(manager.args)
    try:
        await manager.load(args)
    except Exception as e:
        logger.exception("engine-reload mislukt — oude instellingen terugzetten")
        try:
            await manager.load(oud)
        except Exception:
            logger.exception("terugzetten oude engine-instellingen mislukte ook")
        raise HTTPException(500, f"engine kon niet laden met deze instellingen: {e}")
    CONFIG_PATH.write_text(json.dumps(args, indent=1), encoding="utf-8")  # pas ná succes
    return {"reloaded": True, "engine_args": manager.args}


# ------------------------------------------------------------------ websocket

async def forward_results(ws: WebSocket, gen, state: dict, finalize) -> None:
    try:
        async for response in gen:
            d = response.to_dict()
            state["last"] = d
            state["n_results"] += 1
            ev = {
                "wall": round(time.time(), 3),
                "audio_fed": round(state["audio_fed"], 3),
                "n_lines": len(d.get("lines", [])),
                "buffer_len": len(d.get("buffer_transcription", "")),
            }
            # tekst-delta's voor woordniveau-latentiemeting (eval/word_latency.py):
            # committed groeit vrijwel monotoon; bij een herschrijving loggen we alles + vlag
            committed = " ".join(ln.get("text", "") or "" for ln in d.get("lines", []))
            prev = state.get("_prev_committed", "")
            if committed != prev:
                if committed.startswith(prev):
                    ev["delta"] = committed[len(prev):][-4000:]
                else:
                    ev["delta"] = committed[-4000:]
                    ev["rewrite"] = True
                state["_prev_committed"] = committed
            buf = d.get("buffer_transcription", "") or ""
            if buf and buf != state.get("_prev_buffer", ""):
                ev["buffer"] = buf[-300:]
                state["_prev_buffer"] = buf
            state["events"].append(ev)
            await ws.send_json({"type": "update", **d})
        # generator exhausted = pipeline flushed all results for this stream:
        # persist + notify the client NOW, while the socket is still open.
        await finalize(notify=True)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("results forwarder failed")


async def replay_feed(processor, ws: WebSocket, pcm: bytes, speed: float, state: dict) -> None:
    """speed > 0: paced replay (1.0 = realtime streaming behavior).
    speed == 0: 'fast/batch' — feed unpaced (throttled only by a small sleep so the
    pipeline queue doesn't balloon); same models/policy, used for after-the-fact uploads."""
    duration = len(pcm) / BYTES_PER_SEC
    chunk = int(BYTES_PER_SEC * CHUNK_SEC)
    t_next_progress = 0.0
    try:
        for i in range(0, len(pcm), chunk):
            await processor.process_audio(pcm[i:i + chunk])
            state["audio_fed"] = min((i + chunk) / BYTES_PER_SEC, duration)
            if state["audio_fed"] >= t_next_progress:
                await ws.send_json({"type": "replay_progress",
                                    "fed": round(state["audio_fed"], 2),
                                    "duration": round(duration, 2)})
                t_next_progress += 2.0
            await asyncio.sleep(CHUNK_SEC / max(speed, 0.1) if speed > 0 else 0.005)
        await processor.process_audio(b"")  # end of stream -> pipeline finalizes
        await ws.send_json({"type": "replay_done", "duration": round(duration, 2)})
    except asyncio.CancelledError:
        await processor.process_audio(b"")
        raise
    except Exception:
        logger.exception("replay feeder failed")


@app.websocket("/asr")
async def asr_ws(ws: WebSocket):
    from whisperlivekit import AudioProcessor
    if manager.engine is None:
        await ws.close(code=1013, reason="engine not ready")
        return
    await ws.accept()

    session_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    state = {"last": None, "n_results": 0, "audio_fed": 0.0, "events": [],
             "t_start": time.time()}
    meta = {"session_id": session_id, "engine_args": manager.args,
            "created": time.strftime("%Y-%m-%d %H:%M:%S"), "mode": None, "source": None}

    # The processor is created lazily: PCM-vs-container input mode must be set
    # BEFORE create_tasks() starts the pipeline (ffmpeg decoder vs raw PCM path).
    processor = None
    forward_task = None
    replay_task = None

    async def finalize(notify: bool):
        """Persist the session once; optionally tell the client (socket still open)."""
        if state.get("saved"):
            return
        state["saved"] = True
        last = state["last"] or {}
        lines = last.get("lines", [])
        meta.update({"n_results": state["n_results"],
                     "audio_seconds": round(state["audio_fed"], 2),
                     "n_lines": len(lines)})
        if lines or state.get("audio_sink"):  # opnames nooit onzichtbaar laten verdwijnen
            save_session(session_id, lines, meta)
            (SESSIONS / session_id / "events.jsonl").write_text(
                "\n".join(json.dumps(e) for e in state["events"]), encoding="utf-8")
        if notify:
            try:
                if lines:
                    await ws.send_json({"type": "session_saved", "session_id": session_id,
                                        "segments": wlk_lines_to_seglst(lines, session_id)})
                await ws.send_json({"type": "ready_to_stop"})
            except Exception:
                pass

    async def start_processor(pcm_input: bool):
        nonlocal processor, forward_task
        processor = AudioProcessor(transcription_engine=manager.engine)
        if pcm_input:
            processor.is_pcm_input = True
        gen = await processor.create_tasks()
        forward_task = asyncio.create_task(forward_results(ws, gen, state, finalize))
        state["t_start"] = time.time()

    await ws.send_json({"type": "ready", "session_id": session_id})
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                data = msg["bytes"]
                if processor is None:
                    meta["mode"] = "live"
                    await start_processor(pcm_input=False)
                    # persist the raw incoming audio too (user req: recordings bewaren)
                    d = SESSIONS / session_id
                    d.mkdir(parents=True, exist_ok=True)
                    state["audio_sink"] = (d / "audio.stream").open("wb")
                if not data:  # client signals end of stream
                    await processor.process_audio(b"")
                    continue
                if state.get("audio_sink"):
                    state["audio_sink"].write(data)
                state["audio_fed"] = time.time() - state["t_start"]
                await processor.process_audio(data)
            elif msg.get("text"):
                cmd = json.loads(msg["text"])
                if cmd.get("type") == "replay" and replay_task is None and processor is None:
                    meta["mode"] = "replay"
                    meta["source"] = cmd.get("source")
                    meta["speed"] = float(cmd.get("speed", 1.0))
                    path = resolve_source(cmd["source"])
                    pcm = await decode_to_pcm(path, loudnorm=bool(cmd.get("loudnorm")))
                    await start_processor(pcm_input=True)
                    replay_task = asyncio.create_task(
                        replay_feed(processor, ws, pcm, meta["speed"], state))
                elif cmd.get("type") == "stop":
                    if replay_task and not replay_task.done():
                        replay_task.cancel()
                    elif processor is not None:
                        await processor.process_audio(b"")
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("asr websocket error")
    finally:
        if replay_task and not replay_task.done():
            replay_task.cancel()
        # give the pipeline a moment to flush final results, then persist
        if forward_task is not None:
            try:
                await asyncio.wait_for(forward_task, timeout=30)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                forward_task.cancel()
        await finalize(notify=False)  # no-op if already saved by the forwarder
        if state.get("audio_sink"):
            state["audio_sink"].close()
            stream_f = SESSIONS / session_id / "audio.stream"
            if stream_f.exists() and stream_f.stat().st_size > 1000:
                # convert the container stream (webm/mp4, browser-dependent) to wav
                proc2 = await asyncio.create_subprocess_exec(
                    "ffmpeg", "-y", "-i", str(stream_f), "-ar", str(SR), "-ac", "1",
                    str(SESSIONS / session_id / "audio.wav"), "-loglevel", "error")
                if await proc2.wait() == 0:
                    stream_f.unlink()
                else:
                    logger.error("session %s: audio conversion FAILED — raw stream kept at %s",
                                 session_id, stream_f)
            elif stream_f.exists():
                stream_f.unlink()
        if processor is not None:
            await processor.cleanup()
        logger.info("session %s closed (%s, %d results)", session_id, meta["mode"], state["n_results"])


if __name__ == "__main__":
    import argparse

    import uvicorn
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--ssl-certfile", default=None)
    ap.add_argument("--ssl-keyfile", default=None)
    a = ap.parse_args()
    kw = {}
    if a.ssl_certfile and a.ssl_keyfile:
        kw = {"ssl_certfile": a.ssl_certfile, "ssl_keyfile": a.ssl_keyfile}
    uvicorn.run(app, host=a.host, port=a.port, **kw)
