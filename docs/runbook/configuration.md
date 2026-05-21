# Configuration Reference

This document lists every configuration option in `wolfpack.config.settings.Settings`, its `.env` variable name, default value, and usage notes.

## Deployment

| Field | `.env` Variable | Default | Description |
|---|---|---|---|
| `deployment_mode` | `DEPLOYMENT_MODE` | *(required)* | `dev` \| `on_prem_connected` \| `on_prem_airgapped`. Airgapped mode rejects hosted LLMs and public URLs. |

## LLM (`llm.*`)

| Field | `.env` Variable | Default | Description |
|---|---|---|---|
| `provider` | `LLM__PROVIDER` | *(required)* | `ollama` or `openai_compatible` |
| `base_url` | `LLM__BASE_URL` | *(required)* | HTTP(S) endpoint for the LLM server |
| `model` | `LLM__MODEL` | *(required)* | Model name (e.g. `llama3.3:70b`, `llama3.2:1b`) |
| `api_key` | `LLM__API_KEY` | `None` | API key for authenticated endpoints. `SecretStr` — never logged. |
| `hosted` | `LLM__HOSTED` | `false` | Set `true` for Ollama Cloud or other hosted services. Hard-failed in airgapped mode. |
| `request_timeout_s` | `LLM__REQUEST_TIMEOUT_S` | `60.0` | Per-request timeout in seconds. Must be > 0. |

### Airgapped Restrictions

When `DEPLOYMENT_MODE=on_prem_airgapped`:
- `LLM__HOSTED` must be `false`
- `LLM__BASE_URL` must resolve to loopback (`127.*`, `localhost`) or RFC-1918 private address (`10.*`, `172.16-31.*`, `192.168.*`)

## Postgres (`postgres.*`)

| Field | `.env` Variable | Default | Description |
|---|---|---|---|
| `dsn` | `POSTGRES__DSN` | *(required)* | Full connection string. `SecretStr` — never logged. Must include `pgvector` extension. |
| `pool_min_size` | `POSTGRES__POOL_MIN_SIZE` | `2` | Minimum asyncpg pool connections |
| `pool_max_size` | `POSTGRES__POOL_MAX_SIZE` | `10` | Maximum asyncpg pool connections. Must be ≥ `pool_min_size`. |

## NATS (`nats.*`)

| Field | `.env` Variable | Default | Description |
|---|---|---|---|
| `url` | `NATS__URL` | `nats://localhost:4222` | NATS server URL. JetStream must be enabled on the server. |

## OpenTelemetry (`otel.*`)

| Field | `.env` Variable | Default | Description |
|---|---|---|---|
| `endpoint` | `OTEL__ENDPOINT` | `http://localhost:4318` | OTLP HTTP endpoint for the OTel Collector |
| `service_name` | `OTEL__SERVICE_NAME` | `wolfpack` | Service name in span metadata |
| `service_namespace` | `OTEL__SERVICE_NAMESPACE` | `wolfpack` | Service namespace in span metadata |

## MLflow (`mlflow.*`)

| Field | `.env` Variable | Default | Description |
|---|---|---|---|
| `tracking_uri` | `MLFLOW__TRACKING_URI` | `http://localhost:5000` | MLflow tracking server URL |

## Branch Budget (`branch_budget.*`)

| Field | `.env` Variable | Default | Description |
|---|---|---|---|
| `max_depth` | `BRANCH_BUDGET__MAX_DEPTH` | `3` | Maximum Flanker recursion depth per case |
| `max_branches_per_case` | `BRANCH_BUDGET__MAX_BRANCHES_PER_CASE` | `10` | Maximum branches allowed per case |

> Token and tool budgets per branch are reserved for V2 and not yet enforced.

## Learning Queue (`learning.*`)

| Field | `.env` Variable | Default | Description |
|---|---|---|---|
| `schedule_minutes` | `LEARNING__SCHEDULE_MINUTES` | `5` | How often the learning worker wakes up |
| `batch_size` | `LEARNING__BATCH_SIZE` | `50` | Cases to ingest per worker run |
| `retry_limit` | `LEARNING__RETRY_LIMIT` | `3` | Max retries per case before dead-letter |
| `min_confidence` | `LEARNING__MIN_CONFIDENCE` | `3` | Only ingest cases with confidence ≥ this threshold |
| `enable_worker` | `LEARNING__ENABLE_WORKER` | `true` | Set `false` to disable the background worker |

## Alert Webhook (`webhook_config.*`)

| Field | `.env` Variable | Default | Description |
|---|---|---|---|
| `url` | `WEBHOOK_CONFIG__URL` | `None` | POST target for alert and timeout-escalation notifications |
| `timeout_s` | *(nested in `Settings`)* | `30.0` | HTTP timeout for webhook delivery |

## Feature Flags (`feature_flags.*`)

All Tier-2 adapters default to `false`.

| Field | `.env` Variable | Default | Description |
|---|---|---|---|
| `adapter_dns` | `FEATURE_FLAGS__ADAPTER_DNS` | `false` | Enable DNS log adapter |
| `adapter_zeek_suricata` | `FEATURE_FLAGS__ADAPTER_ZEEK_SURICATA` | `false` | Enable Zeek / Suricata adapter |
| `adapter_proxy` | `FEATURE_FLAGS__ADAPTER_PROXY` | `false` | Enable proxy log adapter |
| `adapter_cloudtrail` | `FEATURE_FLAGS__ADAPTER_CLOUDTRAIL` | `false` | Enable AWS CloudTrail adapter |

Feature flags are parsed as JSON if the env value is a string.

## PII Processing

PII settings are currently compile-time (no env toggles in V1):

- **NER stripping** — enabled for all free-text fields before agent context assembly
- **Deterministic pseudonymization** — per-case salt in `pii_salts`; token→encrypted-original mappings in `pii_mappings`
- **Break-glass** — audit-logged, one-time rehydration

## Alert Thresholds

Alert thresholds are compile-time constants in `src/wolfpack/observability/alert_manager.py`:

| Alert | Threshold | Unit |
|---|---|---|
| Schema-retry spike | > 5 % | Schema retries per 5-minute window |
| Ledger-hash mismatch | any | Per-case `verify_chain()` failure |
| Branch depth | > `max_depth` | Per branch |
| Review timeout | > `review_timeout_hours` | Per case (default 24 h) |
| NATS lag | > 1000 messages | Per consumer, > 2 min |
| Tool-allowlist violation | any | Per agent invocation |

## Example `.env`

```env
DEPLOYMENT_MODE=on_prem_connected
LLM__PROVIDER=ollama
LLM__BASE_URL=http://localhost:11434
LLM__MODEL=llama3.3:70b
LLM__HOSTED=false
LLM__REQUEST_TIMEOUT_S=120.0

POSTGRES__DSN=postgresql://wolfpack:changeme@localhost:5432/wolfpack
POSTGRES__POOL_MIN_SIZE=4
POSTGRES__POOL_MAX_SIZE=20

NATS__URL=nats://localhost:4222
OTEL__ENDPOINT=http://localhost:4318
OTEL__SERVICE_NAME=wolfpack
OTEL__SERVICE_NAMESPACE=wolfpack

MLFLOW__TRACKING_URI=http://localhost:5000

WEBHOOK_CONFIG__URL=https://hooks.example.com/alerts

FEATURE_FLAGS__ADAPTER_DNS=true
FEATURE_FLAGS__ADAPTER_ZEEK_SURICATA=true
FEATURE_FLAGS__ADAPTER_PROXY=false
FEATURE_FLAGS__ADAPTER_CLOUDTRAIL=false
```
