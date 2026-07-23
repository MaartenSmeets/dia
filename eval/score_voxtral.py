#!/usr/bin/env python3
"""Voxtral-Mini-3B offline scoren op onze manifests — zelfde normalizer/scoring als de
M-serie en de NeMo-basisrace, zodat de cijfers 1-op-1 vergelijkbaar zijn.

Twee fasen (twee venvs, bewust gescheiden — zie CLAUDE.md venv-regels):
  1) transcribe (venvs/vox):  venvs/vox/bin/python eval/score_voxtral.py --phase transcribe \
                                --manifest ifadv_dev --out-dir eval/results/<stamp>-voxtral-ifadv_dev
     → schrijft per item hyp-segmenten (JSON), géén scoring-imports nodig.
  2) score (venvs/wlk):       venvs/wlk/bin/python eval/score_voxtral.py --phase score \
                                --manifest ifadv_dev --out-dir <zelfde dir>
     → scoort met run_eval.score_item (meeteval/jiwer/normalizer v1) en schrijft summary.json.

Lange audio: hele bestand in één transcriptie-request als het past (≤ --max-single-s, default
25 min; IFADV ~15 min en CGN comp-a ~10 min passen), anders eigen 30s-vensters (zelfde
fallback-vorm als score_nemo.py).
"""
from __future__ import annotations

import argparse
import gc
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))

MODEL_ID = "mistralai/Voxtral-Mini-3B-2507"
SR = 16000


def manifest_wavs(name: str, limit: int | None):
    """Lichte kopie van run_eval.manifest_items zonder referenties (geen zware imports)."""
    m = json.loads((ROOT / f"eval/manifests/{name}.json").read_text())
    if name.startswith("ifadv"):
        for did in m["dialogues"][:limit]:
            hits = sorted((ROOT / "data/ifadv").rglob(f"{did}*.wav"))
            if not hits:
                print(f"  SKIP {did}: audio niet gevonden", flush=True)
                continue
            yield did, hits[0]
    else:
        for it in m["items"][:limit]:
            yield it["utt"], ROOT / it["wav"]


# ------------------------------------------------------------- fase 1: transcribe

