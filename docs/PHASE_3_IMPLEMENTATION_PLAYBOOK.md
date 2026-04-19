# Phase 3 Implementation Playbook — Tracker + RAG + Tier-1 Adapters

This document turns the Phase 3 plan from [`PROJECT_PLAN.md`](./PROJECT_PLAN.md) into an execution-ready implementation plan.

## 0. Outstanding Design Questions

| # | Question | Decision needed by | Default if unresolved | Notes |
|---|----------|--------------------|-----------------------|-------|
| D1 | **NER model for PII stripping** — spaCy, Microsoft Presidio, or a small LLM? | Start of Track C | Microsoft Presidio with custom recognizer packs for SOC-specific identifiers (IPs, CIDR ranges, hostnames) | Presidio is the most security-appropriate choice: it ships pattern libraries for IPs, emails, credit cards, and supports custom recognizers. spaCy is lighter but less domain-tuned. A small LLM adds latency and prompt-injection risk. Presidio also integrates with the per-case pseudonymization salts from Phase 1. |
| D2 | **Haystack index strategy** — single pgvector index or separate threat-intel and case-history indexes? | Start of Track B | Separate indexes: `threat_intel_idx` for ATT&CK/CVE/IOC feeds, `case_history_idx` for prior cases | Separate indexes allow different embedding models, different update cadences (threat intel updates frequently; case history grows slowly), and different retrieval strategies (keyword-heavy for threat intel, semantic-heavy for case history). |
| D3 | **Tracker tool scope** — should Tracker have direct database query capability, or only NATS-mediated lookups? | Start of Track D | Tracker queries telemetry adapters directly (via tools) and RAG pipelines (via tools); it does NOT query the Postgres case-state database directly | This keeps Tracker's blast radius narrow: it can read external data but cannot modify case state. All state mutations go through the graph. |
| D4 | **Embedding model for pgvector indexes** — A2 says "configurable (default: sentence-transformers or Ollama embedding endpoint)" without choosing. The choice sets the vector dimensions and whether a separate model download is needed. Options: `sentence-transformers/all-MiniLM-L6-v2` (CPU, 384-dim, no GPU), or Ollama embedding endpoint (e.g., `nomic-embed-text`, GPU-backed, 768-dim). | Before Track A2 (threat-intel pipeline) | Ollama embedding endpoint (`nomic-embed-text`) — keeps the stack GPU-consistent and avoids pulling a second model framework; dimensions are configurable | CPU sentence-transformers avoid GPU scheduling contention and are faster for small batches. But running two model-serving frameworks (Ollama + sentence-transformers) for a single-tenant system adds operational complexity. Ollama already serves the LLM; embedding via Ollama reuses the same process. |
| D5 | **Hybrid search weighting (BM25 vs. vector)** — A2 specifies "hybrid search (keyword + semantic)" but the BM25/vector combination alpha needs a default. At α=0 the result is pure BM25 (keyword); at α=1 it is pure vector (semantic). The right default differs between threat-intel (keyword-heavy: exact IOC/CVE matching) and case-history (semantic-heavy: narrative similarity). | Before Track A2 and A3 | `threat_intel_idx`: α=0.3 (keyword-dominant); `case_history_idx`: α=0.7 (semantic-dominant). Both configurable via settings. | IOC and CVE lookups need exact-match precision — BM25 dominates. Case-history retrieval is about "similar prior investigations" — semantic similarity dominates. Starting with different alpha defaults per index and tuning via the evaluation harness (E) is safer than a single global default. |

## 1. Current Baseline

The repository has (from Phases 0–2):

- `src/wolfpack/schemas/` — full Pydantic domain models
- `src/wolfpack/orchestrator/` — LangGraph graph with stub nodes, NATS integration, review timeout
- `src/wolfpack/agents/alpha.py` — Alpha Dispatcher wired to Pydantic AI
- `src/wolfpack/agents/scribe.py` — Scribe service writing to evidence ledger
- Postgres schema with all tables, hash-chained ledger, crypto-shredding
- NATS JetStream integration for inter-agent messaging
- Docker Compose stack with pgvector-enabled Postgres

