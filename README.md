# WolfPack-Agents

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

## Documentation

- [`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md) — phased delivery plan, confirmed design decisions, open questions, and recommendations.
- [`docs/tech-stack.txt`](docs/tech-stack.txt) — architecture rationale and a walk-through of a hunt.
- Diagrams in `docs/`:
  - `LangGraph Agent Ecosystem` — service topology.
  - `PackHunter-agents` — agent graph.
  - `PackHunt-swimlane` — swim-lane view across inputs, control, pack, memory, and review.
  - `Threat Hunt sequence` — end-to-end sequence diagram.
  - `Pydantic AI Agents Workflow` — agent implementation view.

## Status

Pre-implementation. The architecture and delivery plan are drafted; the codebase has not been scaffolded yet. See the project plan for phasing.

## License

MIT — see [`LICENSE`](LICENSE).
