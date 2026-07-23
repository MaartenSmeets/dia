#!/usr/bin/env python3
"""End-to-end tests against the RUNNING app server (localhost:8080).

Run:  venvs/wlk/bin/python tests/test_app_e2e.py
Covers: health, uploads (wav + m4a + loudnorm), eval catalog/reference, WS replay
(live pipeline), scoring, sessions + corrections, summarize (skipped if no LLM),
meeting lifecycle incl. artifacts + empty-meeting edge case.
Prints PASS/FAIL per test; exit 1 if any FAIL.
"""
from __future__ import annotations

import asyncio
import io
import json
import math
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

BASE = "http://localhost:8080"
ROOT = Path(__file__).resolve().parent.parent
RESULTS = []


def check(name, cond, info=""):
    RESULTS.append((name, bool(cond), info))
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  [{info}]" if info and not cond else ""))


def tone_wav(seconds=2.0, sr=16000) -> bytes:
    n = int(seconds * sr)
    samples = b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / sr))) for i in range(n))
    hdr = (b"RIFF" + struct.pack("<I", 36 + len(samples)) + b"WAVEfmt " +
           struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * 2, 2, 16) + b"data" + struct.pack("<I", len(samples)))
    return hdr + samples


def main():
    # 1. health
    h = requests.get(f"{BASE}/health", timeout=10).json()
    check("health engine_ready", h.get("engine_ready") is True, str(h))

    # 2. wav upload + loudnorm
    r = requests.post(f"{BASE}/api/upload", files={"file": ("t.wav", tone_wav())},
                      data={"loudnorm": "true"}, timeout=60).json()
    check("upload wav+loudnorm", r.get("id") and 1.5 < r.get("duration", 0) < 2.5, str(r))

    # 3. m4a upload
    with tempfile.NamedTemporaryFile(suffix=".wav") as f:
        f.write(tone_wav()); f.flush()
        m4a = f.name.replace(".wav", ".m4a")
        subprocess.run(["ffmpeg", "-y", "-i", f.name, "-c:a", "aac", m4a],
                       capture_output=True, check=True)
        r = requests.post(f"{BASE}/api/upload", files={"file": ("t.m4a", open(m4a, "rb"))},
                          data={"loudnorm": "false"}, timeout=60).json()
    check("upload m4a", r.get("id") and r.get("duration", 0) > 1.5, str(r))

    # 4. eval catalog + reference
    cat = requests.get(f"{BASE}/api/eval/list", timeout=10).json()
    ids = {d["id"] for d in cat}
    check("eval catalog", {"ifadv_dev", "cgn_a_dev", "fleurs_nl"} <= ids, str(ids))
    fleurs_item = next(d for d in cat if d["id"] == "fleurs_nl")["items"][0]["id"]
    ref = requests.get(f"{BASE}/api/eval/reference", params={"id": fleurs_item}, timeout=10).json()
    check("eval reference", isinstance(ref, list) and ref and "words" in ref[0], str(ref)[:80])

    # 5. WS replay of a short eval sample through the live pipeline
    hyp_segments, session_id = [], None

    async def replay():
        nonlocal hyp_segments, session_id
        import websockets
        async with websockets.connect(f"ws://localhost:8080/asr", max_size=16 * 2**20,
                                      open_timeout=30) as ws:
            await ws.send(json.dumps({"type": "replay", "source": f"eval:{fleurs_item}", "speed": 0}))
            async for raw in ws:
                m = json.loads(raw)
                if m.get("type") == "session_saved":
                    hyp_segments = m["segments"]; session_id = m["session_id"]
                elif m.get("type") == "ready_to_stop":
                    break

    asyncio.run(asyncio.wait_for(replay(), timeout=300))
    check("ws replay produces transcript", bool(hyp_segments), f"{len(hyp_segments)} segs")

    # 6. scoring
    if hyp_segments:
        s = requests.post(f"{BASE}/api/score",
                          json={"reference_id": fleurs_item, "hypothesis": hyp_segments},
                          timeout=120).json()
        check("scoring returns WER", isinstance(s.get("wer", {}).get("wer"), (int, float)), str(s)[:120])

    # 7. sessions + correction
    sessions = requests.get(f"{BASE}/api/sessions?all=1", timeout=10).json()
    check("session persisted", any(x.get("session_id") == session_id for x in sessions))
    if session_id:
        d = requests.get(f"{BASE}/api/sessions/{session_id}", timeout=10).json()
        segs = d["segments"]
        if segs:
            segs[0]["words"] = segs[0]["words"] + " [gecorrigeerd]"
        c = requests.post(f"{BASE}/api/sessions/{session_id}/correction",
                          json={"segments": segs}, timeout=10).json()
        check("correction saved", c.get("saved") is True
              and (ROOT / "data/corrections" / f"{session_id}.seglst.json").exists())

    # 8. summarize (graceful skip if LLM down)
    r = requests.post(f"{BASE}/api/summarize", json={"session_id": session_id}, timeout=300)
    if r.status_code == 503:
        check("summarize (LLM not configured — skip)", True)
    else:
        check("summarize", r.status_code == 200 and (r.json().get("summary") or "") != "", r.text[:120])

    # 8b. LIVE path: stream real webm/opus bytes over WS (the browser-mic route,
    # incl. container header) -> transcript + stored audio afterwards
    live_dir = None
    fleurs_wav = requests.get(f"{BASE}/api/eval/reference", params={"id": fleurs_item}, timeout=10)
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as wf:
        webm = wf.name
    src_wav = ROOT / "eval/audio/fleurs_nl" / (fleurs_item.split("/")[1] + ".wav")
    subprocess.run(["ffmpeg", "-y", "-i", str(src_wav), "-c:a", "libopus", "-b:a", "32k", webm],
                   capture_output=True, check=True)
    live_session = {}

    async def live_ws():
        import websockets
        data = open(webm, "rb").read()
        async with websockets.connect("ws://localhost:8080/asr", max_size=16 * 2**20,
                                      open_timeout=30) as ws:
            for i in range(0, len(data), 8000):   # ~browser chunk sizes, header first
                await ws.send(data[i:i + 8000])
                await asyncio.sleep(0.05)
            await ws.send(json.dumps({"type": "stop"}))
            async for raw in ws:
                m = json.loads(raw)
                if m.get("type") == "session_saved":
                    live_session.update(m)
                elif m.get("type") == "ready_to_stop":
                    break

    asyncio.run(asyncio.wait_for(live_ws(), timeout=300))
    check("live webm path produces transcript", bool(live_session.get("segments")),
          f"{len(live_session.get('segments', []))} segs")
    if live_session.get("session_id"):
        time.sleep(2)
        a = requests.get(f"{BASE}/api/sessions/{live_session['session_id']}/download/audio.wav", timeout=30)
        check("live recording stored as wav", a.status_code == 200 and len(a.content) > 20000,
              f"status={a.status_code} bytes={len(a.content)}")

    # 9. meeting lifecycle with file source (short clip -> auto-finalize)
    m = requests.post(f"{BASE}/api/meetings/start",
                      json={"name": "e2e-test", "source": f"file:{fleurs_item}", "internal": True}, timeout=30).json()
    mid = m.get("id")
    check("meeting start", bool(mid), str(m))
    state = None
    for _ in range(60):
        time.sleep(5)
        st = requests.get(f"{BASE}/api/meetings/{mid}", timeout=10).json()
        state = st.get("state")
        if state == "finished":
            break
    check("meeting auto-finalizes on source end", state == "finished", f"state={state}")
    ok_art = all(requests.get(f"{BASE}/api/meetings/{mid}/download/{a}", timeout=30).status_code == 200
                 for a in ("transcript.txt", "transcript.seglst.json", "audio.wav", "summary.md", "meta.json"))
    check("meeting artifacts downloadable", ok_art)
    txt = requests.get(f"{BASE}/api/meetings/{mid}/download/transcript.txt", timeout=30).text
    check("meeting transcript non-empty", len(txt.strip()) > 10, txt[:60])

    # 10. empty-meeting edge case (browser source, no feeder, immediate stop)
    m2 = requests.post(f"{BASE}/api/meetings/start",
                       json={"name": "e2e-empty", "source": "browser", "internal": True}, timeout=30).json()
    time.sleep(2)
    r = requests.post(f"{BASE}/api/meetings/{m2['id']}/stop", timeout=60).json()
    check("empty meeting stops cleanly", r.get("stopped") is True, str(r))

    # 11. meetings list includes both
    lst = requests.get(f"{BASE}/api/meetings?all=1", timeout=10).json()
    check("meetings listed", {mid, m2["id"]} <= {x["id"] for x in lst})

    # 12. samenvattingssjablonen: defaults aanwezig + CRUD-rondje
    tpls = requests.get(f"{BASE}/api/templates", timeout=10).json()["templates"]
    ids = {t["id"] for t in tpls}
    check("templates defaults aanwezig",
          {"algemeen", "letselschade-intake", "regelingsgesprek"} <= ids, str(ids))
    made = requests.post(f"{BASE}/api/templates", timeout=10,
                         json={"naam": "e2e-sjabloon", "secties": ["Onderwerp", "Besluiten"]}).json()
    tid = made.get("template", {}).get("id")
    check("template aanmaken", bool(tid), str(made)[:80])
    upd = requests.post(f"{BASE}/api/templates", timeout=10,
                        json={"id": tid, "naam": "e2e-sjabloon v2", "secties": ["Onderwerp"]}).json()
    check("template bewerken", upd.get("template", {}).get("naam") == "e2e-sjabloon v2")
    gone = requests.delete(f"{BASE}/api/templates/{tid}", timeout=10)
    still = {t["id"] for t in requests.get(f"{BASE}/api/templates", timeout=10).json()["templates"]}
    check("template verwijderen", gone.status_code == 200 and tid not in still)

    # 13. sprekerrollen: opslaan + teruglezen op de bestandsvergadering van test 9
    rr = requests.post(f"{BASE}/api/roles/meeting/{mid}", timeout=10,
                       json={"rollen": {"spk0": "jurist", "spk1": "cliënt"}, "bevestigd": True}).json()
    back = requests.get(f"{BASE}/api/roles/meeting/{mid}", timeout=10).json()
    check("rollen opslaan+teruglezen",
          rr.get("saved") and back.get("bevestigd") and back.get("rollen", {}).get("spk0") == "jurist",
          str(back)[:80])

    # 14. hersamenvattten met sjabloon (gebruikt LLM; bevestigde rollen gaan mee)
    rs = requests.post(f"{BASE}/api/resummarize", timeout=300,
                       json={"kind": "meeting", "id": mid, "template_id": "letselschade-intake"})
    ok_rs = rs.status_code == 200 and len(rs.json().get("summary", "").strip()) > 20
    check("hersamenvattten met sjabloon", ok_rs, rs.text[:80])

    # 14b. sjabloonkeuze wordt per gesprek onthouden (resummarize hierboven koos intake)
    sv0 = requests.get(f"{BASE}/api/summary/meeting/{mid}", timeout=10).json()
    check("sjabloonkeuze per gesprek onthouden", sv0.get("template_id") == "letselschade-intake",
          str(sv0.get("template_id")))

    # 14c. LLM-sjabloonvoorstel geeft een bestaand sjabloon terug (default: algemeen)
    sug = requests.post(f"{BASE}/api/templates/suggest", timeout=180,
                        json={"kind": "meeting", "id": mid}).json()
    all_ids = {t["id"] for t in requests.get(f"{BASE}/api/templates", timeout=10).json()["templates"]}
    check("LLM-sjabloonvoorstel geldig", sug.get("template_id") in all_ids, str(sug)[:100])

    # 15. versiegeschiedenis: bewerken maakt nieuwe versie; herstellen zet pointer terug
    sv = requests.get(f"{BASE}/api/summary/meeting/{mid}", timeout=10).json()
    n0, v0 = len(sv["versions"]), sv["current"]
    ed = requests.post(f"{BASE}/api/summary/meeting/{mid}", timeout=120,
                       json={"tekst": "E2E: handmatig bewerkte samenvatting."}).json()
    sv2 = requests.get(f"{BASE}/api/summary/meeting/{mid}", timeout=10).json()
    check("samenvatting bewerken = nieuwe versie",
          ed.get("saved") and len(sv2["versions"]) == n0 + 1
          and sv2["tekst"].startswith("E2E:") and sv2["current"] != v0, str(ed)[:80])
    rt = requests.post(f"{BASE}/api/summary/meeting/{mid}/restore", timeout=10,
                       json={"v": v0}).json()
    sv3 = requests.get(f"{BASE}/api/summary/meeting/{mid}", timeout=10).json()
    check("eerdere versie herstellen (niets verloren)",
          rt.get("restored") == v0 and sv3["current"] == v0
          and len(sv3["versions"]) == n0 + 1, str(rt)[:80])

    # 16. padinjectie geweigerd
    bad = requests.post(f"{BASE}/api/resummarize", timeout=10,
                        json={"kind": "session", "id": "../../etc"})
    check("padinjectie geweigerd", bad.status_code == 400, str(bad.status_code))

    # 17. verwijderen is privacy-compleet — de meeting heeft inmiddels rollen (test 13)
    #     én een samenvattings-versiegeschiedenis (test 14/15); na DELETE mag er op schijf
    #     NIETS meer van bestaan (audio, transcript, rollen, alle versies)
    from pathlib import Path as _P
    mdir = _P(__file__).resolve().parent.parent / "data/meetings" / mid
    had_versions = (mdir / "summary_versions.json").exists()
    rd = requests.delete(f"{BASE}/api/meetings/{mid}", timeout=30)
    gone_api = requests.get(f"{BASE}/api/meetings/{mid}", timeout=10).status_code == 404
    check("verwijderen privacy-compleet (incl. versies+rollen)",
          rd.status_code == 200 and had_versions and gone_api and not mdir.exists(),
          f"status={rd.status_code} had_versions={had_versions} dir_weg={not mdir.exists()}")
    requests.delete(f"{BASE}/api/meetings/{m2['id']}", timeout=30)  # opruimen

    fails = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(fails)}/{len(RESULTS)} passed" + (f"; FAILED: {fails}" if fails else ""))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