The repository does **not** yet have:

- Haystack pipeline implementations
- Telemetry adapter implementations (even stubs)
- PII pre-processing layer
- Tracker agent implementation
- Confidence calibration anchors
- Evaluation harness or golden set
- Any real agent intelligence beyond Alpha

## 2. Phase Objective

Deliver the Tracker agent with real intelligence:

- Haystack RAG pipelines over pgvector for threat intel and case history
- Tier-1 telemetry adapters (Syslog, Windows Event Logs, CrowdStrike Falcon, Okta, generic firewall)
- PII pre-processing layer (deterministic pseudonymization + NER-based stripping)
- Tracker agent using Llama 3.3 70B Instruct via Ollama (pluggable)
- Confidence ordinal 1–5 with written anchors
- Evaluation harness with golden-set hunts and MLflow-tracked metrics

No Flanker, Closer, or Tier-2 adapters should land during this phase.

## 3. Execution Strategy

Five implementation tracks:

1. Haystack RAG pipelines
2. Tier-1 telemetry adapters and `TelemetrySource` interface
3. PII pre-processing layer
4. Tracker agent implementation
5. Evaluation harness and golden set

The critical path is:

1. define the `TelemetrySource` interface and `RAGTool` interface
2. implement Haystack pipelines (threat intel and case history)
3. implement Tier-1 adapters
4. implement PII pre-processing
5. wire Tracker with tools, LLM, and confidence output
6. build evaluation harness and golden set

## 4. Work Breakdown Structure

### Track A: Haystack RAG Pipelines

Purpose: provide threat-intel and case-history retrieval as tools the Tracker can invoke.

#### A1. Implement RAG pipeline interface

Tasks:

- Create `src/wolfpack/rag/__init__.py` with `RAGPipeline` abstract base class:
  - `async def index(documents: list[Document]) -> None`
  - `async def retrieve(query: str, top_k: int = 5, filters: dict | None = None) -> list[Document]`
- Create `src/wolfpack/rag/base.py` with shared utilities: embedding model selection, pgvector connection helpers.

Deliverables:

- `src/wolfpack/rag/base.py`

Acceptance checks:

- `RAGPipeline` interface is defined and importable
- pgvector connection helpers work against local Postgres

#### A2. Implement threat-intel pipeline

Tasks:

- Create `src/wolfpack/rag/threat_intel.py`.
- Implement `ThreatIntelPipeline(RAGPipeline)`:
  - Indexing: accepts ATT&CK technique descriptions, CVE records, and IOC feeds.
  - Embedding model: configurable (default: sentence-transformers or Ollama embedding endpoint).
  - Retrieval: hybrid search (keyword + semantic) over pgvector with `threat_intel_idx` index.
  - Returns: relevant ATT&CK techniques, CVEs, and IOC matches with confidence hints.
- Seed with a small set of ATT&CK technique descriptions for testing.

Deliverables:

- `src/wolfpack/rag/threat_intel.py`

Acceptance checks:

- pipeline indexes a batch of threat-intel documents
- retrieval returns relevant results for a threat-intel query
- pgvector index is created and populated

#### A3. Implement case-history pipeline

Tasks:

- Create `src/wolfpack/rag/case_history.py`.
- Implement `CaseHistoryPipeline(RAGPipeline)`:
  - Indexing: accepts closed case summaries (from the learning queue, Phase 7).
  - Retrieval: semantic search over prior cases with `case_history_idx` index.
  - Returns: similar past cases with verdicts and outcomes.
- For now, populate with synthetic case data for testing.

Deliverables:

- `src/wolfpack/rag/case_history.py`

Acceptance checks:

- pipeline indexes case-history documents
- retrieval returns similar cases for a given query
- separate from the threat-intel index

#### A4. Expose RAG pipelines as Pydantic AI tools

Tasks:

- Create `src/wolfpack/rag/tools.py`.
- Implement `threat_intel_tool` — a Pydantic AI tool that:
  - Accepts a query string and optional filters.
  - Calls `ThreatIntelPipeline.retrieve()`.
  - Returns structured results (techniques, CVEs, IOCs).
- Implement `case_history_tool` — a Pydantic AI tool that:
  - Accepts a query string.
  - Calls `CaseHistoryPipeline.retrieve()`.
  - Returns structured case summaries.
- Sanitize retrieved content before returning to the agent: strip HTML/JS/markdown links, wrap in explicit delimiters with instruction-repetition defense.

Deliverables:

- `src/wolfpack/rag/tools.py`

Acceptance checks:

- tools are callable as Pydantic AI tools
- retrieved content is sanitized (no raw HTML/JS in output)
- tools return structured, typed results

#### A5. Add RAG integration tests

Tasks:

- Add `tests/integration/test_rag_pipeline.py`.
- Test: index threat-intel documents → retrieve → verify relevance.
- Test: index case-history documents → retrieve → verify similarity.
- Test: sanitization removes HTML/JS from retrieved content.

Deliverables:

- `tests/integration/test_rag_pipeline.py`

Acceptance checks:

- both pipelines work end-to-end against local Postgres + pgvector
- sanitization is verified

### Track B: Tier-1 Telemetry Adapters

Purpose: provide the Tracker with structured telemetry data from real sources.

#### B1. Define `TelemetrySource` interface

Tasks:

- Create `src/wolfpack/adapters/__init__.py` (update the existing placeholder).
- Define `TelemetrySource` abstract base class:
  - `name: str` — adapter identifier (e.g., `"syslog"`, `"crowdstrike_falcon"`).
  - `async def query(entity: Entity, time_window: TimeWindow, filters: dict | None = None) -> list[Event]`
  - `async def health_check() -> bool`
- Create `src/wolfpack/adapters/base.py` with `Event` and `TimeWindow` models.

Deliverables:

- `src/wolfpack/adapters/base.py`

Acceptance checks:

- `TelemetrySource` interface is defined and importable
- `Event` and `TimeWindow` models are structured and serializable

#### B2. Implement Syslog adapter

Tasks:

- Create `src/wolfpack/adapters/syslog.py`.
- Implement `SyslogSource(TelemetrySource)`:
  - Reads from a local syslog file or UDP receiver (configurable).
  - Parses common syslog formats (RFC 3164, RFC 5424).
  - `query()` filters by entity (hostname, IP) and time window.
  - Returns structured `Event` objects.

Deliverables:

- `src/wolfpack/adapters/syslog.py`

Acceptance checks:

- adapter parses RFC 3164 and RFC 5424 syslog entries
- `query()` returns events matching the entity and time window
- `health_check()` returns `True` when the source is available

#### B3. Implement Windows Event Log adapter

Tasks:

- Create `src/wolfpack/adapters/windows_eventlog.py`.
- Implement `WindowsEventLogSource(TelemetrySource)`:
  - Reads from a remote Windows event log via WinRM or from exported EVTX files.
  - Parses Security, System, and Application event logs.
  - `query()` filters by entity (hostname, username) and time window.

Deliverables:

- `src/wolfpack/adapters/windows_eventlog.py`

Acceptance checks:

- adapter parses EVTX-format event entries
- `query()` returns events matching the entity and time window

#### B4. Implement CrowdStrike Falcon adapter

Tasks:

- Create `src/wolfpack/adapters/crowdstrike.py`.
- Implement `CrowdStrikeSource(TelemetrySource)`:
  - Queries the CrowdStrike Falcon API (or reads from a Falcon stream export).
  - `query()` retrieves detection and audit events for an entity.
  - Handles API rate limiting and pagination.

Deliverables:

- `src/wolfpack/adapters/crowdstrike.py`

Acceptance checks:

- adapter authenticates with the Falcon API (using mocked credentials in tests)
- `query()` returns structured detection events
- rate limiting is handled gracefully

#### B5. Implement Okta adapter

