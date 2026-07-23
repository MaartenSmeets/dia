# OPS-LLM.md — runbook lokaal taalmodel (samenvatter)

*Voor wie de samenvattings-LLM moet controleren, stoppen of vervangen. Conventies volgen
de scripts in `~/tmp` (docker stop = container behouden; `--rm` alleen bij herconfiguratie).*

## Gezondheidscheck (30 seconden)

```bash
curl -s -m 30 http://localhost:8000/v1/chat/completions -H "Content-Type: application/json" \
  -d '{"model":"qwen36","max_tokens":10,"temperature":0,"chat_template_kwargs":{"enable_thinking":false},"messages":[{"role":"user","content":"zeg ok"}]}'
```
- Antwoord binnen seconden → gezond.
- Timeout terwijl de GPU **druk** is (training/scoring) → verwacht gedrag op deze machine; wachten of batchwerk pauzeren.
- Timeout terwijl de GPU **rustig** is → model gedegradeerd → herstart of wissel (hieronder).

## Bekende zwakte huidige model (vlm-qwen36-moe, 35B-A3B MoE)

De NGC-vLLM draait deze MoE op een **weight-only FP4-fallback** (marlin; opstartlog waarschuwt
"no native FP4"). Gevolg: trage decode die onder elke GPU-druk als eerste verhongert; 2×
degradatie/uitval gezien (2026-07-21 crash bij hoge util; 2026-07-22 onbereikbaar in stil venster).

## Stoppen / herstarten (huidig model)

```bash
docker stop vllm-qwen36-moe      # stoppen, container blijft (snel te hervatten)
docker start vllm-qwen36-moe     # hervatten (modelload ~10 min koud)
docker restart vllm-qwen36-moe   # eerste remedie bij degradatie
docker logs --tail 50 vllm-qwen36-moe
```

## Actieve setup sinds 2026-07-22 's nachts: AEON-image + AEON 27B NVFP4 (snel pad)

**Waarom:** de officiële NGC-image is niet volledig NVFP4 — hij rekent deels in BF16
(marlin weight-only fallback) en is daardoor erg traag op de GB10 (bevestigd door
gebruiker + gemeten timeout op 10-token-request in stil venster). De lokale AEON-image
(`ghcr.io/aeon-7/aeon-vllm-ultimate:2026-07-08-v0.24.0-maxsafe`) heeft native sm_121a
NVFP4-kernels. Het officiële NVIDIA-model is **geen harde eis** (gebruiker, 2026-07-22);
we draaien daarom de configuratie die op deze image al bewezen werkte (container
`vllm-qwen36-aeon`, 2026-07): **Qwen3.6-27B-AEON NVFP4 + dflash speculatieve decode**,
aangepast aan de coexistentieregels van deze machine (util 0.40, kortere context):

```bash
docker stop vllm-qwen36-moe   # oude NGC-variant (blijft bestaan als terugvaloptie)
docker run -d --name vllm-qwen36-fast --gpus all --ipc=host \
  -p 127.0.0.1:8000:8000 -v "$HOME/models:/models:ro" --restart no \
  --entrypoint vllm \
  ghcr.io/aeon-7/aeon-vllm-ultimate:2026-07-08-v0.24.0-maxsafe \
  serve /models/Qwen3.6-27B-AEON-Ultimate-Uncensored-Multimodal-NVFP4-MTP \
    --served-model-name qwen36 --host 0.0.0.0 --port 8000 \
    --tensor-parallel-size 1 --dtype auto --quantization modelopt --trust-remote-code \
    --attention-backend TRITON_ATTN --kv-cache-dtype auto \
    --max-model-len 32768 --max-num-seqs 8 --max-num-batched-tokens 16384 \
    --gpu-memory-utilization 0.40 \
    --enable-chunked-prefill --no-enable-prefix-caching \
    --generation-config vllm --reasoning-parser qwen3 \
    --speculative-config '{"method":"dflash","model":"/models/Qwen3.6-27B-DFlash","num_speculative_tokens":12,"attention_backend":"TRITON_ATTN"}'
```
- **VALKUIL 1 (entrypoint):** de AEON-image heeft entrypoint `/bin/bash`. Zonder
  `--entrypoint vllm` voert bash het python-script `/usr/local/bin/vllm` uit →
  `import: command not found` en de container sterft direct (exitcode 2). (2026-07-22.)
- **VALKUIL 2 (prefix-caching — BEWEZEN corrupt op dit model): ALTIJD
  `--no-enable-prefix-caching`.** Met prefix-caching aan degenereerde de uitvoer op
  specifieke prompt-prefixen deterministisch tot herhaalreeksen ("!!!!…", 700 tekens),
  temperatuuronafhankelijk (0,2/0,5/0,8 alle drie garbage) — kenmerk van een vergiftigd
  KV/Mamba-cachevoorvoegsel, niet van sampling. Bewijs 2026-07-23 ~02:30: exact dezelfde
  twee trigger-prompts op een verse server zonder prefix-caching → beide schoon. De
  opstartlog waarschuwt zelf al: "Prefix caching in Mamba cache 'align' mode … is
  experimental" (Qwen3.6 = hybride Mamba-architectuur). Symptoomherkenning: identieke
  garbage bij elke temperatuur op dezelfde prompt = cache, geen modelgril.
- **VALKUIL 3 (init-timing):** de engine reserveert KV-cache bij de start binnen
  `gpu_memory_utilization`; start hij terwijl een ander GPU-proces (bv. whisper-scoring)
  geheugen bezet, dan faalt init met "No available memory for the cache blocks"
  (gezien 2026-07-23 02:04). Container starten in een GPU-stil moment en daarna pas
  batchwerk aanzetten.
- Zelfde poort (8000) en `--served-model-name qwen36` → **de app merkt niets van de wissel**.
- Restart-policy bewust `no` (reboot-veiligheid, conform ~/tmp-conventie).
- Terugdraaien: `docker stop vllm-qwen36-fast && docker start vllm-qwen36-moe`.

### Terugvalopties (alleen als de AEON-setup problemen geeft)

1. **NGC MoE terug**: `docker start vllm-qwen36-moe` (traag maar bekend gedrag).

2. Dense **nvidia/Qwen3.6-27B-NVFP4** (~16 GB, in `~/models/Qwen3.6-27B-NVFP4`) via
`scripts/start_llm_standby.sh`. Kanttekening: op de NGC-image geldt dezelfde
BF16-fallback-traagheid, en dense 27B heeft ~9× meer actieve parameters per token dan de
MoE — verwacht lage tok/s; alleen inzetten om stabiliteit boven snelheid te kiezen.
(Beter idee in dat scenario: hetzelfde officiële model op de AEON-image proberen.)

## Vuistregels op deze machine (GB10, unified memory)

- Eén groot model tegelijk naast de transcriptie-app; vLLM ALTIJD met
  `--gpu-memory-utilization ≤ 0.40` bij coexistentie (incident 2026-07-21: default 0.9 →
  OOM-kill van lopende training).
- LLM-afhankelijke batchstappen (samenvattings-evaluaties) plannen in GPU-stille vensters.
- `nvidia-smi` toont geen bruikbaar geheugen op dit platform: gebruik `free -h`.
