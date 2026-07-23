#!/usr/bin/env python3
"""Evaluation harness: run a METHOD over a MANIFEST, score, and store results.

Methods:
  wlk-stream    stream WAVs through the running app server WebSocket at REALTIME pace
                (true streaming behavior incl. diarization) — requires app on --server
  wlk-fast      same pipeline, unpaced (the "after-the-fact upload" mode)
  whisper-longform  offline OpenAI whisper large-v3 sequential long-form decode
                (language=nl, no diarization) — the classic baseline
  whisper-longform+pyannote  same ASR + pyannote community-1 offline diarization,
                words assigned to diarization segments by max overlap (needs HF gating accepted)

Usage (venvs/wlk python, from repo root):
  venvs/wlk/bin/python eval/run_eval.py --method wlk-stream --manifest ifadv_dev --limit 2
  venvs/wlk/bin/python eval/run_eval.py --method whisper-longform --manifest fleurs_nl --limit 100

Results -> eval/results/<UTC date>-<method>-<manifest>/ {config.json, per_item/*.json, summary.json}
Scoring: dialib.metrics (WER always; cpWER+DER when the reference has >1 speaker).
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

from dialib import metrics  # noqa: E402
from dialib.seglst import load_seglst  # noqa: E402

SR = 16000
BYTES_PER_SEC = SR * 2
CHUNK_SEC = 0.25


# ------------------------------------------------------------------ manifest

def manifest_items(name: str, limit: int | None):
    """Yield (item_id, wav_path, reference_seglst)."""
    if name.startswith("ifadv"):
        m = json.loads((ROOT / f"eval/manifests/{name}.json").read_text())
        for did in m["dialogues"][:limit]:
            hits = sorted((ROOT / "data/ifadv").rglob(f"{did}*.wav"))
            if not hits:
                print(f"  SKIP {did}: audio not found")
                continue
            yield did, hits[0], load_seglst(ROOT / f"eval/references/ifadv/{did}.seglst.json")
    elif name.startswith(("cgn", "hybrid")):  # hybrid_* = synthetische set met ifadv-referenties
        m = json.loads((ROOT / f"eval/manifests/{name}.json").read_text())
        for it in m["items"][:limit]:
            yield it["utt"], ROOT / it["wav"], load_seglst(
                ROOT / f"eval/references/{m['dataset']}/{it['utt']}.seglst.json")
    else:
        m = json.loads((ROOT / f"eval/manifests/{name}_test.json").read_text())
        refs = {s["session_id"]: s for s in load_seglst(ROOT / f"eval/references/{name}.seglst.json")}
        for it in m["items"][:limit]:
            yield it["utt"], ROOT / it["wav"], [refs[it["utt"]]]


# ------------------------------------------------------------------ methods

async def decode_pcm(wav: Path) -> bytes:
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-i", str(wav), "-f", "s16le", "-ar", str(SR), "-ac", "1",
        "-loglevel", "error", "pipe:1", stdout=asyncio.subprocess.PIPE)
    out, _ = await proc.communicate()
    return out


async def run_wlk_replay(item_source: str, server: str, speed: float) -> tuple[list[dict], dict]:
    """Use the app server's replay command (server resolves + feeds audio)."""
    import websockets
    hyp, info = [], {"results": 0}
    t0 = time.time()
    async with websockets.connect(f"ws://{server}/asr", max_size=16 * 2**20,
                                  open_timeout=30, close_timeout=30) as ws:
        await ws.send(json.dumps({"type": "replay", "source": item_source, "speed": speed}))
        async for raw in ws:
            m = json.loads(raw)
            if m.get("type") == "update":
                info["results"] += 1
            elif m.get("type") == "session_saved":
                hyp = m["segments"]
                info["session_id"] = m["session_id"]
            elif m.get("type") == "ready_to_stop":
                break
    info["wall_sec"] = round(time.time() - t0, 2)
    return hyp, info


_WHISPER_MODEL = None
_WHISPER_MODEL_NAME = None


def run_whisper_longform(wav: Path, language: str = "nl", model_name: str = "large-v3") -> tuple[list[dict], dict]:
    """Offline sequential long-form decode with openai-whisper (no diarization)."""
    global _WHISPER_MODEL, _WHISPER_MODEL_NAME
    import whisper
    if _WHISPER_MODEL is None or _WHISPER_MODEL_NAME != model_name:
        _WHISPER_MODEL = whisper.load_model(model_name)
        _WHISPER_MODEL_NAME = model_name
    t0 = time.time()
    result = _WHISPER_MODEL.transcribe(str(wav), language=language, verbose=None)
    wall = time.time() - t0
    segs = [{"session_id": wav.stem, "speaker": "spk0",
             "start_time": round(s["start"], 3), "end_time": round(s["end"], 3),
             "words": s["text"].strip()} for s in result["segments"] if s["text"].strip()]
    return segs, {"wall_sec": round(wall, 2)}


_PYANNOTE = None


def run_pyannote(wav: Path) -> list[tuple[float, float, str]]:
    global _PYANNOTE
    import os

    import torch
    from pyannote.audio import Pipeline
    if _PYANNOTE is None:
        _PYANNOTE = Pipeline.from_pretrained("pyannote/speaker-diarization-community-1",
                                             token=os.environ.get("HF_TOKEN"))
        _PYANNOTE.to(torch.device("cuda"))
    dia = _PYANNOTE(str(wav))
    ann = getattr(dia, "speaker_diarization", dia)  # community-1 returns an object with both
    return [(t.start, t.end, spk) for t, _, spk in ann.itertracks(yield_label=True)]


