"""Fusie van live sprekerstructuur met offline woorden — de 'definitieve versie'-methode.

Gemeten (2026-07-22, IFADV-dev n=6): fusie geeft offline-WER (21.9%) mét live-cpWER-
niveau (33.8% vs pyannote-attributie 41.6%) en beste DER. Zie eval/merge_live_offline.py
voor het experiment; deze module is de productimplementatie.
"""
from __future__ import annotations


def live_turns(live_segs: list[dict], max_gap: float = 2.0) -> list[tuple[float, float, str]]:
    """Opeenvolgende segmenten van dezelfde spreker samenvoegen tot beurten."""
    turns: list[tuple[float, float, str]] = []
    for s in sorted(live_segs, key=lambda x: x["start_time"]):
        if turns and turns[-1][2] == s["speaker"] and s["start_time"] - turns[-1][1] < max_gap:
            turns[-1] = (turns[-1][0], max(turns[-1][1], s["end_time"]), s["speaker"])
        else:
            turns.append((s["start_time"], s["end_time"], s["speaker"]))
    return turns


def fuse(offline_segs: list[dict], turns: list[tuple[float, float, str]]) -> list[dict]:
    """Ken elk offline segment/woord de live-spreker met maximale tijdsoverlap toe."""
    out = []
    for s in offline_segs:
        best, best_ov = None, 0.0
        mid = (s["start_time"] + s["end_time"]) / 2
        for a, b, spk in turns:
            ov = min(s["end_time"], b) - max(s["start_time"], a)
            if ov > best_ov:
                best_ov, best = ov, spk
        if best is None:
            best = min(turns, key=lambda t: min(abs(mid - t[0]), abs(mid - t[1])))[2] if turns else "spk0"
        out.append({**s, "speaker": best})
    return out
