# WolfPack-Agents — Initial Project Plan

*Draft — based on the diagrams and `tech-stack.txt` in `/docs` as of 2026-04-18. Updated with initial design-decision answers from the project owner.*

## 0. Confirmed Design Decisions

These answers from the project owner now anchor the plan:

| # | Topic | Decision |
|---|---|---|
| 1 | Event bus | **NATS** (JetStream) |
| 2 | LLM provider | **Ollama by default**; pluggable across **local Ollama**, **Ollama Cloud** (dev only), **vLLM**, and **LM Studio** |
| 2a | Default model | **Llama 3.3 70B Instruct** at **FP8/BF16** reference precision (Q4_K_M published alongside as a "lightweight reference") |
| 2b | Hardware target | **Enterprise profile (a)** — ≥1× H100/H200 (80GB) or 2× L40S. Reference deployment assumes this class of GPU. |
| 3 | Tenancy | **Single-tenant, on-prem** |
| 4 | Telemetry adapters | **Tier 1:** Syslog (generic), Windows Event Logs, CrowdStrike Falcon, Okta, generic firewall logs. **Tier 2:** Zeek/Suricata, DNS logs, Cloudflare/generic proxy, AWS CloudTrail |
| 4a | Tier-2 priority (on-prem bias) | **DNS → Zeek/Suricata → Cloudflare/proxy → AWS CloudTrail** |
| 5 | Action authority | **Read-only** in V1 |
| 6 | Ledger immutability | **Hash-chained entries** |
| 7 | Case-state concurrency | **Per-branch sub-state** |
| 8 | Analyst approval | **Per-case, any analyst** |
| 9 | PII redaction | **Deterministic pseudonymization** of identifiers with a **per-case salt**; NER-based stripping of free-text fields before context assembly; **audit-logged "show raw" break-glass** for analysts |
| 10 | Confidence semantics | **Ordinal 1–5 with written anchors** (`1` coincidence, `2` weak, `3` plausible, `4` strong, `5` high-fidelity); routing rule: "if Tracker confidence < 3, re-run Flanker" |
| 11 | Retention / erasure | **User-configurable retention, default 1yr**; erasure via **crypto-shredding** — per-case DEK wrapped by per-deployment KEK in local KMS |
| 12 | Analyst-review SLA | **24-hour default timeout**; on expiry, **auto-escalate** with case-outcome tag `analyst_timeout_escalation` + configurable webhook (ticketing/pager) |
| 13 | `CaseState` source of truth | **Pydantic models in `schemas/`, derive LangGraph TypedDict from them** |
| 14 | Scribe | **Non-LLM in V1**, designed to accept an LLM later |
| 15 | Observability backend | **MLflow primary**, design to slot Jaeger in later |
| 16 | Knowledge store | **Haystack over pgvector** (reuses the Postgres already in stack) |
| 17 | Alpha Dispatcher | **LLM-backed** (for flexibility across varying seed formats), same default model as the pack |
| 18 | Deployment mode flag | `dev` \| `on_prem_connected` \| `on_prem_airgapped` — hosted backends (Ollama Cloud, any API) are hard-failed at config load in `on_prem_airgapped` |

All items open at the previous draft are now resolved. Remaining discussion items are operational details (see §7).

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
- Monorepo layout: `orchestrator/` (LangGraph), `agents/` (Pydantic AI), `rag/` (Haystack), `schemas/` (shared Pydantic models), `adapters/` (telemetry integrations), `llm/` (LLM client abstraction), `infra/`, `tests/`.
- Python toolchain (uv), pre-commit (ruff, mypy, pytest), devcontainer, docker-compose stack: Postgres (with **pgvector** extension) + **NATS JetStream** + OTel Collector + **MLflow** + **Ollama** (with **Llama 3.3 70B Instruct** pulled).
- **LLM provider abstraction** (`llm/`): two concrete clients built on Pydantic AI's `Model` abstraction —
  - `OllamaClient` — native Ollama API; same class handles local Ollama and Ollama Cloud, differentiated by `base_url` + `api_key`.
  - `OpenAICompatibleClient` — one class for vLLM, LM Studio, and any other OpenAI-compatible server.
