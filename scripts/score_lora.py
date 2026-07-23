#!/usr/bin/env python3
"""Score a LoRA adapter (or the bare HF turbo baseline) offline on a manifest.

Same scorer for M0/M1/M2/M3 => internally consistent deltas (HF chunked long-form,
which differs from openai-whisper sequential — do not mix the two when comparing).

  venvs/wlk/bin/python scripts/score_lora.py --adapter models/lora/M2-cgn --manifest cgn_a_dev --tag M2
  venvs/wlk/bin/python scripts/score_lora.py --adapter none --manifest cgn_a_dev --tag M0hf

Results: eval/results/<stamp>-lora-<tag>-<manifest>/ (attribute_with_pyannote-compatible).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))

import torch  # noqa: E402

from run_eval import manifest_items, score_item  # noqa: E402

MODEL_ID = "openai/whisper-large-v3-turbo"


def load_pipeline(adapter: str):
    from transformers import WhisperForConditionalGeneration, WhisperProcessor, pipeline
    processor = WhisperProcessor.from_pretrained(MODEL_ID)
    model = WhisperForConditionalGeneration.from_pretrained(MODEL_ID, dtype=torch.bfloat16)
    if adapter and adapter != "none":
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, str(ROOT / adapter))
        model = model.merge_and_unload()
    # batch_size 4: word-timestamp alignment buffers at batch 8 ballooned unified
    # memory to near-OOM (incident 2026-07-22); measured footprint ≈9 GB/slot →
    # 4 slots ≈ 40 GB fits beside qwen(47)+app(6) with margin; chain memguard backstops.
    return pipeline("automatic-speech-recognition", model=model,
                    tokenizer=processor.tokenizer, feature_extractor=processor.feature_extractor,
                    device="cuda", torch_dtype=torch.bfloat16,
                    chunk_length_s=30, batch_size=4)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", required=True, help="peft dir relative to repo root, or 'none'")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()

    asr = load_pipeline(a.adapter)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    out_dir = ROOT / "eval/results" / f"{stamp}-lora-{a.tag}-{a.manifest}"
    (out_dir / "per_item").mkdir(parents=True, exist_ok=True)
    # method recorded as whisper-longform for attribute_with_pyannote compatibility
    (out_dir / "config.json").write_text(json.dumps({
        "method": "whisper-longform", "scorer": "hf-chunked", "lora_adapter": a.adapter,
        "base_model": MODEL_ID, "manifest": a.manifest, "created_utc": stamp}, indent=1))

    rows = []
    for item_id, wav, ref in manifest_items(a.manifest, a.limit):
        multi = len({s["speaker"] for s in ref}) > 1
        t0 = time.time()
        # word-level timestamps: required so downstream speaker attribution (pyannote
        # max-overlap) operates per word — 30 s chunk granularity destroys cpWER/DER.
        out = asr(str(wav), return_timestamps="word",
                  generate_kwargs={"language": "dutch", "task": "transcribe"})
        hyp = []
        for ch in out.get("chunks", []):
            txt = (ch.get("text") or "").strip()
            if not txt:
                continue
            ts = ch.get("timestamp") or (0.0, None)
            s0 = float(ts[0] or 0.0)
            s1 = float(ts[1]) if ts[1] is not None else s0 + 0.4
            hyp.append({"session_id": item_id, "speaker": "spk0",
                        "start_time": round(s0, 3), "end_time": round(max(s1, s0 + 0.01), 3),
                        "words": txt})
        scores = score_item(ref, hyp, multi)
        row = {"item": item_id, "scores": scores, "n_hyp_segments": len(hyp),
               "elapsed": round(time.time() - t0, 1)}
        rows.append(row)
        (out_dir / "per_item" / f"{item_id}.json").write_text(
            json.dumps({**row, "hypothesis": hyp}, ensure_ascii=False, indent=1))
        print(f"{item_id}: WER={scores['wer'].get('wer')} ({row['elapsed']}s)", flush=True)

    def pooled(kind):
        num = den = 0.0
        per = []
        for r in rows:
            s = r["scores"].get(kind) or {}
            if kind == "wer" and s.get("wer") is not None:
                num += s["substitutions"] + s["deletions"] + s["insertions"]; den += s["ref_words"]; per.append(s["wer"])
            elif kind == "cpwer" and s.get("cpwer") is not None:
                num += s["errors"]; den += s["ref_words"]; per.append(s["cpwer"])
        if not per:
            return None
        return {"pooled": round(num / den, 4) if den else None,
                "mean": round(statistics.mean(per), 4), "n": len(per)}

    summary = {"tag": a.tag, "adapter": a.adapter, "manifest": a.manifest,
               "items": len(rows), "wer": pooled("wer"), "cpwer": pooled("cpwer")}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1))
    print("SUMMARY:", json.dumps(summary))
    print("results ->", out_dir.relative_to(ROOT))


if __name__ == "__main__":
    main()
