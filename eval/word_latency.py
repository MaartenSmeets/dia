#!/usr/bin/env python3
"""Woordniveau-emissielatentie van de live-pijplijn (taak #14).

Vereist sessies met tekst-delta's in events.jsonl (app/server.py logt die sinds 2026-07-23):
per result-event de nieuw gecommitteerde tekst ("delta", met "rewrite"-vlag bij herschrijving).
Referentie: IFADV .words.json (per woord: speaker/word/start_time/end_time).

Definitie: emissielatentie van woord w = audio_fed op het moment dat w voor het eerst in de
GECOMMITTEERDE tekst verschijnt, minus de referentie-eindtijd van w. audio_fed is de betrouwbare
klok (gepaced replay op speed 1.0); wandkloktijd heeft een onbekende startoffset.

Matching is bewust conservatief (precisie boven dekking): een hyp-woord matcht alleen als het
genormaliseerd EXACT gelijk is aan precies ÉÉN nog niet gematcht referentiewoord met eindtijd in
(audio_fed − 30 s, audio_fed]. Korte woorden (<3 tekens) doen niet mee. De gerapporteerde
percentielen gaan dus over een schone deelverzameling, niet over alle woorden.

  venvs/wlk/bin/python eval/word_latency.py [--since YYYYMMDD] [--limit N] [--out]
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SESSIONS = ROOT / "data/sessions"

def norm(w: str) -> str:
    """Accentvouwend en interpunctie-strippend: awd-woorden dragen Praat-escapes
    (ok\\e\\' = oké), hyp-woorden echte accenten — na vouwen matchen beide op 'oke'."""
    import unicodedata
    w = unicodedata.normalize("NFD", w.lower())
    w = "".join(c for c in w if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z]+", "", w)


def pct(vals, p):
    if not vals:
        return None
    s = sorted(vals)
    return round(s[min(len(s) - 1, int(p / 100 * len(s)))], 2)


def analyze(session_dir: Path) -> dict | None:
    meta = json.loads((session_dir / "meta.json").read_text())
    if meta.get("mode") != "replay" or float(meta.get("speed", 0)) != 1.0:
        return None
    src = meta.get("source", "")
    m = re.search(r"ifadv/(\w+)", src)
    if not m:
        return None
    dialogue = m.group(1)
    ev_path = session_dir / "events.jsonl"
    if not ev_path.exists():
        return None
    events = [json.loads(l) for l in ev_path.read_text().splitlines() if l.strip()]
    if not any("delta" in e for e in events):
        return None  # sessie van vóór de delta-logging

    ref = json.loads((ROOT / f"eval/references/ifadv/{dialogue}.words.json").read_text())
    ref_words = [{"n": norm(w["word"]), "end": w["end_time"], "matched": False}
                 for w in ref if len(norm(w["word"])) >= 3]

    # hyp-woordemissies reconstrueren uit delta's (rewrite = volledige tekst opnieuw:
    # alleen posities voorbij de vorige lengte tellen als verse emissies)
    emissions = []  # (norm_word, audio_fed)
    committed_words: list[str] = []
    for e in events:
        if "delta" not in e:
            continue
        if e.get("rewrite"):
            new_words = e["delta"].split()
            fresh = new_words[len(committed_words):]
            committed_words = new_words
        else:
            fresh = e["delta"].split()
            committed_words += fresh
        for w in fresh:
            nw = norm(w)
            if len(nw) >= 3:
                emissions.append((nw, e["audio_fed"]))

    # conservatieve matching: uniek in het 30s-venster
    lats = []
    ptr = 0  # ref_words gesorteerd op eindtijd; venster-onderkant schuift mee
    for nw, fed in emissions:
        while ptr < len(ref_words) and ref_words[ptr]["end"] < fed - 30.0:
            ptr += 1
        cands = [r for r in ref_words[ptr:] if r["end"] <= fed and not r["matched"] and r["n"] == nw]
        if len(cands) == 1:
            cands[0]["matched"] = True
            lats.append(fed - cands[0]["end"])

    if len(lats) < 50:
        return None
    return {"session": session_dir.name, "dialogue": dialogue,
            "n_emissions": len(emissions), "n_matched": len(lats),
            "match_frac": round(len(lats) / max(1, len(emissions)), 3),
            "latency_s": {"p50": pct(lats, 50), "p90": pct(lats, 90),
                          "mean": round(statistics.mean(lats), 2), "n": len(lats)},
            "engine": {k: meta.get("engine_args", {}).get(k)
                       for k in ("--model", "--frame-threshold")}}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="20260723")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", action="store_true", help="schrijf rapport naar eval/results/")
    a = ap.parse_args()

    rows = []
    for d in sorted(SESSIONS.iterdir(), reverse=True):
        if d.name < a.since:
            continue
        try:
            r = analyze(d)
        except Exception as e:
            print(f"  SKIP {d.name}: {e}", file=sys.stderr)
            continue
        if r:
            rows.append(r)
        if a.limit and len(rows) >= a.limit:
            break

    all_p50 = [r["latency_s"]["p50"] for r in rows]
    report = {"sessions": rows, "n_sessions": len(rows),
              "median_p50": pct(all_p50, 50), "median_p90": pct([r["latency_s"]["p90"] for r in rows], 50)}
    print(json.dumps(report, indent=1, ensure_ascii=False))
    if a.out and rows:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
        out = ROOT / "eval/results" / f"{stamp}-word-latency"
        out.mkdir(parents=True, exist_ok=True)
        (out / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
        print("results ->", out.relative_to(ROOT))


if __name__ == "__main__":
    main()