Tasks:

- Create `src/wolfpack/adapters/okta.py`.
- Implement `OktaSource(TelemetrySource)`:
  - Queries the Okta System Log API.
  - `query()` retrieves authentication and access events for an entity (user, IP).
  - Handles API pagination and rate limiting.

Deliverables:

- `src/wolfpack/adapters/okta.py`

Acceptance checks:

- adapter queries the Okta System Log (mocked in tests)
- `query()` returns authentication events
- pagination works for large result sets

#### B6. Implement generic firewall log adapter

Tasks:

- Create `src/wolfpack/adapters/firewall.py`.
- Implement `FirewallSource(TelemetrySource)`:
  - Parses common firewall log formats (iptables, pfSense, Palo Alto).
  - `query()` filters by entity (IP, port) and time window.

Deliverables:

- `src/wolfpack/adapters/firewall.py`

Acceptance checks:

- adapter parses iptables and Palo Alto log formats
- `query()` returns firewall events matching the entity and time window

#### B7. Expose adapters as Pydantic AI tools

Tasks:

- Create `src/wolfpack/adapters/tools.py`.
- Implement a tool factory that creates Pydantic AI tools from registered `TelemetrySource` instances:
  - `telemetry_query_tool(source_name, entity, time_window, filters)` — queries a specific telemetry source.
  - Tool names are scoped by adapter: `syslog_query`, `crowdstrike_query`, etc.
  - Returns structured `Event` objects.

Deliverables:

- `src/wolfpack/adapters/tools.py`

Acceptance checks:

- tools are callable as Pydantic AI tools
- each tool queries the correct adapter
- results are structured `Event` objects

#### B8. Add adapter unit tests

Tasks:

- Add `tests/unit/test_adapters.py`.
- Test each adapter with mocked data sources (no real API calls).
- Test `TelemetrySource` interface compliance for all adapters.
- Test tool factory creates correct tool instances.

Deliverables:

- `tests/unit/test_adapters.py`

Acceptance checks:

- all adapters pass unit tests with mocked data
- interface compliance is verified for all adapters
- tool factory tests pass

### Track C: PII Pre-Processing Layer

Purpose: protect agent context from containing raw PII and adversarial content.

#### C1. Implement deterministic pseudonymization

Tasks:

- Create `src/wolfpack/processing/pii.py` (extend the Phase 1 PII module).
- Implement `PseudonymizationLayer`:
  - Uses the per-case salt from `pii_salts` table.
  - `pseudonymize(identifier, identifier_type, case_id) -> str` — deterministic token (e.g., `user_a42`, `host_b17`, `ip_c99`).
  - `depseudonymize(token, case_id) -> str | None` — reverse lookup for break-glass.
  - Maintains a per-case token cache to avoid repeated DB lookups within a session.

Deliverables:

- `src/wolfpack/processing/pii.py`

Acceptance checks:

- pseudonymization is deterministic per case
- different cases produce different tokens for the same input
- token cache avoids repeated DB lookups

#### C2. Implement NER-based stripping

Tasks:

- Create `src/wolfpack/processing/ner.py`.
- Implement `NERStripper`:
  - Uses Microsoft Presidio with custom recognizers for SOC-specific identifiers.
  - Custom recognizers: IP addresses, CIDR ranges, MAC addresses, hostnames, email addresses, URLs with query parameters.
  - `strip_pii(text: str) -> tuple[str, dict[str, str]]` — returns stripped text and a mapping of original → placeholder.
  - Placeholders use deterministic tokens from the pseudonymization layer when a case context is available.
- Add `presidio` and relevant NER model dependencies to `pyproject.toml`.

Deliverables:

- `src/wolfpack/processing/ner.py`

Acceptance checks:

- NER strips PII from free-text fields (email bodies, chat messages, URL paths)
- custom recognizers detect SOC-specific identifiers
- placeholder mapping is preserved for break-glass reversal

#### C3. Implement PII pipeline orchestrator

Tasks:

