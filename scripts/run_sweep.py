#!/usr/bin/env python3
"""Config sweep driver: reconfigures the running app server engine between stages
(POST /api/config), runs eval jobs per stage, restores the default config at the end.

Stages (2026-07-17 plan — tasks #12/#13):
  stability : default config, 3 repeats of realtime streaming on 2 IFADV dialogues
  ft15/ft40 : AlignAtt --frame-threshold 15 / 40
  turbo     : --model large-v3-turbo (+ FLEURS-25 point)
  sf21      : Sortformer v2.1 via --sortformer-model-path, 2 repeats

Run: venvs/wlk/bin/python scripts/run_sweep.py  (server must be up on :8080)
Log: eval/results/sweep_queue.log ; summaries in eval/results/<stamp>-wlk-stream<tag>-<manifest>/
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = "localhost:8080"
LOG = ROOT / "eval/results/sweep_queue.log"
def _base_args() -> dict:
    cfg = ROOT / "app/engine_config.json"
    if cfg.exists():
        return json.loads(cfg.read_text())
    with urllib.request.urlopen(f"http://{SERVER}/health", timeout=10) as r:
        return json.loads(r.read())["engine_args"]


BASE_ARGS = _base_args()

STAGES = [
    {"tag": "-stab", "patch": {}, "repeats": 3,
     "runs": [("wlk-stream", "ifadv_dev", 2)]},
    {"tag": "-ft15", "patch": {"--frame-threshold": 15}, "repeats": 1,
     "runs": [("wlk-stream", "ifadv_dev", 2)]},
    {"tag": "-ft40", "patch": {"--frame-threshold": 40}, "repeats": 1,
     "runs": [("wlk-stream", "ifadv_dev", 2)]},
    {"tag": "-turbo", "patch": {"--model": "large-v3-turbo"}, "repeats": 1,
     "runs": [("wlk-stream", "ifadv_dev", 2), ("wlk-stream", "fleurs_nl", 25)]},
    {"tag": "-sf21", "patch": {"--sortformer-model-path": "nvidia/diar_streaming_sortformer_4spk-v2.1"},
     "repeats": 2, "runs": [("wlk-stream", "ifadv_dev", 2)]},
]


def log(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    with LOG.open("a") as f:
        f.write(line + "\n")


def http_json(url: str, payload=None, timeout=60):
    req = urllib.request.Request(url, method="POST" if payload is not None else "GET",
                                 headers={"Content-Type": "application/json"})
    data = json.dumps(payload).encode() if payload is not None else None
    with urllib.request.urlopen(req, data=data, timeout=timeout) as r:
        return json.loads(r.read())


def mem_available_gb() -> float:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable"):
            return int(line.split()[1]) / 1e6
    return -1


def set_config(args: dict, wait_min: int = 20) -> bool:
    try:
        http_json(f"http://{SERVER}/api/config", {"engine_args": args}, timeout=wait_min * 60)
    except Exception as e:
        log(f"  config POST failed/timed out ({e}); polling health anyway")
    deadline = time.time() + wait_min * 60
    while time.time() < deadline:
        try:
            h = http_json(f"http://{SERVER}/health", timeout=10)
            if h.get("engine_ready") and h.get("engine_args") == args:
                return True
        except Exception:
            pass
        time.sleep(15)
    return False


def main() -> None:
    for stage in STAGES:
        args = {**BASE_ARGS, **stage["patch"]}
        avail = mem_available_gb()
        log(f"=== stage {stage['tag']} patch={stage['patch']} (mem available {avail:.0f} GB)")
        if 0 < avail < 20:
            log("!!! <20 GB available before stage — aborting sweep to protect the box")
            break
        if not set_config(args):
            log(f"!!! engine not ready for stage {stage['tag']} — skipping stage")
            continue
        for rep in range(stage["repeats"]):
            for method, manifest, limit in stage["runs"]:
                tag = f"{stage['tag']}-r{rep+1}"
                cmd = [str(ROOT / "venvs/wlk/bin/python"), str(ROOT / "eval/run_eval.py"),
                       "--method", method, "--manifest", manifest, "--limit", str(limit),
                       f"--tag={tag}"]
                log(f"  run: {method}{tag} {manifest} limit={limit}")
                p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=7200)
                for line in p.stdout.splitlines():
                    if line.startswith("SUMMARY") or ": WER=" in line:
                        log(f"    {line}")
                if p.returncode != 0:
                    log(f"    !!! exit {p.returncode}: {p.stderr[-300:]}")
    log("=== restoring default config")
    ok = set_config(BASE_ARGS)
    log(f"=== SWEEP DONE (default restored: {ok})")


if __name__ == "__main__":
    main()
