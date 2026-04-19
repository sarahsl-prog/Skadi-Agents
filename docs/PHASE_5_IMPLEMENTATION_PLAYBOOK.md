# Phase 5 Implementation Playbook — Closer + Analyst Review UI

This document turns the Phase 5 plan from [`PROJECT_PLAN.md`](./PROJECT_PLAN.md) into an execution-ready implementation plan.

## 0. Outstanding Design Questions

| # | Question | Decision needed by | Default if unresolved | Notes |
|---|----------|--------------------|-----------------------|-------|
| D1 | **Analyst Console stack** — React + FastAPI, SvelteKit, or server-rendered? | Start of Track C | React + FastAPI (most ecosystem support, team familiarity assumed) | This is the biggest front-end decision. React + FastAPI gives the most library support for real-time updates (WebSocket), component libraries, and hiring. SvelteKit is lighter but has fewer SOC-specific component libraries. Server-rendered (e.g., Jinja + HTMX) is fastest to build but limited for interactive features like timeline views and verdict panels. Make this decision at Phase 5 kickoff — it does not block Tracks A or B. |
| D2 | **Real-time update mechanism** — WebSocket, Server-Sent Events (SSE), or polling? | Start of Track C | WebSocket via FastAPI + `websockets` library | WebSocket is the best fit for bidirectional real-time updates (analyst decisions + case state changes). SSE is simpler but unidirectional. Polling adds latency. Decision should align with D1 (React + WebSocket is a natural pair). |
| D3 | **Analyst authentication mechanism** — local accounts, LDAP, or OIDC? | Start of Track C | Local accounts for V1; OIDC as V1.1 target | This only affects the Analyst Console login. The API layer should use a simple token-based auth for V1. LDAP/OIDC integration is a natural V1.1 addition when deploying to enterprise environments. |
| D4 | **API token storage mechanism** — V1 uses simple token-based auth (D3), but where are tokens stored between restarts? Options: (a) Postgres `api_tokens` table with hashed tokens (persistent, auditable), (b) in-memory dict (lost on restart, simplest), (c) signed JWTs (stateless, no storage needed). | Before Track B1 (FastAPI setup) | Postgres `api_tokens` table with bcrypt-hashed tokens — restartable, auditable, and consistent with the existing Postgres stack | In-memory storage fails after an orchestrator restart (analysts lose sessions). JWTs are stateless but cannot be revoked without adding a denylist (which reintroduces storage). A Postgres table is the right V1 tradeoff: one extra table, full auditability, revocable. |
| D5 | **Frontend serving model in production** — should the React app be served as static files by FastAPI (`StaticFiles` mount) or by a separate Nginx container? | Before Track C1 (frontend setup) | FastAPI serves the built React bundle as static files in production (`app.mount("/", StaticFiles(...))`); Vite dev server is used during development and proxied to the FastAPI backend | A separate Nginx container is more production-like but adds complexity for an on-prem single-tenant deployment. Serving from FastAPI is simpler, keeps the Docker Compose stack compact, and is sufficient for V1 analyst team sizes. Move to Nginx if serving performance becomes a concern. |

## 1. Current Baseline

The repository has (from Phases 0–4):

- Full Pydantic domain models, Postgres schema, and persistence layer
- LangGraph orchestration with Alpha (real), Tracker (real), Flanker (real), Scribe (real), Review (stub) nodes
- NATS JetStream integration for inter-agent messaging
- Hash-chained evidence ledger, crypto-shredding, PII store, break-glass
- RAG pipelines (threat intel, case history) and telemetry adapters (Tier-1 + Tier-2)
- Branch creation with explosion controls and hypothesis dedup
- Flanker re-check loop (Tracker confidence < 3 → Flanker)
- Feature-flag infrastructure for Tier-2 adapters
- Evaluation harness with golden-set hunts

The repository does **not** yet have:

- Closer agent implementation
- Analyst Console (web UI)
- Break-glass "show raw" control in the UI
- Policy guardrails display alongside verdicts
- Review timeout UI (countdown, auto-escalation target)

## 2. Phase Objective

Deliver the Closer agent and the Analyst Review UI:

- Closer agent emitting verdict packets (decision, confidence ordinal, next-best action, evidence refs)
- Minimal Analyst Console for queue, case view, verdict review, learning-approval toggle, and case-outcome choice
- Break-glass "show raw" control in the case view
- Policy guardrails displayed alongside verdicts
- Review timeout UI with countdown and auto-escalation target

