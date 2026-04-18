# WolfPack-Agents — Initial Project Plan

*Draft — based on the diagrams and `tech-stack.txt` in `/docs` as of 2026-04-18. Updated with initial design-decision answers from the project owner.*

## 0. Confirmed Design Decisions

These answers from the project owner now anchor the plan:

| # | Topic | Decision |
|---|---|---|
| 1 | Event bus | **NATS** (JetStream) |
| 2 | LLM provider | **Ollama by default, pluggable** for other providers |
| 3 | Tenancy | **Single-tenant, on-prem** |
| 4 | Telemetry adapters | **Tier 1:** Syslog (generic), Windows Event Logs, CrowdStrike Falcon, Okta, generic firewall logs. **Tier 2:** Zeek/Suricata, DNS logs, Cloudflare/generic proxy, AWS CloudTrail |
| 5 | Action authority | **Read-only** in V1 |
| 6 | Ledger immutability | **Hash-chained entries** |
| 7 | Case-state concurrency | **Per-branch sub-state** |
| 8 | Analyst approval | **Per-case, any analyst** |
| 11 | Retention / erasure | **User-configurable retention, default 1yr; crypto-shredding keys** for erasure (open to discussion) |
| 12 | Analyst-review SLA | **Timeout / auto-escalation** path |
| 13 | `CaseState` source of truth | **Pydantic models in `schemas/`, derive LangGraph TypedDict from them** |
| 14 | Scribe | **Non-LLM in V1**, designed to accept an LLM later |
| 15 | Observability backend | **MLflow primary**, design to slot Jaeger in later |
| 16 | Knowledge store | **Haystack** (backend choice still open — see §7) |

Still open: **(9) PII handling / redaction**, **(10) confidence semantics & calibration** — both TBD.

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
- Monorepo layout: `orchestrator/` (LangGraph), `agents/` (Pydantic AI), `rag/` (Haystack), `schemas/` (shared Pydantic models), `adapters/` (telemetry integrations), `infra/`, `tests/`.
- Python toolchain (uv/poetry), pre-commit (ruff, mypy, pytest), devcontainer, docker-compose stack: Postgres + **NATS JetStream** + OTel Collector + **MLflow** + **Ollama**.
- LLM provider abstraction: a small `LLMClient` interface with an `OllamaClient` default and a pluggable registry for OpenAI / Anthropic / Bedrock / local-vLLM implementations (driven by config, no code changes to swap).
- CI: lint, typecheck, unit tests, container build. Single-tenant deployment target (no multi-tenant plumbing).

### Phase 1 — Contracts & case state (≈1–2 weeks)
- Shared Pydantic models in `schemas/`: `Seed`, `Entity`, `Hypothesis`, `EvidenceRef`, `CaseState`, `BranchState`, `BranchSpec`, per-agent `Input`/`Output`. **LangGraph `TypedDict`s are derived from these Pydantic models** (single source of truth — no hand-maintained duplication).
- Postgres schema for `cases`, `branches`, `hypotheses`, `pivots`, `evidence_ledger`, `learning_queue`, `retention_policy`, `crypto_shred_keys`.
- **Per-branch sub-state**: each branch carries its own `BranchState` row; `CaseState` is an aggregate view. Optimistic versioning (`version` column + CAS updates) to prevent Flanker/Tracker write conflicts during parallel work.
- **Hash-chained evidence ledger**: each row stores `prev_hash` + `content_hash`; computed via a Postgres trigger on insert; a `verify_chain(case_id)` SQL function and a replay tool validate integrity.
- **Retention & crypto-shredding**: each case row references a per-case or per-tenant encryption key stored in `crypto_shred_keys`; erasure deletes the key while tombstoning the rows. Default retention = 1 year, overridable per deployment.
- Baseline governance fixtures: `retention_policy` seeded with the 1-year default.

### Phase 2 — Orchestration skeleton (≈1–2 weeks)
- LangGraph graph with `alpha_dispatcher`, `tracker`, `flanker`, `closer`, `scribe`, `review` nodes using mock (deterministic) agent stubs.
- **NATS JetStream** subjects: `hunt.task.*`, `hunt.finding.*`, `hunt.branch.*`, `hunt.status.*`; durable consumers per agent with ack/redeliver semantics.
- `review` node supports **timeout → auto-escalate** (configurable deadline; on expiry, LangGraph transitions the case to an escalated outcome and records the timeout on the ledger).
- Scribe implemented as a **non-LLM service** behind a `ScribeInterface` (drop-in point for a future LLM-backed narrative scribe).
- Happy-path integration test: seed → closed case, full hash-chained ledger present, trace visible in MLflow. Chaos test: kill NATS mid-case, confirm replay from ledger.