- **Deployment-mode gating.** `config.deployment_mode ∈ {dev, on_prem_connected, on_prem_airgapped}`. Hosted endpoints (Ollama Cloud, any external API) are validated at config load and hard-fail in `on_prem_airgapped`.
- GPU sizing guide in `infra/`: reference = 1× H100/H200 80GB (FP8/BF16 Llama 3.3 70B); fallback profile = Q4_K_M on 2× 48GB cards documented as "lightweight".
- CI: lint, typecheck, unit tests, container build. Single-tenant deployment target (no multi-tenant plumbing).

### Phase 1 — Contracts & case state (≈1–2 weeks)
- Shared Pydantic models in `schemas/`: `Seed`, `Entity`, `Hypothesis`, `EvidenceRef`, `CaseState`, `BranchState`, `BranchSpec`, `Confidence` (ordinal 1–5 enum with docstring anchors), per-agent `Input`/`Output`. **LangGraph `TypedDict`s are derived from these Pydantic models** (single source of truth — no hand-maintained duplication).
- Postgres schema for `cases`, `branches`, `hypotheses`, `pivots`, `evidence_ledger`, `learning_queue`, `retention_policy`, `crypto_shred_keys`, `pii_salts`, `breakglass_audit`.
- **Per-branch sub-state**: each branch carries its own `BranchState` row; `CaseState` is an aggregate view. Optimistic versioning (`version` column + CAS updates) to prevent Flanker/Tracker write conflicts during parallel work.
- **Hash-chained evidence ledger**: each row stores `prev_hash` + `content_hash`; computed via a Postgres trigger on insert; a `verify_chain(case_id)` SQL function and a replay tool validate integrity.
- **Crypto-shredding architecture**:
  - **Per-case DEK** (data encryption key) generated at case creation, stored wrapped in `crypto_shred_keys`.
  - **Per-deployment KEK** (key encryption key) sits in a local KMS abstraction — Vault/PKCS#11/software-KMS depending on what the customer runs.
  - Erasure request → delete the DEK row; ledger rows remain (hash chain intact) but decrypt to nothing.
  - Key-rotation policy: KEK rotated annually by default, DEKs not rotated (case-bound).
- **PII pseudonymization store**: `pii_salts` holds per-case salts used to hash identifiers; NER pipeline (Phase 3) uses them to produce deterministic tokens. `breakglass_audit` records every "show raw" action.
- Baseline governance fixtures: `retention_policy` seeded with the 1-year default.

### Phase 2 — Orchestration skeleton (≈1–2 weeks)
- LangGraph graph with `alpha_dispatcher`, `tracker`, `flanker`, `closer`, `scribe`, `review` nodes using mock (deterministic) agent stubs.
- **NATS JetStream** subjects: `hunt.task.*`, `hunt.finding.*`, `hunt.branch.*`, `hunt.status.*`; durable consumers per agent with ack/redeliver semantics.
- `review` node supports **24-hour default timeout → auto-escalate**: on expiry, LangGraph transitions the case to outcome `analyst_timeout_escalation`, records the event on the ledger, and fires the configured webhook (ticketing system, pager, etc.).
- Scribe implemented as a **non-LLM service** behind a `ScribeInterface` (drop-in point for a future LLM-backed narrative scribe).
- Alpha Dispatcher wired to its own Pydantic AI agent instance so seed-format variability doesn't require code changes.
- Happy-path integration test: seed → closed case, full hash-chained ledger present, trace visible in MLflow. Chaos test: kill NATS mid-case, confirm replay from ledger.

### Phase 3 — Tracker + RAG + Tier-1 adapters (≈2–3 weeks)
- **Haystack pipelines over pgvector**: threat-intel pipeline (ATT&CK, CVE, IOC feeds) and case-history pipeline, exposed as Pydantic AI tools.
- **Tier-1 telemetry adapters** (must ship with V1): generic **Syslog**, **Windows Event Logs**, **CrowdStrike Falcon**, **Okta**, **generic firewall logs**. Each adapter implements a common `TelemetrySource` interface (`query(entity, time_window, filters) -> Events`) so agents remain adapter-agnostic.
- **PII pre-processing layer** sits between adapters and agent context:
  - Deterministic pseudonymization (per-case salt → `user_a42`, `host_b17`, etc.) for identifiers.
  - NER-based stripping of free-text fields (email bodies, chat messages, URL paths) before they reach the model.
  - "Show raw" break-glass endpoint available only from the Analyst Console, writes to `breakglass_audit`.