No Blocker, Post-Hunt Analyst, or V1.5 agents should land during this phase.

## 3. Execution Strategy

Three implementation tracks:

1. Closer agent implementation
2. Analyst Console backend (API layer)
3. Analyst Console frontend (web UI)

The critical path is:

1. build the Closer agent with verdict packet output
2. implement the API layer for case management and review
3. build the Analyst Console frontend
4. wire break-glass and policy guardrails
5. end-to-end integration test

## 4. Work Breakdown Structure

### Track A: Closer Agent Implementation

Purpose: build the Closer agent that assembles verdict packets for analyst review.

#### A1. Implement Closer agent

Tasks:

- Create `src/wolfpack/agents/closer.py`.
- Implement `CloserAgent` as a Pydantic AI agent:
  - Input: `CloserInput` (case state, all branches, all hypotheses, evidence refs).
  - Output: `CloserOutput` (decision, confidence ordinal, next-best action, evidence refs, reasoning summary).
  - Decision types: `MALICIOUS`, `BENIGN`, `INCONCLUSIVE`, `NEEDS_MORE_INFO`.
  - Tools available:
    - `threat_intel_tool`, `case_history_tool` (read-only RAG).
    - `telemetry_query_tool` (read-only telemetry — Closer should NOT modify case state).
  - Tool allowlist: no write tools, no branch creation, no telemetry modification.
  - Uses the same LLM model as Tracker and Flanker (Llama 3.3 70B Instruct).
- Wire Closer into the LangGraph graph, replacing `stub_closer`.

Deliverables:

- `src/wolfpack/agents/closer.py`

Acceptance checks:

- Closer processes case state and returns structured `CloserOutput`
- decision is one of the four valid types
- confidence ordinal is in the 1–5 range with anchors
- tool allowlist prevents Closer from using write tools

#### A2. Implement verdict packet schema

Tasks:

- Create `src/wolfpack/schemas/verdict.py`.
- Define `VerdictPacket`:
  - `decision: DecisionType`
  - `confidence: Confidence`
  - `next_best_action: str`
  - `evidence_refs: list[EvidenceRef]`
  - `reasoning_summary: str`
  - `branch_summaries: list[BranchSummary]`
  - `policy_applicable: list[str]` — list of policy IDs that apply to this verdict.
- Define `PolicyGuardrail`:
  - `id: str`
  - `name: str`
  - `description: str`
  - `severity: Literal["info", "warning", "critical"]`
  - `action_required: str | None`

Deliverables:

- `src/wolfpack/schemas/verdict.py`

Acceptance checks:

- `VerdictPacket` serializes and deserializes correctly
- `PolicyGuardrail` has all required fields

#### A3. Implement policy guardrail engine

Tasks:

- Create `src/wolfpack/agents/policy.py`.
- Implement `PolicyEngine`:
  - `async def evaluate(verdict: VerdictPacket, case_state: CaseState) -> list[PolicyGuardrail]` — evaluates a verdict against policy rules.
  - Built-in policies for V1:
    - "High-confidence malicious requires analyst approval" — if `decision == MALICIOUS and confidence >= 4`, flag for mandatory review.
    - "Low-confidence inconclusive requires additional investigation" — if `decision == INCONCLUSIVE and confidence <= 2`, recommend re-routing to Tracker.
    - "Benign with high confidence can auto-close" — if `decision == BENIGN and confidence >= 4`, suggest auto-close (but still require analyst acknowledgment).
  - Policies are configurable via `Settings.policies` (future: loaded from database).
  - Policy evaluation results are attached to the verdict packet and displayed in the Analyst Console.

Deliverables:

- `src/wolfpack/agents/policy.py`

Acceptance checks:

- policy engine evaluates verdicts correctly
- built-in policies flag expected conditions
- policies are configurable

#### A4. Add Closer unit tests

Tasks:

- Add `tests/unit/test_closer.py`.
- Test: Closer output with mocked LLM and tools.
- Test: tool allowlist enforcement (no write tools).
- Test: verdict packet schema validation.

Deliverables:

- `tests/unit/test_closer.py`

Acceptance checks:

- Closer produces structured verdict packets
- tool allowlist blocks write tools
- verdict schema validates correctly

### Track B: Analyst Console Backend (API Layer)