def assign_speakers(asr_segs: list[dict], turns: list[tuple[float, float, str]]) -> list[dict]:
    """Assign each ASR segment the diarization speaker with max temporal overlap."""
    out = []
    for s in asr_segs:
        best, best_ov = "spk0", 0.0
        for a, b, spk in turns:
            ov = min(s["end_time"], b) - max(s["start_time"], a)
            if ov > best_ov:
                best_ov, best = ov, spk
        out.append({**s, "speaker": best})
    return out


# ------------------------------------------------------------------ scoring/run

def score_item(ref: list[dict], hyp: list[dict], multispeaker: bool) -> dict:
    sid = ref[0]["session_id"]
    for h in hyp:
        h["session_id"] = sid
    out = {"wer": metrics.wer(ref, hyp)}
    if multispeaker:
        try:
            out["cpwer"] = metrics.cpwer(ref, hyp)
        except Exception as e:
            out["cpwer"] = {"error": str(e)}
        try:
            out["der"] = metrics.der(ref, hyp)
        except Exception as e:
            out["der"] = {"error": str(e)}
    return out


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--method", required=True,
                    choices=["wlk-stream", "wlk-fast", "whisper-longform", "whisper-longform+pyannote"])
    ap.add_argument("--manifest", required=True,
                    help="ifadv_dev | ifadv_test | fleurs_nl | mls_nl | cv22_nl")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--server", default="localhost:8080")
    ap.add_argument("--tag", default="")
    ap.add_argument("--whisper-model", default="large-v3",
                    help="model for whisper-longform methods (large-v3 | large-v3-turbo | ...)")
    args = ap.parse_args()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    out_dir = ROOT / "eval/results" / f"{stamp}-{args.method}{args.tag}-{args.manifest}"
    (out_dir / "per_item").mkdir(parents=True, exist_ok=True)

    engine_args = None
    if args.method.startswith("wlk"):
        import urllib.request
        with urllib.request.urlopen(f"http://{args.server}/health", timeout=10) as r:
            h = json.loads(r.read())
        if not h.get("engine_ready"):
            sys.exit("app server engine not ready")
        engine_args = h.get("engine_args")

    (out_dir / "config.json").write_text(json.dumps({
        "method": args.method, "manifest": args.manifest, "limit": args.limit,
        "engine_args": engine_args, "created_utc": stamp,
        "normalizer_version": metrics.NORMALIZER_VERSION}, indent=1))

    rows = []
    for item_id, wav, ref in manifest_items(args.manifest, args.limit):
        multi = len({s["speaker"] for s in ref}) > 1
        t0 = time.time()
        def eval_source(item):
            if args.manifest.startswith("ifadv"):
                return f"eval:ifadv/{item}"
            if args.manifest.startswith("cgn_a"):
                return f"eval:cgn_a/{item}"
            return f"eval:{args.manifest}/{item}"

        if args.method == "wlk-stream":
            hyp, info = await run_wlk_replay(eval_source(item_id), args.server, speed=1.0)
        elif args.method == "wlk-fast":
            hyp, info = await run_wlk_replay(eval_source(item_id), args.server, speed=0)
        elif args.method == "whisper-longform":
            hyp, info = await asyncio.to_thread(run_whisper_longform, wav, "nl", args.whisper_model)
        else:  # whisper-longform+pyannote
            hyp, info = await asyncio.to_thread(run_whisper_longform, wav, "nl", args.whisper_model)
            turns = await asyncio.to_thread(run_pyannote, wav)
            hyp = assign_speakers(hyp, turns)
        scores = score_item(ref, hyp, multi)
        row = {"item": item_id, "scores": scores, "info": info,
               "n_hyp_segments": len(hyp), "elapsed": round(time.time() - t0, 1)}
        rows.append(row)
        (out_dir / "per_item" / f"{item_id}.json").write_text(
            json.dumps({**row, "hypothesis": hyp}, ensure_ascii=False, indent=1))
        wer = scores["wer"].get("wer")
        cp = scores.get("cpwer", {}).get("cpwer") if multi else None
        d = scores.get("der", {}).get("der") if multi else None
        print(f"{item_id}: WER={wer} cpWER={cp} DER={d} ({row['elapsed']}s)", flush=True)

    def pooled(kind: str):
        """Pooled rate over all items (total errors / total reference mass)."""
        num = den = 0.0
        per_item = []
        for r in rows:
            s = r["scores"].get(kind) or {}
            if kind == "wer" and s.get("wer") is not None:
                e = s["substitutions"] + s["deletions"] + s["insertions"]
                num, den = num + e, den + s["ref_words"]
                per_item.append(s["wer"])
            elif kind == "cpwer" and s.get("cpwer") is not None:
                num, den = num + s["errors"], den + s["ref_words"]
                per_item.append(s["cpwer"])
            elif kind == "der" and s.get("der") is not None:
                e = (s["missed_speaker_time"] or 0) + (s["falarm_speaker_time"] or 0) + (s["speaker_error_time"] or 0)
                num, den = num + e, den + (s["scored_speaker_time"] or 0)
                per_item.append(s["der"])
        if not per_item:
            return None
        return {"pooled": round(num / den, 4) if den else None,
                "mean": round(statistics.mean(per_item), 4), "n": len(per_item)}

    summary = {"method": args.method, "manifest": args.manifest, "items": len(rows),
               "wer": pooled("wer"), "cpwer": pooled("cpwer"), "der": pooled("der")}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1))
    print("\nSUMMARY:", json.dumps(summary))
    print("results ->", out_dir.relative_to(ROOT))


if __name__ == "__main__":
    asyncio.run(main())
