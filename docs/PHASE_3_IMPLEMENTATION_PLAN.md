# Phase 3 Implementation Plan — Tracker + RAG + Tier-1 Adapters

**Objective:** Deliver the first real agent intelligence (Tracker), Haystack RAG pipelines, Tier-1 telemetry adapters, PII pre-processing, and evaluation harness.

**Estimated Duration:** 2–3 weeks  
**Depends on:** Phase 2 (orchestration skeleton)  
**Blocks:** Phase 4 (Flanker + branching + Tier-2 adapters)

---

## 1. Scope

### In Scope
- Haystack RAG pipelines over pgvector (threat intel, case history)
- Tier-1 telemetry adapters: Syslog, Windows Event Logs, CrowdStrike Falcon, Okta, generic firewall
- PII pre-processing layer (deterministic pseudonymization + NER-based stripping)
- Tracker agent using Pydantic AI with tools and confidence ordinal
- Tool allowlist enforcement at graph level
- Confidence calibration anchors
- Evaluation harness with golden-set hunts and MLflow-tracked metrics

### Out of Scope
- Flanker, Closer, or other agents (Tracker only)
- Tier-2 telemetry adapters (DNS, Zeek/Suricata, Cloudflare, CloudTrail)
- Branch creation or management
- Analyst Console or API layer
- Blocker or Post-Hunt Analyst agents (V1.5)

---

## 2. Deliverables

| # | Deliverable | Location | Success Criteria |
|---|-------------|----------|------------------|
| 1 | RAG pipeline interface | `src/wolfpack/rag/base.py` | `RAGPipeline` ABC with `index()` and `retrieve()`; pgvector helpers work |
| 2 | Threat-intel pipeline | `src/wolfpack/rag/threat_intel.py` | Indexes ATT&CK, CVE, IOC; hybrid search (keyword + semantic); α=0.3 keyword-dominant |
| 3 | Case-history pipeline | `src/wolfpack/rag/case_history.py` | Indexes closed cases; semantic search; α=0.7 semantic-dominant |
| 4 | RAG Pydantic AI tools | `src/wolfpack/rag/tools.py` | Sanitized output (strip HTML/JS/markdown); explicit delimiters; instruction-repetition defense |
| 5 | `TelemetrySource` interface | `src/wolfpack/adapters/base.py` | `query(entity, time_window, filters) -> list[Event]`; `health_check()` |
| 6 | Syslog adapter | `src/wolfpack/adapters/syslog.py` | RFC 3164 / RFC 5424 parsing; filters by entity and time window |
| 7 | Windows Event Log adapter | `src/wolfpack/adapters/windows_eventlog.py` | EVTX parsing via WinRM or file; Security/System/Application events |
| 8 | CrowdStrike adapter | `src/wolfpack/adapters/crowdstrike.py` | Falcon API with rate limiting and pagination |
| 9 | Okta adapter | `src/wolfpack/adapters/okta.py` | System Log API with pagination and rate limiting |
| 10 | Firewall adapter | `src/wolfpack/adapters/firewall.py` | iptables, pfSense, Palo Alto parsing |
| 11 | Adapter Pydantic AI tools | `src/wolfpack/adapters/tools.py` | Tool factory per adapter; returns structured `Event` objects |
| 12 | PII pseudonymization | `src/wolfpack/processing/pii.py` | Deterministic per-case; token cache; break-glass reversal |
| 13 | NER stripping | `src/wolfpack/processing/ner.py` | Microsoft Presidio with custom SOC recognizers (IPs, CIDR, MAC, hostnames, emails, URLs) |
| 14 | PII pipeline | `src/wolfpack/processing/pii_pipeline.py` | Sanitizes events; logs steps to evidence ledger |
| 15 | Break-glass endpoint | `src/wolfpack/processing/breakglass.py` | Rehydrates raw data; writes to `breakglass_audit` before returning |
| 16 | Tracker agent | `src/wolfpack/agents/tracker.py` | Pydantic AI agent; `TrackerInput` → `TrackerOutput`; tools: threat_intel, case_history, telemetry queries |
| 17 | Tool allowlist enforcement | `src/wolfpack/orchestrator/graph.py` | Graph-level validation; violations logged to ledger |
| 18 | Confidence anchors | `src/wolfpack/schemas/confidence.py` + `docs/confidence_anchors.md` | Written anchors for ordinal 1–5; `calibrate()` helper |
| 19 | Evaluation harness | `src/wolfpack/eval/harness.py` | Runs golden sets; computes precision, confidence distribution, analyst-agreement proxy; logs to MLflow |
| 20 | Golden sets | `tests/eval/golden_sets/` | 5–10 JSON fixtures with known outcomes |

