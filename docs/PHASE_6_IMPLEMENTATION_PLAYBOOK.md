# Phase 6 Implementation Playbook — Observability Hardening

This document turns the Phase 6 plan from [`PROJECT_PLAN.md`](./PROJECT_PLAN.md) into an execution-ready implementation plan.

## 0. Outstanding Design Questions

| # | Question | Decision needed by | Default if unresolved | Notes |
|---|----------|--------------------|-----------------------|-------|
| D1 | **V1.5 trigger metrics** — what are the concrete thresholds for analyst-hours saved, false-positive rate, and branch-elevation precision that gate Blocker and Post-Hunt Analyst work? | End of Phase 6 (after eval dashboards have real data) | Defer: define after eval dashboards are live with real deployment data | The project plan §7 explicitly says these are "best defined after Phase 6 eval dashboards are live with real data." Do not define thresholds prematurely — they will be wrong. Instead, ship the dashboards and let data inform the thresholds. |
| D2 | **Alerting channel** — should alerts go to the Analyst Console UI, a Slack/webhook channel, or both? | Start of Track C | Both: alerts surface in the Analyst Console notification feed AND fire configured webhooks | The Analyst Console already has WebSocket support from Phase 5. Adding an alert feed is low effort. Webhooks are already configured for review-timeout escalation. Use both. |
| D3 | **Jaeger exporter readiness** — should the Jaeger OTLP exporter be enabled-by-default or kept disabled? | Start of Track B | Disabled-by-default (consistent with Phase 0 decision) | The OTel Collector config from Phase 0 already has a Jaeger exporter block commented out. Keep it disabled-by-default but document the enablement path. |
| D4 | **OTel sampling strategy** — full tracing of every node, tool call, NATS message, and ledger entry can generate very high span volume per case (especially with multiple branches). Options: always-on sampling (complete audit but expensive), head-based probabilistic (loses some traces), or tail-based (complete traces only). | Before Track A1 (LangGraph node instrumentation) | Always-on sampling for security events (ledger writes, break-glass, tool allowlist violations) and LangGraph node transitions; 10% probabilistic sampling for individual RAG and adapter tool call spans | Security events must be 100% captured for audit completeness. Tool-call spans at scale (Flanker making 15 calls × 10 branches) can overwhelm the collector. The tiered sampling approach keeps the audit trail complete while controlling collector load. |
| D5 | **Alert severity routing** — multiple alert types have different severities (`info`, `warning`, `critical` from the `PolicyGuardrail` schema). Phase 6 adds operational alerts. Should different severity levels route to different webhook endpoints or channels? | Before Track C6 (alert manager) | Single configured webhook URL for V1, with severity included in the alert payload for the receiver to route. Severity-specific endpoint configuration is a V1.5 addition. | Adding per-severity endpoints in V1 requires the operator to configure 3 endpoints and maintain 3 integrations. A single endpoint with a rich payload (severity, alert type, case ID) lets the receiver (e.g., PagerDuty, Slack) do its own routing. This is simpler and more consistent with how the review-timeout webhook already works. |

## 1. Current Baseline

The repository has (from Phases 0–5):

- Full LangGraph orchestration with all five agents (Alpha, Tracker, Flanker, Closer, Scribe) + Review node
- NATS JetStream integration, hash-chained ledger, crypto-shredding, PII store
- RAG pipelines and telemetry adapters (Tier-1 + Tier-2 with feature flags)
- Branch creation with explosion controls and hypothesis dedup
- Analyst Console (React + FastAPI) with verdict review, break-glass, timeout display
- OTel TracerProvider bootstrap from Phase 0 (basic setup)
- OTel Collector with `debug` exporter
- MLflow container (behind `full` Docker Compose profile)
- Logfire wiring from Phase 0

The repository does **not** yet have:

- Consistent OTel instrumentation across all three service rings
- `case_id` / `branch_id` / `agent_run_id` as OTel baggage propagated across all spans
- MLflow dashboards for per-agent metrics
- Jaeger/Tempo exporter (config exists but disabled)
- Alerting on schema-retry spikes, ledger-hash mismatch, branch depth, review timeouts, NATS lag

## 2. Phase Objective

Harden the observability layer for production readiness:

- OTel instrumentation across all three service rings (LangGraph, Pydantic AI, Haystack)
- Consistent `case_id` / `branch_id` / `agent_run_id` span attributes propagated as OTel baggage
- MLflow dashboards for per-agent latency, tool call counts, retry rates, eval scores, per-branch token spend
- Jaeger OTLP exporter documented and ready (disabled-by-default)
- Alerting on key operational and security signals

No Blocker, Post-Hunt Analyst, or V1.5 features should land during this phase.

## 3. Execution Strategy

Three implementation tracks:

1. OTel instrumentation and baggage propagation
2. MLflow dashboards and Jaeger readiness
3. Alerting and operational monitors

The critical path is:

1. instrument all services with OTel spans and baggage
2. configure MLflow to consume and display OTel data
3. enable the Jaeger exporter path
4. implement alerting on key signals
5. validate with load and chaos tests

## 4. Work Breakdown Structure

### Track A: OTel Instrumentation and Baggage Propagation

Purpose: ensure every span, log line, and ledger entry carries the full operational context.

#### A1. Instrument LangGraph nodes with OTel spans

Tasks:

- Update every LangGraph node handler (Alpha, Tracker, Flanker, Closer, Scribe, Review) to:
  - Start an OTel span on entry and end on exit.
  - Set span attributes: `wolfpack.agent_name`, `wolfpack.case_id`, `wolfpack.branch_id`, `wolfpack.agent_run_id`.
  - Record span events for: tool calls, state transitions, NATS messages published, ledger entries written.
  - Record span status (OK, ERROR) and any exceptions.
- Create a decorator or wrapper function `traced_node(node_fn, agent_name)` that instruments any node handler automatically.

Deliverables:

- updated node handlers with OTel spans
- `src/wolfpack/observability/tracing.py` updates (traced_node helper)

Acceptance checks:

- every node execution creates an OTel span
- spans carry `agent_name`, `case_id`, `branch_id`, `agent_run_id` attributes
- span events record tool calls and state transitions

#### A2. Instrument Pydantic AI agent calls with OTel spans

Tasks:

- Update each Pydantic AI agent (Alpha, Tracker, Flanker, Closer) to:
  - Propagate the current OTel context into the LLM call.
  - Record span attributes for: `wolfpack.model_name`, `wolfpack.provider`, `wolfpack.token_count` (prompt + completion).
  - Record span events for: tool invocations (tool name, input hash, output hash — no raw content in spans).
- Leverage Logfire's built-in Pydantic AI integration (from Phase 0) for LLM-specific spans.

Deliverables:

- updated agent implementations with OTel spans

Acceptance checks:

- LLM calls create child spans under the node span
- spans carry model and provider attributes
- token counts are recorded
- tool invocations are traced (without raw content)

#### A3. Instrument Haystack RAG calls with OTel spans

Tasks:

- Update RAG pipeline calls (`threat_intel_tool`, `case_history_tool`) to:
  - Start an OTel span for each retrieval call.
  - Set span attributes: `wolfpack.rag_pipeline`, `wolfpack.query_hash`, `wolfpack.top_k`, `wolfpack.result_count`.
  - Record retrieval latency.
- Create a `traced_retrieval(pipeline_name, retrieve_fn)` wrapper.

Deliverables:

- updated RAG tools with OTel spans

Acceptance checks:

- RAG retrieval calls create child spans
- spans carry pipeline name and query metadata
- retrieval latency is recorded

#### A4. Implement OTel baggage propagation

Tasks:

- Update `src/wolfpack/observability/baggage.py` (new file):
  - `set_case_baggage(case_id, branch_id, agent_run_id)` — sets OTel baggage for the current context.
  - `get_case_baggage() -> CaseBaggage` — reads current OTel baggage.
- Update the Alpha Dispatcher node to set baggage at case creation:
  - `case_id` from the newly created case.
  - `branch_id` from the initial branch.
  - `agent_run_id` as a UUID generated per graph execution.
- Update all downstream nodes and NATS message handlers to propagate baggage.
- Update the evidence ledger writer to include `agent_run_id` from baggage.

Deliverables:

- `src/wolfpack/observability/baggage.py`
- updated nodes and ledger writer

Acceptance checks:

- baggage is set at case creation
- baggage propagates through all nodes and tool calls
- ledger entries carry `agent_run_id` from baggage
- NATS messages include baggage in headers

#### A5. Instrument NATS message publishing with OTel context

Tasks:

- Update `src/wolfpack/orchestrator/bus.py` to:
  - Inject the current OTel trace context and baggage into NATS message headers.
  - Extract OTel context from NATS message headers on the receiving end.
  - This ensures distributed traces span across NATS-mediated communication.

Deliverables:

- updated `bus.py` with OTel context propagation

Acceptance checks:

- NATS messages carry OTel trace context in headers
- receiving end links to the originating trace
- distributed traces span across NATS boundaries

#### A6. Add instrumentation integration tests

Tasks:

- Add `tests/integration/test_observability.py`.
- Test: run a hunt flow → verify OTel spans exist for every node.
- Test: baggage propagates from Alpha through all downstream nodes.
- Test: NATS messages carry OTel context.
- Test: ledger entries carry `agent_run_id` from baggage.

Deliverables:

- `tests/integration/test_observability.py`

Acceptance checks:

- every node execution produces an OTel span
- baggage propagates through the full hunt flow
- NATS context propagation works
- ledger entries have `agent_run_id`

### Track B: MLflow Dashboards and Jaeger Readiness

Purpose: make the observability data visible and actionable.

#### B1. Configure MLflow OTel ingestion

Tasks:

- Update `infra/otel/otel-collector-config.yaml` to:
  - Add an OTLP exporter pointing to the MLflow tracking server.
  - Configure batch processing and memory limits.
  - Keep the `debug` exporter for local development.
- Verify that MLflow receives and displays OTel traces.
- Document the MLflow trace viewing path in `infra/sizing.md` or a new `infra/observability.md`.

Deliverables:

- updated OTel Collector config
- `infra/observability.md` (new)

Acceptance checks:

- MLflow receives OTel trace data
- traces are viewable in the MLflow UI
- documentation describes the viewing path

#### B2. Create MLflow per-agent dashboards

Tasks:

- Create MLflow dashboard configurations for:
  - **Per-agent latency**: P50/P95/P99 latency for each agent (Alpha, Tracker, Flanker, Closer, Scribe).
  - **Tool call counts**: number of tool invocations per agent per case.
  - **Retry rates**: percentage of retries due to schema validation failures.
  - **Eval scores**: golden-set evaluation metrics over time.
  - **Per-branch token spend**: tokens consumed per branch (prompt + completion).
  - **Case throughput**: cases completed per hour.
- Store dashboard configurations as code (MLflow experiment tags or JSON files in `infra/mlflow/dashboards/`).

Deliverables:

- MLflow dashboard configurations

Acceptance checks:

- dashboards display live data from the running system
- per-agent latency, tool counts, and retry rates are visible
- eval scores are tracked over time

#### B3. Enable Jaeger OTLP exporter path

Tasks:

- Update `infra/otel/otel-collector-config.yaml`:
  - Uncomment/add the Jaeger OTLP exporter block.
  - Set it to `disabled-by-default` (controlled via environment variable or compose profile).
- Add `jaeger` service to `docker-compose.yml` behind a `tracing` profile:
  - `jaegertracing/all-in-one:latest`
  - OTLP receiver enabled
  - UI at `http://localhost:16686`
- Document the enablement path: `docker compose --profile tracing up` starts Jaeger alongside the other services.

Deliverables:

- updated OTel Collector config with Jaeger exporter
- updated `docker-compose.yml` with Jaeger service
- documentation in `infra/observability.md`

Acceptance checks:

- `docker compose --profile tracing up` starts Jaeger
- Jaeger UI shows traces when the exporter is enabled
- `docker compose up` (without the `tracing` profile) does not start Jaeger

#### B4. Keep Collector config backend-agnostic

Tasks:

- Ensure the OTel Collector configuration is structured so that:
  - Adding a new exporter (e.g., Grafana Tempo, Datadog) requires only a config change, not code changes.
  - Exporter enablement is controlled via environment variables or compose profiles.
  - Processors (batch, memory_limiter) are shared across all exporters.
- Document the extensibility pattern in `infra/observability.md`.

Deliverables:

- updated Collector config
- `infra/observability.md` documentation

Acceptance checks:

- adding a new exporter requires only config changes
- processors are shared across exporters
- extensibility is documented

### Track C: Alerting and Operational Monitors

Purpose: detect operational and security issues proactively.

#### C1. Implement schema-retry spike alert

Tasks:

- Create `src/wolfpack/observability/alerts.py`.
- Implement `SchemaRetrySpikeAlert`:
  - Monitors Pydantic AI agent retry rates (from OTel metrics).
  - Triggers when retry rate exceeds a threshold (default: 20% of calls over a 5-minute window).
  - Fires an alert via the configured webhook (same webhook mechanism as review-timeout escalation).
  - Logs the alert event to the evidence ledger.

Deliverables:

- `src/wolfpack/observability/alerts.py`

Acceptance checks:

- alert triggers when retry rate exceeds the threshold
- webhook is called with alert details
- alert event is logged to the evidence ledger

#### C2. Implement ledger-hash mismatch alert

Tasks:

- Implement `LedgerHashMismatchAlert`:
  - Periodically runs `verify_chain()` on active cases.
  - Triggers if any chain verification fails (hash mismatch).
  - Fires a critical alert via the webhook.
  - Logs the alert event to the evidence ledger (this is a security-critical signal).

Deliverables:

- updated `src/wolfpack/observability/alerts.py`

Acceptance checks:

- alert triggers when a ledger hash mismatch is detected
- critical alert fires via webhook
- alert event is audit-logged

#### C3. Implement runaway branch depth alert

Tasks:

- Implement `BranchDepthAlert`:
  - Monitors branch depth per case.
  - Triggers when branch depth approaches the configured maximum (default: 3) or when the branch count per case exceeds 80% of the maximum (default: 8 out of 10).
  - Fires a warning alert via the webhook.
  - Logs the alert event to the evidence ledger.

Deliverables:

- updated `src/wolfpack/observability/alerts.py`

Acceptance checks:

- alert triggers when branch depth or count approaches limits
- warning alert fires via webhook
- alert event is audit-logged

#### C4. Implement review-timeout escalation alert

Tasks:

- Integrate with the existing review watchdog from Phase 2:
  - When the watchdog auto-escalates a review timeout, also fire an alert.
  - Track escalation rate (escalations per day) as a metric in MLflow.
  - Alert if escalation rate exceeds a threshold (default: 5 per day).

Deliverables:

- updated watchdog integration
- updated `src/wolfpack/observability/alerts.py`

Acceptance checks:

- review-timeout escalation triggers an alert
- escalation rate is tracked in MLflow
- rate threshold alert works

#### C5. Implement NATS consumer lag alert

Tasks:

- Implement `NATSConsumerLagAlert`:
  - Monitors NATS JetStream consumer pending message counts.
  - Triggers when pending messages exceed a threshold (default: 1000 per consumer).
  - Fires a warning alert via the webhook.
  - Logs the alert event to the evidence ledger.

Deliverables:

- updated `src/wolfpack/observability/alerts.py`

Acceptance checks:

- alert triggers when consumer lag exceeds threshold
- warning alert fires via webhook
- alert event is audit-logged

#### C6. Implement alert manager and scheduling

Tasks:

- Create `src/wolfpack/observability/alert_manager.py`.
- Implement `AlertManager`:
  - Registers all alert monitors.
  - Runs each monitor on a configurable schedule (e.g., every 60 seconds).
  - Deduplicates alerts (no duplicate alert for the same condition within a cooldown window).
  - Routes alerts to the configured webhook.
  - Exposes alert state via an API endpoint (`GET /api/alerts`) for the Analyst Console.
- Add `AlertConfig` to `Settings` for thresholds and webhook URL.

Deliverables:

- `src/wolfpack/observability/alert_manager.py`
- updated `src/wolfpack/config/settings.py`
- `GET /api/alerts` endpoint

Acceptance checks:

- alert manager runs all monitors on schedule
- deduplication prevents alert storms
- alert state is accessible via API
- Analyst Console can display alert feed

#### C7. Add alert integration tests

Tasks:

- Add `tests/integration/test_alerts.py`.
- Test each alert type by simulating the trigger condition.
- Test deduplication: same condition does not fire duplicate alerts within cooldown.
- Test alert webhook delivery.

Deliverables:

- `tests/integration/test_alerts.py`

Acceptance checks:

- all alert types trigger correctly
- deduplication works
- webhooks receive alert payloads

## 5. Recommended Delivery Sequence

1. OTel baggage propagation (A4) — foundational for all other instrumentation
2. Instrument LangGraph nodes (A1)
3. Instrument Pydantic AI agents (A2)
4. Instrument Haystack RAG (A3)
5. Instrument NATS context propagation (A5)
6. Configure MLflow OTel ingestion (B1)
7. Create MLflow dashboards (B2)
8. Enable Jaeger exporter path (B3)
9. Implement alerts (C1–C5)
10. Implement alert manager (C6)
11. Integration tests (A6, C7)