- Tracker agent uses **Llama 3.3 70B Instruct** via Ollama (pluggable), wired to the Tier-1 adapters and the Haystack intel tool.
- **Confidence ordinal 1–5**: Tracker returns `Confidence` enum values; written anchors ship alongside the Pydantic schema for reviewer calibration.
- Evaluation harness: golden-set hunts with known outcomes; MLflow-tracked metrics (precision of initial hypothesis, distribution of `tracker_confidence` buckets, analyst-agreement on the anchor scale).

### Phase 4 — Flanker + branching + Tier-2 adapters (≈2–3 weeks)
- Flanker agent with lateral-pivot tools spanning the Tier-1 adapters plus **Tier-2 adapters**, rolled out in on-prem-biased priority order:
  1. **DNS logs** — highest-leverage pivot source (C2 beacons, newly-registered domains, DGA).
  2. **Zeek/Suricata** — rich network-level signal for on-prem customers.
  3. **Cloudflare / generic proxy**.
  4. **AWS CloudTrail** — last, since on-prem-heavy customers use it less.
- LangGraph branch creation writes new `BranchState` rows; routing and concurrency use the per-branch sub-state model from Phase 1.
- Branch-explosion controls: max-depth, max-branches per case, dedup on hypothesis similarity hashes, token/tool budget per branch.
- Flanker re-check loop: if Tracker's `Confidence < 3`, route back to Flanker for additional pivots before Closer runs.
- Each Tier-2 adapter lands behind a feature flag so a deployment can ship with just a subset enabled.

### Phase 5 — Closer + Analyst Review UI (≈2–3 weeks)
- Closer agent emitting verdict packets (decision, `Confidence` ordinal, next-best action, evidence refs).
- Minimal Analyst Console (web UI) for queue, case view with timeline, verdict review, **per-case learning-approval toggle (any analyst can approve)**, and case-outcome choice.
- **Break-glass "show raw" control** in the case view: rehydrates pseudonymized identifiers and raw free-text fields for the current analyst session; every invocation writes to `breakglass_audit`.
- Policy guardrails displayed alongside the verdict.
- Review timeout defaults to **24 hours**, configurable per deployment; the UI shows remaining time and the auto-escalation target/webhook.

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
- Crypto-shredding dry-run: erase a test case, verify ledger hash chain remains intact and rows decrypt to null.
- Break-glass audit review: confirm every invocation is captured in `breakglass_audit` and surfaced on the case timeline.

V1.5 agents (Blocker, Post-Hunt Analyst) are staged after V1 hardens. **Specialist reasoning model for Closer** (DeepSeek-R1 or R1-Distill 70B) is a V1.1 pilot, gated on golden-set verdict-quality data from V1.

## 6. Cross-cutting Workstreams

- **Security of the system itself.** The agents read attacker-controlled data (alerts, emails, logs). Prompt-injection defense, tool-scope minimization, and output validation are first-class.
- **Evaluation.** A hunt-level golden set plus per-agent unit evals (Tracker hypothesis precision, Flanker branch relevance, Closer verdict calibration).
- **Cost/latency budget.** Per-case token and tool-call budgets, enforced at the LangGraph level.
- **Human factors.** Analyst-console UX is part of the product, not an afterthought — the verdict view is where trust is won or lost.

## 7. Outstanding Design Questions / Clarifications

All blocking design questions from earlier drafts are resolved in §0. The remaining items are operational details that can be closed during the phase in which they land:

- **KMS implementation choice.** Phase 1 needs a concrete KMS behind the KEK abstraction. HashiCorp Vault is the safe default for most enterprise customers; cloud KMS (AWS/GCP/Azure) is an alternative for cloud-adjacent deployments; a PKCS#11 HSM is the high-assurance option. A software-only fallback exists for dev. Which concrete KMS ships as the reference (vs. pluggable) is decidable during Phase 1 architecture review.
- **NER model for PII stripping.** Phase 3 needs a concrete choice (spaCy, Presidio, a small LLM). Presidio is the most security-appropriate since it ships pattern libraries for IPs/emails/credit cards; spaCy is lighter but less domain-tuned. Decidable during Phase 3.
- **Analyst Console stack.** Phase 5 needs a front-end choice (React + FastAPI, SvelteKit, or server-rendered). Not blocking earlier work; decidable at Phase 5 kickoff.
- **V1.5 trigger metrics.** Concrete thresholds for analyst-hours saved, false-positive rate, and branch-elevation precision that gate Blocker and Post-Hunt Analyst work. Best defined after the Phase 6 eval dashboards are live with real data.

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

