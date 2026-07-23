#!/usr/bin/env python3
"""Export ~N hours of CommonVoice-22 nl train (legacy datasets venv, like download_cv_legacy).
venvs/cvdl/bin/python scripts/export_cv_train.py --hours 20
-> data/ft/audio/cv/*.wav + data/ft/cv_train.jsonl
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import numpy as np
import soundfile as sf
from datasets import Audio, load_dataset

ROOT = Path(__file__).resolve().parent.parent
SR = 16000

ap = argparse.ArgumentParser()
ap.add_argument("--hours", type=float, default=20)
a = ap.parse_args()

ds = load_dataset("fsicoli/common_voice_22_0", "nl", split="train", trust_remote_code=True)
idx = list(range(len(ds)))
random.Random(7).shuffle(idx)
ds = ds.select(idx)
ds = ds.cast_column("audio", Audio(sampling_rate=SR))

audio_dir = ROOT / "data/ft/audio/cv"
audio_dir.mkdir(parents=True, exist_ok=True)
out = (ROOT / "data/ft/cv_train.jsonl").open("w", encoding="utf-8")
total_s, n = 0.0, 0
for ex in ds:
    arr = ex["audio"]["array"]
    if arr.ndim > 1:
        arr = arr.mean(axis=1)
    dur = len(arr) / SR
    if dur > 29.0 or dur < 1.0:
        continue
    wav = audio_dir / f"cv_{n:06d}.wav"
    sf.write(wav, arr.astype(np.float32), SR, subtype="PCM_16")
    out.write(json.dumps({"wav": str(wav.relative_to(ROOT)), "start": 0.0,
                          "end": round(dur, 3), "text": ex["sentence"].strip()},
                         ensure_ascii=False) + "\n")
    total_s += dur
    n += 1
    if n % 2000 == 0:
        print(f"{n} utts, {total_s/3600:.1f} h", flush=True)
    if total_s >= a.hours * 3600:
        break
out.close()
print(f"CV_EXPORT_DONE {n} utts, {total_s/3600:.1f} h")