def phase_transcribe(a: argparse.Namespace) -> None:
    import numpy as np
    import soundfile as sf
    import torch
    from transformers import AutoProcessor, VoxtralForConditionalGeneration

    out_dir = Path(a.out_dir)
    (out_dir / "per_item").mkdir(parents=True, exist_ok=True)

    processor = AutoProcessor.from_pretrained(MODEL_ID)
    model = VoxtralForConditionalGeneration.from_pretrained(
        MODEL_ID, dtype=torch.bfloat16, device_map="cuda")
    model.eval()

    (out_dir / "config.json").write_text(json.dumps({
        "method": "voxtral-offline", "model": MODEL_ID, "manifest": a.manifest,
        "windowing": f"heel bestand ≤{a.max_single_s:.0f}s, anders 30s-vensters",
        "max_new_tokens": a.max_new_tokens,
        "created_utc": datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")}, indent=1))

    # oudere transformers-versies hadden een typo in de methodenaam — vang beide
    apply_fn = getattr(processor, "apply_transcription_request", None) \
        or processor.apply_transcrition_request

    def transcribe_audio(wav_path: Path, offset_s: float = 0.0) -> list[dict]:
        info = sf.info(wav_path)
        dur = info.frames / info.samplerate
        inputs = apply_fn(language="nl", audio=str(wav_path), model_id=MODEL_ID)
        inputs = inputs.to("cuda", dtype=torch.bfloat16)
        # cap generatie op audiolengte (~15 tok/s spraak is al ruim): stopt herhaal-loops
        max_new = min(a.max_new_tokens, int(dur * 15) + 50)
        with torch.inference_mode():
            out = model.generate(**inputs, max_new_tokens=max_new, do_sample=False)
        txt = processor.batch_decode(
            out[:, inputs.input_ids.shape[1]:], skip_special_tokens=True)[0].strip()
        del inputs, out
        gc.collect(); torch.cuda.empty_cache()
        if not txt:
            return []
        return [{"speaker": "spk0", "start_time": round(offset_s, 3),
                 "end_time": round(offset_s + dur, 3), "words": txt}]

    for item_id, wav in manifest_wavs(a.manifest, a.limit):
        hyp_path = out_dir / "per_item" / f"{item_id}.hyp.json"
        if hyp_path.exists():
            print(f"{item_id}: al gedaan, sla over", flush=True)
            continue
        info = sf.info(wav)
        dur = info.frames / info.samplerate
        t0 = time.time()
        if dur <= a.max_single_s:
            segs = transcribe_audio(wav)
        else:  # 30s-venster-fallback (zelfde vorm als score_nemo)
            import tempfile
            x, sr = sf.read(wav, dtype="float32", always_2d=True)
            x = x.mean(axis=1)
            if sr != SR:
                idx = (np.arange(int(len(x) * SR / sr)) * (sr / SR)).astype(np.int64)
                x = x[np.clip(idx, 0, len(x) - 1)]
            segs = []
            step = 30 * SR
            with tempfile.TemporaryDirectory() as td:
                for i in range(0, len(x), step):
                    chunk = x[i:i + step]
                    if len(chunk) < SR // 2:
                        continue
                    cp = Path(td) / f"c{i}.wav"
                    sf.write(cp, chunk, SR, subtype="PCM_16")
                    segs += transcribe_audio(cp, offset_s=i / SR)
        for s in segs:
            s["session_id"] = item_id
        hyp_path.write_text(json.dumps(
            {"item": item_id, "elapsed": round(time.time() - t0, 1),
             "duration_s": round(dur, 1), "hypothesis": segs}, ensure_ascii=False, indent=1))
        nw = sum(len(s["words"].split()) for s in segs)
        print(f"{item_id}: {nw} woorden in {time.time()-t0:.0f}s (audio {dur:.0f}s)", flush=True)
    print("TRANSCRIBE-FASE KLAAR", flush=True)


# ------------------------------------------------------------- fase 2: score

def phase_score(a: argparse.Namespace) -> None:
    from run_eval import manifest_items, score_item

    out_dir = Path(a.out_dir)
    rows = []
    for item_id, _wav, ref in manifest_items(a.manifest, a.limit):
        hyp_path = out_dir / "per_item" / f"{item_id}.hyp.json"
        if not hyp_path.exists():
            print(f"  SKIP {item_id}: geen hypothese", flush=True)
            continue
        h = json.loads(hyp_path.read_text())
        segs = h["hypothesis"]
        multi = len({s["speaker"] for s in ref}) > 1
        scores = score_item(ref, segs, multi)
        row = {"item": item_id, "scores": scores, "n_hyp_segments": len(segs),
               "elapsed": h.get("elapsed")}
        rows.append(row)
        (out_dir / "per_item" / f"{item_id}.json").write_text(
            json.dumps({**row, "hypothesis": segs}, ensure_ascii=False, indent=1))
        print(f"{item_id}: WER={scores['wer'].get('wer')}", flush=True)

    wers = [r["scores"]["wer"]["wer"] for r in rows if r["scores"]["wer"].get("wer") is not None]
    num = sum(r["scores"]["wer"]["substitutions"] + r["scores"]["wer"]["deletions"]
              + r["scores"]["wer"]["insertions"] for r in rows)
    den = sum(r["scores"]["wer"]["ref_words"] for r in rows)
    summary = {"model": MODEL_ID, "manifest": a.manifest, "items": len(rows),
               "wer": {"pooled": round(num / den, 4) if den else None,
                       "mean": round(statistics.mean(wers), 4) if wers else None,
                       "n": len(wers)}}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1))
    print("SUMMARY:", json.dumps(summary))
    print("results ->", out_dir)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True, choices=["transcribe", "score"])
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--max-single-s", type=float, default=1500.0)
    ap.add_argument("--max-new-tokens", type=int, default=8000)
    a = ap.parse_args()
    if a.phase == "transcribe":
        phase_transcribe(a)
    else:
        phase_score(a)


if __name__ == "__main__":
    main()
