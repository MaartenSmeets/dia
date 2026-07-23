#!/usr/bin/env python3
"""CommonVoice-nl test export via legacy datasets (script-dataset support removed in v3+).

Runs in venvs/cvdl (datasets==2.21.0). Exports the same layout as download_hf_datasets.py:
eval/audio/cv22_nl/*.wav + eval/references/cv22_nl.seglst.json + eval/manifests/cv22_nl_test.json
"""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

import numpy as np
import soundfile as sf
from datasets import Audio, load_dataset

ROOT = Path(__file__).resolve().parent.parent
SR = 16000
CAP = 1000

ds = load_dataset("fsicoli/common_voice_22_0", "nl", split="test", trust_remote_code=True)
idx = list(range(len(ds)))
random.Random(42).shuffle(idx)
ds = ds.select(sorted(idx[:CAP]))
ds = ds.cast_column("audio", Audio(sampling_rate=SR))

audio_dir = ROOT / "eval/audio/cv22_nl"
audio_dir.mkdir(parents=True, exist_ok=True)
seglst, manifest = [], []
for i, ex in enumerate(ds):
    arr = ex["audio"]["array"]
    if arr.ndim > 1:
        arr = arr.mean(axis=1)
    utt = f"cv22_{i:05d}"
    wav = audio_dir / f"{utt}.wav"
    sf.write(wav, arr.astype(np.float32), SR, subtype="PCM_16")
    dur = round(len(arr) / SR, 3)
    text = ex["sentence"].strip()
    seglst.append({"session_id": utt, "speaker": "spk0", "start_time": 0.0,
                   "end_time": dur, "words": text})
    manifest.append({"utt": utt, "wav": str(wav.relative_to(ROOT)), "duration": dur,
                     "text": text, "sha256": hashlib.sha256(wav.read_bytes()).hexdigest()[:16]})
    if (i + 1) % 250 == 0:
        print(f"{i+1} exported", flush=True)

(ROOT / "eval/references/cv22_nl.seglst.json").write_text(
    json.dumps(seglst, ensure_ascii=False, indent=1), encoding="utf-8")
(ROOT / "eval/manifests/cv22_nl_test.json").write_text(
    json.dumps({"dataset": "cv22_nl", "n": len(manifest), "items": manifest},
               ensure_ascii=False, indent=1), encoding="utf-8")
print(f"CV22_NL_DONE {len(manifest)} utts, {sum(m['duration'] for m in manifest)/3600:.2f} h")
