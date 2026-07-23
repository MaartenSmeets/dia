#!/usr/bin/env python3
"""Re-score existing eval results (per_item hypotheses) without re-running the pipeline.
Use after normalizer/metrics changes. Usage:
  venvs/wlk/bin/python eval/rescore.py eval/results/<run-dir>
Rewrites scores in per_item/*.json and summary.json in place.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from run_eval import score_item  # noqa: E402  (same directory)
from dialib.seglst import load_seglst  # noqa: E402


def main(run_dir: Path) -> None:
    cfg = json.loads((run_dir / "config.json").read_text())
    manifest = cfg["manifest"]
    rows = []
    for p in sorted((run_dir / "per_item").glob("*.json")):
        d = json.loads(p.read_text())
        item = d["item"]
        if manifest.startswith("ifadv"):
            ref = load_seglst(ROOT / f"eval/references/ifadv/{item}.seglst.json")
        else:
            refs = load_seglst(ROOT / f"eval/references/{manifest}.seglst.json")
            ref = [s for s in refs if s["session_id"] == item]
        multi = len({s["speaker"] for s in ref}) > 1
        d["scores"] = score_item(ref, d["hypothesis"], multi)
        p.write_text(json.dumps(d, ensure_ascii=False, indent=1))
        rows.append(d)
        s = d["scores"]
        print(f"{item}: WER={s['wer'].get('wer')} cpWER={s.get('cpwer', {}).get('cpwer')} "
              f"DER={s.get('der', {}).get('der')}")

    def pooled(kind):
        num = den = 0.0
        per = []
        for r in rows:
            s = r["scores"].get(kind) or {}
            if kind == "wer" and s.get("wer") is not None:
                num += s["substitutions"] + s["deletions"] + s["insertions"]; den += s["ref_words"]; per.append(s["wer"])
            elif kind == "cpwer" and s.get("cpwer") is not None:
                num += s["errors"]; den += s["ref_words"]; per.append(s["cpwer"])
            elif kind == "der" and s.get("der") is not None:
                e = (s["missed_speaker_time"] or 0) + (s["falarm_speaker_time"] or 0) + (s["speaker_error_time"] or 0)
                num += e; den += (s["scored_speaker_time"] or 0); per.append(s["der"])
        if not per:
            return None
        return {"pooled": round(num / den, 4) if den else None,
                "mean": round(statistics.mean(per), 4), "n": len(per)}

    summary = {"method": cfg["method"], "manifest": manifest, "items": len(rows),
               "wer": pooled("wer"), "cpwer": pooled("cpwer"), "der": pooled("der"),
               "rescored": True}
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=1))
    print("SUMMARY:", json.dumps(summary))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
