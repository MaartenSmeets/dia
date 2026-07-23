"""SegLST helpers: the project's canonical transcript format (meeteval-compatible).

A SegLST record: {"session_id", "speaker", "start_time", "end_time", "words"}.
Also converts WhisperLiveKit FrontData `lines` into SegLST.
"""
from __future__ import annotations

import json
from pathlib import Path


def parse_wlk_time(t) -> float:
    """WLK line times arrive either as floats/None or 'H:MM:SS(.cc)' strings."""
    if t is None:
        return 0.0
    if isinstance(t, (int, float)):
        return float(t)
    parts = str(t).split(":")
    parts = [float(p) for p in parts]
    while len(parts) < 3:
        parts.insert(0, 0.0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def wlk_lines_to_seglst(lines: list[dict], session_id: str) -> list[dict]:
    """Convert WLK FrontData['lines'] to SegLST. Silence (-2) and empty lines dropped."""
    out = []
    for line in lines:
        spk = line.get("speaker")
        text = (line.get("text") or "").strip()
        if spk == -2 or not text:
            continue
        spk_label = f"spk{spk}" if isinstance(spk, int) and spk >= 0 else "spk?"
        start = round(parse_wlk_time(line.get("start")), 3)
        end = round(parse_wlk_time(line.get("end")), 3)
        if end <= start:  # WLK occasionally emits inverted/zero spans; clamp (meeteval rejects them)
            end = start + 0.01
        out.append({
            "session_id": session_id,
            "speaker": spk_label,
            "start_time": start,
            "end_time": end,
            "words": text,
        })
    return out


def load_seglst(path: str | Path) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_seglst(segments: list[dict], path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(segments, ensure_ascii=False, indent=1), encoding="utf-8")


def seglst_to_rttm(segments: list[dict]) -> str:
    lines = []
    for s in sorted(segments, key=lambda x: x["start_time"]):
        dur = max(0.0, s["end_time"] - s["start_time"])
        lines.append(f"SPEAKER {s['session_id']} 1 {s['start_time']:.3f} {dur:.3f} "
                     f"<NA> <NA> {s['speaker']} <NA> <NA>")
    return "\n".join(lines) + "\n"
