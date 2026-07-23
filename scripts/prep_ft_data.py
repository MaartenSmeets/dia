#!/usr/bin/env python3
"""Build fine-tuning window manifests (JSONL: {wav, start, end, text}) for the M-series.

CGN comp-a (M2/M3): time-windows (<=28 s) over the MIXED audio with the time-ordered
merged transcript of ALL speakers inside the window (matches what a single-stream ASR
should output on multi-party audio). Verbatim targets (fillers kept) — that is CGN's
edge; the scoring normalizer strips them on both sides at eval time.
Recordings in cgn_a_dev/cgn_a_test manifests are EXCLUDED (never train on eval splits).

Usage:
  venvs/wlk/bin/python scripts/prep_ft_data.py cgn --hours 80 [--region nl]
Outputs data/ft/cgn_a_train.jsonl + prints hour count.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data/ft"
WINDOW_S = 28.0
MIN_WORDS = 3


def cgn_windows(hours: float, region: str) -> None:
    catalog = json.loads((ROOT / "eval/references/cgn_a/catalog.json").read_text())
    excluded = set()
    for split in ("dev", "test"):
        m = json.loads((ROOT / f"eval/manifests/cgn_a_{split}.json").read_text())
        excluded |= {it["utt"] for it in m["items"]}
    pool = [e for e in catalog if e["region"] == region and e["id"] not in excluded]
    rng = random.Random(7)
    rng.shuffle(pool)

    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / "cgn_a_train.jsonl"
    total_s, n_win = 0.0, 0
    with out_path.open("w", encoding="utf-8") as f:
        for e in pool:
            if total_s >= hours * 3600:
                break
            segs = json.loads((ROOT / f"eval/references/cgn_a/{e['id']}.seglst.json").read_text())
            segs.sort(key=lambda s: (s["start_time"], s["end_time"]))
            i = 0
            while i < len(segs):
                t0 = segs[i]["start_time"]
                j, words = i, []
                while j < len(segs) and segs[j]["end_time"] <= t0 + WINDOW_S:
                    words.append(segs[j]["words"])
                    j += 1
                if j == i:  # single segment longer than window: skip it
                    i += 1
                    continue
                t1 = max(s["end_time"] for s in segs[i:j])
                text = " ".join(words).strip()
                if len(text.split()) >= MIN_WORDS and set(text.split()) - {"xxx", "ggg"}:
                    f.write(json.dumps({"wav": e["wav"], "start": round(t0, 3),
                                        "end": round(t1, 3), "text": text},
                                       ensure_ascii=False) + "\n")
                    total_s += t1 - t0
                    n_win += 1
                i = j
    print(f"cgn_a_train.jsonl: {n_win} windows, {total_s/3600:.1f} h "
          f"(target {hours} h, region={region}, {len(excluded)} eval recordings excluded)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", choices=["cgn"])
    ap.add_argument("--hours", type=float, default=80)
    ap.add_argument("--region", default="nl")
    a = ap.parse_args()
    if a.source == "cgn":
        cgn_windows(a.hours, a.region)


if __name__ == "__main__":
    main()
