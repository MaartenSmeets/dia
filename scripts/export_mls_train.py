#!/usr/bin/env python3
"""Export an N-hour subset of MLS-nl train via HF streaming (no full 1554 h download).

venvs/eval/bin/python scripts/export_mls_train.py --hours 60
-> data/ft/audio/mls/*.wav (16 kHz mono) + data/ft/mls_train.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from datasets import load_dataset

ROOT = Path(__file__).resolve().parent.parent
SR = 16000


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=60)
    a = ap.parse_args()
    audio_dir = ROOT / "data/ft/audio/mls"
    audio_dir.mkdir(parents=True, exist_ok=True)
    ds = load_dataset("facebook/multilingual_librispeech", "dutch", split="train", streaming=True)
    total_s, n = 0.0, 0
    out = (ROOT / "data/ft/mls_train.jsonl").open("w", encoding="utf-8")
    for ex in ds:
        arr = ex["audio"]["array"]
        sr = ex["audio"]["sampling_rate"]
        if sr != SR:
            import math
            idx = (np.arange(int(len(arr) * SR / sr)) * (sr / SR)).astype(np.int64)
            arr = arr[np.clip(idx, 0, len(arr) - 1)]
        dur = len(arr) / SR
        if dur > 29.0 or dur < 1.0:
            continue
        wav = audio_dir / f"mls_{n:06d}.wav"
        sf.write(wav, arr.astype(np.float32), SR, subtype="PCM_16")
        out.write(json.dumps({"wav": str(wav.relative_to(ROOT)), "start": 0.0,
                              "end": round(dur, 3), "text": ex["transcript"].strip()},
                             ensure_ascii=False) + "\n")
        total_s += dur
        n += 1
        if n % 2000 == 0:
            print(f"{n} utts, {total_s/3600:.1f} h", flush=True)
        if total_s >= a.hours * 3600:
            break
    out.close()
    print(f"MLS_EXPORT_DONE {n} utts, {total_s/3600:.1f} h")


if __name__ == "__main__":
    main()
