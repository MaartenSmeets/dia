#!/usr/bin/env python3
"""LoRA fine-tune whisper-large-v3-turbo on window manifests (M-series, CGN-VALUE.md).

Identical recipe for every M-variant; ONLY --data differs. Runs in venvs/wlk.

  venvs/wlk/bin/python scripts/train_lora.py \
      --data data/ft/cgn_a_train.jsonl [--data more.jsonl ...] \
      --out models/lora/M2-cgn --steps 1500 [--batch 8] [--accum 2] [--lr 1e-4]

Manifest lines: {"wav": rel path, "start": s, "end": s, "text": target}
Saves adapter to <out>/ (peft format; WLK can serve it via --lora-path) + train_log.jsonl.
"""
from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from torch.utils.data import DataLoader, Dataset

ROOT = Path(__file__).resolve().parent.parent
MODEL_ID = "openai/whisper-large-v3-turbo"
SR = 16000


class WindowDataset(Dataset):
    def __init__(self, manifests: list[str], processor, seed: int = 7):
        self.items = []
        for m in manifests:
            for line in (ROOT / m).read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self.items.append(json.loads(line))
        random.Random(seed).shuffle(self.items)
        self.processor = processor

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        it = self.items[i]
        path = ROOT / it["wav"]
        start, end = float(it["start"]), float(it["end"])
        with sf.SoundFile(path) as f:
            sr = f.samplerate
            f.seek(int(start * sr))
            x = f.read(int((end - start) * sr), dtype="float32", always_2d=True).mean(axis=1)
        if sr != SR:  # CGN/exports are all 16k; guard anyway
            idx = (np.arange(int(len(x) * SR / sr)) * (sr / SR)).astype(np.int64)
            x = x[np.clip(idx, 0, len(x) - 1)]
        feats = self.processor.feature_extractor(x, sampling_rate=SR,
                                                 return_tensors="pt").input_features[0]
        labels = self.processor.tokenizer(it["text"], max_length=440,
                                          truncation=True).input_ids
        return {"input_features": feats, "labels": torch.tensor(labels)}


def collate(batch, pad_id):
    feats = torch.stack([b["input_features"] for b in batch])
    maxlen = max(len(b["labels"]) for b in batch)
    labels = torch.full((len(batch), maxlen), -100, dtype=torch.long)
    for i, b in enumerate(batch):
        labels[i, : len(b["labels"])] = b["labels"]
    return {"input_features": feats, "labels": labels}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", action="append", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--steps", type=int, default=1500)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--accum", type=int, default=2)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--warmup", type=int, default=50)
    ap.add_argument("--save-every", type=int, default=500)
    a = ap.parse_args()
    out_dir = ROOT / a.out
    out_dir.mkdir(parents=True, exist_ok=True)
    log = (out_dir / "train_log.jsonl").open("a")

    from peft import LoraConfig, get_peft_model
    from transformers import WhisperForConditionalGeneration, WhisperProcessor

    processor = WhisperProcessor.from_pretrained(MODEL_ID, language="dutch", task="transcribe")
    model = WhisperForConditionalGeneration.from_pretrained(MODEL_ID, dtype=torch.bfloat16)
    model.config.forced_decoder_ids = None
    model.generation_config.language = "dutch"
    # non-reentrant checkpointing: reentrant mode double-backwards under autocast+LoRA here
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.enable_input_require_grads()
    lcfg = LoraConfig(r=32, lora_alpha=64, lora_dropout=0.05, bias="none",
                      target_modules=["q_proj", "v_proj", "k_proj", "out_proj"])
    model = get_peft_model(model, lcfg)
    model.print_trainable_parameters()
    model.to("cuda")

    ds = WindowDataset(a.data, processor)
    print(f"dataset: {len(ds)} windows from {a.data}")
    # num_workers=0: forked workers wedged on this platform (bring-up hang, 2026-07-21)
    dl = DataLoader(ds, batch_size=a.batch, shuffle=True, num_workers=0,
                    collate_fn=lambda b: collate(b, processor.tokenizer.pad_token_id),
                    drop_last=True)
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=a.lr)
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: min(1.0, s / max(a.warmup, 1)) * max(0.0, 1 - s / a.steps))

    model.train()
    step, t0, run_loss = 0, time.time(), 0.0
    done = False
    while not done:
        for batch in dl:
            batch = {k: v.to("cuda") for k, v in batch.items()}
            with torch.autocast("cuda", dtype=torch.bfloat16):
                loss = model(**batch).loss / a.accum
            loss.backward()
            run_loss += loss.item()
            if (step + 1) % a.accum == 0:
                torch.nn.utils.clip_grad_norm_(
                    [p for p in model.parameters() if p.requires_grad], 1.0)
                opt.step()
                sched.step()
                opt.zero_grad(set_to_none=True)
            step += 1
            if step % (20 * a.accum) == 0:
                rec = {"step": step // a.accum, "loss": round(run_loss / (20), 4),
                       "sec_per_opt_step": round((time.time() - t0) / 20 * a.accum / a.accum, 2),
                       "elapsed_min": round((time.time() - t0) / 60, 1)}
                run_loss = 0.0
                print(json.dumps(rec), flush=True)
                log.write(json.dumps(rec) + "\n")
                log.flush()
            if (step // a.accum) >= a.steps:
                done = True
                break
            if step % (a.save_every * a.accum) == 0:
                model.save_pretrained(out_dir / f"ckpt-{step // a.accum}")
    model.save_pretrained(out_dir)
    print(f"TRAIN_DONE {a.out} opt_steps={step // a.accum} "
          f"elapsed={{:.1f}}min".format((time.time() - t0) / 60))


if __name__ == "__main__":
    main()
