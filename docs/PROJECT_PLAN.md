# WolfPack-Agents — Initial Project Plan

*Draft — based on the diagrams and `tech-stack.txt` in `/docs` as of 2026-04-18.*

## 1. System Purpose

WolfPack-Agents is a multi-agent "pack-hunt" Security Operations Center (SOC) assistant. Seeds (IOCs, alerts, anomalies, or analyst-driven hunt queries) are triaged and expanded by a team of specialized AI agents that coordinate through a shared case state and an immutable evidence ledger. Every decision is traceable, replayable, and gated on analyst review before anything enters institutional memory.

Two properties are non-negotiable:

- **Audit trail** — every agent action, tool call, retrieved document, and state transition is logged to an immutable ledger keyed by case ID.
- **Traceability** — the reasoning path from seed → hypothesis → verdict is reconstructable end-to-end (via the ledger + OpenTelemetry traces).

## 2. Architecture Overview

Three concentric rings (per `tech-stack.txt`):

| Ring | Framework | Responsibility |
|---|---|---|
| Orchestration | **LangGraph** | Case state machine (`New → Scented → Shadowing → Decision → Review → Closed/Continue`), node transitions, branching, event-bus integration |
| Agent implementation | **Pydantic AI** | Type-safe `Agent[InputModel, OutputModel]` per role, tool invocation, retries on schema failure, Logfire → OTel emission |
| Context / RAG | **Haystack** | Threat-intel pipeline (ATT&CK, CVEs, IOC feeds) and case-history pipeline, exposed as tools |

Supporting infrastructure:

- **Postgres** — case state store (cases, hypotheses, pivots, branches) and evidence ledger.
- **Event Bus** — NATS / Redis Streams / Kafka for task/finding/branch/status messages.
- **OpenTelemetry Collector** → **MLflow** (primary UI) and optional Prometheus/Grafana/Jaeger.
- **Policy Guardrails** — approval rules and execution boundaries surfaced to the analyst.

## 3. Agent Roster

**V1 Pack (in scope):**

- **Alpha Dispatcher** — normalizes seed, creates `CaseState`, routes tasks. Light arbitration, not a heavy supervisor.
- **Tracker** — finds the initial credible scent; queries telemetry + threat intel; emits `new_hypotheses`, `updated_entities`, `evidence_refs`, `tracker_confidence`.
- **Flanker** — lateral pivots across hosts/users/DNS/email; can elevate a side signal to a fresh branch (`branches_to_create`).
- **Closer** — assembles verdict packet (decision, confidence, next-best action, evidence refs) for analyst review.
- **Scribe** — logging-only. Transforms structured events into immutable ledger entries and factual case-timeline updates. *No analysis.*

**V1.5 (explicitly deferred):**

- **Blocker** — predict escape paths, recommend containment.
- **Post-Hunt Analyst** — summaries, ATT&CK mapping, lessons learned.

## 4. Hunt Flow (canonical path)

1. Seed arrives → Alpha creates case, starts ledger, publishes initial task.
2. Tracker enriches signals → writes hypothesis + evidence → publishes findings.
3. Flanker pivots laterally → may create branches → notifies Alpha for follow-up tasking.
4. Closer reads case state + pulls final intel → submits verdict to Analyst.
5. Scribe streams log entries to the ledger in parallel throughout.
6. Analyst decides: **approve learning** (→ Learning Queue → case memory), **escalate**, **close benign**, or **continue hunt** (→ back to Alpha).

Nothing enters "institutional memory" without explicit analyst approval — learning is opt-in by design.

## 5. Delivery Plan

Proposed phasing, each phase ends in a demoable slice.

### Phase 0 — Repo & environment bootstrap (≈1 week)
- Monorepo layout: `orchestrator/` (LangGraph), `agents/` (Pydantic AI), `rag/` (Haystack), `schemas/` (shared Pydantic models), `infra/`, `tests/`.
- Python toolchain (uv/poetry), pre-commit (ruff, mypy, pytest), devcontainer, docker-compose for Postgres + event bus + OTel collector + MLflow.
- CI: lint, typecheck, unit tests, container build.

### Phase 1 — Contracts & case state (≈1–2 weeks)
- Shared Pydantic models: `Seed`, `Entity`, `Hypothesis`, `EvidenceRef`, `CaseState`, `BranchSpec`, per-agent `Input`/`Output`.
- Postgres schema for `cases`, `hypotheses`, `pivots`, `branches`, `evidence_ledger`, `learning_queue`.
- Ledger guarantees: append-only, content-addressed hash chain per case for tamper-evidence.
- LangGraph `CaseState` TypedDict mirroring the Pydantic model.