- Create `src/wolfpack/processing/pii_pipeline.py`.
- Implement `PIIPipeline`:
  - Takes raw telemetry events and case context.
  - Applies pseudonymization to identifiers (usernames, hostnames, IPs).
  - Applies NER stripping to free-text fields (email bodies, chat messages).
  - Returns a sanitized event payload safe for agent context.
  - Logs every processing step to the evidence ledger (for audit trail).

Deliverables:

- `src/wolfpack/processing/pii_pipeline.py`

Acceptance checks:

- pipeline produces sanitized events with no raw PII
- pseudonymized identifiers are deterministic
- free-text fields have PII replaced with placeholders
- processing steps are logged to the evidence ledger

#### C4. Implement break-glass endpoint

Tasks:

- Create `src/wolfpack/processing/breakglass.py`.
- Implement break-glass access:
  - `async def show_raw(case_id, analyst_id, field) -> str` — rehydrates pseudonymized identifiers and raw free-text fields for the current analyst session.
  - Every invocation writes to `breakglass_audit` (analyst ID, field accessed, timestamp).
  - Returns the original raw data only after audit logging.

Deliverables:

- `src/wolfpack/processing/breakglass.py`

Acceptance checks:

- break-glass returns original PII
- every invocation is recorded in `breakglass_audit`
- audit log includes analyst ID, field, and timestamp

#### C5. Add PII processing tests

Tasks:

- Add `tests/unit/test_pii_pipeline.py`.
- Test: pseudonymize → strip → verify no raw PII in output.
- Test: break-glass → verify audit log entry.
- Test: NER recognizes SOC-specific identifiers.
- Add `tests/integration/test_pii_pipeline.py` for end-to-end flow against real DB.

Deliverables:

- `tests/unit/test_pii_pipeline.py`
- `tests/integration/test_pii_pipeline.py`

Acceptance checks:

- no raw PII in sanitized output
- break-glass audit trail is complete
- NER custom recognizers work

### Track D: Tracker Agent Implementation

Purpose: build the Tracker agent with real LLM intelligence and tools.

#### D1. Implement Tracker agent

Tasks:

- Create `src/wolfpack/agents/tracker.py`.
- Implement `TrackerAgent` as a Pydantic AI agent:
  - Input: `TrackerInput` (seed, entity list, initial context).
  - Output: `TrackerOutput` (hypotheses, updated entities, evidence refs, tracker_confidence).
  - Tools available:
    - `threat_intel_tool` — query threat-intel RAG pipeline.
    - `case_history_tool` — query case-history RAG pipeline.
    - `telemetry_query_tool` — query telemetry adapters (each registered adapter is a separate tool).
  - Uses Llama 3.3 70B Instruct via `get_model()` from the LLM factory.
  - Returns `Confidence` ordinal with written anchors (coincidence, weak, plausible, strong, high-fidelity).
- Wire Tracker into the LangGraph graph, replacing `stub_tracker`.

Deliverables:

- `src/wolfpack/agents/tracker.py`

Acceptance checks:

- Tracker processes a seed and returns structured `TrackerOutput`
- confidence value is in the 1–5 ordinal range
- all tool calls go through Pydantic AI tool interface

#### D2. Add Tracker tool allowlist enforcement

Tasks:

- Implement tool allowlist per agent in the graph configuration:
  - Tracker can use: `threat_intel_tool`, `case_history_tool`, telemetry query tools.
  - Tracker cannot use: identity-pivot tools, case-modification tools, or any tool not in its allowlist.
- Add allowlist validation at the graph level (before tool dispatch).
- Log allowlist violations to the evidence ledger.

Deliverables:

- tool allowlist enforcement in `src/wolfpack/orchestrator/graph.py`

Acceptance checks:

- Tracker can only invoke allowed tools
- attempts to invoke disallowed tools are blocked and logged

#### D3. Implement confidence calibration anchors

Tasks:

- Create `src/wolfpack/schemas/confidence.py` (update from Phase 1) with:
  - Written anchors for each confidence level (e.g., `1="coincidence: single weak signal, no corroboration"`, `2="weak: multiple signals but inconsistent"`, etc.).
  - `calibrate(confidence, evidence_count, corroboration_level) -> Confidence` helper that adjusts raw confidence based on evidence quality.
- Create a calibration reference document in `docs/confidence_anchors.md`.

Deliverables:

- updated `src/wolfpack/schemas/confidence.py`
- `docs/confidence_anchors.md`

Acceptance checks:

- each confidence level has a written anchor description
- `calibrate()` adjusts confidence based on evidence quality

#### D4. Add Tracker unit tests

Tasks:

- Add `tests/unit/test_tracker.py`.
- Test: Tracker output with mocked LLM and tools.
- Test: tool allowlist enforcement.
- Test: confidence calibration.

Deliverables:

- `tests/unit/test_tracker.py`

Acceptance checks:

- Tracker produces structured output with mocked LLM
- tool allowlist blocks unauthorized tools
- confidence calibration produces expected adjustments

### Track E: Evaluation Harness and Golden Set

Purpose: measure Tracker quality and track improvements.

#### E1. Create golden-set hunts

Tasks:

- Create `tests/eval/` directory.
- Define 5–10 golden-set hunts with known outcomes:
  - Each hunt has: seed input, expected hypotheses, expected confidence level, relevant telemetry data, expected evidence.
  - Scenarios: simple IOC enrichment, multi-signal alert correlation, false-positive identification, lateral movement detection, benign activity confirmation.
- Store golden sets as JSON fixtures in `tests/eval/golden_sets/`.

Deliverables:

- `tests/eval/golden_sets/` directory with JSON fixtures

Acceptance checks:

- each golden set has a clear expected outcome
- golden sets cover diverse scenarios (true positive, false positive, lateral movement, benign)

#### E2. Implement evaluation harness

Tasks:

- Create `src/wolfpack/eval/harness.py`.
- Implement `EvalHarness`:
  - Runs a golden-set hunt through the Tracker (with mocked telemetry and RAG).
  - Compares Tracker output against expected outcomes.
  - Computes metrics: precision of initial hypothesis, distribution of `tracker_confidence` buckets, analyst-agreement proxy.
  - Logs results to MLflow: metrics, parameters, and artifacts.
- Create `just eval` command in the justfile.

Deliverables:

- `src/wolfpack/eval/harness.py`
- `justfile` update

Acceptance checks:

- harness runs golden sets end-to-end
- metrics are logged to MLflow
- `just eval` command works

#### E3. Add evaluation tests

Tasks:

- Add `tests/unit/test_eval_harness.py`.
- Test: harness computes metrics correctly.
- Test: MLflow logging works (with mocked MLflow).

Deliverables:

- `tests/unit/test_eval_harness.py`

Acceptance checks:

- metrics are computed correctly for known inputs
- MLflow logging succeeds

## 5. Recommended Delivery Sequence

1. RAG pipeline interface and base utilities (A1)
2. TelemetrySource interface and Event model (B1)
3. Threat-intel pipeline (A2)
4. Case-history pipeline (A3)
5. Tier-1 adapters (B2–B6)
6. RAG tools (A4)
7. Adapter tools (B7)
8. PII pseudonymization layer (C1)
9. NER stripping (C2)
10. PII pipeline orchestrator (C3)
11. Tracker agent (D1)
12. Tool allowlist (D2)
13. Confidence calibration (D3)
14. Break-glass endpoint (C4)
15. Golden sets (E1)
16. Evaluation harness (E2)
17. Integration and eval tests (A5, B8, C5, D4, E3)

## 6. Parallelization Plan

### Safe parallel lanes after A1 and B1

- Lane 1: Threat-intel pipeline (A2)
- Lane 2: Syslog adapter (B2)
- Lane 3: PII pseudonymization (C1)

### Safe parallel lanes after Track A

- Lane 1: All Tier-1 adapters (B2–B6)
- Lane 2: NER stripping (C2)
- Lane 3: Confidence calibration (D3)

