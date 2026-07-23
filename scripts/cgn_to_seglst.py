#!/usr/bin/env python3
"""Convert CGN comp-a orthographic annotations (.ort.gz, short-TextGrid) to SegLST/RTTM
references + catalog + dev/test manifests.

- Speaker tiers = names matching [NV]\\d+ ; UNKNOWN kept as a speaker; BACKGROUND/COMMENT skipped.
- CGN token markers (*d dialect, *z foreign, *n neologism, *u mispronounced, *a incomplete,
  *x unclear, *t) are stripped from the token; xxx/ggg kept verbatim (normalizer handles them).
- Splits: NL region, 2-4 speakers, no UNKNOWN tier, seeded; stratified over speaker count.
- Timeline audit: union speech activity (reference) vs energy-VAD union of both channels; flag <0.60.

Outputs: eval/references/cgn_a/<id>.{seglst.json,rttm}, eval/references/cgn_a/catalog.json,
         eval/manifests/cgn_a_{dev,test}.json
Run: venvs/wlk/bin/python scripts/cgn_to_seglst.py   (needs soundfile+numpy for the audit)
"""
from __future__ import annotations

import gzip
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ifadv_to_seglst import decode_praat_text, parse_short_textgrid  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CGN = ROOT / "data/cgn/CGN_2.0.3"
OUT = ROOT / "eval/references/cgn_a"
SPEAKER_RE = re.compile(r"^[NV]\d+")
MARKER_RE = re.compile(r"\*[a-z]\b")
DEV_N, TEST_N = 12, 12


def clean_token_text(s: str) -> str:
    s = decode_praat_text(s)
    s = MARKER_RE.sub("", s)
    return re.sub(r"\s+", " ", s).strip()


def convert_one(ort_gz: Path, region: str, comp: str = "a") -> dict | None:
    rec_id = ort_gz.name.split(".")[0]
    text = gzip.open(ort_gz, "rt", encoding="latin-1").read()
    tiers = parse_short_textgrid(ort_gz, text=text)
    seglst, rttm = [], []
    speakers, has_unknown = set(), False
    xmax = 0.0
    for t in tiers:
        name = t["name"]
        if name in ("BACKGROUND", "COMMENT"):
            continue
        if name == "UNKNOWN":
            has_unknown = True
        elif not SPEAKER_RE.match(name):
            continue
        speakers.add(name)
        for a, b, txt in t["intervals"]:
            xmax = max(xmax, b)
            txt = clean_token_text(txt)
            if not txt or b <= a:
                continue
            seglst.append({"session_id": rec_id, "speaker": name,
                           "start_time": round(a, 3), "end_time": round(b, 3), "words": txt})
            rttm.append(f"SPEAKER {rec_id} 1 {a:.3f} {b - a:.3f} <NA> <NA> {name} <NA> <NA>")
    if not seglst:
        return None
    seglst.sort(key=lambda s: s["start_time"])
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{rec_id}.seglst.json").write_text(json.dumps(seglst, ensure_ascii=False), encoding="utf-8")
    (OUT / f"{rec_id}.rttm").write_text("\n".join(sorted(rttm, key=lambda l: float(l.split()[3]))) + "\n")
    wav = CGN / f"data/audio/wav/comp-{comp}/{region}/{rec_id}.wav"
    speech = sum(s["end_time"] - s["start_time"] for s in seglst)
    return {"id": rec_id, "region": region, "component": comp,
            "n_speakers": len(speakers - {"UNKNOWN"}),
            "has_unknown": has_unknown, "duration": round(xmax, 1),
            "speech_sec": round(speech, 1), "n_segments": len(seglst),
            "wav": str(wav.relative_to(ROOT))}


def audit(entry: dict, frame: float = 0.03) -> float:
    import numpy as np
    import soundfile as sf
    x, sr = sf.read(ROOT / entry["wav"])
    if x.ndim > 1:
        chans = [x[:, i] for i in range(x.shape[1])]
    else:
        chans = [x]
    n = int(sr * frame)
    vad = None
    for c in chans:
        nf = len(c) // n
        e = (c[: nf * n].reshape(nf, n) ** 2).mean(axis=1) ** 0.5
        v = e > (np.percentile(e, 20) * 4 + 1e-6)
        vad = v if vad is None else (vad | v)
    segs = json.loads((OUT / f"{entry['id']}.seglst.json").read_text())
    ref = np.zeros(len(vad), bool)
    for s in segs:
        ref[int(s["start_time"] / frame): int(s["end_time"] / frame)] = True
    inter = (ref & vad).sum()
    return round(2 * inter / max(ref.sum() + vad.sum(), 1), 3)


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--components", default="a", help="comma list, e.g. a or c,d")
    ap.add_argument("--out-name", default="cgn_a", help="dataset name for refs/manifests")
    args = ap.parse_args()
    comps = args.components.split(",")

    global OUT
    OUT = ROOT / f"eval/references/{args.out_name}"

    catalog = []
    for comp in comps:
        for region in ("nl", "vl"):
            d = CGN / f"data/annot/text/ort/comp-{comp}/{region}"
            if not d.exists():
                continue
            for p in sorted(d.glob("*.ort.gz")):
                e = convert_one(p, region, comp)
                if e:
                    catalog.append(e)
    (OUT / "catalog.json").write_text(json.dumps(catalog, indent=1))
    print(f"converted {len(catalog)} recordings "
          f"(nl={sum(1 for e in catalog if e['region']=='nl')}, "
          f"vl={sum(1 for e in catalog if e['region']=='vl')})")

    # splits: NL, 2-4 speakers, no UNKNOWN, stratified by n_speakers
    cands = [e for e in catalog if e["region"] == "nl" and 2 <= e["n_speakers"] <= 4
             and not e["has_unknown"]]
    rng = random.Random(42)
    by_spk = {k: sorted([e for e in cands if e["n_speakers"] == k], key=lambda e: e["id"]) for k in (2, 3, 4)}
    for k in by_spk:
        rng.shuffle(by_spk[k])
    quota = {2: 8, 3: 3, 4: 1}
    dev, test = [], []
    for k, q in quota.items():
        picked = []
        for e in by_spk[k]:  # walk the shuffled pool, keep only timeline-clean recordings
            if len(picked) >= 2 * q:
                break
            m = audit(e)
            if m >= 0.60:
                e["timeline_match"] = m
                picked.append(e)
            else:
                print(f"  (skip {e['id']}: timeline audit {m} < 0.60)")
        dev += picked[:q]
        test += picked[q:2 * q]
    for name, items in (("dev", dev), ("test", test)):
        (ROOT / f"eval/manifests/{args.out_name}_{name}.json").write_text(json.dumps({
            "dataset": args.out_name, "split": name,
            **({"HELD_OUT": "never tune on this"} if name == "test" else {}),
            "items": [{"utt": e["id"], "wav": e["wav"], "n_speakers": e["n_speakers"],
                       "duration": e["duration"]} for e in items]}, indent=1))
    print(f"splits: dev={len(dev)} test={len(test)} (from {len(cands)} NL 2-4spk candidates)")

    print("selected (all timeline-clean):")
    for e in dev + test:
        print(f"  {e['id']} ({e['n_speakers']}spk, {e['duration']}s): {e['timeline_match']}")


if __name__ == "__main__":
    main()
