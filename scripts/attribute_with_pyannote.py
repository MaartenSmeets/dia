#!/usr/bin/env python3
"""Method D: offline diarized transcription = stored whisper-longform ASR + pyannote
community-1 diarization + max-overlap speaker attribution. Runs in venvs/eval
(pyannote lives there; ASR hypotheses are read from a finished whisper-longform run).

Usage:
  venvs/eval/bin/python scripts/attribute_with_pyannote.py \
      --from-run eval/results/<stamp>-whisper-longform-<manifest>

Writes eval/results/<stamp>-whisper-longform+pyannote-<manifest>/.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
os.environ.setdefault("HF_HOME", str(ROOT / "data/hf"))

from dialib.seglst import load_seglst  # noqa: E402
from run_eval import score_item  # noqa: E402

_PIPELINE = None


def diarize(wav: Path) -> list[tuple[float, float, str]]:
    global _PIPELINE
    import torch
    from pyannote.audio import Pipeline
    if _PIPELINE is None:
        _PIPELINE = Pipeline.from_pretrained("pyannote/speaker-diarization-community-1",
                                             token=os.environ.get("HF_TOKEN"))
        _PIPELINE.to(torch.device("cuda"))
    out = _PIPELINE(str(wav))
    ann = getattr(out, "speaker_diarization", out)
    return [(t.start, t.end, spk) for t, _, spk in ann.itertracks(yield_label=True)]


def assign_speakers(asr_segs: list[dict], turns: list[tuple[float, float, str]]) -> list[dict]:
    out = []
    for s in asr_segs:
        best, best_ov = "spk0", 0.0
        for a, b, spk in turns:
            ov = min(s["end_time"], b) - max(s["start_time"], a)
            if ov > best_ov:
                best_ov, best = ov, spk
        out.append({**s, "speaker": best})
    return out


def wav_for(manifest: str, item: str) -> Path:
    if manifest.startswith("ifadv"):
        hits = sorted((ROOT / "data/ifadv").rglob(f"{item}*.wav"))
        return hits[0]
    if manifest.startswith("cgn_a"):
        cat = json.loads((ROOT / "eval/references/cgn_a/catalog.json").read_text())
        for e in cat:
            if e["id"] == item:
                return ROOT / e["wav"]
        raise SystemExit(f"cgn_a wav for {item} not found")
    m = json.loads((ROOT / f"eval/manifests/{manifest}_test.json").read_text())
    for it in m["items"]:
        if it["utt"] == item:
            return ROOT / it["wav"]
    raise SystemExit(f"wav for {item} not found")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-run", required=True)
    args = ap.parse_args()
    src = ROOT / args.from_run if not Path(args.from_run).is_absolute() else Path(args.from_run)
    cfg = json.loads((src / "config.json").read_text())
    assert cfg["method"] == "whisper-longform", "source run must be whisper-longform"
    manifest = cfg["manifest"]

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    out_dir = ROOT / "eval/results" / f"{stamp}-whisper-longform+pyannote-{manifest}"
    (out_dir / "per_item").mkdir(parents=True, exist_ok=True)
    (out_dir / "config.json").write_text(json.dumps({
        "method": "whisper-longform+pyannote", "manifest": manifest,
        "asr_from": str(src.name), "diarizer": "pyannote/speaker-diarization-community-1",
        "created_utc": stamp}, indent=1))

    rows = []
    for p in sorted((src / "per_item").glob("*.json")):
        d = json.loads(p.read_text())
        item = d["item"]
        if manifest.startswith("ifadv"):
            ref = load_seglst(ROOT / f"eval/references/ifadv/{item}.seglst.json")
        elif manifest.startswith("cgn_a"):
            ref = load_seglst(ROOT / f"eval/references/cgn_a/{item}.seglst.json")
        else:
            refs = load_seglst(ROOT / f"eval/references/{manifest}.seglst.json")
            ref = [s for s in refs if s["session_id"] == item]
        multi = len({s["speaker"] for s in ref}) > 1
        t0 = time.time()
        turns = diarize(wav_for(manifest, item))
        hyp = assign_speakers(d["hypothesis"], turns)
        scores = score_item(ref, hyp, multi)
        row = {"item": item, "scores": scores,
               "info": {"diarize_sec": round(time.time() - t0, 1), "n_turns": len(turns)},
               "n_hyp_segments": len(hyp), "elapsed": round(time.time() - t0, 1)}
        rows.append(row)
        (out_dir / "per_item" / f"{item}.json").write_text(
            json.dumps({**row, "hypothesis": hyp}, ensure_ascii=False, indent=1))
        print(f"{item}: WER={scores['wer'].get('wer')} "
              f"cpWER={scores.get('cpwer', {}).get('cpwer')} DER={scores.get('der', {}).get('der')} "
              f"({row['elapsed']}s, {len(turns)} turns)", flush=True)

    def pooled(kind):
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

    summary = {"method": "whisper-longform+pyannote", "manifest": manifest, "items": len(rows),
               "wer": pooled("wer"), "cpwer": pooled("cpwer"), "der": pooled("der")}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1))
    print("\nSUMMARY:", json.dumps(summary))
    print("results ->", out_dir.relative_to(ROOT))


if __name__ == "__main__":
    main()