### Phase 3 — Tracker + RAG + Tier-1 adapters (≈2–3 weeks)
- Haystack pipelines for threat intel (ATT&CK, CVE, IOC feeds) and case history; expose as Pydantic AI tools.
- **Tier-1 telemetry adapters** (must ship with V1): generic **Syslog**, **Windows Event Logs**, **CrowdStrike Falcon**, **Okta**, **generic firewall logs**. Each adapter implements a common `TelemetrySource` interface (`query(entity, time_window, filters) -> Events`) so agents remain adapter-agnostic.
- Tracker agent implemented with Ollama as the default LLM (pluggable), wired to the Tier-1 adapters and the Haystack intel tool.
- Evaluation harness: golden-set hunts with known outcomes; MLflow-tracked metrics (precision of initial hypothesis, calibration of `tracker_confidence`).

### Phase 4 — Flanker + branching + Tier-2 adapters (≈2–3 weeks)
- Flanker agent with lateral-pivot tools spanning the Tier-1 adapters plus **Tier-2 adapters**: **Zeek/Suricata**, **DNS logs**, **Cloudflare / generic proxy**, **AWS CloudTrail**.
- LangGraph branch creation writes new `BranchState` rows; routing and concurrency use the per-branch sub-state model from Phase 1.
- Branch-explosion controls: max-depth, max-branches per case, dedup on hypothesis similarity hashes, token/tool budget per branch.
- Tier-2 adapter rollout order can be parallelized across the phase; each lands behind a feature flag so a deployment can ship with just a subset enabled.

### Phase 5 — Closer + Analyst Review UI (≈2–3 weeks)
- Closer agent emitting verdict packets.
- Minimal Analyst Console (web UI) for queue, case view with timeline, verdict review, **per-case learning-approval toggle (any analyst can approve)**, and case-outcome choice.
- Policy guardrails displayed alongside the verdict.
- Review timeout configurable per deployment; the UI shows remaining time and the auto-escalation target.

### Phase 6 — Observability hardening (≈1 week)
- OTel across all three services, consistent `case_id` / `branch_id` / `agent_run_id` span attributes propagated as OTel baggage.
- **MLflow** dashboards (primary): per-agent latency, tool call counts, retry rates, eval scores, per-branch token spend.
- Collector config kept backend-agnostic: a `jaeger` exporter block is included but disabled-by-default so Jaeger/Tempo can be slotted in later without code changes.
- Alerting on schema-retry spikes, ledger-hash mismatch, runaway branch depth, review-timeout auto-escalations, NATS consumer lag.

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

Most items from the first draft are now resolved in §0. The ones still open:

### Still TBD
- **(9) PII / data-handling.** SOC telemetry contains user identifiers, URLs, file paths, and sometimes email bodies. Even with Ollama on-prem (no external egress), we still need a policy for what reaches the model context window — redaction rules, entity-type allowlists, and whether analysts can opt-in richer context per case. Default stance for V1 needs to be decided before Phase 3.
  - *Proposed default until decided:* deterministic redaction of free-text fields (emails, bodies) into hashed tokens that agents can correlate but not read, with a break-glass "show raw" toggle that's audit-logged on the ledger.
- **(10) Confidence semantics & calibration.** `tracker_confidence` and Closer's `confidence` field need a shared definition and a rubric. Proposals: (a) a calibrated probability with a golden-set evaluation harness, or (b) an ordinal 1–5 scale with written anchors. Decision needed before Phase 3 so the routing rule "if confidence < X, re-run Flanker" is meaningful.
- **Knowledge-store backend.** Haystack is confirmed, but Haystack sits in front of OpenSearch / Elasticsearch / Weaviate / Qdrant / pgvector. Given the on-prem single-tenant constraint, **pgvector** is the simplest choice (reuses the Postgres already in stack); **OpenSearch** is the richer option if full-text + vector hybrid matters. Recommend pgvector for V1 unless hybrid ranking is critical.

### Newly surfaced by the answers
- **Crypto-shredding key management.** Per-case, per-tenant, or hierarchical? HSM-backed or software KMS? Key rotation cadence? This needs a design review before Phase 1 ships — the ledger's integrity story depends on it.
- **Ollama model defaults.** Which Ollama model is the V1 default (e.g., Llama 3.1 70B, Qwen 2.5, Mistral)? Affects GPU sizing for the on-prem deployment and the eval baseline.
- **Review-timeout policy.** What is the default timeout duration, and what does "auto-escalate" route to — a separate ticketing system, an on-call pager, or just a case-outcome tag? Minimal V1 default should still be explicit.
- **Tier-2 adapter priority order.** Zeek/Suricata, DNS, Cloudflare/proxy, CloudTrail all land in Phase 4 — which is highest priority if the phase slips?

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

With the answers in §0 captured, the remaining blockers for me are:

1. **PII redaction default (§7-9)** — needed before Phase 3 so the Tracker agent doesn't leak raw identifiers into context.
2. **Confidence rubric (§7-10)** — needed before Phase 3 so we can evaluate Tracker and route on Flanker's re-check loop meaningfully.
3. **Haystack backend choice** — needed before Phase 3. Recommend **pgvector** for V1 simplicity given on-prem single-tenant; please confirm or counter.
4. **Crypto-shredding key-management design** — needed before Phase 1 lands the ledger.
5. **Default Ollama model** — needed for infra sizing and the eval baseline.

Everything else in §7 can be resolved during the relevant phase without blocking earlier work.
