#!/usr/bin/env python3
"""Convert IFADV Praat annotations to SegLST + RTTM references.

Inputs  (data/ifadv/Annotations/):
  ort/*.ort  — utterance-level per-speaker orthographic transcripts (Praat short TextGrid)
  awd/*.stg  — word-level alignments per speaker (Praat short TextGrid)

Outputs (eval/references/ifadv/):
  <ID>.seglst.json — meeteval SegLST: [{session_id, speaker, start_time, end_time, words}]
  <ID>.rttm        — diarization reference (one SPEAKER line per utterance interval)
  <ID>.words.json  — word-level timestamps from .awd (for latency eval); sil/sp/empty excluded
plus eval/manifests/ifadv_dev.json and ifadv_test.json (fixed alternating split).

IFADV conventions preserved verbatim in `words` (handled later by the scoring normalizer):
  xxx = unintelligible, ggg = nonverbal (laugh etc.); Praat \\trigraphs are decoded to unicode here.

File-variant selection per dialogue: prefer *Corr* (latest correction) > plain _3rd_pass.ort
> *Shift* > anything else; never *ORIGINAL* / *_nodia* when an alternative exists.
(The awd/ aligned files follow the same convention, e.g. DVA12S_alignedShift6_031230.stg.)

Usage: python3 scripts/ifadv_to_seglst.py [--annotations DIR] [--out DIR] [--manifests DIR]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------- Praat parsing

# Praat backslash trigraphs (subset that occurs in Dutch orthography).
# Ref: Praat manual "Special symbols". Applied longest-first.
PRAAT_TRIGRAPHS = {
    r"\a'": "á", r"\e'": "é", r"\i'": "í", r"\o'": "ó", r"\u'": "ú",
    r'\a"': "ä", r'\e"': "ë", r'\i"': "ï", r'\o"': "ö", r'\u"': "ü",
    r"\a`": "à", r"\e`": "è", r"\i`": "ì", r"\o`": "ò", r"\u`": "ù",
    r"\a^": "â", r"\e^": "ê", r"\i^": "î", r"\o^": "ô", r"\u^": "û",
    r"\c,": "ç", r"\n~": "ñ",
    r"\A'": "Á", r"\E'": "É", r"\I'": "Í", r"\O'": "Ó", r"\U'": "Ú",
    r'\A"': "Ä", r'\E"': "Ë", r'\I"': "Ï", r'\O"': "Ö", r'\U"': "Ü",
}
_UNKNOWN_TRIGRAPH = re.compile(r"\\[a-zA-Z][\'\"`^~,]")


def decode_praat_text(s: str) -> str:
    for tri, uni in PRAAT_TRIGRAPHS.items():
        s = s.replace(tri, uni)
    leftover = _UNKNOWN_TRIGRAPH.findall(s)
    if leftover:
        print(f"  WARNING: undecoded Praat trigraph(s) {leftover!r} in: {s!r}", file=sys.stderr)
    return s


def _tokenize_short_textgrid(text: str):
    """Yield tokens of a Praat 'ooTextFile short' file: floats, ints, or quoted strings.

    Quoted strings use "" as an escaped quote and may in principle span lines.
    Bare tokens (<exists>, numbers) sit on their own lines.
    """
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
            continue
        if c == '"':
            j = i + 1
            parts = []
            while j < n:
                if text[j] == '"':
                    if j + 1 < n and text[j + 1] == '"':  # escaped quote
                        parts.append('"')
                        j += 2
                        continue
                    break
                parts.append(text[j])
                j += 1
            yield ("str", "".join(parts))
            i = j + 1
        else:
            j = i
            while j < n and not text[j].isspace():
                j += 1
            yield ("bare", text[i:j])
            i = j


def parse_short_textgrid(path: Path, text: str | None = None) -> list[dict]:
    """Return [{name, intervals: [(xmin, xmax, text), ...]}, ...] for IntervalTiers.

    Non-interval tiers (TextTier/point tiers) are skipped with a note.
    `text` overrides reading from `path` (used for gzipped CGN ort files).
    """
    raw = text if text is not None else path.read_text(encoding="utf-8", errors="replace")
    toks = list(_tokenize_short_textgrid(raw))
    # Header lines: `File type = "ooTextFile short"` / `"TextGrid"` (bare tokens precede the strings)
    str_idx = [i for i, (kind, _) in enumerate(toks) if kind == "str"]
    # Some IFADV files say just "ooTextFile" but still use the short body layout.
    assert toks[str_idx[0]][1] in ("ooTextFile short", "ooTextFile") and toks[str_idx[1]][1] == "TextGrid", \
        f"not a short TextGrid: {path}"
    pos = str_idx[1] + 1
    _xmin, _xmax = float(toks[pos][1]), float(toks[pos + 1][1])
    assert toks[pos + 2][1] == "<exists>", f"unexpected token {toks[pos+2]} in {path}"
    ntiers = int(toks[pos + 3][1])
    pos += 4
    tiers = []
    for _ in range(ntiers):
        kind = toks[pos][1]
        name = toks[pos + 1][1]
        pos += 4  # kind, name, tier xmin, tier xmax
        count = int(toks[pos][1])
        pos += 1
        if kind == "IntervalTier":
            intervals = []
            for _k in range(count):
                a = float(toks[pos][1]); b = float(toks[pos + 1][1]); t = toks[pos + 2][1]
                pos += 3
                intervals.append((a, b, t))
            tiers.append({"name": name, "intervals": intervals})
        else:  # TextTier: points are (time, text) pairs
            pos += 2 * count
            print(f"  note: skipping non-interval tier {name!r} ({kind}) in {path.name}", file=sys.stderr)
    return tiers


# ---------------------------------------------------------------- variant selection

def pick_variant(files: list[Path], prefer_tag: str | None = None) -> Path:
    """prefer_tag: when the word-alignment (awd) file carries a timeline tag like
    'Shift6', the ort variant with the SAME tag matches the audio timeline — the
    plain variant is offset (observed: DVA12S plain ort => DER ~0.65 for every
    system; Shift6 ort fixes it). Corrected (Corr) passes outrank everything."""
    def rank(p: Path) -> tuple:
        s = p.stem
        return (
            0 if "Corr" in s else
            1 if prefer_tag and prefer_tag in s else
            # Shift variants outrank plain: measured on DVA12S/DVA2C, the Shift
            # timeline matches the audio (channel-VAD agreement 0.85/0.87) while
            # the plain one is offset (0.50/0.63) => plain gives bogus DER.
            2 if "Shift" in s else
            3 if re.fullmatch(r"DVA\d+[A-Z]+_15min_3rd_pass", s) or re.fullmatch(r"DVA\d+[A-Z]+_aligned", s) else
            4 if "nodia" in s else
            5 if "ORIGINAL" in s.upper() else 4,
            s,
        )
    return sorted(files, key=rank)[0]


def dialogue_id(p: Path) -> str:
    m = re.match(r"(DVA\d+[A-Z]+)", p.name)
    if not m:
        raise ValueError(f"cannot extract dialogue id from {p.name}")
    return m.group(1)


# ---------------------------------------------------------------- conversion

SPEAKER_TIERS = ("spreker1", "spreker2")
NONWORD = {"", "sil", "sp", "_"}


def convert_dialogue(did: str, ort_path: Path, awd_path: Path | None, out_dir: Path) -> dict:
    tiers = {t["name"]: t for t in parse_short_textgrid(ort_path)}
    missing = [s for s in SPEAKER_TIERS if s not in tiers]
    if missing:
        raise ValueError(f"{did}: missing speaker tiers {missing}; found {list(tiers)}")

    seglst, rttm_lines = [], []
    for spk in SPEAKER_TIERS:
        for a, b, text in tiers[spk]["intervals"]:
            text = decode_praat_text(text.strip())
            if not text:
                continue
            seglst.append({
                "session_id": did,
                "speaker": spk,
                "start_time": round(a, 3),
                "end_time": round(b, 3),
                "words": text,
            })
            rttm_lines.append(
                f"SPEAKER {did} 1 {a:.3f} {b - a:.3f} <NA> <NA> {spk} <NA> <NA>"
            )
    seglst.sort(key=lambda s: s["start_time"])
    rttm_lines.sort(key=lambda l: float(l.split()[3]))

    words = []
    if awd_path is not None:
        # awd-bestanden bevatten DRIE tier-paren met identieke namen (spreker1/spreker2):
        # 1) orthografische woorden, 2) fonemische woordvormen (SAMPA), 3) fonen.
        # Eerste-wint — een dict-comprehension hield stilletjes de fonentier over
        # (bug gevonden 2026-07-23 bij de woordlatentie-analyse).
        wtiers: dict = {}
        for t in parse_short_textgrid(awd_path):
            wtiers.setdefault(t["name"], t)
        for spk in SPEAKER_TIERS:
            if spk not in wtiers:
                print(f"  WARNING: {did}: awd missing tier {spk}; tiers={list(wtiers)}", file=sys.stderr)
                continue
            for a, b, w in wtiers[spk]["intervals"]:
                w = decode_praat_text(w.strip())
                if w in NONWORD:
                    continue
                words.append({"speaker": spk, "word": w, "start_time": round(a, 3), "end_time": round(b, 3)})
        words.sort(key=lambda w: w["start_time"])

    (out_dir / f"{did}.seglst.json").write_text(
        json.dumps(seglst, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / f"{did}.rttm").write_text("\n".join(rttm_lines) + "\n", encoding="utf-8")
    if words:
        (out_dir / f"{did}.words.json").write_text(
            json.dumps(words, ensure_ascii=False), encoding="utf-8")

    per_spk = {s: sum(x["end_time"] - x["start_time"] for x in seglst if x["speaker"] == s)
               for s in SPEAKER_TIERS}
    return {
        "id": did,
        "ort": ort_path.name,
        "awd": awd_path.name if awd_path else None,
        "segments": len(seglst),
        "words": len(words),
        "speech_sec": {k: round(v, 1) for k, v in per_spk.items()},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    root = Path(__file__).resolve().parent.parent
    ap.add_argument("--annotations", type=Path, default=root / "data/ifadv/Annotations")
    ap.add_argument("--out", type=Path, default=root / "eval/references/ifadv")
    ap.add_argument("--manifests", type=Path, default=root / "eval/manifests")
    args = ap.parse_args()

    orts: dict[str, list[Path]] = {}
    for p in sorted((args.annotations / "ort").glob("*.ort")):
        orts.setdefault(dialogue_id(p), []).append(p)
    awds: dict[str, list[Path]] = {}
    for p in sorted((args.annotations / "awd").glob("*.stg")):
        awds.setdefault(dialogue_id(p), []).append(p)

    args.out.mkdir(parents=True, exist_ok=True)
    args.manifests.mkdir(parents=True, exist_ok=True)

    report = []
    for did in sorted(orts, key=lambda d: int(re.search(r"\d+", d).group())):
        awd = pick_variant(awds[did]) if did in awds else None
        # timeline tag from the awd filename (e.g. DVA12S_alignedShift6_031230 -> Shift6)
        tag = None
        if awd is not None:
            m = re.search(r"(Shift\d+)", awd.stem)
            tag = m.group(1) if m else None
        ort = pick_variant(orts[did], prefer_tag=tag)
        if awd is None:
            print(f"  WARNING: {did}: no awd word alignment found", file=sys.stderr)
        info = convert_dialogue(did, ort, awd, args.out)
        report.append(info)
        print(f"{did}: {info['segments']} segments, {info['words']} words, "
              f"speech {info['speech_sec']} (ort={info['ort']})")

    # Fixed alternating split by dialogue number: even index -> dev, odd -> test.
    # NOTE: IFADV has ~34 unique speakers over 20 dialogues; a strict speaker-disjoint
    # split was not attempted (documented limitation — dev/test may share speakers).
    ids = [r["id"] for r in report]
    dev, test = ids[0::2], ids[1::2]
    (args.manifests / "ifadv_dev.json").write_text(json.dumps({
        "dataset": "ifadv", "split": "dev", "dialogues": dev,
        "audio_dir": "data/ifadv", "references_dir": "eval/references/ifadv"}, indent=1))
    (args.manifests / "ifadv_test.json").write_text(json.dumps({
        "dataset": "ifadv", "split": "test", "dialogues": test, "HELD_OUT": "never tune on this",
        "audio_dir": "data/ifadv", "references_dir": "eval/references/ifadv"}, indent=1))
    (args.out / "conversion_report.json").write_text(json.dumps(report, indent=1))
    print(f"\n{len(ids)} dialogues -> {args.out}; dev={len(dev)} test={len(test)}")


if __name__ == "__main__":
    main()
