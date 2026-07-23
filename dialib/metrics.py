"""Scoring: WER (jiwer), cpWER (meeteval), DER (meeteval md-eval wrapper).

All text passes through dialib.normalizer.normalize_dutch before WER/cpWER.
DER uses collar 0.25 s, all regions (with overlap) — see docs/EVALUATION.md.
"""
from __future__ import annotations

import jiwer
import meeteval
from meeteval.io.seglst import SegLST

from .normalizer import NORMALIZER_VERSION, normalize_dutch

DER_COLLAR = 0.25


def _f(x):
    """JSON-safe float (md-eval yields Decimal)."""
    return None if x is None else round(float(x), 4)


def _to_meeteval(segments: list[dict], normalize: bool = True) -> SegLST:
    recs = []
    for s in segments:
        words = normalize_dutch(s["words"]) if normalize else s["words"]
        start, end = float(s["start_time"]), float(s["end_time"])
        if end <= start:  # defensive: meeteval rejects inverted/empty intervals
            end = start + 0.01
        recs.append({
            "session_id": s["session_id"],
            "speaker": s["speaker"],
            "start_time": start,
            "end_time": end,
            "words": words,
        })
    return SegLST(recs)


def wer(reference: list[dict], hypothesis: list[dict]) -> dict:
    """Speaker-agnostic WER over concatenated (time-sorted) text."""
    ref = " ".join(normalize_dutch(s["words"]) for s in sorted(reference, key=lambda x: x["start_time"]))
    hyp = " ".join(normalize_dutch(s["words"]) for s in sorted(hypothesis, key=lambda x: x["start_time"]))
    ref, hyp = ref.strip(), hyp.strip()
    if not ref:
        return {"wer": None, "note": "empty reference after normalization"}
    m = jiwer.process_words(ref, hyp)
    return {
        "wer": round(m.wer, 4),
        "substitutions": m.substitutions, "deletions": m.deletions,
        "insertions": m.insertions, "hits": m.hits,
        "ref_words": m.hits + m.substitutions + m.deletions,
        "normalizer_version": NORMALIZER_VERSION,
    }


def _combine(result):
    """meeteval returns {session_id: ErrorRate}; combine into one ErrorRate."""
    if not isinstance(result, dict):
        return result
    vals = list(result.values())
    if len(vals) == 1:
        return vals[0]
    from meeteval.wer import combine_error_rates
    return combine_error_rates(*vals)


def cpwer(reference: list[dict], hypothesis: list[dict]) -> dict:
    """Concatenated-minimum-permutation WER — the headline joint metric."""
    r = _combine(meeteval.wer.cpwer(_to_meeteval(reference), _to_meeteval(hypothesis)))
    return {
        "cpwer": _f(r.error_rate),
        "errors": r.errors, "ref_words": r.length,
        "missed_speakers": r.missed_speaker, "falarm_speakers": r.falarm_speaker,
        "normalizer_version": NORMALIZER_VERSION,
    }


def der(reference: list[dict], hypothesis: list[dict], collar: float = DER_COLLAR) -> dict:
    """Diarization error rate via meeteval's md-eval-22 wrapper (text ignored)."""
    r = meeteval.der.md_eval_22(_to_meeteval(reference, normalize=False),
                                _to_meeteval(hypothesis, normalize=False),
                                collar=collar)
    if isinstance(r, dict):
        vals = list(r.values())
        if len(vals) == 1:
            r = vals[0]
        else:  # aggregate DER over sessions by total times
            scored = sum(v.scored_speaker_time for v in vals)
            missed = sum(v.missed_speaker_time for v in vals)
            falarm = sum(v.falarm_speaker_time for v in vals)
            spkerr = sum(v.speaker_error_time for v in vals)
            return {"der": _f((missed + falarm + spkerr) / scored) if scored else None,
                    "collar": collar, "scored_speaker_time": _f(scored),
                    "missed_speaker_time": _f(missed), "falarm_speaker_time": _f(falarm),
                    "speaker_error_time": _f(spkerr)}
    return {
        "der": _f(r.error_rate),
        "collar": collar,
        "scored_speaker_time": _f(getattr(r, "scored_speaker_time", None)),
        "missed_speaker_time": _f(getattr(r, "missed_speaker_time", None)),
        "falarm_speaker_time": _f(getattr(r, "falarm_speaker_time", None)),
        "speaker_error_time": _f(getattr(r, "speaker_error_time", None)),
    }


def score_all(reference: list[dict], hypothesis: list[dict]) -> dict:
    """WER + cpWER + DER in one call; single-speaker references skip DER/cpWER speaker value."""
    out = {"wer": wer(reference, hypothesis)}
    try:
        out["cpwer"] = cpwer(reference, hypothesis)
    except Exception as e:  # cpWER can fail on degenerate hypotheses; report, don't crash
        out["cpwer"] = {"error": str(e)}
    try:
        out["der"] = der(reference, hypothesis)
    except Exception as e:
        out["der"] = {"error": str(e)}
    return out
