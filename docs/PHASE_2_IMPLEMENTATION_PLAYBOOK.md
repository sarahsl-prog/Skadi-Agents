# Phase 2 Implementation Playbook — Orchestration Skeleton

This document turns the Phase 2 plan from [`PROJECT_PLAN.md`](./PROJECT_PLAN.md) into an execution-ready implementation plan.

## 0. Outstanding Design Questions

| # | Question | Decision needed by | Default if unresolved | Notes |
|---|----------|--------------------|-----------------------|-------|
| D1 | **NATS consumer group naming** — per-agent durable consumers or per-role? | Start of Track B | Per-agent durable consumers (`tracker-consumer`, `flanker-consumer`, etc.) | Per-agent durables allow independent redelivery and ack semantics. Per-role would merge Tracker/Flanker into a "hunter" group but loses isolation. |
| D2 | **Review timeout mechanism** — LangGraph `Interrupt` + `sleep`, or external scheduler + webhook? | Start of Track C | LangGraph `Interrupt` with an external watchdog timer | LangGraph's built-in interrupt is cleaner for the graph flow. An external watchdog (cron job / systemd timer) checks for timed-out reviews and triggers the auto-escalate transition. This is the most portable for on-prem. |
| D3 | **Scribe interface granularity** — single `ScribeInterface` or split into `LedgerWriter` + `TimelineWriter`? | Start of Track D | Single `ScribeInterface` with two methods: `write_ledger_entry()` and `write_timeline_event()` | Splitting adds complexity for no V1 benefit. The interface is a drop-in point for a future LLM-backed scribe; splitting can happen then if needed. |
| D4 | **LangGraph checkpointing backend** — for graph state to survive NATS failures (chaos test E2), LangGraph needs a persistent checkpointer. Options: in-memory (lost on restart), Postgres (reuses existing stack), or SQLite (lightweight but single-node). | Before Track A (graph definition) | Postgres checkpointer using `langgraph-checkpoint-postgres` — reuses the existing Postgres container and makes graph state recoverable after process restart | The chaos test (E2) validates that case state survives NATS failure. This only works if the LangGraph checkpoint is stored outside the process. In-memory checkpointing would fail the chaos test. |
| D5 | **Watchdog deployment model** — C2 says the watchdog can run "as a background task within the orchestrator process, or as a separate process triggered by a cron/systemd timer." These have different restart and failure semantics. | Start of Track C (before C2) | Background asyncio task within the orchestrator process, polling on a configurable interval (default: 60s) | A separate process adds operational complexity (two processes to monitor). A background asyncio task is simpler and sufficient for V1. If the orchestrator crashes, the watchdog also stops — acceptable since the orchestrator restart will re-register the task. |

## 1. Current Baseline

The repository has (from Phase 1):

- `src/wolfpack/schemas/` — full Pydantic domain models (`Seed`, `Entity`, `Hypothesis`, `EvidenceRef`, `CaseState`, `BranchState`, `Confidence`, per-agent I/O models)
- `src/wolfpack/schemas/graph_state.py` — LangGraph TypedDict derived from Pydantic models
- `src/wolfpack/schemas/persistence.py` — async CRUD helpers with optimistic concurrency
- `src/wolfpack/schemas/ledger.py` — hash-chain verification and replay
- Postgres schema: `cases`, `branches`, `hypotheses`, `pivots`, `evidence_ledger`, `learning_queue`, `retention_policy`, `crypto_shred_keys`, `pii_salts`, `breakglass_audit`
- Alembic migrations working against local Postgres
- Docker Compose stack with NATS JetStream enabled

The repository does **not** yet have:

- LangGraph graph definition or node implementations
- NATS subject publishing/consuming from application code
- Agent stubs (deterministic mock implementations)
- Review timeout / auto-escalation logic
- Scribe implementation
- Alpha Dispatcher wired to Pydantic AI
- End-to-end hunt flow integration test

## 2. Phase Objective

Deliver the orchestration skeleton that wires the full hunt flow:

