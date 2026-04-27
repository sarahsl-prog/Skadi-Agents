# Phase 2 Implementation Plan — Orchestration Skeleton

**Objective:** Deliver the LangGraph orchestration skeleton with deterministic stubs, NATS integration, review timeout, and end-to-end happy-path test. No real agent intelligence yet.

**Estimated Duration:** 1–2 weeks  
**Depends on:** Phase 1 (contracts & case state)  
**Blocks:** Phase 3 (Tracker + RAG + Tier-1 adapters)

---

## 1. Scope

### In Scope
- LangGraph graph definition with all nodes and conditional edges
- Deterministic agent stubs (pure functions, no LLM calls)
- NATS JetStream integration (client wrapper, publish/subscribe, durable consumers)
- Review node with LangGraph `Interrupt` and 24-hour timeout watchdog
- Scribe service (non-LLM) writing to evidence ledger
- Alpha Dispatcher wired to Pydantic AI for seed normalization
- Happy-path and chaos integration tests

### Out of Scope
- Real agent intelligence (Tracker, Flanker, Closer use stubs)
- RAG pipelines or telemetry adapters
- Analyst Console or API layer
- Break-glass UI (Phase 5)

---

## 2. Deliverables

| # | Deliverable | Location | Success Criteria |
|---|-------------|----------|------------------|
| 1 | LangGraph graph | `src/wolfpack/orchestrator/graph.py` | Compiles with `get_graph().draw_mermaid()`; all nodes and edges present |
| 2 | Agent stubs | `src/wolfpack/orchestrator/stubs.py` | Pure functions; deterministic outputs; no LLM/network calls |
| 3 | NATS client wrapper | `src/wolfpack/orchestrator/bus.py` | Connect, ensure streams, publish, subscribe, durable consumers |
| 4 | Review node | `src/wolfpack/orchestrator/review.py` | LangGraph `Interrupt`; handles approve/escalate/close/continue |
| 5 | Timeout watchdog | `src/wolfpack/orchestrator/watchdog.py` | 24h default; auto-escalation on expiry; ledger entry + webhook |
| 6 | Scribe service | `src/wolfpack/agents/scribe.py` | Writes ledger entries and timeline events; no LLM |
| 7 | Alpha Dispatcher | `src/wolfpack/agents/alpha.py` | Pydantic AI agent; normalizes seeds; creates cases; publishes to NATS |
| 8 | Happy-path integration test | `tests/integration/test_hunt_flow.py` | Seed → closed case; full hash-chained ledger; OTel spans; NATS messages |
| 9 | Chaos tests | `tests/integration/test_chaos_*.py` | NATS failure recovery; concurrent branch write safety |

---

## 3. Work Breakdown

### Track A: LangGraph Graph Definition (Days 1–3)

**A1. Graph structure**
- `src/wolfpack/orchestrator/graph.py`
- Nodes: `alpha_dispatcher`, `tracker`, `flanker`, `closer`, `scribe`, `review`
- Edges:
  - `START → alpha_dispatcher`
  - `alpha_dispatcher → tracker`
  - `tracker → flanker` (if confidence < 3, re-route; otherwise → closer)
  - `flanker → closer` (or `flanker → alpha_dispatcher` for follow-up)
  - `closer → review`
  - `review → END` (approved/escalated/closed) or `review → alpha_dispatcher` (continue hunt)
  - `scribe` runs in parallel alongside every other node

**A2. Deterministic stubs**
- `src/wolfpack/orchestrator/stubs.py`
- `stub_alpha(state)` — creates `CaseState` from `Seed`
- `stub_tracker(state)` — returns fixed hypotheses, entities, evidence refs, `Confidence.PLUSIBLE` (3)
- `stub_flanker(state)` — returns pivot with `branches_to_create=[]`
- `stub_closer(state)` — returns verdict packet
- `stub_scribe(state)` — no-op
- `stub_review(state)` — returns `approved`

