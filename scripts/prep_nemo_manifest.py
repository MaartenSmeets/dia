#!/usr/bin/env python3
"""Zet onze fine-tune-windowmanifests (data/ft/*.jsonl) om naar NeMo-manifests,
zodat de winnende NeMo-basis (canary/parakeet) op dezelfde CGN-data gefinetuned kan
worden als de M-serie (identieke data → eerlijke vergelijking van basismodellen).

NeMo-regelformaat (AED/canary):
  {"audio_filepath": ..., "offset": s, "duration": s, "text": ...,
   "source_lang": "nl", "target_lang": "nl", "pnc": "yes", "answer": <text>, "taskname": "asr"}

  venvs/wlk/bin/python scripts/prep_nemo_manifest.py data/ft/cgn_a_train.jsonl data/ft/nemo_cgn_a_train.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    n = 0
    with (ROOT / dst if not dst.is_absolute() else dst).open("w", encoding="utf-8") as out:
        for line in (ROOT / src if not src.is_absolute() else src).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            it = json.loads(line)
            dur = round(float(it["end"]) - float(it["start"]), 3)
            out.write(json.dumps({
                "audio_filepath": str((ROOT / it["wav"]).resolve()),
                "offset": float(it["start"]),
                "duration": dur,
                "text": it["text"],
                "answer": it["text"],
                "source_lang": "nl", "target_lang": "nl",
                "pnc": "yes", "taskname": "asr",
            }, ensure_ascii=False) + "\n")
            n += 1
    print(f"{n} regels -> {dst}")


if __name__ == "__main__":
    main()
