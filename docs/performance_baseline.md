# Performance Baseline

**Date:** 2026-05-01  
**Status:** Documented expected profile — live benchmark deferred to post-deployment on reference hardware.

## 1. Reference Hardware

| Tier | GPU | RAM | Disk |
|---|---|---|---|
| Enterprise (a) | ≥1× H100/H200 (80 GB) or 2× L40S | ≥64 GB | ≥500 GB NVMe |
| Lightweight | 2× 48 GB (e.g. RTX A6000) | ≥32 GB | ≥250 GB SSD |
| CI / Dev | CPU-only OK | ≥16 GB | ≥100 GB |

## 2. Standard Workload

Defined per `docs/PHASE_8_IMPLEMENTATION_PLAYBOOK.md` §0 D5:

- 10 concurrent cases
- Mixed seed types: 4 IOC, 3 alert, 2 anomaly, 1 hunt query
- Default branch budget: `max_depth=3`, `max_branches_per_case=10`
- Tier-1 adapters enabled
- Tier-2 adapters disabled (default)

Target runtime: < 30 minutes on enterprise hardware.

## 3. Expected Metrics

### Per-Agent Latency (P50 / P95 / P99)

| Agent | P50 | P95 | P99 | Notes |
|---|---|---|---|---|
| Alpha | 200 ms | 500 ms | 800 ms | Case creation + NATS publish |
| Tracker | 2 s | 5 s | 10 s | LLM call + RAG + telemetry queries |
| Flanker | 3 s | 8 s | 15 s | LLM call + lateral pivots + branch creation |
| Closer | 1 s | 3 s | 6 s | LLM call + verdict synthesis |
| Scribe | 50 ms | 100 ms | 200 ms | Ledger write (non-LLM) |

### Throughput

| Metric | Target | Notes |
|---|---|---|
| Cases completed per hour | ≥20 | End-to-end (seed → review) |
| Ledger writes per second | ≥50 | Scribe throughput |
| RAG queries per second | ≥10 | Haystack + pgvector |
| NATS messages per second | ≥100 | Producer + consumer combined |

### Resource Usage

| Resource | Expected | Peak |
|---|---|---|
| GPU VRAM | ~60 GB (Llama 3.3 70B FP8) | ~72 GB with large context |
| GPU Utilisation | 60–80 % | 95 % during concurrent cases |
| System RAM | 32–48 GB | 64 GB under load |
| Postgres | 512 MB–1 GB | 2 GB with large pgvector indexes |
| NATS JetStream | 256 MB | 512 MB with deep streams |
| OTel Collector | 256 MB | 512 MB with always-on sampling |

## 4. Benchmark Reproduction Steps

1. Deploy on reference hardware with `DEPLOYMENT_MODE=on_prem_connected`.
2. Ensure Ollama model `llama3.3:70b` is loaded and warm.
3. Seed the system with the standard workload (10 concurrent cases).
4. Collect metrics from:
   - MLflow dashboard (`full` profile)
   - NATS monitoring (`:8222/jsz`)
   - Postgres query logs (slow-query threshold 1 s)
   - `docker stats` for container resource usage
5. Run `verify_chain()` on all cases post-completion.
6. Record P50/P95/P99 latencies per agent, throughput, and resource peaks.

## 5. Known Bottlenecks

- **LLM inference latency** dominates end-to-end case time (Tracker + Flanker).
- **pgvector index size** grows with learning-queue ingestion; monitor disk.
- **NATS consumer lag** spikes if a single consumer stalls; scale replicas.
- **OTel span volume** can overwhelm the collector if always-on sampling is enabled for RAG and adapter tool calls. Use 10 % probabilistic sampling for those spans.

## 6. Scaling Headroom

| Bottleneck | Horizontal | Vertical |
|---|---|---|
| LLM inference | Multiple Ollama instances + LB | Larger GPU / FP8 |
| Postgres reads | Read replicas | Larger instance / NVMe |
| NATS consumers | Consumer group replicas | Larger NATS server |
| OTel Collector | Multiple collectors with LB | More RAM / sampling tuning |