## 9. Status

All blocking design questions are resolved. The plan is ready to move into Phase 0 execution. Remaining items in §7 are phase-scoped operational details that do not block earlier work.

---

## Phase 0 Retro (completed 2026-04-19)

**Actual duration:** ~1 day (Tracks A–C were done on 2026-04-18; Tracks D–G on 2026-04-19).

**What landed:**
- Track A: Repo scaffold, pyproject.toml, uv.lock, justfile, Ruff/mypy/pytest config, pre-commit hooks.
- Track B: DeploymentMode enum, is_loopback_or_private() guard, Settings with pydantic-settings and airgapped enforcement, .env.example.
- Track C: OllamaProvider and OpenAICompatibleProvider wrappers, get_model() factory, LLMConfigError, unit tests with mocked network.
- Track D: docker-compose.yml (5 services, MLflow behind 'full' profile), infra/ configs (postgres init.sql, nats-server.conf, otel-collector-config.yaml, mlflow Dockerfile, ollama entrypoint.sh), sizing.md, override example.
- Track E: OTel TracerProvider bootstrap with OTLP HTTP exporter, Logfire wiring, Typer smoke CLI with traced LLM call.
- Track F: conftest.py shared fixtures, observability unit tests, testcontainers integration tests, real ci.yml replacing blank.yml.
- Track G: README refreshed with getting-started guide, this retro note.

**Deviations from plan:**
- The justfile originally used PowerShell syntax (from a Windows/WSL authoring environment); corrected to POSIX shell.
- Placeholder tests (test_placeholder.py) were removed rather than left as dead weight.
- MLflow is gated behind a Docker Compose profile (`full`) rather than a separate minimal CI profile — functionally equivalent.

**Unresolved risks carried forward:**
- OTel-to-MLflow bridge maturity — Phase 0 uses the debug exporter as the proof point; MLflow trace ingestion is deferred to Phase 6 observability hardening.
- Integration tests require Docker and are skipped by default (`SKIP_INTEGRATION=1`); CI should run them with Docker available.

**Next phase:** Phase 1 — Contracts & case state (schemas, Postgres schema, hash-chained ledger, crypto-shredding architecture).

---

## Phase 8 — V1 Release Readiness

**Planned duration:** 1 week  
**Actual duration:** 1 day (Tracks A–C: 2026-05-01 morning; Tracks D–E: 2026-05-01 afternoon)

**What landed:**
- **Track A:** Threat model (`docs/security/threat_model.md`), red-team prompt-injection tests (RAG + tools), tool-allowlist enforcement tests.
- **Track B:** Crypto-shredding dry-run (`tests/security/test_crypto_shredding.py`), break-glass audit review (`tests/security/test_breakglass_audit.py`).
- **Track C:** Secret-handling audit tests (`tests/security/test_secret_handling.py`), secret audit report (`docs/security/secret_audit.md`), `.gitleaks.toml` allowlist.
- **Track D:** Deployment runbook, on-call runbook, architecture documentation, configuration reference.
- **Track E:** Final security review (`docs/security/security_review.md`), release readiness checklist (`docs/RELEASE_READINESS.md`), performance baseline document, README + PROJECT_PLAN updates.

**Deviations from plan:**
- Live performance benchmark deferred to post-deployment because reference GPU hardware (H100/H200) is not available in the CI/dev environment.
- MLflow dashboard validation with live data deferred to first production deployment.
- Airgapped-mode end-to-end testing deferred; config validation is unit-tested via mocked `Settings`.

**Unresolved risks carried forward:**
- Performance baseline is documented but not measured live.
- MLflow/Jaeger exporter validation requires a running stack with real load.
- V1.5 trigger metrics (Blocker / Post-Hunt Analyst thresholds) remain deferred per original plan.

**Next phase:** V1.5 planning — Blocker agent, Post-Hunt Analyst, token/tool budgets per branch, Jaeger default-on.
