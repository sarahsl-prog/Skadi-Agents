# WolfPack Infrastructure Sizing Guide

## Reference deployment (Enterprise profile)

| Component | Spec | Notes |
|---|---|---|
| GPU | >=1x H100/H200 80GB | FP8/BF16 for Llama 3.3 70B Instruct |
| CPU | >=16 cores | Orchestrator + agent overhead |
| RAM | >=64 GB | Model loading + Postgres + OTel |
| Disk | >=200 GB SSD | Model storage + Postgres data |

## Lightweight fallback (dev / CI)

| Component | Spec | Notes |
|---|---|---|
| GPU | 2x 48GB (L40S, A6000) or CPU-only | Q4_K_M quantised, or llama3.2:1b for smoke |
| CPU | >=8 cores | |
| RAM | >=32 GB | |
| Disk | >=50 GB | |

## Docker Compose resource hints

The compose file sets modest memory limits suitable for dev/CI.
Increase them for the enterprise profile via `docker-compose.override.yml`.

| Service | Memory (dev) | Memory (prod) |
|---|---|---|
| postgres | 512 MB | 4 GB |
| nats | 256 MB | 1 GB |
| otel-collector | 256 MB | 512 MB |
| mlflow | 512 MB | 2 GB |
| ollama | 4 GB | 40 GB+ (model-dependent) |

## Ollama model sizing

| Model | Quant | VRAM required | Use case |
|---|---|---|---|
| llama3.2:1b | Q4_K_M | ~1 GB | CI / smoke test |
| llama3.3:70b | FP8/BF16 | ~70 GB | Production |
| llama3.3:70b | Q4_K_M | ~40 GB | Lightweight prod |