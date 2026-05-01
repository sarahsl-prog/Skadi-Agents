# WolfPack Observability Guide

## Architecture

Three rings of instrumentation:

| Ring | OTel Spans | Key Attributes |
|---|---|---|
| LangGraph nodes | `node.{alpha,tracker,flanker,closer,scribe,review}` | `wolfpack.agent_name`, `wolfpack.status`, `wolfpack.case_id`, `wolfpack.branch_id`, `wolfpack.agent_run_id` |
| Pydantic AI agents | `agent.run`, `tool.call` | `wolfpack.model_name`, `wolfpack.provider`, `wolfpack.tool_name` |
| Haystack RAG | `rag.{threat_intel,case_history}` | `wolfpack.rag_pipeline`, `wolfpack.query_hash`, `wolfpack.result_count` |

## Baggage Propagation

Baggage is set once at case creation (`Alpha`) and propagated automatically:

- Through LangGraph node spans via `attach_baggage_to_span()`
- Through Pydantic AI agent runs via the current OTel context
- Through NATS messages via `inject_nats_headers()`
- Through RAG retrieval via `traced_retrieve()`

## Viewing Traces

### Debug exporter (default)
- OTel Collector prints spans to stdout — useful during local development.

### MLflow (Phase 6+)
- Enable the `otlp/mlflow` exporter in `infra/otel/otel-collector-config.yaml` by uncommenting `- otlp/mlflow`.
- Then start the *full* compose profile: `docker compose --profile full up -d`.
- Open `http://localhost:5000` → MLflow tracking UI.

### Jaeger (Phase 6+, disabled-by-default)
- Enable the `tracing` compose profile: `docker compose --profile tracing up -d`.
- Jaeger UI is available at `http://localhost:16686`.
- OTLP ports are mapped to host `4319` (gRPC) and `4320` (HTTP) to avoid conflict with the OTel Collector.

## Alerting

Five built-in alerts are monitored by the `AlertManager`:

| Alert | Severity | Trigger |
|---|---|---|
| SchemaRetrySpike | warning | > 20% retries over 5 min |
| LedgerHashMismatch | critical | `verify_chain()` fails |
| BranchDepth | warning | depth > 3 or count > 8/10 |
| ReviewTimeoutEscalation | info | individual timeout |
| NATSConsumerLag | warning | pending > 1000 msgs |

The alert manager is accessible via `GET /api/alerts` and streams real-time alerts over WebSocket.

## MLflow Dashboards

Per-agent dashboard definitions are stored as JSON in `infra/mlflow/dashboards/dashboards.json`. They include:

- **Per-agent latency** — P50 / P95 per agent (Alpha, Tracker, Flanker, Closer)
- **Tool call counts** — Number of tool invocations per agent per case
- **Schema retry rate** — Percentage of retries over 5-min windows
- **Evaluation scores** — Golden-set metrics (precision, recall, mean score)
- **Per-branch token spend** — Prompt + completion tokens consumed per branch
- **Case throughput** — Cases completed per hour

These dashboards are loaded as MLflow experiment tags when the MLflow OTLP exporter is enabled.

## Extensibility

Adding a new exporter (e.g. Grafana Tempo):
1. Add exporter block to `infra/otel/otel-collector-config.yaml`
2. Add it to the `traces` pipeline `exporters` list
3. No code changes required
