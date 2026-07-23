"""Persistent meeting sessions: server-side record + transcribe + diarize + summarize.

Design (docs/WEBAPP.md §Meetings): the meeting lives on the SERVER —
- feeder: a browser streams mic audio over WS /api/meetings/{id}/feed; it may disconnect
  and re-attach at any time (each connection gets its own ffmpeg webm->PCM decoder; the
  wall-clock gap is filled with silence, capped, so timestamps stay roughly aligned).
  Alternatively source="file:<eval-id>" feeds audio server-side (demo/tests).
- viewers: stateless — the UI polls GET /api/meetings/{id} every 2 s; closing the tab
  changes nothing.
- persistence: raw PCM appended to disk continuously + state.json snapshot every 30 s,
  so a crash preserves audio + transcript-so-far. stop() finalizes downloadable
  artifacts: audio.wav, transcript.seglst.json, transcript.txt, summary.md, meta.json.
- rolling summary every ~150 s via the configured local LLM (skipped if not configured).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import struct
import tempfile
import time
import uuid
from pathlib import Path

from fastapi import HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

logger = logging.getLogger("dia.meetings")

SR = 16000
BYTES_PER_SEC = SR * 2
SNAPSHOT_EVERY = 30
SUMMARY_EVERY = 150
MAX_GAP_SILENCE_S = 300

ARTIFACTS = ("audio.wav", "transcript.seglst.json", "transcript.txt", "summary.md", "meta.json",
             "refined_transcript.seglst.json", "refined_transcript.txt", "refined_summary.md",
             "refined_meta.json")

# Nederlandse downloadnamen (het dossier van de gebruiker); overige artifacts houden hun eigen naam
DOWNLOAD_NAMES = {"summary.md": "gespreksverslag.md",
                  "refined_summary.md": "definitief-gespreksverslag.md",
                  "refined_transcript.txt": "definitief-transcript.txt",
                  "refined_transcript.seglst.json": "definitief-transcript.seglst.json"}

_BG: set = set()  # referenties naar achtergrondtaken (stop-finalisatie), anders kan GC ze afbreken

_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}")


def _check_id(mid: str):
    """Pad-id-validatie vóór elk gebruik van mid in een bestandspad (mid='..' zou anders
    bv. via delete heel data/meetings/../ raken)."""
    if ".." in mid or not _ID_RE.fullmatch(mid):
        raise HTTPException(400, "ongeldig id")


class Meeting:
    def __init__(self, root: Path, name: str, source: str, engine, resolve_source, lines_to_seglst):
        self.id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        self.name = name or self.id
        self.source = source
        self.dir = root / "data/meetings" / self.id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.engine = engine
        self._resolve_source = resolve_source
        self._lines_to_seglst = lines_to_seglst
        self.state = "starting"
        self.internal = False
        self.template_id = ""   # verslagsjabloon voor dit gesprek ("" = LLM kiest achteraf)
        self.created = time.strftime("%Y-%m-%d %H:%M:%S")
        self.lines: list[dict] = []
        self.buffer = ""
        self.summary = ""
        self.summary_at = 0.0
        self.audio_seconds = 0.0
        self.last_audio_wall = time.time()
        self.feeder_connected = False
        self._raw = (self.dir / "audio.raw").open("ab")
        # bytepositie bijhouden voor PCM-uitlijning (dekt ook hervatting na serverherstart)
        self.audio_bytes = (self.dir / "audio.raw").stat().st_size
        self.processor = None
        self._tasks: list[asyncio.Task] = []
        self._stopping = False
        self._refine_cb = None

    # ---------------------------------------------------------------- pipeline

    async def start(self, summarize_fn):
        from whisperlivekit import AudioProcessor
        self.processor = AudioProcessor(transcription_engine=self.engine)
        self.processor.is_pcm_input = True
        gen = await self.processor.create_tasks()
        self._summarize_fn = summarize_fn
        self._tasks.append(asyncio.create_task(self._consume(gen)))
        self._tasks.append(asyncio.create_task(self._housekeeping()))
        if self.source.startswith("file:"):
            self._tasks.append(asyncio.create_task(self._file_feeder(self.source[5:])))
        self.state = "recording"
        logger.info("meeting %s started (source=%s)", self.id, self.source)

    async def ingest_pcm(self, chunk: bytes):
        if self._stopping or not chunk:
            return
        self._raw.write(chunk)
        self.audio_bytes += len(chunk)
        self.audio_seconds += len(chunk) / BYTES_PER_SEC
        self.last_audio_wall = time.time()
        await self.processor.process_audio(chunk)

    async def align_pcm(self):
        """PCM-uitlijning herstellen op een verbindingsgrens. Een halverwege gestopte
        decoder kan een HALF 16-bit-sample achterlaten; alle audio daarna decodeert dan
        als statische ruis — in het bestand én in de live-engine (incident 2026-07-23:
        'alleen ruis' + 0 transcriptie-aanroepen). Eén nulbyte maakt het sample af."""
        if self._stopping or self.audio_bytes % 2 == 0:
            return
        self._raw.write(b"\x00")
        self._raw.flush()
        self.audio_bytes += 1
        await self.processor.process_audio(b"\x00")
        logger.warning("meeting %s: oneven PCM-grens hersteld (+1 uitlijnbyte)", self.id)

    async def feed_gap_silence(self):
        """On feeder re-attach: keep timeline roughly wall-aligned across the gap."""
        await self.align_pcm()
        gap = time.time() - self.last_audio_wall
        if 0.5 < gap < MAX_GAP_SILENCE_S:
            silence = b"\x00" * (int(gap * BYTES_PER_SEC) & ~1)  # altijd hele samples
            for i in range(0, len(silence), BYTES_PER_SEC):
                await self.ingest_pcm(silence[i:i + BYTES_PER_SEC])
            logger.info("meeting %s: filled %.1fs disconnect gap with silence", self.id, gap)

    async def _file_feeder(self, source_id: str):
        path = self._resolve_source(f"eval:{source_id}") if not source_id.startswith("/") else Path(source_id)
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-i", str(path), "-f", "s16le", "-ar", str(SR), "-ac", "1",
            "-loglevel", "error", "pipe:1", stdout=asyncio.subprocess.PIPE)
        chunk = int(BYTES_PER_SEC * 0.25)
        try:
            while not self._stopping:
                data = await proc.stdout.read(chunk)
                if not data:
                    # source exhausted: signal end-of-stream so the pipeline flushes,
                    # the results generator ends, and _consume finalizes the meeting
                    if not self._stopping:
                        await self.processor.process_audio(b"")
                    break
                await self.ingest_pcm(data)
                await asyncio.sleep(0.25)  # realtime pace
        finally:
            if proc.returncode is None:
                proc.terminate()

    async def _consume(self, gen):
        try:
            async for response in gen:
                d = response.to_dict()
                self.lines = [l for l in d.get("lines", []) if l.get("speaker") != -2 and (l.get("text") or "").strip()]
                self.buffer = (d.get("buffer_transcription") or "")
        except Exception:
            logger.exception("meeting %s consumer failed", self.id)
        finally:
            if not self._stopping:  # pipeline ended on its own (file source finished)
                await self.stop()

    async def _housekeeping(self):
        last_snap = 0.0
        while not self._stopping:
            await asyncio.sleep(5)
            now = time.time()
            if now - last_snap >= SNAPSHOT_EVERY:
                self._snapshot()
                last_snap = now
            if now - self.summary_at >= SUMMARY_EVERY and len(self.lines) >= 3:
                self.summary_at = now
                try:
                    s = await self._summarize_fn(self.segments(), self.summary,
                                                 template_id=self.template_id or None)
                    if s:
                        self.summary = s
                        self._snapshot()
                except Exception as e:
                    logger.warning("meeting %s rolling summary failed: %s", self.id, e)

    # ---------------------------------------------------------------- state/artifacts

    def segments(self) -> list[dict]:
        return self._lines_to_seglst(self.lines, self.id)

    def status(self, with_transcript: bool = True) -> dict:
        d = {"id": self.id, "name": self.name, "state": self.state, "source": self.source,
             "created": self.created, "audio_seconds": round(self.audio_seconds, 1),
             "n_lines": len(self.lines), "feeder_connected": self.feeder_connected,
             "internal": self.internal, "summary": self.summary,
             "template_id": self.template_id}
        if with_transcript:
            d["segments"] = self.segments()
            d["buffer"] = self.buffer
        return d

    def _snapshot(self):
        # mergen + atomair: server-endpoints zetten extra velden in state.json
        # (speaker_roles, refined, refine_pending, template_id) — die mag de 30s-snapshot
        # niet wissen, en een crash halverwege mag geen halve JSON achterlaten
        try:
            state = json.loads((self.dir / "state.json").read_text(encoding="utf-8"))
            if not isinstance(state, dict):
                state = {}
        except Exception:
            state = {}
        state.update(self.status())
        fd, tmp = tempfile.mkstemp(dir=self.dir, prefix="state.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(state, ensure_ascii=False, indent=1))
        os.replace(tmp, self.dir / "state.json")

    async def stop(self):
        if self._stopping:
            return
        self._stopping = True
        self.state = "finalizing"
        try:  # end-of-stream; bounded — can block on pipelines that never saw audio
            await asyncio.wait_for(self.processor.process_audio(b""), timeout=10)
        except (asyncio.TimeoutError, Exception):
            pass
        await asyncio.sleep(3)  # let the pipeline flush its final results
        for t in self._tasks:
            if t is not asyncio.current_task() and not t.done():
                t.cancel()
        try:
            await asyncio.wait_for(self.processor.cleanup(), timeout=15)
        except (asyncio.TimeoutError, Exception):
            logger.warning("meeting %s: processor cleanup timed out/failed", self.id)
        self._raw.close()
        # final summary over the full transcript (best effort; skip empty meetings)
        if self.lines:
            try:
                s = await asyncio.wait_for(
                    self._summarize_fn(self.segments(), self.summary, final=True,
                                       template_id=self.template_id or None), timeout=240)
                if s:
                    self.summary = s
            except (asyncio.TimeoutError, Exception) as e:
                logger.warning("meeting %s final summary failed: %s", self.id, e)
        await asyncio.to_thread(self._write_artifacts)
        self.state = "finished"
        self._snapshot()
        logger.info("meeting %s finished (%.0fs audio, %d lines)", self.id, self.audio_seconds, len(self.lines))
        # automatische nabewerking: offline "definitieve versie" met de beste motor
        if self.audio_seconds > 10 and self._refine_cb is not None and not self.internal:
            try:
                self._refine_cb(self.id, self.dir)
            except Exception:
                logger.exception("meeting %s: kon nabewerking niet starten", self.id)

    def _write_artifacts(self):
        raw_p = self.dir / "audio.raw"
        # afronden op hele 16-bit samples: een halverwege gestopte ffmpeg-decoder kan een
        # half sample achterlaten en strikte decoders (torchcodec, in de nabewerking)
        # weigeren dan het HELE bestand (gezien 2026-07-23: 415671 bytes → refine-crash)
        n = raw_p.stat().st_size if raw_p.exists() else 0
        n -= n % 2
        hdr = (b"RIFF" + struct.pack("<I", 36 + n) + b"WAVEfmt " +
               struct.pack("<IHHIIHH", 16, 1, 1, SR, BYTES_PER_SEC, 2, 16) +
               b"data" + struct.pack("<I", n))
        # streamend kopiëren i.p.v. read_bytes: 2 uur opname ≈ 230 MB hoort niet in RAM
        with (self.dir / "audio.wav").open("wb") as wav:
            wav.write(hdr)
            if n:
                with raw_p.open("rb") as src:
                    shutil.copyfileobj(src, wav, 1 << 20)
                wav.truncate(len(hdr) + n)  # evt. half slotsample weer afknippen
        segs = self.segments()
        (self.dir / "transcript.seglst.json").write_text(
            json.dumps(segs, ensure_ascii=False, indent=1), encoding="utf-8")
        lines = []
        for s in segs:
            mm, ss = divmod(int(s["start_time"]), 60)
            lines.append(f"[{mm:02d}:{ss:02d}] {s['speaker']}: {s['words']}")
        (self.dir / "transcript.txt").write_text("\n".join(lines), encoding="utf-8")
        (self.dir / "summary.md").write_text(
            f"# {self.name}\n\n{self.summary or '(geen gespreksverslag — taalmodel niet geconfigureerd)'}\n",
            encoding="utf-8")
        (self.dir / "meta.json").write_text(json.dumps(self.status(with_transcript=False), indent=1),
                                            encoding="utf-8")


class MeetingRegistry:
    def __init__(self, root: Path):
        self.root = root
        self.active: dict[str, Meeting] = {}

    def list_all(self) -> list[dict]:
        out = [m.status(with_transcript=False) for m in self.active.values()]
        seen = {m["id"] for m in out}
        base = self.root / "data/meetings"
        if base.exists():
            for p in sorted(base.iterdir(), reverse=True):
                if p.name in seen or not (p / "state.json").exists():
                    continue
                try:
                    s = json.loads((p / "state.json").read_text())
                    d = {k: s.get(k) for k in ("id", "name", "state", "source", "created",
                                               "audio_seconds", "n_lines", "summary", "internal", "refined")}
                    if d["state"] in ("recording", "starting", "finalizing"):
                        d["state"] = "orphaned"
                    out.append(d)
                except Exception:
                    continue
        return out[:100]


def recover_orphans(root: Path) -> int:
    """After a server restart: meetings that never finalized still have audio.raw and
    the last transcript snapshot — turn those into downloadable artifacts (user req:
    opnames mogen nooit verloren gaan)."""
    n = 0
    base = root / "data/meetings"
    if not base.exists():
        return 0
    for d in base.iterdir():
        state_p, raw_p = d / "state.json", d / "audio.raw"
        if not state_p.exists() or (d / "audio.wav").exists():
            continue
        try:
            s = json.loads(state_p.read_text())
            if s.get("state") == "finished":
                continue
            raw = raw_p.read_bytes() if raw_p.exists() else b""
            hdr = (b"RIFF" + struct.pack("<I", 36 + len(raw)) + b"WAVEfmt " +
                   struct.pack("<IHHIIHH", 16, 1, 1, SR, BYTES_PER_SEC, 2, 16) +
                   b"data" + struct.pack("<I", len(raw)))
            (d / "audio.wav").write_bytes(hdr + raw)
            segs = s.get("segments", [])
            (d / "transcript.seglst.json").write_text(json.dumps(segs, ensure_ascii=False, indent=1),
                                                      encoding="utf-8")
            lines = []
            for seg in segs:
                mm, ss = divmod(int(seg["start_time"]), 60)
                lines.append(f"[{mm:02d}:{ss:02d}] {seg['speaker']}: {seg['words']}")
            (d / "transcript.txt").write_text("\n".join(lines), encoding="utf-8")
            (d / "summary.md").write_text(f"# {s.get('name', d.name)}\n\n"
                                          f"{s.get('summary') or '(gespreksverslag niet beschikbaar — opname hersteld na serverherstart)'}\n",
                                          encoding="utf-8")
            s["state"] = "finished"
            s["recovered"] = True
            state_p.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
            (d / "meta.json").write_text(json.dumps({k: s.get(k) for k in
                ("id", "name", "state", "source", "created", "audio_seconds", "n_lines", "recovered")}, indent=1),
                encoding="utf-8")
            n += 1
            logger.info("recovered orphaned meeting %s (%.0fs audio)", d.name, len(raw) / BYTES_PER_SEC)
        except Exception:
            logger.exception("recovery failed for %s", d.name)
    return n


def register(app, root: Path, get_engine, resolve_source, lines_to_seglst, summarize_fn,
             refine_cb=None):
    reg = MeetingRegistry(root)
    recovered = recover_orphans(root)
    if recovered:
        logger.info("meeting recovery: %d orphaned meeting(s) finalized", recovered)

    @app.post("/api/meetings/start")
    async def start_meeting(payload: dict):
        engine = get_engine()
        if engine is None:
            raise HTTPException(503, "engine not ready")
        m = Meeting(root, payload.get("name", ""), payload.get("source", "browser"),
                    engine, resolve_source, lines_to_seglst)
        m.internal = bool(payload.get("internal"))  # tests/system runs: hidden from UI lists
        m.template_id = str(payload.get("template_id") or "").strip()[:80]
        m._refine_cb = refine_cb
        await m.start(summarize_fn)
        reg.active[m.id] = m
        return {"id": m.id}

    @app.get("/api/meetings")
    async def list_meetings(all: int = 0):
        items = reg.list_all()
        if not all:
            items = [x for x in items if not x.get("internal")
                     and not (x.get("name") or "").startswith("e2e-")]
        return items

    @app.get("/api/meetings/{mid}")
    async def meeting_status(mid: str):
        _check_id(mid)
        if mid in reg.active:
            return reg.active[mid].status()
        p = root / "data/meetings" / mid / "state.json"
        if p.exists():
            return JSONResponse(json.loads(p.read_text()))
        raise HTTPException(404, "meeting not found")

    @app.post("/api/meetings/{mid}/stop")
    async def stop_meeting(mid: str):
        _check_id(mid)
        m = reg.active.get(mid)
        if not m:
            raise HTTPException(404, "meeting not active")
        # finalisatie (LLM-eindverslag) kan minuten duren — nooit in het HTTP-verzoek
        # blokkeren (client-disconnect zou de handler en dus de finalisatie annuleren).
        # De meeting blijft in reg.active tot de achtergrond-stop klaar is, zodat
        # GET /api/meetings/{mid} 'finalizing' en daarna 'finished' blijft rapporteren.
        m.state = "finalizing"
        t = asyncio.create_task(m.stop())
        _BG.add(t)
        t.add_done_callback(_BG.discard)

        def _cleanup(task, mid=mid):
            reg.active.pop(mid, None)  # status komt daarna uit state.json (state=finished)
            if not task.cancelled() and task.exception():
                logger.error("meeting %s: achtergrond-stop mislukt: %s", mid, task.exception())
        t.add_done_callback(_cleanup)
        return {"stopped": True, "state": "finalizing",
                "artifacts": [f"/api/meetings/{mid}/download/{a}" for a in ARTIFACTS]}

    @app.delete("/api/meetings/{mid}")
    async def delete_meeting(mid: str):
        _check_id(mid)
        m = reg.active.get(mid)
        # opnemen én afronden blokkeren (rmtree tijdens de achtergrond-afronding zou de
        # artefact-schrijver raken); een afgerond gesprek is gewoon verwijderbaar
        if m and m.state in ("recording", "starting", "finalizing"):
            raise HTTPException(409, "gesprek wordt nog opgenomen of afgerond — probeer het zo opnieuw")
        reg.active.pop(mid, None)
        d = root / "data/meetings" / mid
        if not d.exists():
            raise HTTPException(404, "gesprek niet gevonden")
        shutil.rmtree(d)  # hele map: audio, transcript, rollen én alle verslagversies
        logger.info("meeting %s deleted", mid)
        return {"deleted": True}

    @app.get("/api/meetings/{mid}/download/{artifact}")
    async def download(mid: str, artifact: str):
        _check_id(mid)
        if artifact not in ARTIFACTS:
            raise HTTPException(404, "unknown artifact")
        p = root / "data/meetings" / mid / artifact
        if not p.exists():
            raise HTTPException(404, "not available (meeting still running?)")
        return FileResponse(p, filename=f"{mid}-{DOWNLOAD_NAMES.get(artifact, artifact)}")

    @app.websocket("/api/meetings/{mid}/feed")
    async def feed(ws: WebSocket, mid: str):
        _check_id(mid)
        m = reg.active.get(mid)
        if not m or m.state != "recording":
            await ws.close(code=4404, reason="meeting not recording")
            return
        await ws.accept()
        if m.feeder_connected:
            await ws.close(code=4409, reason="another feeder is connected")
            return
        m.feeder_connected = True
        await m.feed_gap_silence()
        ff = await asyncio.create_subprocess_exec(
            "ffmpeg", "-i", "pipe:0", "-f", "s16le", "-ar", str(SR), "-ac", "1",
            "-loglevel", "error", "pipe:1",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE)

        async def pump_out():
            while True:
                data = await ff.stdout.read(int(BYTES_PER_SEC * 0.25))
                if not data:
                    break
                await m.ingest_pcm(data)

        out_task = asyncio.create_task(pump_out())
        try:
            while True:
                msg = await ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
                if msg.get("bytes"):
                    ff.stdin.write(msg["bytes"])
                    await ff.stdin.drain()
        except WebSocketDisconnect:
            pass
        finally:
            m.feeder_connected = False
            try:
                ff.stdin.close()
            except Exception:
                pass
            try:
                await asyncio.wait_for(out_task, timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                out_task.cancel()
            if ff.returncode is None:
                ff.terminate()
            await m.align_pcm()  # gekapte decoder mag geen half sample achterlaten
            logger.info("meeting %s: feeder detached (meeting continues)", mid)

    return reg