---

## 3. Work Breakdown

### Track A: Haystack RAG Pipelines (Days 1–5)

**A1. RAG interface and base**
- `src/wolfpack/rag/base.py`
- `RAGPipeline` ABC: `index(documents)`, `retrieve(query, top_k, filters)`
- pgvector connection helpers; embedding model selection (default: Ollama `nomic-embed-text`)

**A2. Threat-intel pipeline**
- `src/wolfpack/rag/threat_intel.py`
- Index ATT&CK technique descriptions, CVE records, IOC feeds
- Hybrid search over `threat_intel_idx` with α=0.3 (keyword-dominant)
- Seed with small test set of ATT&CK descriptions

**A3. Case-history pipeline**
- `src/wolfpack/rag/case_history.py`
- Index closed case summaries from learning queue
- Semantic search over `case_history_idx` with α=0.7 (semantic-dominant)
- Populate with synthetic case data for testing

**A4. RAG tools**
- `src/wolfpack/rag/tools.py`
- `threat_intel_tool(query, filters)` and `case_history_tool(query)`
- Sanitize retrieved content: strip HTML/JS/markdown links, explicit delimiters, instruction-repetition defense

**A5. Integration tests**
- `tests/integration/test_rag_pipeline.py`
- Test: index → retrieve → verify relevance and sanitization

---

### Track B: Tier-1 Telemetry Adapters (Days 2–6)

**B1. Interface and base models**
- `src/wolfpack/adapters/base.py`
- `TelemetrySource` ABC: `name`, `query(entity, time_window, filters) -> list[Event]`, `health_check()`
- `Event` and `TimeWindow` Pydantic models

**B2. Syslog adapter**
- `src/wolfpack/adapters/syslog.py`
- RFC 3164 / RFC 5424 parsing; local file or UDP receiver
- Filter by entity (hostname, IP) and time window

**B3. Windows Event Log adapter**
- `src/wolfpack/adapters/windows_eventlog.py`
- WinRM or EVTX file parsing; Security/System/Application events

**B4. CrowdStrike adapter**
- `src/wolfpack/adapters/crowdstrike.py`
- Falcon API queries with rate limiting and pagination

**B5. Okta adapter**
- `src/wolfpack/adapters/okta.py`
- System Log API with pagination and rate limiting

**B6. Firewall adapter**
- `src/wolfpack/adapters/firewall.py`
- iptables, pfSense, Palo Alto log parsing

**B7. Adapter tools**
- `src/wolfpack/adapters/tools.py`
- Tool factory creating Pydantic AI tools per registered adapter
- Scoped names: `syslog_query`, `crowdstrike_query`, etc.

**B8. Unit tests**
- `tests/unit/test_adapters.py`
- Mocked data for each adapter; interface compliance; tool factory correctness

---

### Track C: PII Pre-Processing Layer (Days 4–7)

**C1. Deterministic pseudonymization**
- `src/wolfpack/processing/pii.py`
- Uses per-case salt from `pii_salts` table
- `pseudonymize(identifier, identifier_type, case_id)` → `user_a42`, `host_b17`, etc.
- `depseudonymize(token, case_id)` → reverse lookup
- Per-case token cache to avoid repeated DB lookups