Purpose: create the FastAPI backend that the Analyst Console frontend communicates with.

#### B1. Set up FastAPI application

Tasks:

- Add `fastapi`, `uvicorn`, `websockets` to `pyproject.toml` dependencies.
- Create `src/wolfpack/api/` package:
  - `__init__.py`
  - `app.py` — FastAPI application factory.
  - `auth.py` — simple token-based auth for V1 (per D3 decision).
  - `routes/` — API route modules.
- Configure CORS for local development.
- Add `just api` command to start the API server.
- Add `api` service to `docker-compose.yml` (optional, for containerized deployment).

Deliverables:

- `src/wolfpack/api/app.py`
- `src/wolfpack/api/auth.py`
- `justfile` update
- `docker-compose.yml` update (optional)

Acceptance checks:

- `just api` starts the FastAPI server
- CORS is configured for local development
- simple token-based auth works

#### B2. Implement case management API routes

Tasks:

- Create `src/wolfpack/api/routes/cases.py`.
- Implement REST endpoints:
  - `GET /api/cases` — list cases (with filtering by status, date range).
  - `GET /api/cases/{case_id}` — get case details (including all branches, hypotheses, evidence).
  - `GET /api/cases/{case_id}/timeline` — get case timeline (ordered evidence ledger entries).
  - `GET /api/cases/{case_id}/verdict` — get current verdict packet for a case.
- Wire to the persistence layer from Phase 1.

Deliverables:

- `src/wolfpack/api/routes/cases.py`

Acceptance checks:

- all endpoints return correct data
- filtering by status and date range works
- case details include all branches and evidence

#### B3. Implement review API routes

Tasks:

- Create `src/wolfpack/api/routes/review.py`.
- Implement REST endpoints:
  - `GET /api/review/queue` — list cases awaiting review (status = `review`).
  - `POST /api/review/{case_id}/approve` — approve learning (case → learning queue).
  - `POST /api/review/{case_id}/escalate` — escalate case (re-route to Tracker/Flanker).
  - `POST /api/review/{case_id}/close_benign` — close as benign.
  - `POST /api/review/{case_id}/continue_hunt` — continue hunting (route back to Alpha).
  - Each review action writes to the evidence ledger and updates the case status.
- Wire to the LangGraph graph's review node.

Deliverables:

- `src/wolfpack/api/routes/review.py`

Acceptance checks:

- review queue lists cases awaiting review
- all four review actions update case status correctly
- each action writes to the evidence ledger

#### B4. Implement break-glass API routes

Tasks:

- Create `src/wolfpack/api/routes/breakglass.py`.
- Implement REST endpoints:
  - `POST /api/cases/{case_id}/show-raw` — rehydrate pseudonymized identifiers and raw free-text fields for the current analyst session.
  - Every invocation writes to `breakglass_audit` (analyst ID, field, timestamp).
  - Returns raw data only after audit logging.
- Wire to the PII break-glass module from Phase 3.

Deliverables:

- `src/wolfpack/api/routes/breakglass.py`

Acceptance checks:

- break-glass endpoint returns original PII
- every invocation is recorded in `breakglass_audit`
- endpoint requires authentication

#### B5. Implement WebSocket endpoint for real-time updates

Tasks:

- Create `src/wolfpack/api/routes/ws.py`.
- Implement WebSocket endpoint `/ws/cases/{case_id}`:
  - Subscribes to NATS `hunt.status.*` messages for the case.
  - Pushes real-time updates to the connected analyst (case status changes, new evidence, verdict updates).
  - Handles connection drops and reconnection.

Deliverables:

- `src/wolfpack/api/routes/ws.py`

Acceptance checks:

- WebSocket connection receives real-time updates for a case
- connection drops are handled gracefully
- NATS messages are forwarded to connected clients

#### B6. Add API integration tests

Tasks:

- Add `tests/integration/test_api.py`.
- Test: case listing, case details, review actions, break-glass, WebSocket updates.
- Use FastAPI's `TestClient` for HTTP endpoints and a WebSocket test client for real-time updates.

Deliverables:

- `tests/integration/test_api.py`

Acceptance checks:

- all API endpoints return correct data
- review actions update case state
- break-glass is audit-logged
- WebSocket updates are received

### Track C: Analyst Console Frontend (Web UI)

Purpose: build the minimal Analyst Console for case review and verdict approval.

