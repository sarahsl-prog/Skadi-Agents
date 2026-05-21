# Production Deployment Runbook

## 1. Prerequisites

### Hardware (Reference Profile)

| Tier | GPU | RAM | Disk | Notes |
|---|---|---|---|---|
| **Enterprise (a)** | ≥1× H100/H200 (80 GB) or 2× L40S | ≥64 GB | ≥500 GB NVMe | FP8/BF16 Llama 3.3 70B |
| **Lightweight** | 2× 48 GB (e.g. RTX A6000) | ≥32 GB | ≥250 GB SSD | Q4_K_M (documented alongside) |
| **CI / Dev** | CPU-only OK | ≥16 GB | ≥100 GB | `llama3.2:1b` smoke test |

### Software

- **Docker Engine** ≥ 24.0 with Compose plugin (`docker compose`)
- **Ollama** server reachable at `LLM__BASE_URL` (loopback or RFC-1918 for airgapped)
- **Python** 3.11 (for local dev / test)
- **uv** or **pip** with virtualenv (see `pyproject.toml`)

### Network

| Deployment Mode | Outbound | LLM Endpoint | Notes |
|---|---|---|---|
| `dev` | Allowed | Any (localhost, LAN, cloud) | Suitable for development and CI |
| `on_prem_connected` | Allowed | Loopback / private / cloud | Cloud LLMs permitted for threat intel |
| `on_prem_airgapped` | Blocked | Loopback or RFC-1918 only | Hosted providers hard-failed at startup |

### Ports

| Service | Port | Protocol | Used By |
|---|---|---|---|
| Postgres | 5432 | TCP | App, MLflow (optional) |
| NATS | 4222 | TCP | App (JetStream) |
| NATS monitoring | 8222 | HTTP | Ops health checks |
| OTel Collector gRPC | 4317 | gRPC | App OTLP spans |
| OTel Collector HTTP | 4318 | HTTP | App OTLP spans, logs |
| MLflow | 5000 | HTTP | Web UI, API |
| Ollama | 11434 | HTTP | LLM inference |
| Jaeger UI | 16686 | HTTP | Tracing (optional `tracing` profile) |

## 2. Step-by-Step Deployment

### 2.1 Clone and configure

```bash
git clone <repo-url> wolfpack
cd wolfpack
cp .env.example .env
# Edit .env — see docs/runbook/configuration.md for every option
```

### 2.2 Pull the LLM model

```bash
# Local Ollama (dev or airgapped)
docker compose up -d ollama
docker compose exec ollama ollama pull llama3.3:70b

# Or for CI / lightweight dev
docker compose exec ollama ollama pull llama3.2:1b
```

### 2.3 Start core services

```bash
docker compose up -d
```

This starts: `postgres`, `nats`, `otel-collector`, `ollama`.

### 2.4 (Optional) Start MLflow

```bash
docker compose --profile full up -d
```

### 2.5 Verify health

```bash
docker compose ps
# All services should show `healthy`
```

### 2.6 Run migrations

```bash
# If using the local Python environment
uv run alembic upgrade head
```

Or use the Alembic container if one exists in your deployment wrapper.

### 2.7 Start the application

```bash
# From the project root with the virtualenv activated
PYTHONPATH=src uv run python -m wolfpack.main
```

## 3. Configuration

See `docs/runbook/configuration.md` for the complete configuration reference.

Key files:
- `.env` — runtime secrets and connection strings (gitignored)
- `.env.example` — template with placeholders
- `docker-compose.yml` — service topology and resource limits
- `infra/otel/otel-collector-config.yaml` — telemetry exporters
- `infra/nats/nats-server.conf` — JetStream settings

## 4. Feature Flags

Tier-2 adapters are disabled by default. Enable in `.env`:

```env
FEATURE_FLAGS__ADAPTER_DNS=true
FEATURE_FLAGS__ADAPTER_ZEEK_SURICATA=true
FEATURE_FLAGS__ADAPTER_PROXY=true
FEATURE_FLAGS__ADAPTER_CLOUDTRAIL=true
```

## 5. Scaling

### Horizontal

- **NATS consumers**: increase the consumer replica count in `nats-server.conf` or deploy additional app instances with the same consumer group.
- **Postgres read replicas**: route read-only analytics queries to replicas; keep writes on the primary.
- **Ollama**: scale with multiple Ollama instances behind a load balancer. Set `LLM__BASE_URL` to the LB endpoint.

### Vertical

- Increase `POSTGRES__POOL_MAX_SIZE` when raising app worker count.
- Increase Ollama container memory limit for larger context windows.
- Increase OTel Collector memory if always-on sampling is enabled.

## 6. Monitoring

| Dashboard | URL | Profile |
|---|---|---|
| MLflow Tracking | http://localhost:5000 | `full` |
| NATS Monitoring | http://localhost:8222 | default |
| Jaeger Traces | http://localhost:16686 | `tracing` |
| OTel Collector Health | http://localhost:13133 | default |

### Alert Webhook

Configure `WEBHOOK_CONFIG__URL` in `.env` to receive operational and security alerts (schema-retry spikes, ledger-hash mismatch, review timeouts, NATS lag, tool-allowlist violations).

## 7. Backup

### Postgres

Use `pg_dump` or a scheduled container:

```bash
docker compose exec postgres pg_dump -U wolfpack -Fc wolfpack > wolfpack_$(date +%F).dump
```

Critical tables: `cases`, `branches`, `evidence_ledger`, `breakglass_audit`, `crypto_shred_keys`, `pii_salts`, `pii_mappings`.

### NATS JetStream

Enable stream file backup:

```bash
nats stream backup wolfpack_cases /backup/nats
```

### Evidence Ledger

The ledger is hash-chained. Any single-row tamper breaks `verify_chain()`. Back up the full `evidence_ledger` table alongside Postgres dumps.

### MLflow Artifacts

Volume `mlflow_artifacts` is mounted from Docker. Back up the host path or use S3-compatible object storage in production.

## 8. First-Time Checklist

- [ ] `.env` copied from `.env.example` and all values filled
- [ ] `DEPLOYMENT_MODE` set correctly (`dev` / `on_prem_connected` / `on_prem_airgapped`)
- [ ] LLM model pulled and health endpoint responds
- [ ] Postgres `pgvector` extension confirmed (`SELECT * FROM pg_extension WHERE extname = 'vector';`)
- [ ] NATS JetStream enabled (`nats stream ls` returns streams)
- [ ] Alembic migrations applied
- [ ] OTel Collector receiving spans (`docker compose logs otel-collector`)
- [ ] Alert webhook reachable (if configured)
- [ ] `wolfpack.verify_chain()` SQL function present (or trigger installed by migrations)