**C2. NER-based stripping**
- `src/wolfpack/processing/ner.py`
- Microsoft Presidio with custom SOC recognizers
- Recognizers: IPs, CIDR ranges, MAC addresses, hostnames, emails, URLs with query params
- `strip_pii(text)` → `(stripped_text, original_to_placeholder_mapping)`

**C3. PII pipeline orchestrator**
- `src/wolfpack/processing/pii_pipeline.py`
- Takes raw telemetry events + case context
- Applies pseudonymization to identifiers; NER stripping to free-text fields
- Logs every processing step to evidence ledger

**C4. Break-glass endpoint**
- `src/wolfpack/processing/breakglass.py`
- `show_raw(case_id, analyst_id, field)` → rehydrates pseudonymized data
- Writes to `breakglass_audit` before returning raw data; fails closed

**C5. Tests**
- `tests/unit/test_pii_pipeline.py` — no raw PII in output; audit log completeness
- `tests/integration/test_pii_pipeline.py` — end-to-end flow against real DB

---

### Track D: Tracker Agent Implementation (Days 6–9)

**D1. Tracker agent**
- `src/wolfpack/agents/tracker.py`
- Pydantic AI agent: `TrackerInput` → `TrackerOutput`
- Tools: `threat_intel_tool`, `case_history_tool`, telemetry query tools (one per adapter)
- LLM: `get_model()` from Phase 0 factory (default: Llama 3.3 70B Instruct via Ollama)
- Output: hypotheses, updated entities, evidence refs, `tracker_confidence: Confidence`

**D2. Tool allowlist enforcement**
- Graph-level validation before tool dispatch
- Tracker allowlist: `threat_intel_tool`, `case_history_tool`, telemetry query tools
- Blocked: identity-pivot tools, case-modification tools
- Log violations to evidence ledger

**D3. Confidence calibration**
- Update `src/wolfpack/schemas/confidence.py`
- Written anchors: 1=coincidence, 2=weak, 3=plausible, 4=strong, 5=high-fidelity
- `calibrate(confidence, evidence_count, corroboration_level)` helper
- Document in `docs/confidence_anchors.md`

**D4. Unit tests**
- `tests/unit/test_tracker.py`
- Mocked LLM and tools; tool allowlist enforcement; confidence calibration

---

### Track E: Evaluation Harness and Golden Set (Days 8–11)

**E1. Golden sets**
- `tests/eval/golden_sets/` — 5–10 JSON fixtures
- Scenarios: simple IOC enrichment, multi-signal alert correlation, false-positive identification, lateral movement detection, benign activity confirmation
- Each: seed input, expected hypotheses, expected confidence, relevant telemetry, expected evidence

**E2. Evaluation harness**
- `src/wolfpack/eval/harness.py`
- `EvalHarness`: runs golden sets through Tracker (mocked telemetry and RAG)
- Metrics: hypothesis precision, confidence distribution, analyst-agreement proxy
- Logs to MLflow: metrics, parameters, artifacts
- Add `just eval` command to justfile

**E3. Tests**
- `tests/unit/test_eval_harness.py` — metric computation correctness; mocked MLflow logging

---

## 4. Dependency Graph

```
A1 (RAG interface) ──→ A2 (threat_intel) ──→ A3 (case_history) ──→ A4 (tools) ──→ A5 (tests)
B1 (TelemetrySource) ──→ B2–B6 (adapters) ──→ B7 (tools) ──→ B8 (tests)
C1 (pseudonymization) ──→ C2 (NER) ──→ C3 (pipeline) ──→ C4 (breakglass) ──→ C5 (tests)
D1 (Tracker) ──→ D2 (allowlist) ──→ D3 (calibration) ──→ D4 (tests)
E1 (golden sets) ──→ E2 (harness) ──→ E3 (tests)

A4, B7, C3 ──→ D1 (Tracker depends on RAG tools, adapter tools, PII pipeline)
D1 ──→ E2 (evaluation depends on Tracker)
```

