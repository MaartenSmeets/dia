#!/usr/bin/env python3
"""Latency stats from saved sessions' events.jsonl (realtime streaming sessions only).

For each result event the server logged: wall clock, audio_fed (stream position),
n_lines (finalized), buffer_len. From consecutive events we estimate:
  - finalization lag: audio_fed at the moment the last committed line's end time advanced
    minus that end time (how far finalized text trails the live edge)
  - update cadence: time between result events
Only sessions with meta.mode == replay and speed == 1.0 are realtime-faithful.

Usage: venvs/wlk/bin/python eval/latency_report.py [--since YYYYMMDD] [--limit N]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dialib.seglst import load_seglst  # noqa: E402


def pct(vals, p):
    if not vals:
        return None
    s = sorted(vals)
    return round(s[min(len(s) - 1, int(p / 100 * len(s)))], 2)


def analyze(session_dir: Path):
    meta = json.loads((session_dir / "meta.json").read_text())
    if meta.get("mode") != "replay" or float(meta.get("speed", 0)) != 1.0:
        return None
    ev_path = session_dir / "events.jsonl"
    if not ev_path.exists():
        return None
    events = [json.loads(l) for l in ev_path.read_text().splitlines() if l.strip()]
    if len(events) < 10:
        return None
    hyp = load_seglst(session_dir / "hyp.seglst.json")
    # committed-line frontier per event: n_lines index into final hyp (approximation:
    # lines are cumulative; use end_time of line n_lines-1 at each event)
    ends = [s["end_time"] for s in hyp]
    lags, cadence = [], []
    prev_wall, prev_n = None, 0
    for e in events:
        if prev_wall is not None:
            cadence.append(e["wall"] - prev_wall)
        prev_wall = e["wall"]
        n = min(e["n_lines"], len(ends))
        if n > prev_n and n >= 1:
            lag = e["audio_fed"] - ends[n - 1]
            if -5 < lag < 120:
                lags.append(lag)
            prev_n = n
    return {
        "session": meta["session_id"], "source": meta.get("source"),
        "audio_sec": meta.get("audio_seconds"), "n_events": len(events),
        "finalization_lag_s": {"p50": pct(lags, 50), "p90": pct(lags, 90), "n": len(lags)},
        "update_cadence_s": {"p50": pct(cadence, 50), "p90": pct(cadence, 90)},
        "engine": {k: meta.get("engine_args", {}).get(k) for k in ("--model", "--frame-threshold")},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="")
    ap.add_argument("--limit", type=int, default=50)
    args = ap.parse_args()
    rows = []
    for d in sorted((ROOT / "data/sessions").iterdir(), reverse=True)[: args.limit * 3]:
        if args.since and d.name < args.since:
            continue
        if not (d / "meta.json").exists():
            continue
        try:
            r = analyze(d)
        except Exception as e:
            print(f"  skip {d.name}: {e}", file=sys.stderr)
            continue
        if r:
            rows.append(r)
        if len(rows) >= args.limit:
            break
    print(json.dumps(rows, indent=1))
    all_lags_p50 = [r["finalization_lag_s"]["p50"] for r in rows if r["finalization_lag_s"]["p50"] is not None]
    if all_lags_p50:
        print(f"\n# {len(rows)} realtime sessions; median finalization-lag p50: "
              f"{statistics.median(all_lags_p50):.2f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