**A3. Graph factory**
- `build_hunt_graph(use_stubs: bool = True)` switches between stubs and real agents
- Graph can be invoked with a `Seed` input and produce a terminal state

---

### Track B: NATS JetStream Integration (Days 2–4)

**B1. NATS client wrapper**
- `src/wolfpack/orchestrator/bus.py`
- `NATSClient` class:
  - `connect(settings: NATSConfig)`
  - `ensure_streams()` — creates `hunt.task.*`, `hunt.finding.*`, `hunt.branch.*`, `hunt.status.*`
  - `publish(subject, payload)` with ack confirmation
  - `subscribe(subject, durable, handler)` — durable consumer with ack/redeliver
  - `close()`
- Wire to `NATSConfig` from Phase 0 settings

**B2. Wired graph nodes**
- Each node publishes to appropriate NATS subject:
  - `alpha_dispatcher` → `hunt.task.tracker`
  - `tracker` → `hunt.finding.tracker`
  - `flanker` → `hunt.finding.flanker`
  - `closer` → `hunt.status.verdict`
  - `review` → `hunt.status.review`
- Messages are JSON-serialized agent output models
- NATS client injected at graph build time

**B3. Integration tests**
- `tests/integration/test_nats_bus.py`
- Test: connect → create streams → publish → subscribe → receive → ack
- Test: durable consumer redelivers unacknowledged messages
- Test: graph execution produces expected NATS messages

---

### Track C: Review Timeout and Auto-Escalation (Days 3–5)

**C1. Review node with interrupt**
- `src/wolfpack/orchestrator/review.py`
- Emits verdict packet to `hunt.status.verdict`
- Uses LangGraph `Interrupt` to pause for analyst input
- Accepts: approve, escalate, close benign, continue hunt
- Resumes to correct next node

**C2. Timeout watchdog**
- `src/wolfpack/orchestrator/watchdog.py`
- `ReviewWatchdog`:
  - `start(case_id, timeout_hours=24)` — records start time
  - `check_timeouts()` — polls cases in `review` status (default interval: 60s)
  - On timeout: transition to `analyst_timeout_escalation`; ledger entry; fire webhook
- Webhook config from `Settings.webhook_config`
- Runs as background asyncio task within orchestrator process

**C3. Integration tests**
- `tests/integration/test_review_timeout.py`
- Test: submit → simulate timeout → verify auto-escalation
- Test: approve before timeout → no escalation
- Test: webhook called with correct payload on escalation

---

### Track D: Scribe and Alpha Dispatcher (Days 4–6)

**D1. Scribe service**
- `src/wolfpack/agents/scribe.py`
- `ScribeInterface`:
  - `write_ledger_entry(case_id, entry_type, content, agent_run_id)` → inserts to `evidence_ledger`
  - `write_timeline_event(case_id, event_type, description)` → appends structured timeline event
- Pure structural translator; no LLM
- Runs in parallel with other nodes

**D2. Alpha Dispatcher**
- `src/wolfpack/agents/alpha.py`
- Pydantic AI agent:
  - Input: raw `Seed` (variable format)
  - Output: normalized `AlphaOutput` with `CaseState`, entity list, task assignments
  - Uses `get_model()` from Phase 0 LLM factory
  - Tool: create initial case in database via persistence helpers
- Wired into graph replacing `stub_alpha`

**D3. Unit tests**
- `tests/unit/test_scribe.py` — ledger entry creation, timeline events
- `tests/unit/test_alpha.py` — seed normalization with mocked LLM

---

### Track E: Integration and Chaos Tests (Days 6–8)

**E1. Happy-path integration test**
- `tests/integration/test_hunt_flow.py`
- Seed → Alpha creates case → Tracker stub → Flanker stub → Closer stub → Review auto-approves → case closed
- Verify: full hash-chained ledger, OTel spans, NATS messages

**E2. Chaos — NATS failure**
- `tests/integration/test_chaos_nats.py`
- Start hunt → kill NATS mid-case → restart NATS → verify case resumes from ledger state
- Validates: event bus is fan-out, not state store (Postgres is source of truth)