- LangGraph graph with all nodes (Alpha, Tracker, Flanker, Closer, Scribe, Review)
- NATS JetStream integration for inter-agent messaging
- Deterministic agent stubs that exercise the graph without real LLM calls
- Review node with 24-hour timeout and auto-escalation
- Scribe as a non-LLM service
- Alpha Dispatcher wired to Pydantic AI for seed normalization
- Happy-path integration test: seed → closed case, full hash-chained ledger

No real agent intelligence, RAG pipelines, or telemetry adapters should land during this phase.

## 3. Execution Strategy

Five implementation tracks:

1. LangGraph graph definition and node stubs
2. NATS JetStream integration
3. Review timeout and auto-escalation
4. Scribe and Alpha Dispatcher wiring
5. Integration tests and chaos testing

The critical path is:

1. define the graph structure → stub nodes
2. wire NATS publishing/consuming into nodes
3. implement review node with timeout
4. wire Alpha to Pydantic AI and Scribe to the ledger
5. run happy-path and chaos integration tests

## 4. Work Breakdown Structure

### Track A: LangGraph Graph Definition and Node Stubs

Purpose: create the graph skeleton that all future agent implementations plug into.

#### A1. Define the LangGraph graph

Tasks:

- Create `src/wolfpack/orchestrator/graph.py`.
- Define the `StateGraph` using the `graph_state.py` TypedDict from Phase 1.
- Add nodes: `alpha_dispatcher`, `tracker`, `flanker`, `closer`, `scribe`, `review`.
- Define edges for the canonical hunt flow:
  - `START → alpha_dispatcher`
  - `alpha_dispatcher → tracker`
  - `tracker → flanker` (if confidence < 3, route to re-check; otherwise → closer)
  - `flanker → closer` (or `flanker → alpha_dispatcher` for follow-up tasking)
  - `closer → review`
  - `review → END` (approved/escalated/closed) or `review → alpha_dispatcher` (continue hunt)
  - `scribe` runs in parallel alongside every other node
- Implement conditional routing at the `tracker` node based on `tracker_confidence`.

Deliverables:

- `src/wolfpack/orchestrator/graph.py`

Acceptance checks:

- graph compiles and visualizes correctly (LangGraph `get_graph().draw_mermaid()`)
- all nodes and edges match the canonical hunt flow
- conditional routing logic exists at the tracker and review nodes

#### A2. Implement deterministic agent stubs

Tasks:

- Create `src/wolfpack/orchestrator/stubs.py`.
- Implement `stub_alpha(state) -> dict` — creates a `CaseState` from a `Seed`, returns initial graph state.
- Implement `stub_tracker(state) -> dict` — returns fixed hypotheses, entities, evidence refs, and `Confidence.PLUSIBLE` (3).
- Implement `stub_flanker(state) -> dict` — returns a pivot result with `branches_to_create=[]`.
- Implement `stub_closer(state) -> dict` — returns a verdict packet with decision, confidence, and evidence refs.
- Implement `stub_scribe(state) -> dict` — no-op (actual Scribe implementation in Track D).
- Implement `stub_review(state) -> dict` — returns `approved` (auto-approve in stub mode).
- All stubs are pure functions with deterministic outputs — no LLM calls, no network.

Deliverables:

- `src/wolfpack/orchestrator/stubs.py`

Acceptance checks:

- each stub returns a valid output dict matching the graph state schema
- running the graph with stubs produces a complete case lifecycle
- no LLM or network calls occur during stub execution

#### A3. Wire stubs into the graph

Tasks:

- Update `graph.py` to use the stub functions as node handlers.
- Add a `build_hunt_graph(use_stubs: bool = True)` factory that switches between stubs and real agents.
- Ensure the graph can be invoked with a `Seed` input and produce a terminal state.

Deliverables:

- updated `src/wolfpack/orchestrator/graph.py`

Acceptance checks:

- `graph.invoke({"seed": ...})` completes the full hunt flow
- the terminal state includes a closed case with a verdict

### Track B: NATS JetStream Integration

Purpose: connect the graph nodes to the event bus for inter-agent messaging.

#### B1. Implement NATS client wrapper

Tasks:

- Create `src/wolfpack/orchestrator/bus.py`.
- Implement `NATSClient` class:
  - `async def connect(settings: NATSConfig)` — connects to the NATS server.
  - `async def ensure_streams()` — creates JetStream streams for `hunt.task.*`, `hunt.finding.*`, `hunt.branch.*`, `hunt.status.*` if they don't exist.
  - `async def publish(subject: str, payload: bytes)` — publishes a message with ack confirmation.
  - `async def subscribe(subject: str, durable: str, handler: Callable)` — creates a durable consumer with ack/redeliver.
  - `async def close()`.
- Use the `nats-py` library.
- Wire connection to `NATSConfig` from Phase 0 settings.

Deliverables:

- `src/wolfpack/orchestrator/bus.py`

Acceptance checks:

- client connects to the local NATS JetStream container
- streams are created with correct subjects
- publish/subscribe round-trips work

#### B2. Wire NATS into graph nodes

Tasks:

- Each graph node publishes findings to the appropriate NATS subject:
  - `alpha_dispatcher` → `hunt.task.tracker` (task assignment)
  - `tracker` → `hunt.finding.tracker` (hypotheses, evidence)
  - `flanker` → `hunt.finding.flanker` (pivots, branch proposals)
  - `closer` → `hunt.status.verdict` (verdict packet)
  - `review` → `hunt.status.review` (review outcome)
- Each node optionally subscribes to subjects for follow-up tasking.
- Messages are JSON-serialized versions of the per-agent output models.
- Add the NATS client as a graph-level dependency (injected at graph build time).

Deliverables:

- NATS-wired graph nodes

Acceptance checks:

- running the graph publishes messages to all expected subjects
- messages contain valid JSON matching the output model schemas
- durable consumers receive and ack messages

#### B3. Add NATS integration tests

Tasks:

- Add `tests/integration/test_nats_bus.py`.
- Test: connect → create streams → publish → subscribe → receive → ack.
- Test: durable consumer redelivers unacknowledged messages.
- Test: graph execution produces expected NATS messages.

Deliverables:

- `tests/integration/test_nats_bus.py`

Acceptance checks:

- all tests pass against the local NATS container
- redelivery works after a simulated consumer crash

### Track C: Review Timeout and Auto-Escalation

Purpose: implement the analyst review gate with timeout and auto-escalation.

#### C1. Implement review node with interrupt

Tasks:

- Update the `review` node in the graph to:
  - Emit a verdict packet to the analyst queue (NATS `hunt.status.verdict`).
  - Use LangGraph's `Interrupt` mechanism to pause the graph execution pending analyst input.
  - Accept analyst input (approve, escalate, close benign, continue hunt) when resumed.
- Create `src/wolfpack/orchestrator/review.py` encapsulating the review logic.

Deliverables:

- `src/wolfpack/orchestrator/review.py`
- updated graph

Acceptance checks:

- graph pauses at the review node
- resuming with an analyst decision transitions to the correct next node
- all four analyst outcomes (approve, escalate, close, continue) are handled

#### C2. Implement timeout watchdog

Tasks:

- Create `src/wolfpack/orchestrator/watchdog.py`.
- Implement `ReviewWatchdog`:
  - `async def start(case_id, timeout_hours=24)` — records the review start time and schedules a check.
  - `async def check_timeouts()` — queries all cases in `review` status, identifies expired ones.
  - On timeout: transition the case to outcome `analyst_timeout_escalation`, record the event on the evidence ledger, and fire the configured webhook.
- Webhook configuration comes from a new `WebhookConfig` in settings.
- The watchdog can run as a background task within the orchestrator process, or as a separate process triggered by a cron/systemd timer.

Deliverables:

- `src/wolfpack/orchestrator/watchdog.py`

Acceptance checks:

- a case in review status for longer than the timeout period gets auto-escalated
- the escalation event is recorded on the evidence ledger
- the configured webhook is called with the case details

#### C3. Add review timeout integration tests

Tasks:

- Add `tests/integration/test_review_timeout.py`.
- Test: submit case for review → simulate timeout → verify auto-escalation.
- Test: analyst approves before timeout → verify no escalation.
- Test: webhook is called with correct payload on escalation.

Deliverables:

- `tests/integration/test_review_timeout.py`

Acceptance checks:

- timeout escalation works end-to-end
- no escalation occurs if the analyst acts in time

### Track D: Scribe and Alpha Dispatcher Wiring