#### C1. Set up frontend project

Tasks:

- Create `console/` directory at the project root (or `src/wolfpack/console/` depending on D1 decision).
- Initialize a React + TypeScript project (using Vite or similar).
- Configure to proxy API requests to the FastAPI backend.
- Add basic layout: sidebar navigation, main content area.
- Configure linting and type checking for the frontend.

Deliverables:

- `console/` directory with React + TypeScript setup
- proxy configuration for API
- basic layout component

Acceptance checks:

- `npm install` and `npm run dev` start the frontend
- proxy to backend works

#### C2. Implement case queue view

Tasks:

- Create the case queue page:
  - Lists cases awaiting review, filtered by status.
  - Shows case ID, seed summary, confidence, and time in review.
  - Highlights cases approaching the 24-hour review timeout.
  - Clicking a case navigates to the case detail view.

Deliverables:

- case queue page component

Acceptance checks:

- queue displays cases awaiting review
- timeout countdown is visible
- navigation to case detail works

#### C3. Implement case detail view with timeline

Tasks:

- Create the case detail page:
  - Displays case summary, all branches, and the current verdict.
  - Timeline view showing evidence ledger entries in chronological order.
  - Branch visualization showing parallel investigation paths.
  - Pseudonymized identifiers displayed by default (break-glass button to show raw).
  - Policy guardrails displayed alongside the verdict (warnings, required actions).

Deliverables:

- case detail page component
- timeline view
- branch visualization
- policy guardrail display

Acceptance checks:

- case detail shows all relevant information
- timeline displays evidence in chronological order
- branch visualization shows parallel paths
- pseudonymized data is shown by default
- policy guardrails are visible alongside the verdict

#### C4. Implement verdict review and actions

Tasks:

- Create the verdict review panel:
  - Displays the Closer's verdict: decision, confidence, next-best action, reasoning summary, evidence refs.
  - Four action buttons: Approve Learning, Escalate, Close Benign, Continue Hunt.
  - Per-case learning-approval toggle (any analyst can approve).
  - Confirmation dialog for each action.
- Each action calls the corresponding API endpoint and updates the case status in real time.

Deliverables:

- verdict review panel component

Acceptance checks:

- all four review actions call the correct API endpoints
- case status updates in real time
- learning-approval toggle works per-case

#### C5. Implement break-glass "show raw" control

Tasks:

- Create the break-glass UI:
  - Button in the case detail view to "Show Raw Data".
  - Clicking the button calls the break-glass API endpoint.
  - Displays a confirmation dialog warning that the action is audit-logged.
  - On confirmation, pseudonymized identifiers are replaced with raw identifiers for the current session.
  - A persistent banner indicates "Raw data view active — actions are being logged".
  - Raw data view expires when the analyst navigates away or after a session timeout.

Deliverables:

- break-glass UI component

Acceptance checks:

- break-glass button calls the API endpoint
- confirmation dialog appears before showing raw data
- raw data is displayed with an audit banner
- every invocation is audit-logged

#### C6. Implement review timeout UI

Tasks:

- Add review timeout display to the case detail view:
  - Shows remaining time before auto-escalation (countdown timer).
  - Displays the auto-escalation target (webhook URL, ticketing system, pager).
  - Visual indicator (color change) when timeout is approaching.
  - The countdown updates via WebSocket (real-time).

Deliverables:

- review timeout UI component

Acceptance checks:

- countdown timer displays remaining time
- auto-escalation target is visible
- timer updates in real time via WebSocket

#### C7. Add frontend tests

Tasks:

- Add unit tests for React components (using React Testing Library or similar).
- Add end-to-end tests for key flows (using Playwright or Cypress):
  - Login → view queue → review case → approve learning.
  - Login → view case → break-glass → view raw data.
  - Login → view case → observe timeout countdown.

Deliverables:

- frontend unit tests
- frontend end-to-end tests

Acceptance checks:

- unit tests pass
- end-to-end tests pass against a running backend

## 5. Recommended Delivery Sequence

1. Verdict packet schema and policy engine (A2, A3)
2. Closer agent (A1)
3. FastAPI application setup (B1)
4. Case management API (B2)
5. Review API (B3)
6. Break-glass API (B4)
7. WebSocket API (B5)
8. Frontend project setup (C1)
9. Case queue view (C2)
10. Case detail view (C3)
11. Verdict review panel (C4)
12. Break-glass UI (C5)
13. Review timeout UI (C6)
14. Integration and E2E tests (A4, B6, C7)