## 6. Parallelization Plan

### Safe parallel lanes after A4 (baggage propagation)

- Lane 1: LangGraph node instrumentation (A1)
- Lane 2: Pydantic AI agent instrumentation (A2)
- Lane 3: Haystack RAG instrumentation (A3)

### Safe parallel lanes after Track A

- Lane 1: MLflow dashboards (B1–B2)
- Lane 2: Alert implementations (C1–C5)

### Work that should stay on the critical path

- Baggage propagation must land before other instrumentation (all spans need it)
- MLflow OTel ingestion must work before dashboards
- Alert manager must land before alert integration tests

## 7. Milestones and Exit Criteria

### Milestone 1: Full OTel Instrumentation

Exit criteria:

- every node, agent call, and RAG call produces OTel spans
- baggage propagates `case_id`, `branch_id`, `agent_run_id` across all spans
- NATS messages carry OTel context

### Milestone 2: MLflow Dashboards Live

Exit criteria:

- MLflow displays live traces from the running system
- per-agent latency, tool counts, and retry rates are visible
- Jaeger exporter path is documented and ready

### Milestone 3: Alerting Operational

Exit criteria:

- all five alert types trigger correctly
- alert manager deduplicates and routes alerts
- alert state is accessible via API

### Milestone 4: Phase 6 Complete

Exit criteria:

- all integration tests pass
- observability documentation is complete
- V1.5 trigger metrics are discussed (but not finalized — wait for real data)

## 8. Command-Level Validation Checklist

```bash
uv sync
just lint
just typecheck
just test
just test-integration
docker compose --profile full --profile tracing up  # verify Jaeger starts
```

All of these should succeed before Phase 6 is marked complete.

## 9. Risks to Watch During Execution

### OTel-to-MLflow bridge maturity (carried from Phase 0)

The OTel Collector to MLflow bridge may still be immature. If MLflow OTLP ingestion is unreliable, fall back to the `debug` exporter and log MLflow ingestion as a known limitation. Jaeger can serve as the primary trace viewer in this case.

### Span cardinality explosion

Every tool call, NATS message, and ledger entry creates a span. For a complex case with multiple branches, span count can be high. Set the OTel batch processor to aggregate spans and avoid overwhelming the collector.

### Alert fatigue risk

Too many alerts reduce their value. Set conservative thresholds and tune based on real data. The alert manager's deduplication is critical for preventing alert storms.

### MLflow scalability

MLflow tracking server is not designed for high-throughput trace ingestion. Monitor MLflow's performance under load. If it becomes a bottleneck, consider sampling or adding a dedicated trace backend (Jaeger/Tempo).

### V1.5 metric definition risk

Defining V1.5 trigger metrics too early (before having real deployment data) will produce wrong thresholds. Resist the pressure to set them during this phase. Ship the dashboards, gather data, and define thresholds afterward.

## 10. Definition of Done Mapping

| Definition of done item | Proof artifact |
|---|---|
| All services instrumented with OTel | span coverage in integration test |
| Baggage propagates case context | baggage integration test |
| MLflow shows live traces | dashboard screenshots or automated verification |
| Jaeger exporter is documented | `infra/observability.md`, compose profile |
| All five alert types trigger | alert integration tests |
| Alert manager deduplicates | dedup integration test |
| Alert state accessible via API | `GET /api/alerts` endpoint |
| Observability docs are complete | `infra/observability.md` |

## 11. Suggested PR Slicing

1. `phase6-baggage` — OTel baggage propagation, traced_node helper
2. `phase6-instrumentation` — LangGraph, Pydantic AI, Haystack instrumentation, NATS context propagation
3. `phase6-dashboards` — MLflow ingestion, dashboards, Jaeger exporter path
4. `phase6-alerts` — All five alert types, alert manager, alert API endpoint
5. `phase6-docs` — `infra/observability.md`, updated `infra/sizing.md`

## 12. Immediate Next Action

The first implementation step should be:

1. create `src/wolfpack/observability/baggage.py` with `set_case_baggage()` and `get_case_baggage()`
2. update the Alpha Dispatcher node to set baggage at case creation
3. create the `traced_node()` wrapper for instrumenting LangGraph nodes

That establishes the baggage foundation every other instrumentation task depends on.