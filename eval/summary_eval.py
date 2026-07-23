#!/usr/bin/env python3
"""Summary-quality experiment (docs/SUMMARY-EVAL.md): does diarization make summaries
more accurate, and how much does live-vs-offline transcript quality matter?

Conditions per dialogue (transcripts reused from existing eval results — no ASR reruns):
  A  live transcript,   WITH speaker labels   (wlk-stream per_item hypothesis)
  B  live transcript,   labels stripped       (same text as A, speakers hidden)
  C  offline transcript WITH diarization      (whisper-longform+pyannote per_item)
  D  offline transcript, no diarization       (whisper-longform per_item, single stream)
  R  gold reference transcript WITH speakers  (ceiling)

Each condition -> same summarizer LLM + same prompt. Judging: the judge LLM answers
attribution questions ("who proposed/agreed/said X?") derived from the GOLD reference,
plus coverage/factuality scores, blind to condition, randomized order. Judge caveats in
the doc: same-model-judging bias; treat comparative deltas, not absolute scores.

Usage (needs SUMMARIZER_URL[/SUMMARIZER_MODEL] in .env; judge defaults to same endpoint):
  venvs/wlk/bin/python eval/summary_eval.py --manifest ifadv_dev --limit 4 \
      --live-run <dir> --offline-run <dir> --offlineD-run <dir>
Results -> eval/results/<stamp>-summary-eval-<manifest>/
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from dialib.seglst import load_seglst  # noqa: E402

BASE = os.environ.get("SUMMARIZER_URL", "").rstrip("/")
MODEL = os.environ.get("SUMMARIZER_MODEL", "default")
JUDGE_BASE = os.environ.get("JUDGE_URL", BASE).rstrip("/")
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", MODEL)

SUM_SYSTEM = ("Je bent een assistent die Nederlandse gesprekken samenvat. Geef beknopt in het "
              "Nederlands: 1) Onderwerp, 2) Kernpunten, 3) Wie heeft wat gezegd/toegezegd (indien "
              "af te leiden), 4) Afspraken/acties. Korte bullets.")


async def chat(base: str, model: str, system: str, user: str, temperature=0.2, max_tokens=700) -> str:
    import httpx
    last = None
    for attempt in range(5):  # vLLM restarts under memory pressure; ride out blips
        try:
            async with httpx.AsyncClient(timeout=300) as client:
                r = await client.post(f"{base}/chat/completions", json={
                    "model": model, "temperature": temperature, "max_tokens": max_tokens,
                    "chat_template_kwargs": {"enable_thinking": False},
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"] or ""
        except (httpx.HTTPError, KeyError) as e:
            last = e
            await asyncio.sleep(min(120, 15 * (attempt + 1)))
    raise RuntimeError(f"LLM endpoint failed after retries: {last}")


def is_degenerate(text: str) -> bool:
    """Herken ontspoorde LLM-uitvoer (bv. 700 uitroeptekens, gemeten 2026-07-23 DVA1A/E).
    De rechter is NIET robuust hiertegen (gaf 6/6 attributie + feitelijkheid 5 aan '!!!…'),
    dus dit moet vóór de beoordeling worden afgevangen."""
    import re
    t = text.strip()
    if len(t) < 40:
        return True
    words = re.findall(r"[a-zA-Zà-ÿ]{2,}", t.lower())
    if len(words) < 15:
        return True
    if len(set(words)) < max(8, len(words) // 10):  # extreem repetitief
        return True
    return False


async def summarize_robust(text: str) -> tuple[str, bool]:
    """Samenvatten met degeneratie-detectie + herkansingen op oplopende temperatuur.
    Retourneert (samenvatting, degenerate_vlag)."""
    for temp in (0.2, 0.5, 0.8):
        summary = await chat(BASE, MODEL, SUM_SYSTEM, f"Transcript:\n{text[:14000]}",
                             temperature=temp)
        if not is_degenerate(summary):
            return summary, False
        print(f"  degeneratie gedetecteerd (temp={temp}), herkansing...", flush=True)
    return summary, True


def transcript_text(segments: list[dict], with_speakers: bool) -> str:
    if with_speakers:
        return "\n".join(f"[{s['speaker']}] {s['words']}" for s in segments)
    return "\n".join(s["words"] for s in segments)


def load_hyp(run_dir: Path, item: str) -> list[dict]:
    return json.loads((run_dir / "per_item" / f"{item}.json").read_text())["hypothesis"]


async def make_questions(ref_segs: list[dict], n: int = 6) -> list[dict]:
    """Attribution questions derived from the GOLD transcript (with speakers)."""
    gold = transcript_text(ref_segs, True)[:12000]
    out = await chat(JUDGE_BASE, JUDGE_MODEL,
        "Je maakt toetsvragen over sprekerattributie in een Nederlands gesprek.",
        f"Gesprek (met sprekerlabels):\n{gold}\n\n"
        f"Maak {n} korte vragen van de vorm 'Wie zei/stelde voor/beloofde ...?' waarvan het "
        "antwoord één spreker is, plus het juiste antwoord (het sprekerlabel). "
        'Antwoord ALLEEN met JSON: [{"q": "...", "a": "spreker-label"}]', temperature=0.4)
    try:
        qs = json.loads(out[out.index("["): out.rindex("]") + 1])
        return [q for q in qs if isinstance(q, dict) and q.get("q") and q.get("a")][:n]
    except Exception:
        return []


async def judge_summary(summary: str, ref_segs: list[dict], questions: list[dict],
                        degenerate: bool = False) -> dict:
    """Label-vocabulary-free: conditions use different speaker labels (spreker1 vs spk0…),
    so the judge verifies attribution SEMANTICALLY against the gold transcript instead of
    matching label strings. Verdicts: correct | misattributed | absent.
    NB (gemeten): op gedegenereerde samenvattingen zegt de rechter overal 'correct' —
    die krijgen daarom zonder rechter-aanroep alles 'absent' + bodemscores."""
    if degenerate or is_degenerate(summary):
        return {"attribution_correct": 0, "attribution_total": len(questions),
                "misattributed": 0, "degenerate": True,
                "rubric": {"coverage": 1, "factuality": 1, "hallucinations": 0},
                "answers": [{"q": q["q"], "want": q["a"], "verdict": "absent",
                             "correct": False} for q in questions]}
    gold = transcript_text(ref_segs, True)[:12000]
    q_answers = []
    for q in questions:
        ans = await chat(JUDGE_BASE, JUDGE_MODEL,
            "Je controleert sprekerattributie in een samenvatting tegen het gouden transcript. "
            "De samenvatting kan ANDERE sprekerlabels gebruiken dan het transcript; beoordeel op "
            "inhoud (wie zegt verder wat), niet op labelnamen. Antwoord met precies één woord: "
            "'correct' (samenvatting schrijft het aan de juiste spreker toe), "
            "'fout' (aan de verkeerde spreker toegeschreven), of "
            "'afwezig' (samenvatting bevat dit niet of zonder sprekertoeschrijving).",
            f"GOUDEN TRANSCRIPT:\n{gold}\n\nSAMENVATTING:\n{summary}\n\n"
            f"Te controleren: {q['q']} (juiste antwoord volgens transcript: {q['a']})",
            temperature=0.0, max_tokens=10)
        verdict = ans.strip().lower()
        verdict = ("correct" if "correct" in verdict else
                   "misattributed" if "fout" in verdict else "absent")
        q_answers.append({"q": q["q"], "want": q["a"], "verdict": verdict,
                          "correct": verdict == "correct"})
    scored = await chat(JUDGE_BASE, JUDGE_MODEL,
        "Je beoordeelt een samenvatting tegen het gouden transcript. Antwoord ALLEEN met JSON "
        '{"coverage": 1-5, "factuality": 1-5, "hallucinations": <aantal>}.',
        f"GOUDEN TRANSCRIPT:\n{gold}\n\nSAMENVATTING:\n{summary}", temperature=0.0, max_tokens=60)
    try:
        rub = json.loads(scored[scored.index("{"): scored.rindex("}") + 1])
    except Exception:
        rub = {"coverage": None, "factuality": None, "hallucinations": None}
    n_ok = sum(1 for a in q_answers if a["correct"])
    n_mis = sum(1 for a in q_answers if a.get("verdict") == "misattributed")
    return {"attribution_correct": n_ok, "attribution_total": len(q_answers),
            "misattributed": n_mis, "rubric": rub, "answers": q_answers}


def aggregate(rows: list[dict]) -> dict:
    agg = {}
    for r in rows:
        for c, v in r["conditions"].items():
            g = agg.setdefault(c, {"attr_ok": 0, "attr_n": 0, "mis": 0,
                                   "coverage": [], "factuality": [], "halluc": []})
            g["attr_ok"] += v["attribution_correct"]; g["attr_n"] += v["attribution_total"]
            g["mis"] += v.get("misattributed", 0)
            for k, tgt in (("coverage", "coverage"), ("factuality", "factuality"), ("halluc", "hallucinations")):
                val = v["rubric"].get(tgt)
                if isinstance(val, (int, float)):
                    g[k].append(val)
    return {c: {"attribution_acc": round(g["attr_ok"] / g["attr_n"], 3) if g["attr_n"] else None,
                "misattribution_rate": round(g["mis"] / g["attr_n"], 3) if g["attr_n"] else None,
                "coverage": round(sum(g["coverage"]) / len(g["coverage"]), 2) if g["coverage"] else None,
                "factuality": round(sum(g["factuality"]) / len(g["factuality"]), 2) if g["factuality"] else None,
                "hallucinations": round(sum(g["halluc"]) / len(g["halluc"]), 2) if g["halluc"] else None}
            for c, g in agg.items()}


async def rejudge(src: Path, manifest: str) -> None:
    from run_eval import manifest_items
    refs = {item: ref for item, _, ref in manifest_items(manifest, None)}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    out_dir = ROOT / "eval/results" / f"{stamp}-summary-eval-rejudged-{manifest}"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for p in sorted(src.glob("*.json")):
        if p.name in ("config.json", "summary.json"):
            continue
        d = json.loads(p.read_text())
        item = d["item"]
        if item not in refs:
            continue
        questions = [{"q": ans["q"], "a": ans["want"]}
                     for ans in next(iter(d["conditions"].values()))["answers"]]
        result = {"item": item, "conditions": {}}
        for name, v in d["conditions"].items():
            verdict = await judge_summary(v["summary"], refs[item], questions)
            result["conditions"][name] = {"summary": v["summary"], **verdict}
            print(f"{item} {name}: attribution {verdict['attribution_correct']}/{verdict['attribution_total']} "
                  f"mis={verdict['misattributed']}", flush=True)
        rows.append(result)
        (out_dir / f"{item}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    summary = aggregate(rows)
    (out_dir / "summary.json").write_text(json.dumps({"items": len(rows), "conditions": summary,
                                                      "rejudged_from": str(src)}, indent=1))
    print("\nSUMMARY:", json.dumps(summary, indent=1))
    print("results ->", out_dir.relative_to(ROOT))


def remap_speakers_to_ref(hyp: list[dict], ref: list[dict]) -> list[dict]:
    """Hernoem hyp-sprekerlabels naar de gouden labelnamen via maximale tijdsoverlap (greedy).

    WAAROM (gemeten 2026-07-23, probe in sessielog): de rechter-LLM ankert op labelNAMEN
    ondanks de semantische instructie — zelfde samenvatting met Spk1<->Spk2 geswapt flipte
    het oordeel 'fout'->'correct'. Zonder hernoeming is attributie per item een muntworp
    (of de hyp-labelnummering toevallig met goud meeloopt). Globale hernoeming verwijdert
    alleen dat naamgevingsartefact; echte attributiefouten (beurten bij de verkeerde
    spreker) blijven gewoon fout."""
    from collections import defaultdict
    ov: dict = defaultdict(float)
    for h in hyp:
        for r in ref:
            o = min(h["end_time"], r["end_time"]) - max(h["start_time"], r["start_time"])
            if o > 0:
                ov[(h["speaker"], r["speaker"])] += o
    mapping: dict = {}
    used_ref: set = set()
    for (hs, rs), _ in sorted(ov.items(), key=lambda kv: -kv[1]):
        if hs in mapping or rs in used_ref:
            continue
        mapping[hs] = rs
        used_ref.add(rs)
    return [{**h, "speaker": mapping.get(h["speaker"], h["speaker"])} for h in hyp]


def merge_word_segs(segs: list[dict]) -> list[dict]:
    """Woord-per-segment (fusie-uitvoer van dialib/fuse.py) → sprekersbeurten, anders wordt
    het transcript één woord per regel en kapt de 14k-tekens-limiet het gesprek af."""
    turns: list[dict] = []
    for s in segs:
        if turns and turns[-1]["speaker"] == s["speaker"]:
            turns[-1]["words"] += " " + s["words"]
            turns[-1]["end_time"] = s["end_time"]
        else:
            turns.append(dict(s))
    return turns


async def add_fused(src: Path, fused_run: str, manifest: str) -> None:
    """Voeg conditie E_fused_diar (productiepad: live-beurten × offline-M2-woorden) toe aan een
    bestaande summary-eval-run, met HERGEBRUIK van de opgeslagen vragen én de bestaande
    condities/verdicts — alleen de nieuwe conditie wordt samengevat en beoordeeld."""
    from run_eval import manifest_items
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    out_dir = ROOT / "eval/results" / f"{stamp}-summary-eval-plusfused-{manifest}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "config.json").write_text(json.dumps({
        "base_run": str(src), "fused_run": fused_run, "manifest": manifest,
        "summarizer": {"url": BASE, "model": MODEL},
        "judge": {"url": JUDGE_BASE, "model": JUDGE_MODEL}, "created_utc": stamp}, indent=1))
    rows = []
    for item, _wav, ref in manifest_items(manifest, None):
        src_fp = src / f"{item}.json"
        if not src_fp.exists():
            continue
        d = json.loads(src_fp.read_text())
        questions = [{"q": ans["q"], "a": ans["want"]}
                     for ans in next(iter(d["conditions"].values()))["answers"]]
        try:
            fused = merge_word_segs(load_hyp(ROOT / fused_run, item))
        except FileNotFoundError:
            print(f"SKIP {item}: geen fusie-hypothese", flush=True)
            continue
        text = transcript_text(fused, True)
        summary, degen = await summarize_robust(text)
        verdict = await judge_summary(summary, ref, questions, degenerate=degen)
        d["conditions"]["E_fused_diar"] = {"summary": summary, **verdict}
        print(f"{item} E_fused_diar: attribution {verdict['attribution_correct']}/"
              f"{verdict['attribution_total']} rubric={verdict['rubric']}", flush=True)
        rows.append(d)
        (out_dir / f"{item}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1))
    summary = aggregate(rows)
    (out_dir / "summary.json").write_text(json.dumps({"items": len(rows), "conditions": summary}, indent=1))
    print("\nSUMMARY:", json.dumps(summary, indent=1))
    print("results ->", out_dir.relative_to(ROOT))


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--limit", type=int, default=4)
    ap.add_argument("--live-run")
    ap.add_argument("--offline-run")
    ap.add_argument("--offlineD-run")
    ap.add_argument("--rejudge", help="existing summary-eval run dir: reuse stored summaries+questions, re-judge only")
    ap.add_argument("--add-fused", help="existing summary-eval run dir: add condition E_fused_diar (needs --fused-run)")
    ap.add_argument("--fused-run", help="fusion result dir (merged-liveturns-offwords) with per_item hypotheses")
    a = ap.parse_args()
    if not BASE:
        sys.exit("SUMMARIZER_URL not set in .env")
    if a.add_fused:
        if not a.fused_run:
            sys.exit("--fused-run required with --add-fused")
        await add_fused(Path(a.add_fused), a.fused_run, a.manifest)
        return
    if a.rejudge:
        await rejudge(Path(a.rejudge), a.manifest)
        return
    if not (a.live_run and a.offline_run and a.offlineD_run):
        sys.exit("--live-run/--offline-run/--offlineD-run required (or --rejudge)")

    from run_eval import manifest_items
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    out_dir = ROOT / "eval/results" / f"{stamp}-summary-eval-{a.manifest}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "config.json").write_text(json.dumps({
        "summarizer": {"url": BASE, "model": MODEL}, "judge": {"url": JUDGE_BASE, "model": JUDGE_MODEL},
        "live_run": a.live_run, "offline_run": a.offline_run, "offlineD_run": a.offlineD_run,
        "fused_run": a.fused_run, "speaker_label_remap": "tijdsoverlap naar gouden labels (A/C/E)",
        "manifest": a.manifest, "created_utc": stamp}, indent=1))

    rows = []
    for item, wav, ref in manifest_items(a.manifest, a.limit):
        conds = {}
        try:
            live = load_hyp(ROOT / a.live_run, item)
            # gelabelde condities: labels hernoemen naar gouden namen (tijdsoverlap) —
            # zie remap_speakers_to_ref voor het gemeten rechter-artefact dat dit voorkomt
            conds["A_live_diar"] = transcript_text(remap_speakers_to_ref(live, ref), True)
            conds["B_live_nodiar"] = transcript_text(live, False)
            conds["C_off_diar"] = transcript_text(
                remap_speakers_to_ref(load_hyp(ROOT / a.offlineD_run, item), ref), True)
            conds["D_off_nodiar"] = transcript_text(load_hyp(ROOT / a.offline_run, item), False)
            conds["R_gold"] = transcript_text(ref, True)
            if a.fused_run:
                fused = merge_word_segs(load_hyp(ROOT / a.fused_run, item))
                conds["E_fused_diar"] = transcript_text(remap_speakers_to_ref(fused, ref), True)
        except FileNotFoundError as e:
            print(f"SKIP {item}: {e}")
            continue
        questions = await make_questions(ref)
        if not questions:
            print(f"SKIP {item}: question generation failed")
            continue
        result = {"item": item, "conditions": {}}
        order = list(conds.items())
        random.Random(item).shuffle(order)  # blind-ish: judge never sees condition names anyway
        for name, text in order:
            summary, degen = await summarize_robust(text)
            verdict = await judge_summary(summary, ref, questions, degenerate=degen)
            result["conditions"][name] = {"summary": summary, **verdict}
            print(f"{item} {name}: attribution {verdict['attribution_correct']}/{verdict['attribution_total']} "
                  f"rubric={verdict['rubric']}", flush=True)
        rows.append(result)
        (out_dir / f"{item}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))

    summary = aggregate(rows)
    (out_dir / "summary.json").write_text(json.dumps({"items": len(rows), "conditions": summary}, indent=1))
    print("\nSUMMARY:", json.dumps(summary, indent=1))
    print("results ->", out_dir.relative_to(ROOT))


if __name__ == "__main__":
    asyncio.run(main())