Purpose: implement the two special-case agents.

#### D1. Implement Scribe service

Tasks:

- Create `src/wolfpack/agents/scribe.py`.
- Implement `ScribeInterface` (from D3 decision) with:
  - `async def write_ledger_entry(case_id, entry_type, content, agent_run_id)` — inserts into `evidence_ledger` (trigger populates hashes).
  - `async def write_timeline_event(case_id, event_type, description)` — appends a structured event to the case timeline.
- The Scribe is a pure structural-event → ledger-row translator. No LLM, no analysis.
- Wire the Scribe into the graph as a parallel node that runs alongside every other node.

Deliverables:

- `src/wolfpack/agents/scribe.py`

Acceptance checks:

- Scribe writes to the evidence ledger and the hash chain is maintained
- no LLM calls occur during Scribe execution
- Scribe runs in parallel with other nodes without blocking them

#### D2. Wire Alpha Dispatcher to Pydantic AI

Tasks:

- Create `src/wolfpack/agents/alpha.py`.
- Implement `AlphaDispatcher` as a Pydantic AI agent:
  - Input: raw `Seed` (variable format: IOC string, alert JSON, anomaly payload, or hunt query).
  - Output: normalized `AlphaOutput` with structured `CaseState`, entity list, and task assignments.
  - Uses the LLM factory from Phase 0 (`get_model()`) to build its model.
  - Has a tool for creating the initial case in the database (via persistence helpers).
- Wire `AlphaDispatcher` into the graph, replacing the `stub_alpha` function.

Deliverables:

- `src/wolfpack/agents/alpha.py`

Acceptance checks:

- Alpha processes various seed formats (IOC, alert, anomaly, hunt query)
- Alpha creates a case in the database
- Alpha publishes the initial task to NATS
- LLM calls go through the factory, not hardcoded

#### D3. Add Scribe and Alpha unit tests

Tasks:

- Add `tests/unit/test_scribe.py` — test ledger entry creation and timeline events.
- Add `tests/unit/test_alpha.py` — test seed normalization with mocked LLM.

Deliverables:

- `tests/unit/test_scribe.py`
- `tests/unit/test_alpha.py`

Acceptance checks:

- Scribe tests pass without LLM or database
- Alpha tests use mocked LLM responses

### Track E: Integration Tests and Chaos Testing

Purpose: prove the orchestration skeleton works end-to-end.

#### E1. Happy-path integration test

Tasks:

- Add `tests/integration/test_hunt_flow.py`.
- Test: seed → Alpha creates case → Tracker stub enriches → Flanker stub pivots → Closer stub submits verdict → Review auto-approves → case closed.
- Verify: full hash-chained ledger is present for the case.
- Verify: trace data is emitted (check OTel spans via the debug exporter).
- Verify: NATS messages were published at each step.

Deliverables:

- `tests/integration/test_hunt_flow.py`

Acceptance checks:

- test passes with all stubs
- evidence ledger has entries for every node transition
- NATS messages are present on all expected subjects
- OTel trace spans exist for the run

#### E2. Chaos test — NATS failure

Tasks:

- Add `tests/integration/test_chaos_nats.py`.
- Test: start a hunt → kill NATS mid-case → restart NATS → verify case resumes from the ledger state.
- This validates that the event bus is a fan-out mechanism, not the state store (case state is in Postgres).

Deliverables:

- `tests/integration/test_chaos_nats.py`

Acceptance checks:

- case state survives NATS failure
- hunt resumes after NATS restart
- no data loss in the evidence ledger

#### E3. Chaos test — concurrent branch writes

Tasks:

- Add `tests/integration/test_chaos_concurrency.py`.
- Test: two concurrent Tracker/Flanker writes to the same branch → verify optimistic concurrency prevents stale writes.
- Test: one writer wins, the other gets a `VersionConflictError` and retries.

Deliverables:

- `tests/integration/test_chaos_concurrency.py`

Acceptance checks:

- only one concurrent write succeeds per attempt
- the losing writer gets a clear error
- the branch state is consistent after resolution

## 5. Recommended Delivery Sequence