### Phase 2 — Orchestration skeleton (≈1–2 weeks)
- LangGraph graph with `alpha_dispatcher`, `tracker`, `flanker`, `closer`, `scribe`, `review` nodes using mock (deterministic) agent stubs.
- Event bus wiring (pick NATS or Redis Streams first; Kafka later if needed).
- Happy-path integration test: seed → closed case, full ledger present, trace visible in MLflow.

### Phase 3 — Tracker + RAG (≈2 weeks)
- Haystack pipelines for threat intel (ATT&CK, CVE, IOC feeds) and case history; expose as Pydantic AI tools.
- Tracker agent implemented with real LLM, SIEM/EDR adapter stubs, intel tool.
- Evaluation harness: golden-set hunts with known outcomes; MLflow-tracked metrics.

### Phase 4 — Flanker + branching (≈2 weeks)
- Flanker agent with lateral-pivot tools (endpoint/identity/DNS adapters).
- LangGraph branch creation and sub-case routing.
- Tests for branch explosion controls (max-depth, max-branches, dedup on similar hypotheses).

### Phase 5 — Closer + Analyst Review UI (≈2–3 weeks)
- Closer agent emitting verdict packets.
- Minimal Analyst Console (web UI) for queue, case view with timeline, verdict review, learning-approval toggle, case-outcome choice.
- Policy guardrails displayed alongside the verdict.

### Phase 6 — Observability hardening (≈1 week)
- OTel across all three services, consistent `case_id` / `branch_id` / `agent_run_id` span attributes.
- MLflow dashboards: per-agent latency, tool call counts, retry rates, eval scores.
- Alerting on schema-retry spikes, ledger-hash mismatch, runaway branch depth.

### Phase 7 — Learning loop (≈1 week)
- Learning Queue worker: approved entries → Haystack ingestion for case-history index.
- Replay tests: prior cases with learned lessons produce improved similar-case retrieval.

### Phase 8 — V1 release readiness
- Threat-model review, secret-handling audit, red-team prompt-injection tests on RAG and tool inputs, runbook, on-call docs.

V1.5 agents (Blocker, Post-Hunt Analyst) are staged after V1 hardens.

## 6. Cross-cutting Workstreams

- **Security of the system itself.** The agents read attacker-controlled data (alerts, emails, logs). Prompt-injection defense, tool-scope minimization, and output validation are first-class.
- **Evaluation.** A hunt-level golden set plus per-agent unit evals (Tracker hypothesis precision, Flanker branch relevance, Closer verdict calibration).
- **Cost/latency budget.** Per-case token and tool-call budgets, enforced at the LangGraph level.
- **Human factors.** Analyst-console UX is part of the product, not an afterthought — the verdict view is where trust is won or lost.

## 7. Outstanding Design Questions / Clarifications

Items I could not resolve from the docs alone:

1. **Event bus choice.** Docs list NATS / Redis Streams / Kafka as alternatives. What are the deployment and throughput targets? (Recommend starting with NATS JetStream for simplicity unless Kafka is already mandated.)
2. **LLM provider(s).** No model selection is stated. Is this Anthropic / OpenAI / Bedrock / local? Any data-residency or no-egress requirements (common in SOC contexts)?
3. **Tenancy model.** Single-tenant on-prem for one SOC, or multi-tenant SaaS? This affects secrets, ledger partitioning, RBAC on the UI, and deployment topology.
4. **Telemetry adapters in scope for V1.** Which SIEM/EDR/IAM/DNS/email/cloud-log sources must ship with V1? (Splunk? Elastic? Sentinel? CrowdStrike? Defender? Okta?) The diagrams treat them as a monolithic `Telemetry Sources` box.
5. **Action authority.** Does any agent ever *do* something (isolate host, disable user), or is V1 strictly read-only with containment deferred to the V1.5 Blocker? Docs imply read-only; worth confirming and encoding in policy guardrails.
6. **Ledger immutability guarantees.** Append-only Postgres table is simplest, but "immutable timeline / replay trail" could mean hash-chained entries, WORM storage, or external anchoring (e.g., object-lock S3). How strong a tamper-evidence property is required for compliance?
7. **Case-state concurrency.** When Flanker creates branches in parallel with Tracker still working, what is the conflict-resolution model on `CaseState`? (Optimistic versioning in Postgres? Per-branch sub-state?)
8. **Analyst-approval granularity.** Is the approval per-lesson, per-case, or per-playbook-change? And who can approve — any analyst, or tier-2+ only?
9. **PII / data-handling.** SOC telemetry contains user identifiers, URLs, and sometimes email bodies. What redaction happens before data reaches the LLM? Is there an approved-egress list per model?
10. **Definition of "confidence."** Tracker emits `tracker_confidence: float` and Closer a `confidence` field. Is this a calibrated probability, an ordinal score, or a free-form 0–1 float? Calibration matters for the routing rule "if confidence < X, route back to Flanker."
11. **Retention & right-to-erasure.** How long are cases and the ledger retained? If the ledger is truly immutable, how is a GDPR/CCPA erasure request handled (crypto-shredding keys, tombstones, etc.)?
12. **Human-in-loop SLAs.** Is there an expectation that the Closer blocks indefinitely for analyst review, or a timeout/auto-escalate? Affects LangGraph `review` node design.
13. **`CaseState` duplication risk.** Docs say "TypedDict used by LangGraph and mirrored as a Pydantic model." What is the single source of truth, and how is drift prevented — code-gen from one side, or a shared schema module?
14. **Scribe LLM or non-LLM.** Docs offer both. Recommend non-LLM for V1 (see §8) — please confirm.
15. **MLflow as primary observability backend.** MLflow's LLM-observability features are newer; for production-grade distributed tracing you may want Jaeger/Tempo alongside. Is MLflow preferred for the eval story specifically, or for everything?
16. **Knowledge-store choice.** Haystack supports many backends (OpenSearch, Weaviate, Qdrant, pgvector, Elasticsearch). Any preference, or driven by existing infra?