**Critical path:** B1 → B2–B6 → B7 → A1 → A2 → A3 → A4 → C1 → C2 → C3 → D1 → D2 → D3 → E1 → E2

---

## 5. Parallelization

### Safe parallel lanes after A1 + B1

- **Lane 1:** Threat-intel pipeline (A2)
- **Lane 2:** Syslog adapter (B2)
- **Lane 3:** PII pseudonymization (C1)

### Safe parallel lanes after Track A

- **Lane 1:** All Tier-1 adapters (B2–B6)
- **Lane 2:** NER stripping (C2)
- **Lane 3:** Confidence calibration (D3)

---

## 6. Milestones

| Milestone | Target | Exit Criteria |
|-----------|--------|---------------|
| RAG Pipelines Working | Day 5 | Both threat-intel and case-history pipelines index and retrieve; RAG tools return sanitized, structured results |
| Tier-1 Adapters Working | Day 6 | All five adapters implement `TelemetrySource`; tools return structured `Event` objects; unit tests pass |
| PII Pipeline Working | Day 7 | Pseudonymization deterministic per case; NER strips PII from free-text; break-glass is audit-logged |
| Tracker Agent Functional | Day 9 | Tracker processes seed and returns structured `TrackerOutput`; tool allowlist prevents unauthorized access; confidence values include written anchors |
| Phase 3 Complete | Day 11 | Golden-set evaluation passes; metrics tracked in MLflow; all integration tests pass; no raw PII in agent context |

---

## 7. Validation Checklist

```bash
uv sync
just lint
just typecheck
just test
just test-integration
just eval
```

All must succeed before Phase 3 is marked complete.

---

## 8. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Presidio NER model size | Medium | Test with smallest viable model first; document tradeoff |
| Adapter API stability | Medium | Pin API versions; mock thoroughly in tests |
| RAG retrieval quality | Medium | Start with sentence-transformers; iterate; evaluation harness measures quality |
| PII false positives | Medium | Tune recognizers for SOC-specific patterns; validate against golden set |
| Confidence calibration drift | Low | Anchors are theoretical without real analyst feedback; document as known limitation; refine in Phase 6 |

---

## 9. Definition of Done

| Item | Proof Artifact |
|------|----------------|
| RAG pipelines index and retrieve | `threat_intel.py`, `case_history.py`, integration tests |
| Tier-1 adapters implement `TelemetrySource` | All five adapters, unit tests |
| PII pipeline produces sanitized output | `pii_pipeline.py`, NER tests |
| Break-glass is audit-logged | `breakglass.py`, integration test |
| Tracker produces structured output with confidence | `tracker.py`, unit test |
| Tool allowlist is enforced | Graph-level validation, test |
| Confidence anchors are documented | `confidence.py`, `confidence_anchors.md` |
| Golden sets evaluate Tracker | `tests/eval/`, harness, MLflow metrics |

---

## 10. PR Slicing

1. `phase3-rag-base` — RAG interface, threat-intel pipeline, case-history pipeline
2. `phase3-adapters` — `TelemetrySource` interface, all five Tier-1 adapters, adapter tools
3. `phase3-pii` — PII pseudonymization, NER stripping, pipeline orchestrator, break-glass
4. `phase3-tracker` — Tracker agent, tool allowlist, confidence calibration
5. `phase3-eval` — Golden sets, evaluation harness, MLflow tracking

---

## 11. Immediate Next Action

1. Define `TelemetrySource` interface and `Event` model in `src/wolfpack/adapters/base.py`
2. Define `RAGPipeline` interface in `src/wolfpack/rag/base.py`
3. Implement the threat-intel pipeline

These establish the interfaces every adapter and RAG tool depends on.
