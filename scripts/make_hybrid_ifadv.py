#!/usr/bin/env python3
"""Synthetische hybride-vergadering-set (taak #20, fase 1: schade kwantificeren).

IFADV is stereo met één spreker per kanaal (headsets, met wat overspraak). We bouwen per
dialoog drie mono-16k-varianten:
  clean/  — beide kanalen naveld (eerlijke mixdown; dit is de bestaande eval-conditie)
  deg/    — kanaal 2 gedegradeerd als "online/telefoon-deelnemer": 300–3400 Hz banddoorlaat,
            8 kHz-omweg (bandbreedtecrush), compressie en een roze ruisvloer; kanaal 1 blijft
            naveld. Daarna mono gemixt — het producttypische één-kanaal-invoerformaat.
  fix/    — deg + GLOBALE goedkope opknapbeurt (afftdn-ruisonderdrukking + speechnorm).
            Bewust globaal: dit meet of domme DSP al helpt; per-spreker-behandeling (het
            eigenlijke doel van taak #20) is de vervolgstap en gebruikt deze set.

Referenties blijven de gewone IFADV-referenties (zelfde spraak, zelfde tijdlijn).
Gebruik: venvs/wlk/bin/python scripts/make_hybrid_ifadv.py [--dialogues DVA1A,DVA3E,DVA6H]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEG_CHAIN = ("aresample=8000,aresample=48000,highpass=f=300,lowpass=f=3400,"
             "acompressor=threshold=-18dB:ratio=4:makeup=4dB")


def run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"ffmpeg faalde: {' '.join(cmd)}\n{r.stderr[-800:]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dialogues", default="DVA1A,DVA3E,DVA6H")
    a = ap.parse_args()
    dialogues = a.dialogues.split(",")

    for variant in ("clean", "deg", "fix"):
        (ROOT / "data/hybrid" / variant).mkdir(parents=True, exist_ok=True)

    for did in dialogues:
        src = ROOT / f"data/ifadv/AudioWAV/{did}.wav"
        if not src.exists():
            sys.exit(f"bron ontbreekt: {src}")
        clean = ROOT / f"data/hybrid/clean/{did}.wav"
        deg = ROOT / f"data/hybrid/deg/{did}.wav"
        fix = ROOT / f"data/hybrid/fix/{did}.wav"
        run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-filter_complex",
             "[0:a]pan=mono|c0=0.5*c0+0.5*c1,aresample=16000[out]",
             "-map", "[out]", "-c:a", "pcm_s16le", str(clean)])
        run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-filter_complex",
             f"[0:a]channelsplit=channel_layout=stereo[L][R];"
             f"[R]{DEG_CHAIN}[Rd];"
             f"anoisesrc=color=pink:amplitude=0.004:duration=900:sample_rate=48000[nz];"
             f"[Rd][nz]amix=inputs=2:duration=first:normalize=0[Rn];"
             f"[L][Rn]amix=inputs=2:duration=first:normalize=0,pan=mono|c0=0.5*c0,aresample=16000[out]",
             "-map", "[out]", "-c:a", "pcm_s16le", str(deg)])
        run(["ffmpeg", "-y", "-v", "error", "-i", str(deg), "-af",
             "afftdn=nr=12:nf=-30,speechnorm=e=6.25:r=0.0001:l=1", "-ar", "16000",
             "-c:a", "pcm_s16le", str(fix)])
        print(f"{did}: clean/deg/fix gebouwd", flush=True)

    for variant in ("clean", "deg", "fix"):
        man = {"dataset": "ifadv", "split": "dev-hybrid",
               "note": "synthetische hybride-vergadering-set, zie scripts/make_hybrid_ifadv.py",
               "items": [{"utt": d, "wav": f"data/hybrid/{variant}/{d}.wav", "n_speakers": 2,
                          "duration": 900.0} for d in dialogues]}
        p = ROOT / f"eval/manifests/hybrid_{variant}_dev.json"
        p.write_text(json.dumps(man, indent=1))
        print("manifest ->", p.relative_to(ROOT), flush=True)


if __name__ == "__main__":
    main()