## 8. Recommendations

### Architecture
- **Keep Scribe non-LLM in V1.** It is pure structured-event → ledger-row translation. An LLM adds cost, latency, and a failure mode (hallucinated log entries) for zero upside. Reserve the "Scribe as Pydantic AI agent" option for narrative summaries in V1.5's Post-Hunt Analyst.
- **Single source of truth for `CaseState`.** Define Pydantic models in `schemas/`, and derive the LangGraph `TypedDict` from them (or pass the Pydantic model directly — modern LangGraph supports this). Avoid hand-maintained duplication.
- **Hash-chain the evidence ledger.** Each row stores `prev_hash` + `content_hash`; compute on insert via a Postgres trigger or an append service. Replay validates the chain. Cheap, strong tamper-evidence without WORM infrastructure.
- **Treat the event bus as a fan-out, not the state store.** Case state lives in Postgres; the bus carries work items. This keeps replay deterministic.

### Agent & LLM design
- **Strict tool allowlists per agent.** Tracker doesn't need identity-pivot tools; Closer probably shouldn't hit telemetry directly. Narrow scopes limit the blast radius of a prompt-injection success.
- **Sanitize retrieved content before LLM ingestion.** Threat intel blogs and email bodies are prime injection vectors. Wrap them with explicit delimiters + instruction-repetition defenses, and strip HTML/JS/markdown links on ingestion into Haystack.
- **Calibrate confidence.** Define a rubric (e.g., anchor points at 0.2/0.5/0.8 with examples) and evaluate calibration in the golden-set suite. Otherwise the `confidence < X` routing rule is superstition.
- **Budget enforcement at the LangGraph level.** Per-case caps on tokens, tool calls, branch depth, and wall-clock. Closer gets the remaining budget so it cannot be starved by runaway Flanker branches.

### Observability & evaluation
- **Propagate `case_id`, `branch_id`, `agent_run_id` as OTel baggage.** Every span, log line, and ledger entry should be filterable by these. MLflow + Jaeger/Tempo both benefit.
- **Dual observability backends.** MLflow for LLM eval + dataset versioning; Jaeger or Grafana Tempo for distributed trace exploration. They serve different audiences (ML engineers vs. on-call).
- **Eval-in-CI.** Run a small golden-set against mocked tools in CI to catch prompt/schema regressions before merge.

### Security & compliance
- **Threat-model the agent system early** — attackers will notice SOC agents read their payloads. Document the expected posture on prompt injection, tool abuse, data exfiltration via retrieval, and privilege escalation.
- **Secrets out of prompts.** Tool adapters hold credentials; agents hold reference handles, never raw tokens.
- **Read-only V1.** Defer any action-taking to V1.5 Blocker, behind analyst approval and with strong guardrails. Confirms to analysts that "worst case, it's noisy."

### Product & process
- **Make the Analyst Console a first-class milestone**, not an afterthought. The verdict view, evidence drill-down, and learning-approval flow are where the system's traceability story pays off.
- **Replay-first demos.** Ship a "replay a prior case" feature early — it's the most persuasive artifact for showing the audit trail and it doubles as a test harness.
- **Decide V1.5 triggers now.** Define the metrics (analyst-hours saved, false-positive rate, branch-elevation precision) that gate Blocker and Post-Hunt Analyst work, so scope creep is explicit.

## 9. Immediate Asks

Before I take this further, the biggest unknowns for me are **(2) LLM provider & data-residency constraints**, **(4) which telemetry adapters ship with V1**, and **(5) whether V1 is strictly read-only**. Answers to those three would most sharply shape Phase 3–5 scope.
