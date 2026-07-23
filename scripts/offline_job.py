#!/usr/bin/env python3
"""Offline best-quality pass: HF whisper-large-v3-turbo (+ optionele LoRA-adapter, bv. de
CGN-getrainde M2) + pyannote community-1 diarisatie + woord/segment-attributie.

Gebruikt voor (a) de upload-modus "beste kwaliteit" en (b) de automatische nabewerking
("definitieve versie") van vergaderingen en live-sessies na afloop.

  venvs/eval/bin/python scripts/offline_job.py --audio <wav> --session-id <id> \
      [--adapter models/lora/M2-cgn] [--out-dir data/meetings/<id>] [--prefix refined_]

Zonder --out-dir: schrijft data/sessions/<session-id>/{hyp.seglst.json, meta.json} (upload-flow).
Met --out-dir + --prefix: schrijft <out-dir>/<prefix>{transcript.seglst.json, transcript.txt,
summary.md-placeholder wordt door de aanroeper gedaan} — de verfijningsflow.

LICENTIE: een CGN-getrainde adapter (M2/M3) valt onder de NC-CGN-licentie — intern gebruik
toegestaan, niet uitleveren in een commercieel product zonder commerciële CGN-licentie.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
os.environ.setdefault("HF_HOME", str(ROOT / "data/hf"))

from dialib.seglst import save_seglst  # noqa: E402

MODEL_ID = "openai/whisper-large-v3-turbo"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--session-id", required=True)
    ap.add_argument("--language", default="nl")
    ap.add_argument("--adapter", default="", help="peft dir (bv. models/lora/M2-cgn); leeg = basismodel")
    ap.add_argument("--out-dir", default="", help="doelmap (verfijningsflow); leeg = data/sessions/<id>")
    ap.add_argument("--prefix", default="", help="bestandsprefix in out-dir, bv. refined_")
    args = ap.parse_args()
    audio = Path(args.audio)
    t0 = time.time()

    print("STAGE audio_loading", flush=True)
    import numpy as np
    import soundfile as sf
    # tolerant decoderen: strikte decoders (torchaudio→torchcodec) weigeren een heel
    # bestand om bv. één afgekapt laatste sample (crash gezien 2026-07-23). Eén keer
    # inladen met soundfile en de array doorgeven aan ASR én diarization.
    wav, in_sr = sf.read(str(audio), dtype="float32", always_2d=True)
    wav = wav.mean(axis=1)
    if in_sr != 16000:
        idx = (np.arange(int(len(wav) * 16000 / in_sr)) * (in_sr / 16000)).astype(np.int64)
        wav = wav[np.clip(idx, 0, len(wav) - 1)]
        in_sr = 16000

    print("STAGE asr_loading", flush=True)
    import torch
    from transformers import WhisperForConditionalGeneration, WhisperProcessor, pipeline
    processor = WhisperProcessor.from_pretrained(MODEL_ID)
    model = WhisperForConditionalGeneration.from_pretrained(MODEL_ID, dtype=torch.bfloat16)
    adapter_used = ""
    if args.adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, str(ROOT / args.adapter)).merge_and_unload()
        adapter_used = args.adapter
    asr = pipeline("automatic-speech-recognition", model=model,
                   tokenizer=processor.tokenizer, feature_extractor=processor.feature_extractor,
                   device="cuda", torch_dtype=torch.bfloat16,
                   chunk_length_s=30, batch_size=2)

    print("STAGE asr_running", flush=True)
    out = asr({"array": wav, "sampling_rate": in_sr}, return_timestamps=True,
              generate_kwargs={"language": "dutch", "task": "transcribe"})
    segs = []
    for ch in out.get("chunks", []):
        txt = (ch.get("text") or "").strip()
        if not txt:
            continue
        ts = ch.get("timestamp") or (0.0, None)
        s0 = float(ts[0] or 0.0)
        s1 = float(ts[1]) if ts[1] is not None else s0 + 2.0
        segs.append({"session_id": args.session_id, "speaker": "spk0",
                     "start_time": round(s0, 3), "end_time": round(max(s1, s0 + 0.01), 3),
                     "words": txt})
    asr_secs = time.time() - t0
    del model, asr
    torch.cuda.empty_cache()

    print("STAGE diarizing", flush=True)
    from pyannote.audio import Pipeline
    pipe = Pipeline.from_pretrained("pyannote/speaker-diarization-community-1",
                                    token=os.environ.get("HF_TOKEN"))
    pipe.to(torch.device("cuda"))
    dia = pipe({"waveform": torch.from_numpy(wav).unsqueeze(0), "sample_rate": in_sr})
    ann = getattr(dia, "speaker_diarization", dia)
    turns = [(t.start, t.end, spk) for t, _, spk in ann.itertracks(yield_label=True)]

    print("STAGE attributing", flush=True)
    for s in segs:
        best, best_ov = "spk0", 0.0
        for a, b, spk in turns:
            ov = min(s["end_time"], b) - max(s["start_time"], a)
            if ov > best_ov:
                best_ov, best = ov, spk
        s["speaker"] = best

    n_spk = len({s["speaker"] for s in segs})
    meta = {"session_id": args.session_id, "mode": "offline",
            "method": f"turbo{'+' + adapter_used if adapter_used else ''}+pyannote",
            "adapter": adapter_used, "source": str(audio),
            "language": args.language, "n_lines": len(segs), "n_speakers": n_spk,
            "asr_sec": round(asr_secs, 1), "total_sec": round(time.time() - t0, 1),
            "created": time.strftime("%Y-%m-%d %H:%M:%S")}

    if args.out_dir:  # verfijningsflow: naast bestaande artefacten schrijven
        d = ROOT / args.out_dir
        d.mkdir(parents=True, exist_ok=True)
        p = args.prefix
        save_seglst(segs, d / f"{p}transcript.seglst.json")
        lines = []
        for s in segs:
            mm, ss = divmod(int(s["start_time"]), 60)
            lines.append(f"[{mm:02d}:{ss:02d}] {s['speaker']}: {s['words']}")
        (d / f"{p}transcript.txt").write_text("\n".join(lines), encoding="utf-8")
        (d / f"{p}meta.json").write_text(json.dumps(meta, indent=1))
    else:  # upload-flow (sessies)
        d = ROOT / "data/sessions" / args.session_id
        d.mkdir(parents=True, exist_ok=True)
        save_seglst(segs, d / "hyp.seglst.json")
        (d / "meta.json").write_text(json.dumps(meta, indent=1))
    print(f"DONE {len(segs)} segments, {n_spk} speakers, {time.time() - t0:.0f}s total", flush=True)


if __name__ == "__main__":
    main()