**E3. Chaos — concurrent branch writes**
- `tests/integration/test_chaos_concurrency.py`
- Two concurrent writes to same branch → optimistic concurrency prevents stale writes
- One writer wins; loser gets `VersionConflictError` and retries

---

## 4. Dependency Graph

```
A1 (graph structure) ──→ A2 (stubs) ──→ A3 (factory)
   │
   ├─→ B1 (NATS client) ──→ B2 (wired nodes) ──→ B3 (tests)
   │
   ├─→ C1 (review) ──→ C2 (watchdog) ──→ C3 (tests)
   │
   ├─→ D1 (scribe) ──→ D3 (tests)
   │
   └─→ D2 (alpha) ──→ D3
```

**Critical path:** A1 → A2 → A3 → B1 → B2 → C1 → C2 → D1 → D2 → E1

---

## 5. Parallelization

### Safe parallel lanes after Track A

- **Lane 1:** NATS integration (Track B)
- **Lane 2:** Review timeout logic (Track C)

### Safe parallel lanes after Track B + C

- **Lane 1:** Scribe (D1)
- **Lane 2:** Alpha Dispatcher (D2)

---

## 6. Milestones

| Milestone | Target | Exit Criteria |
|-----------|--------|---------------|
| Graph Skeleton Proven | Day 3 | Graph runs end-to-end with deterministic stubs; all nodes and edges present; conditional routing works |
| NATS Integration Working | Day 4 | Graph nodes publish/consume from NATS JetStream; durable consumers with ack/redeliver work |
| Review Gate Functional | Day 5 | Graph pauses at review node; analyst decisions transition correctly; timeout triggers auto-escalation |
| Real Agents Wired | Day 6 | Alpha uses Pydantic AI with LLM factory; Scribe writes to ledger without LLM |
| Phase 2 Complete | Day 8 | Happy-path integration test passes; chaos tests pass (NATS failure, concurrent writes); full hash-chained ledger on completed cases; trace data visible |

---

## 7. Validation Checklist

```bash
uv sync
just lint
just typecheck
just test
just up
just test-integration
```

All must succeed before Phase 2 is marked complete.

---

## 8. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| LangGraph API stability | Medium | Pin version in `pyproject.toml`; test against pinned version |
| NATS consumer lag | Medium | Set `max_ack_pending` on durable consumers for backpressure |
| Review timeout accuracy | Low | Document `configured_timeout + polling_interval` effective timeout; keep polling interval ≤ 60s |
| Graph debugging complexity | Medium | Structured logging at every node entry/exit; OTel spans per node |

---

## 9. Definition of Done

| Item | Proof Artifact |
|------|----------------|
| LangGraph graph runs end-to-end | `graph.py`, stubs, passing happy-path test |
| NATS integration works | `bus.py`, integration test with publish/subscribe |
| Review timeout escalates | `review.py`, `watchdog.py`, timeout integration test |
| Scribe writes to ledger | `scribe.py`, unit test |
| Alpha uses Pydantic AI | `alpha.py`, unit test with mocked LLM |
| Chaos tests pass | NATS failure test, concurrency test |
| Hash-chained ledger is complete | Happy-path test verifies ledger integrity |
| Trace data is visible | OTel spans present in debug exporter |

---

## 10. PR Slicing

1. `phase2-graph-stubs` — Graph definition, stubs, happy-path with stubs
2. `phase2-nats-integration` — NATS client, wired nodes, bus tests
3. `phase2-review-timeout` — Review node, watchdog, timeout tests
4. `phase2-scribe-alpha` — Scribe service, Alpha Dispatcher, unit tests
5. `phase2-integration-chaos` — End-to-end integration tests, chaos tests

---

## 11. Immediate Next Action

1. Create `src/wolfpack/orchestrator/graph.py` with the `StateGraph` definition
2. Implement deterministic stub functions
3. Verify the graph runs end-to-end with stubs and a `Seed` input
