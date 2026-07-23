#!/usr/bin/env python3
"""Score een NeMo-model (canary-1b-v2 / parakeet-tdt-0.6b-v3) offline op onze manifests —
zelfde normalizer/scoring als de M-serie, zodat de cijfers 1-op-1 vergelijkbaar zijn.

  venvs/wlk/bin/python eval/score_nemo.py --model nvidia/canary-1b-v2 --manifest ifadv_dev --tag canary
Resultaten: eval/results/<stamp>-nemo-<tag>-<manifest>/
Lange audio: probeert NeMo's ingebouwde chunked long-form; valt terug op eigen 30s-vensters.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

from run_eval import manifest_items, score_item  # noqa: E402

SR = 16000


def load_model(name: str):
    import nemo.collections.asr as nemo_asr
    model = nemo_asr.models.ASRModel.from_pretrained(name)
    model = model.cuda().eval()
    return model


def read_16k_mono(wav: Path) -> np.ndarray:
    x, sr = sf.read(wav, dtype="float32", always_2d=True)
    x = x.mean(axis=1)
    if sr != SR:
        idx = (np.arange(int(len(x) * SR / sr)) * (sr / SR)).astype(np.int64)
        x = x[np.clip(idx, 0, len(x) - 1)]
    return x


def transcribe_long(model, name: str, wav: Path, window_s: float = 30.0) -> list[dict]:
    """Eigen venstering (30 s, geen overlap): robuust voor elk NeMo-model; segmenttijden grof."""
    import tempfile
    x = read_16k_mono(wav)
    segs = []
    is_canary = "canary" in name.lower()
    step = int(window_s * SR)
    with tempfile.TemporaryDirectory() as td:
        for i in range(0, len(x), step):
            chunk = x[i:i + step]
            if len(chunk) < SR // 2:
                continue
            cp = Path(td) / f"c{i}.wav"
            sf.write(cp, chunk, SR, subtype="PCM_16")
            if is_canary:
                out = model.transcribe([str(cp)], batch_size=1, verbose=False,
                                       source_lang="nl", target_lang="nl", pnc="yes")
            else:
                out = model.transcribe([str(cp)], batch_size=1, verbose=False)
            txt = out[0].text if hasattr(out[0], "text") else str(out[0])
            txt = (txt or "").strip()
            if txt:
                segs.append({"speaker": "spk0", "start_time": round(i / SR, 3),
                             "end_time": round(min((i + step), len(x)) / SR, 3), "words": txt})
    return segs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()

    model = load_model(a.model)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    out_dir = ROOT / "eval/results" / f"{stamp}-nemo-{a.tag}-{a.manifest}"
    (out_dir / "per_item").mkdir(parents=True, exist_ok=True)
    (out_dir / "config.json").write_text(json.dumps({
        "method": "nemo-offline", "model": a.model, "manifest": a.manifest,
        "windowing": "30s fixed", "created_utc": stamp}, indent=1))

    rows = []
    for item_id, wav, ref in manifest_items(a.manifest, a.limit):
        multi = len({s["speaker"] for s in ref}) > 1
        t0 = time.time()
        segs = transcribe_long(model, a.model, wav)
        for s in segs:
            s["session_id"] = item_id
        scores = score_item(ref, segs, multi)
        row = {"item": item_id, "scores": scores, "n_hyp_segments": len(segs),
               "elapsed": round(time.time() - t0, 1)}
        rows.append(row)
        (out_dir / "per_item" / f"{item_id}.json").write_text(
            json.dumps({**row, "hypothesis": segs}, ensure_ascii=False, indent=1))
        print(f"{item_id}: WER={scores['wer'].get('wer')} ({row['elapsed']}s)", flush=True)

    wers = [r["scores"]["wer"]["wer"] for r in rows if r["scores"]["wer"].get("wer") is not None]
    num = sum(r["scores"]["wer"]["substitutions"] + r["scores"]["wer"]["deletions"]
              + r["scores"]["wer"]["insertions"] for r in rows)
    den = sum(r["scores"]["wer"]["ref_words"] for r in rows)
    summary = {"model": a.model, "manifest": a.manifest, "items": len(rows),
               "wer": {"pooled": round(num / den, 4) if den else None,
                       "mean": round(statistics.mean(wers), 4) if wers else None, "n": len(wers)}}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1))
    print("SUMMARY:", json.dumps(summary))
    print("results ->", out_dir.relative_to(ROOT))


if __name__ == "__main__":
    main()
