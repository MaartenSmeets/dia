# DATASETS.md — Dutch evaluation & fine-tuning data

All license/URL facts verified 2026-07-15 (see RESEARCH.md §5/§9.3 and the verification appendix). Download status lives in [PROGRESS.md](PROGRESS.md). Everything downloads into `data/`, which is never committed.

## Priority 1 — IFADV (conversational eval: DER + cpWER + speaker-attributed WER)

The primary "curated Dutch audio with per-speaker transcriptions" for this project.

- **What:** IFA Dialog Video corpus — 20 fully annotated dyadic (2-person) free Dutch conversations, ~15 min each (~5 h annotated of 24 recorded), ~34 native speakers.
- **Killer feature:** stereo with **subject A = left channel, subject B = right channel** → exact per-speaker ground truth, independent of any diarizer.
- **Annotations:** Praat TextGrids — `.ort` (orthographic transcript per speaker), `.awd` (word + phoneme alignment → word-level timestamps), POS tags.
- **License:** GNU **AGPL-3.0-or-later** (fine for internal evaluation; check before redistributing derivatives).
- **Download (verified live):** Zenodo record [14906857](https://zenodo.org/records/14906857)
  ```bash
  cd data/ifadv
  wget -c "https://zenodo.org/records/14906857/files/Annotations.zip?download=1" -O Annotations.zip   # ~12.5 MB
  wget -c "https://zenodo.org/records/14906857/files/AudioWAV.zip?download=1"    -O AudioWAV.zip      # ~5.8 GB
  unzip -o Annotations.zip && unzip -o AudioWAV.zip
  ```
- **Conversion:** `scripts/ifadv_to_seglst.py` → `eval/references/ifadv/*.seglst.json` + `.rttm`. Validation protocol: RESEARCH.md R10.
- **Splits:** `eval/manifests/ifadv_dev.json` (10 dialogues, tuning allowed) / `eval/manifests/ifadv_test.json` (10 dialogues, **held out**).
- Corpus homepage (background/docs): https://www.fon.hum.uva.nl/IFA-SpokenLanguageCorpora/IFADVcorpus/

## Priority 2 — clean-WER benchmarks (HF, instant)

| Dataset | HF id / config | Split(s) we use | License | Purpose |
|---|---|---|---|---|
| FLEURS Dutch | `google/fleurs` / `nl_nl` | test (~350 sent.) | CC-BY-4.0 | Literature anchor: published Dutch WERs (canary 6.12 %, Voxtral 7.07 %, parakeet 7.48 %) are FLEURS-based |
| MLS Dutch | `facebook/multilingual_librispeech` / `dutch` | test + dev (12.76 h each) | CC-BY-4.0 | Headline clean WER; train split (1554 h) = main fine-tune corpus later |
| Common Voice NL | `fsicoli/common_voice_22_0` / `nl` (ungated CC0 mirror; official Mozilla moved to Mozilla Data Collective 2025-10, HF originals froze at v17). **Note:** script-based dataset → needs the legacy loader: `venvs/cvdl` (datasets==2.21.0) + `scripts/download_cv_legacy.py`; exported 1000-utt seeded test subset (1.36 h) on 2026-07-17 | test (1000 seeded) | CC0 | Crowd-read WER; **fine-tune caution:** CV-only fine-tunes overfit read speech (RESEARCH §7.6) |
| VoxPopuli NL | `facebook/voxpopuli` / `nl` | — | CC0 | **BEWUST VERVALLEN (2026-07-23):** rol was formeel-domein-WER-anker, maar de modelkeuze is inmiddels beslist op eigen conversationele sets (COMPARISON.md Update 4), formeel/voorgelezen is al gedekt door FLEURS+MLS+CV, en VoxPopuli-NL-transcripten zijn bekend rommelig. Heropenen alleen als er een formeel-domein-use-case bijkomt. |

```python
# venvs/eval; HF_TOKEN loaded from .env
from datasets import load_dataset
fleurs = load_dataset("google/fleurs", "nl_nl", split="test")
mls    = load_dataset("facebook/multilingual_librispeech", "dutch", split="test")
cv     = load_dataset("fsicoli/common_voice_22_0", "nl", split="test")
```

## Priority 3 — CGN (requires signed license; **user action, file early**)

- **What:** Corpus Gesproken Nederlands — ~900 h spoken Dutch (NL + Flanders). Component **comp-a: ~925 face-to-face spontaneous conversations, 2–5 speakers, ~99.5 h** — the gold standard for spontaneous Dutch conversation; also prime fine-tune material.
- **Access (verified 2026-07-15, account created + order kit downloaded):** een eigen account op taalmaterialen.ivdnt.org kan downloaden: the **order kit** from the product page (`?wpdmdl=1290`) — saved to `data/cgn/order/`: `Bestelinstructies_OrderInstructions.docx` + license agreement (`Licentie-NC_CGN.docx` NL / `Licence-NC-CGN_ENG.docx` EN).
- **Process:** print the license → fill out completely → sign → email a scan to **servicedesk@ivdnt.org** (or post: Instituut voor de Nederlandse Taal, Postbus 9515, 2300 RA Leiden). INT then replies with a download link to **BP_CGN_NC.zip (~96 GB, v2.0.3)**. When the link arrives, paste it into a session and the download can be automated (disk headroom is sufficient).
- **Value assessment / commercial-license decision:** see **[CGN-VALUE.md](CGN-VALUE.md)** — the concrete experiment matrix (fine-tune with vs without CGN, scored on held-out conversational Dutch) that produces the accuracy delta the commercial license would buy, plus the proposed ≥3-cpWER-point decision rule.
- **⚠ LICENSE SCOPE (read carefully):** this is the **NON-COMMERCIAL** edition. Key terms extracted from the agreement: licensee is a *natural person*, for *personal research*; commercial use is explicitly prohibited; "New Products" developed using it may NOT be made public, sold, or provided to third parties, and the Product may not be recognizably included in them. **Consequence: NC-CGN is fine for internal evaluation/benchmarking, but fine-tuning a model that ships in a commercial product is NOT covered.** For that, use the separate commercial edition: https://hdl.handle.net/10032/tm-a2-d9 — or keep fine-tuning on CC-licensed data (MLS CC-BY-4.0, CommonVoice CC0) and use CGN strictly for evaluation.

## Priority 4 — optional / later

- **JASMIN-CGN** — children/elderly/non-native Dutch; academic license via INT; robustness testing + fine-tune diversity. Scaffolding: https://github.com/syfengcuhk/jasmin
- **"DutchMix" synthetic overlap set** — build 2–3-speaker mixtures with controllable overlap from MLS-nl `speaker_id` clips using **lhotse** (`cut.mix()` / meeting simulation; exports supervisions → RTTM directly). Use when we need controllable-overlap DER beyond IFADV. Not turnkey (LibriMix scripts are LibriSpeech-specific) — treat as a small integration task.
- **Rejected:** N-Best 2008 Dutch benchmark (ELRA channel only, no self-service download).

## Corrections data (grows over time)

Human-corrected sessions from the web app's correction mode are stored as SegLST JSONL in `data/corrections/` — `session_id`, `speaker`, `start_time`, `end_time`, `words`, plus `audio_path` + config provenance in a sidecar `meta.json`. This doubles as (a) a growing in-domain eval set and (b) future fine-tuning data. Format rationale: RESEARCH.md §6.