1. Define LangGraph graph structure (A1)
2. Implement deterministic stubs (A2)
3. Wire stubs into the graph and verify the happy path (A3)
4. Implement NATS client wrapper (B1)
5. Wire NATS into graph nodes (B2)
6. Implement review node with interrupt (C1)
7. Implement timeout watchdog (C2)
8. Implement Scribe service (D1)
9. Wire Alpha to Pydantic AI (D2)
10. Integration tests (E1–E3)

## 6. Parallelization Plan

### Safe parallel lanes after Track A

- Lane 1: NATS integration (Track B)
- Lane 2: Review timeout logic (Track C)

### Safe parallel lanes after Track B and C

- Lane 1: Scribe implementation (D1)
- Lane 2: Alpha Dispatcher wiring (D2)

### Work that should stay on the critical path

- Graph definition must land before NATS wiring (nodes need to exist)
- Review interrupt must land before the watchdog (watchdog checks interrupted cases)
- Integration tests are the final gate

## 7. Milestones and Exit Criteria

### Milestone 1: Graph Skeleton Proven

Exit criteria:

- graph runs end-to-end with deterministic stubs
- all nodes and edges are present
- conditional routing works (confidence < 3 → Flanker re-check)

### Milestone 2: NATS Integration Working

Exit criteria:

- graph nodes publish to and consume from NATS JetStream
- durable consumers with ack/redeliver work

### Milestone 3: Review Gate Functional

Exit criteria:

- graph pauses at review node
- analyst decisions transition correctly
- timeout triggers auto-escalation

### Milestone 4: Real Agents Wired

Exit criteria:

- Alpha Dispatcher uses Pydantic AI with the LLM factory
- Scribe writes to the evidence ledger without LLM

### Milestone 5: Phase 2 Complete

Exit criteria:

- happy-path integration test passes
- chaos tests pass (NATS failure, concurrent writes)
- full hash-chained ledger is present on completed cases
- trace data is visible in MLflow/debug exporter

## 8. Command-Level Validation Checklist

```bash
uv sync
just lint
just typecheck
just test
just up
just test-integration
```

All of these should succeed before Phase 2 is marked complete.

## 9. Risks to Watch During Execution

### LangGraph API stability risk

LangGraph is actively developed. Pin the version in `pyproject.toml` and test against the pinned version. If the `Interrupt` API changes, the review node will need adjustment.

### NATS consumer lag risk

If a consumer falls behind (e.g., Tracker is slow), messages will accumulate. Set `max_ack_pending` on durable consumers to provide backpressure. Monitor consumer lag in Phase 6.

### Review timeout accuracy risk

The watchdog checks for timeouts on a polling interval. The effective timeout is `configured_timeout + polling_interval`. Document this and keep the polling interval short (e.g., 60 seconds).

### Graph debugging complexity

LangGraph execution can be hard to debug when nodes fail. Add structured logging at every node entry/exit and ensure OTel spans are emitted per node.

## 10. Definition of Done Mapping

| Definition of done item | Proof artifact |
|---|---|
| LangGraph graph runs end-to-end | `graph.py`, stubs, passing happy-path test |
| NATS integration works | `bus.py`, integration test with publish/subscribe |
| Review timeout escalates | `review.py`, `watchdog.py`, timeout integration test |
| Scribe writes to ledger | `scribe.py`, unit test |
| Alpha uses Pydantic AI | `alpha.py`, unit test with mocked LLM |
| Chaos tests pass | NATS failure test, concurrency test |
| Hash-chained ledger is complete | happy-path test verifies ledger integrity |
| Trace data is visible | OTel spans present in debug exporter |

## 11. Suggested PR Slicing

1. `phase2-graph-stubs` — Graph definition, stubs, happy-path with stubs
2. `phase2-nats-integration` — NATS client, wired nodes, bus tests
3. `phase2-review-timeout` — Review node, watchdog, timeout tests
4. `phase2-scribe-alpha` — Scribe service, Alpha Dispatcher, unit tests
5. `phase2-integration-chaos` — End-to-end integration tests, chaos tests

## 12. Immediate Next Action

The first implementation step should be:

1. create `src/wolfpack/orchestrator/graph.py` with the `StateGraph` definition
2. implement deterministic stub functions
3. verify the graph runs end-to-end with stubs and a `Seed` input