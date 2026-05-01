# Skadi-Agents (WolfPack)

A multi-agent, pack-hunt Security Operations Center (SOC) assistant. WolfPack-Agents triages seeds (IOCs, alerts, anomalies, or analyst-driven hunt queries) by coordinating a small team of specialized AI agents against shared case state and an immutable, hash-chained evidence ledger. Every decision is traceable, replayable, and gated on analyst review before anything enters institutional memory.

## Core ideas

- **Audit trail.** Every agent action, tool call, retrieved document, and state transition is logged to an append-only, hash-chained ledger keyed by case ID.
- **Traceability.** The reasoning path from seed → hypothesis → verdict is reconstructable end-to-end via the ledger and OpenTelemetry traces.
- **Human-in-the-loop.** Nothing enters institutional memory without an analyst's explicit approval; V1 is strictly read-only.

## Agents (V1 pack)

- **Alpha Dispatcher** — normalizes seeds, opens cases, routes tasks.
- **Tracker** — finds the initial credible scent.
- **Flanker** — expands laterally and elevates fresh branches.
- **Closer** — assembles a verdict and next-best action for analyst review.
- **Scribe** — non-LLM logging service that writes structured entries to the ledger.

V1.5 adds a **Blocker** (containment recommendations) and a **Post-Hunt Analyst** (summaries, ATT&CK mapping, lessons learned).

## Stack

| Layer | Choice |
|---|---|
| Orchestration / state machine | LangGraph |
| Agent implementation | Pydantic AI |
| RAG / context | Haystack |
| LLM | Ollama by default, pluggable |
| State & ledger | Postgres (hash-chained evidence table) |
| Event bus | NATS JetStream |
| Observability | OpenTelemetry → MLflow (primary) |
| Deployment | Single-tenant, on-prem |

## Getting started

### Prerequisites

- **Python 3.11** (exact version enforced)
- **uv** — [install](https://docs.astral.sh/uv/getting-started/installation/)
- **Docker** — for the local infrastructure stack
- **Node.js 20+** — for the Analyst Console frontend
- **(Optional) NVIDIA GPU** — for Ollama inference; CPU-only works for the smoke test with `llama3.2:1b`

### Setup

```sh
# Clone and enter the repo
git clone https://github.com/sarahsl-prog/Skadi-Agents.git && cd Skadi-Agents

# Install Python dependencies
uv sync --all-extras --dev

# Install pre-commit hooks
pre-commit install

# Copy and edit environment configuration
cp .env.example .env
# Edit .env for your deployment mode (dev, on_prem_connected, on_prem_airgapped)
```

### Start the local stack

```sh
# Default stack (Postgres, NATS, OTel Collector, Ollama)
docker compose up -d

# Full stack (add MLflow tracking server)
docker compose --profile full up -d

# Stop and clean up
docker compose --profile full down --remove-orphans
```

### Run the smoke test

```sh
# Requires the local stack to be running
just smoke
# Or: uv run python -m wolfpack.smoke.hello_pack
```

This runs a traced LLM call and prints the trace ID, span ID, and OTel endpoint for inspection.

### Common commands

```sh
just install             # Install all dependencies
just fmt                 # Format code (ruff)
just lint                # Lint code (ruff)
just typecheck           # Type-check (mypy strict)
just test                # Run unit tests
just test-integration    # Run integration tests (requires Docker)
just api                 # Start the Analyst Console API server
```

### Analyst Console

```sh
# Start the FastAPI backend
just api

# In a second terminal, start the React frontend
cd console
npm install
npm run dev
```

The Analyst Console is available at `http://localhost:3000` and proxies API calls to the FastAPI backend at `http://localhost:8000`.

### Docker Compose profiles

| Profile | Services | Use case |
|---|---|---|
| default | postgres, nats, otel-collector, ollama | Development, CI |
| full | default + mlflow | Full observability stack |

### GPU overrides

Copy `docker-compose.override.yml.example` to `docker-compose.override.yml` and uncomment the NVIDIA device section. Requires the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html).

## Infrastructure sizing

See [`infra/sizing.md`](infra/sizing.md) for hardware recommendations (enterprise vs. dev/CI profiles).

## Documentation

- [`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md) — phased delivery plan, confirmed design decisions, open questions, and recommendations.
- [`docs/PHASE_0_PLAN.md`](docs/PHASE_0_PLAN.md) — Phase 0 implementation plan.
- [`docs/PHASE_0_IMPLEMENTATION_PLAYBOOK.md`](docs/PHASE_0_IMPLEMENTATION_PLAYBOOK.md) — execution-ready Phase 0 runbook.
- [`docs/tech-stack.txt`](docs/tech-stack.txt) — architecture rationale and a walk-through of a hunt.
- Diagrams in `docs/`:
  - `LangGraph Agent Ecosystem` — service topology.
  - `PackHunter-agents` — agent graph.
  - `PackHunt-swimlane` — swim-lane view across inputs, control, pack, memory, and review.
  - `Threat Hunt sequence` — end-to-end sequence diagram.
  - `Pydantic AI Agents Workflow` — agent implementation view.

## Status

| Phase | Status | Description |
|-------|--------|-------------|
| 0 | Complete | Repo scaffold, config/LLM abstractions, Docker infrastructure, observability, smoke-test CLI, CI |
| 1 | Complete | Pydantic schemas, Postgres schema, hash-chained ledger, crypto-shredding, PII store |
| 2 | Complete | LangGraph graph, deterministic stubs, NATS integration, review timeout, Alpha Dispatcher, Scribe |
| 3 | Complete | Tracker agent, Haystack RAG, Tier-1 adapters, PII pipeline, evaluation harness |
| 4 | Complete | Flanker agent, Tier-2 adapters, branching, budget controls, hypothesis dedup, re-check loop |
| 5 | Complete | Closer agent, Analyst Console (React + FastAPI), break-glass UI, policy guardrails, verdict packet |
| 6 | Complete | OTel instrumentation (LangGraph nodes, Pydantic AI agents, Haystack RAG), baggage propagation, NATS context propagation, alerting layer, MLflow dashboards |
| 7 | Complete | Learning loop (approve → ingest → improved retrieval), replay evaluation, eval harness |
| 8 | Complete | Threat model, red-team tests (prompt injection RAG/tools, allowlist), crypto-shredding dry-run, break-glass audit, secret-handling audit, runbooks, security review, release readiness checklist |

## Security

- [Threat model](docs/security/threat_model.md) — attack surface, mitigations, residual risks
- [Secret-handling audit](docs/security/secret_audit.md) — no secrets in prompts, logs, or spans
- [Security review](docs/security/security_review.md) — final V1 sign-off summary
- [Release readiness](docs/RELEASE_READINESS.md) — checklist and deferred items

## Runbooks

- [Deployment](docs/runbook/deployment.md) — prerequisites, step-by-step, scaling, backup
- [On-call](docs/runbook/oncall.md) — alert catalog, incidents, escalation, rollback
- [Architecture](docs/runbook/architecture.md) — three rings, agent roster, hunt flow, data stores
- [Configuration reference](docs/runbook/configuration.md) — every `Settings` field with `.env` names and defaults

## License

MIT — see [`LICENSE`](LICENSE).