## 6. Parallelization Plan

### Safe parallel lanes after Track A starts

- Lane 1: Closer agent and policy engine (A1–A3)
- Lane 2: FastAPI setup and case management API (B1–B2)

### Safe parallel lanes after Track B starts

- Lane 1: Review API and break-glass API (B3–B4)
- Lane 2: Frontend setup and case queue (C1–C2)

### Work that should stay on the critical path

- Verdict packet schema must land before Closer agent
- API routes must land before frontend components
- Break-glass API must land before break-glass UI
- WebSocket API must land before review timeout UI

## 7. Milestones and Exit Criteria

### Milestone 1: Closer Agent Functional

Exit criteria:

- Closer produces structured verdict packets
- policy guardrails are evaluated and attached
- tool allowlist prevents Closer from using write tools

### Milestone 2: API Layer Complete

Exit criteria:

- all API endpoints return correct data
- review actions update case state
- break-glass is audit-logged
- WebSocket pushes real-time updates

### Milestone 3: Analyst Console Usable

Exit criteria:

- case queue displays cases awaiting review
- case detail shows timeline and verdict
- review actions work end-to-end
- break-glass "show raw" works
- review timeout countdown is visible

### Milestone 4: Phase 5 Complete

Exit criteria:

- end-to-end flow: seed → Tracker → Flanker → Closer → verdict → analyst review → approve/escalate
- all integration tests pass
- E2E tests pass for key flows
- no V1.5 agents have landed

## 8. Command-Level Validation Checklist

```bash
uv sync
just lint
just typecheck
just test
just test-integration
cd console && npm install && npm run build && npm test
```

All of these should succeed before Phase 5 is marked complete.

## 9. Risks to Watch During Execution

### Frontend scope creep risk

The Analyst Console is the most visible deliverable and最容易扩展范围。Keep the V1 scope minimal: queue, case detail, verdict review, break-glass, timeout display. Advanced features (filtering, search, bulk actions, custom dashboards) are V1.5+.

### WebSocket connection management risk

WebSocket connections can drop and need reconnection logic. Implement heartbeat/ping-pong and automatic reconnection on the frontend. The backend should handle stale connections gracefully.

### Break-glass audit completeness risk

Every break-glass invocation must be captured in `breakglass_audit`. Write the audit entry before returning the raw data — if the audit write fails, the raw data should not be returned.

### Closer verdict calibration risk

The Closer's confidence calibration may drift from the Tracker's. Use the evaluation harness from Phase 3 to measure Closer verdict quality against the golden set. Add Closer-specific golden sets if needed.

### Authentication simplicity risk

V1 uses simple token-based auth. This is intentionally minimal — do not over-engineer. OIDC/LDAP integration is a V1.1 target. Document the auth mechanism clearly so the transition is straightforward.

## 10. Definition of Done Mapping

| Definition of done item | Proof artifact |
|---|---|
| Closer emits verdict packets | `closer.py`, unit test |
| Policy guardrails are evaluated | `policy.py`, unit test |
| API endpoints work | `routes/`, integration test |
| Review actions update case state | review API, integration test |
| Break-glass is audit-logged | breakglass API, integration test |
| WebSocket pushes real-time updates | ws.py, integration test |
| Analyst Console is usable | frontend components, E2E test |
| Break-glass UI works with audit trail | breakglass component, E2E test |
| Review timeout is visible | timeout UI, E2E test |

## 11. Suggested PR Slicing

1. `phase5-closer` — Closer agent, verdict packet, policy engine, unit tests
2. `phase5-api` — FastAPI setup, case management, review, break-glass, WebSocket routes
3. `phase5-console-setup` — Frontend project setup, case queue, case detail, timeline
4. `phase5-console-review` — Verdict review panel, break-glass UI, timeout display
5. `phase5-e2e` — End-to-end integration and E2E tests

## 12. Immediate Next Action

The first implementation step should be:

1. define the `VerdictPacket` and `PolicyGuardrail` schemas in `src/wolfpack/schemas/verdict.py`
2. implement the policy engine in `src/wolfpack/agents/policy.py`
3. implement the Closer agent in `src/wolfpack/agents/closer.py`

That establishes the verdict contract every other track depends on.