#!/usr/bin/env python3
"""Download Dutch eval sets from HF and export as WAV + SegLST references.

Run with venvs/eval. HF_HOME should point at data/hf (set via .env).
Exports per dataset:
  eval/audio/<dataset>/<utt_id>.wav          (16 kHz mono PCM16)
  eval/references/<dataset>.seglst.json      (single-speaker segments, start=0, end=duration)
  eval/manifests/<dataset>_test.json         (utterance list + text + sha256 of wav)

Datasets (see docs/DATASETS.md): FLEURS nl_nl test (full), MLS dutch test (full),
CommonVoice 22 nl test (capped, seeded sample). VoxPopuli deferred.
"""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

import numpy as np
import soundfile as sf
from datasets import load_dataset, Audio

ROOT = Path(__file__).resolve().parent.parent
SR = 16000
CV_CAP = 1000  # CommonVoice test is large; fixed seeded subset is enough for WER tracking


def export(name: str, ds, text_key: str, utt_prefix: str) -> None:
    audio_dir = ROOT / "eval/audio" / name
    audio_dir.mkdir(parents=True, exist_ok=True)
    ds = ds.cast_column("audio", Audio(sampling_rate=SR))
    seglst, manifest = [], []
    for i, ex in enumerate(ds):
        arr = ex["audio"]["array"]
        if arr.ndim > 1:
            arr = arr.mean(axis=1)
        utt = f"{utt_prefix}_{i:05d}"
        wav_path = audio_dir / f"{utt}.wav"
        sf.write(wav_path, arr.astype(np.float32), SR, subtype="PCM_16")
        dur = round(len(arr) / SR, 3)
        text = ex[text_key].strip()
        seglst.append({"session_id": utt, "speaker": "spk0",
                       "start_time": 0.0, "end_time": dur, "words": text})
        manifest.append({"utt": utt, "wav": str(wav_path.relative_to(ROOT)),
                         "duration": dur, "text": text,
                         "sha256": hashlib.sha256(wav_path.read_bytes()).hexdigest()[:16]})
        if (i + 1) % 250 == 0:
            print(f"  {name}: {i+1} exported", flush=True)
    (ROOT / "eval/references" / f"{name}.seglst.json").write_text(
        json.dumps(seglst, ensure_ascii=False, indent=1), encoding="utf-8")
    (ROOT / "eval/manifests" / f"{name}_test.json").write_text(
        json.dumps({"dataset": name, "n": len(manifest), "items": manifest},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    hours = sum(m["duration"] for m in manifest) / 3600
    print(f"{name}: {len(manifest)} utts, {hours:.2f} h -> eval/audio/{name}/", flush=True)


def main() -> None:
    (ROOT / "eval/references").mkdir(parents=True, exist_ok=True)
    (ROOT / "eval/manifests").mkdir(parents=True, exist_ok=True)

    print("== FLEURS nl_nl test", flush=True)
    fleurs = load_dataset("google/fleurs", "nl_nl", split="test")
    export("fleurs_nl", fleurs, "transcription", "fleurs")

    print("== MLS dutch test", flush=True)
    mls = load_dataset("facebook/multilingual_librispeech", "dutch", split="test")
    export("mls_nl", mls, "transcript", "mls")

    print("== CommonVoice 22 nl test (seeded cap)", flush=True)
    cv = load_dataset("fsicoli/common_voice_22_0", "nl", split="test")
    idx = list(range(len(cv)))
    random.Random(42).shuffle(idx)
    cv = cv.select(sorted(idx[:CV_CAP]))
    export("cv22_nl", cv, "sentence", "cv22")

    print("ALL_DATASETS_DONE", flush=True)


if __name__ == "__main__":
    main()
