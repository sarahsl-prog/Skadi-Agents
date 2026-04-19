---
name: wolfpack-devops
description: Infrastructure and DevOps skill for WolfPack stack. Use when modifying or creating: docker-compose.yml, docker-compose.override.yml.example, infra/ configs (postgres/init.sql, nats/nats-server.conf, otel/otel-collector-config.yaml, mlflow/Dockerfile, ollama/entrypoint.sh, sizing.md), justfile, .github/workflows/ci.yml, .env.example, .pre-commit-config.yaml. Triggers on: setting up Docker services, configuring NATS JetStream, wiring OTel Collector, setting up MLflow, Day 4 and Day 6 Phase 0 tasks, CI pipeline changes, infra updates, service restarts.
---

# WolfPack DevOps Configuration

## Docker Compose Rules

**Required for every service:**
```yaml
healthcheck:
  test: [...]
  interval: 5s
  timeout: 3s
  retries: 10
depends_on:
  service-name:
    condition: service_healthy
```

Never use `depends_on: [service-name]` (soft dep) — always `condition: service_healthy`.

**Image pinning**: Use exact tags. Never `latest` in any production-intent config (exception: `ollama/ollama:latest` is acceptable since Ollama doesn't publish stable semver tags yet — document this).

**Profile assignment**:
- `profiles: [minimal]` — Postgres, NATS, OTel Collector, Ollama (CI-safe services)
- `profiles: [full]` — MLflow (adds ~200MB, skip in CI)
- Default compose (no `--profile`) brings up nothing intentionally — always specify a profile

## Service Configs

### Postgres
```yaml
image: pgvector/pgvector:pg16
environment:
  POSTGRES_DB: wolfpack
  POSTGRES_USER: wolfpack
  POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
volumes:
  - ./infra/postgres/init.sql:/docker-entrypoint-initdb.d/init.sql
healthcheck:
  test: ["CMD-SHELL", "pg_isready -U wolfpack"]
```

`infra/postgres/init.sql`:
```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE ROLE wolfpack_app LOGIN PASSWORD 'changeme';
GRANT CONNECT ON DATABASE wolfpack TO wolfpack_app;
```

### NATS JetStream
```yaml
image: nats:2.10-alpine
command: ["-js", "-c", "/etc/nats/nats-server.conf"]
volumes:
  - ./infra/nats/nats-server.conf:/etc/nats/nats-server.conf
  - nats_data:/data
```

`infra/nats/nats-server.conf`:
```
jetstream {
  store_dir: /data
}
```

### OTel Collector
`infra/otel/otel-collector-config.yaml`:
- Receivers: `otlp` (grpc: 4317, http: 4318)
- Processors: `memory_limiter`, `batch`
- Exporters: `debug` (always), `otlp/mlflow` (when MLflow is up), `jaeger` (disabled by default — block comment with instructions to enable)
- Pipeline: `traces: receivers[otlp] → processors[memory_limiter, batch] → exporters[debug, otlp/mlflow]`

### Ollama
```yaml
image: ollama/ollama:latest
volumes:
  - ollama_data:/root/.ollama
  - ./infra/ollama/entrypoint.sh:/entrypoint.sh
entrypoint: ["/entrypoint.sh"]
```

`infra/ollama/entrypoint.sh`: Start Ollama, pull `llama3.2:1b` (CI/dev default), then exec the main process.

## Justfile

Use recipe format (not Makefile). Tab-indent commands.

```just
install:
    uv sync

fmt:
    ruff format src tests

lint:
    ruff check src tests

typecheck:
    mypy --strict src tests

test:
    pytest tests/unit -q

test-integration:
    pytest tests/integration -q

up:
    docker compose --profile full up -d

down:
    docker compose down

smoke:
    python -m wolfpack.smoke.hello_pack
```

## GitHub Actions CI

`ci.yml` structure:
```yaml
jobs:
  lint:        # ruff via pre-commit
  typecheck:   # mypy --strict
  test-unit:   # pytest tests/unit
  test-integration:  # pytest tests/integration (needs: [test-unit])
  build:       # docker compose --profile minimal build
```

Use `astral-sh/setup-uv@v3` for dep install. Cache: `~/.cache/uv`. Python: `3.11` only.

Integration tests: set `RUN_INTEGRATION: "1"` env var in the step. Use `--profile minimal` compose.

## .env.example

Every field must be documented with a comment explaining valid values and which deployment modes accept it:
```env
# LLM provider: "ollama" | "openai_compatible"
LLM__PROVIDER=ollama
# Base URL for Ollama. Must be loopback/private in ON_PREM_AIRGAPPED mode.
LLM__BASE_URL=http://localhost:11434
```

## Output Format

Produce complete, runnable config files. YAML must be valid (validate mentally against schema). Shell scripts must have `#!/usr/bin/env bash` and `set -euo pipefail`.
