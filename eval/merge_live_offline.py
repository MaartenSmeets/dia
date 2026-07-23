#!/usr/bin/env python3
"""Fusie-experiment: LIVE sprekerstructuur (Sortformer, sterke cpWER) × OFFLINE woorden
(M2-adapter, sterke WER) → mogelijk beste-van-beide voor de "definitieve versie".

Methode: live-hypothesesegmenten (met sprekers) worden sprekerbeurten; elk offline
woord(-segment) krijgt de spreker van de beurt met maximale tijdsoverlap (midpoint-
fallback). Gescoord met dezelfde suite; vergeleken met live-only en offline+pyannote.

  venvs/wlk/bin/python eval/merge_live_offline.py \
      --live-run eval/results/20260717-1416-wlk-stream-turbo-val-ifadv_dev \
      --offline-run eval/results/20260722-1333-lora-M2w-ifadv_dev --manifest ifadv_dev
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))

from run_eval import manifest_items, score_item  # noqa: E402


def load_hyp(run_dir: Path, item: str) -> list[dict] | None:
    p = run_dir / "per_item" / f"{item}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())["hypothesis"]


def live_turns(live_segs: list[dict]) -> list[tuple[float, float, str]]:
    """Opeenvolgende segmenten van dezelfde spreker samenvoegen tot beurten."""
    turns = []
    for s in sorted(live_segs, key=lambda x: x["start_time"]):
        if turns and turns[-1][2] == s["speaker"] and s["start_time"] - turns[-1][1] < 2.0:
            turns[-1] = (turns[-1][0], max(turns[-1][1], s["end_time"]), s["speaker"])
        else:
            turns.append((s["start_time"], s["end_time"], s["speaker"]))
    return turns


def merge(offline_segs: list[dict], turns: list[tuple[float, float, str]]) -> list[dict]:
    out = []
    for s in offline_segs:
        best, best_ov = None, 0.0
        mid = (s["start_time"] + s["end_time"]) / 2
        for a, b, spk in turns:
            ov = min(s["end_time"], b) - max(s["start_time"], a)
            if ov > best_ov:
                best_ov, best = ov, spk
        if best is None:  # geen overlap: dichtstbijzijnde beurt op midpoint
            best = min(turns, key=lambda t: min(abs(mid - t[0]), abs(mid - t[1])))[2] if turns else "spk0"
        out.append({**s, "speaker": best})
    return out


def pooled(rows, kind):
    num = den = 0.0
    per = []
    for r in rows:
        s = r["scores"].get(kind) or {}
        if kind == "wer" and s.get("wer") is not None:
            num += s["substitutions"] + s["deletions"] + s["insertions"]; den += s["ref_words"]; per.append(s["wer"])
        elif kind == "cpwer" and s.get("cpwer") is not None:
            num += s["errors"]; den += s["ref_words"]; per.append(s["cpwer"])
        elif kind == "der" and s.get("der") is not None:
            e = (s["missed_speaker_time"] or 0) + (s["falarm_speaker_time"] or 0) + (s["speaker_error_time"] or 0)
            num += e; den += (s["scored_speaker_time"] or 0); per.append(s["der"])
    if not per:
        return None
    return {"pooled": round(num / den, 4) if den else None,
            "mean": round(statistics.mean(per), 4), "n": len(per)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live-run", required=True)
    ap.add_argument("--offline-run", required=True)
    ap.add_argument("--manifest", required=True)
    a = ap.parse_args()
    live_dir, off_dir = ROOT / a.live_run, ROOT / a.offline_run

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    out_dir = ROOT / "eval/results" / f"{stamp}-merged-liveturns-offwords-{a.manifest}"
    (out_dir / "per_item").mkdir(parents=True, exist_ok=True)
    (out_dir / "config.json").write_text(json.dumps({
        "method": "merged-liveturns+offlinewords", "live_run": a.live_run,
        "offline_run": a.offline_run, "manifest": a.manifest, "created_utc": stamp}, indent=1))

    rows = []
    for item, wav, ref in manifest_items(a.manifest, None):
        live = load_hyp(live_dir, item)
        off = load_hyp(off_dir, item)
        if not live or not off:
            continue
        merged = merge(off, live_turns(live))
        for s in merged:
            s["session_id"] = item
        scores = score_item(ref, merged, True)
        rows.append({"item": item, "scores": scores})
        (out_dir / "per_item" / f"{item}.json").write_text(
            json.dumps({"item": item, "scores": scores, "hypothesis": merged},
                       ensure_ascii=False, indent=1))
        print(f"{item}: WER={scores['wer'].get('wer')} cpWER={scores['cpwer'].get('cpwer')} "
              f"DER={scores['der'].get('der')}", flush=True)

    summary = {"method": "merged", "items": len(rows), "wer": pooled(rows, "wer"),
               "cpwer": pooled(rows, "cpwer"), "der": pooled(rows, "der")}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1))
    print("SUMMARY:", json.dumps(summary))


if __name__ == "__main__":
    main()