### Work that should stay on the critical path

- TelemetrySource interface must land before adapters
- RAG tools and adapter tools must land before Tracker
- PII pipeline must land before Tracker (Tracker reads sanitized data)
- Tracker agent must land before evaluation harness

## 7. Milestones and Exit Criteria

### Milestone 1: RAG Pipelines Working

Exit criteria:

- both threat-intel and case-history pipelines can index and retrieve
- RAG tools return sanitized, structured results

### Milestone 2: Tier-1 Adapters Working

Exit criteria:

- all five Tier-1 adapters implement the `TelemetrySource` interface
- adapter tools return structured `Event` objects
- adapter unit tests pass with mocked data

### Milestone 3: PII Pipeline Working

Exit criteria:

- pseudonymization is deterministic per case
- NER stripping removes PII from free-text
- break-glass access is audit-logged

### Milestone 4: Tracker Agent Functional

Exit criteria:

- Tracker processes a seed and returns structured `TrackerOutput`
- tool allowlist prevents unauthorized tool access
- confidence values include written anchors

### Milestone 5: Phase 3 Complete

Exit criteria:

- golden-set evaluation passes
- metrics are tracked in MLflow
- all integration tests pass
- no raw PII in agent context

## 8. Command-Level Validation Checklist

```bash
uv sync
just lint
just typecheck
just test
just test-integration
just eval
```

All of these should succeed before Phase 3 is marked complete.

## 9. Risks to Watch During Execution

### Presidio NER model size risk

Presidio requires an NLP model (typically spaCy or a transformer). The model size affects cold-start latency and memory. Test with the smallest viable model first and document the tradeoff.

### Adapter API stability risk

CrowdStrike Falcon and Okta APIs may change or require specific API versions. Pin API versions in the adapter configuration and mock thoroughly.

### RAG retrieval quality risk

Retrieval quality depends on the embedding model and chunking strategy. Start with sentence-transformers (lightweight) and iterate. Do not over-optimize retrieval in this phase — the evaluation harness will measure it.

### PII false positive risk

Over-aggressive NER stripping can remove useful context (e.g., stripping "admin" from a hostname that happens to match a person name). Tune recognizers for SOC-specific patterns and validate against the golden set.

### Confidence calibration risk

The 1–5 ordinal scale needs calibration data from the golden set. Without real analyst feedback, the anchors are theoretical. Document this as a known limitation and refine in Phase 6 when real eval data is available.

## 10. Definition of Done Mapping

| Definition of done item | Proof artifact |
|---|---|
| RAG pipelines index and retrieve | `threat_intel.py`, `case_history.py`, integration tests |
| Tier-1 adapters implement `TelemetrySource` | all five adapters, unit tests |
| PII pipeline produces sanitized output | `pii_pipeline.py`, NER tests |
| Break-glass is audit-logged | `breakglass.py`, integration test |
| Tracker produces structured output with confidence | `tracker.py`, unit test |
| Tool allowlist is enforced | graph-level validation, test |
| Confidence anchors are documented | `confidence.py`, `confidence_anchors.md` |
| Golden sets evaluate Tracker | `tests/eval/`, harness, MLflow metrics |

## 11. Suggested PR Slicing

1. `phase3-rag-base` — RAG interface, threat-intel pipeline, case-history pipeline
2. `phase3-adapters` — TelemetrySource interface, all five Tier-1 adapters, adapter tools
3. `phase3-pii` — PII pseudonymization, NER stripping, pipeline orchestrator, break-glass
4. `phase3-tracker` — Tracker agent, tool allowlist, confidence calibration
5. `phase3-eval` — Golden sets, evaluation harness, MLflow tracking

## 12. Immediate Next Action

The first implementation step should be:

1. define the `TelemetrySource` interface and `Event` model in `src/wolfpack/adapters/base.py`
2. define the `RAGPipeline` interface in `src/wolfpack/rag/base.py`
3. implement the threat-intel pipeline

That establishes the interfaces every adapter and RAG tool depends on.