# Phase 5 Implementation Plan — Closer + Analyst Review UI

**Objective:** Deliver the Closer agent (verdict assembly), Analyst Console (React + FastAPI), break-glass UI, policy guardrails, and review timeout display.

**Estimated Duration:** 2–3 weeks  
**Depends on:** Phase 4 (Flanker + branching + Tier-2 adapters)  
**Blocks:** Phase 6 (OTel hardening, MLflow dashboards)

---

## 1. Scope

### In Scope
- Closer agent emitting verdict packets (decision, confidence, next-best action, evidence refs)
- Policy engine with built-in guardrails
- FastAPI backend: case management, review actions, break-glass, WebSocket real-time updates
- React + TypeScript + Vite frontend: case queue, case detail, timeline, verdict review, break-glass
- Review timeout UI with countdown and auto-escalation target
- Token-based authentication (bcrypt-hashed tokens in Postgres)
- End-to-end integration and frontend E2E tests

### Out of Scope
- Blocker agent (containment recommendations) — V1.5
- Post-Hunt Analyst agent (summaries, ATT&CK mapping) — V1.5
- OIDC/LDAP authentication — V1.1 target
- Bulk actions, custom dashboards, advanced filtering — V1.5+

---

## 2. Deliverables

| # | Deliverable | Location | Success Criteria |
|---|-------------|----------|------------------|
| 1 | Closer agent | `src/wolfpack/agents/closer.py` | Structured `CloserOutput`; decision types: MALICIOUS, BENIGN, INCONCLUSIVE, NEEDS_MORE_INFO |
| 2 | Verdict packet schema | `src/wolfpack/schemas/verdict.py` | `VerdictPacket` serializes correctly; includes decision, confidence, evidence, reasoning, branch summaries, policy applicability |
| 3 | Policy engine | `src/wolfpack/agents/policy.py` | Evaluates verdict against rules; built-in policies for high-confidence malicious, low-confidence inconclusive, high-confidence benign |
| 4 | FastAPI app | `src/wolfpack/api/app.py` | Factory with CORS; `just api` starts server |
| 5 | Token-based auth | `src/wolfpack/api/auth.py` | Postgres `api_tokens` table with bcrypt-hashed tokens; revocable |
| 6 | Case management API | `src/wolfpack/api/routes/cases.py` | GET /api/cases, /cases/{id}, /cases/{id}/timeline, /cases/{id}/verdict |
| 7 | Review API | `src/wolfpack/api/routes/review.py` | GET /api/review/queue; POST /review/{id}/approve, /escalate, /close_benign, /continue_hunt |
| 8 | Break-glass API | `src/wolfpack/api/routes/breakglass.py` | POST /api/cases/{id}/show-raw; audit-logged; fails closed |
| 9 | WebSocket endpoint | `src/wolfpack/api/routes/ws.py` | `/ws/cases/{case_id}` forwards NATS messages for real-time updates |
| 10 | Frontend project | `console/` | React + TypeScript + Vite; proxy to FastAPI; `npm run dev` works |
| 11 | Case queue view | `console/src/pages/Queue.tsx` | Lists cases awaiting review; filter by status; highlights approaching timeout |
| 12 | Case detail view | `console/src/pages/CaseDetail.tsx` | Summary, branches, verdict, timeline, branch visualization, policy guardrails |
| 13 | Verdict review panel | `console/src/components/VerdictPanel.tsx` | Four actions: Approve Learning, Escalate, Close Benign, Continue Hunt; learning-approval toggle |
| 14 | Break-glass UI | `console/src/components/BreakGlass.tsx` | "Show Raw Data" button; confirmation dialog; audit banner; session-scoped raw view |
| 15 | Review timeout UI | `console/src/components/TimeoutDisplay.tsx` | Countdown timer; auto-escalation target; color change as deadline approaches; WebSocket updates |
| 16 | API integration tests | `tests/integration/test_api.py` | HTTP + WebSocket endpoint tests |
| 17 | Frontend E2E tests | `console/e2e/` | Playwright/Cypress: login → queue → review → approve; break-glass flow; timeout countdown |

---

## 3. Work Breakdown

### Track A: Closer Agent Implementation (Days 1–3)

**A1. Closer agent**
- `src/wolfpack/agents/closer.py`
- Pydantic AI agent: `CloserInput` → `CloserOutput`
- Input: case state, all branches, all hypotheses, evidence refs
- Output: decision, confidence ordinal, next-best action, evidence refs, reasoning summary
- Decision types: `MALICIOUS`, `BENIGN`, `INCONCLUSIVE`, `NEEDS_MORE_INFO`
- Tools: read-only only (`threat_intel_tool`, `case_history_tool`, telemetry queries)
- Tool allowlist: NO write tools, NO branch creation, NO telemetry modification
- LLM: same as Tracker/Flanker

**A2. Verdict packet schema**
- `src/wolfpack/schemas/verdict.py`
- `VerdictPacket`: decision, confidence, next_best_action, evidence_refs, reasoning_summary, branch_summaries, policy_applicable
- `PolicyGuardrail`: id, name, description, severity (info/warning/critical), action_required

**A3. Policy engine**
- `src/wolfpack/agents/policy.py`
- `PolicyEngine.evaluate(verdict, case_state) -> list[PolicyGuardrail]`
- Built-in policies:
  - High-confidence malicious → mandatory review
  - Low-confidence inconclusive → recommend re-routing to Tracker
  - High-confidence benign → suggest auto-close (still requires analyst acknowledgment)
- Configurable via `Settings.policies`

**A4. Unit tests**
- `tests/unit/test_closer.py` — mocked LLM and tools; tool allowlist blocks write tools; verdict schema validation

---

### Track B: Analyst Console Backend (Days 2–6)

**B1. FastAPI setup**
- Add `fastapi`, `uvicorn`, `websockets` to `pyproject.toml`
- `src/wolfpack/api/app.py` — FastAPI factory with CORS
- `src/wolfpack/api/auth.py` — token-based auth with bcrypt-hashed tokens in Postgres `api_tokens`
- Add `just api` command; optional `api` service in `docker-compose.yml`

**B2. Case management routes**
- `src/wolfpack/api/routes/cases.py`
- `GET /api/cases` — list with filtering by status and date range
- `GET /api/cases/{case_id}` — case details with branches, hypotheses, evidence
- `GET /api/cases/{case_id}/timeline` — ordered evidence ledger entries
- `GET /api/cases/{case_id}/verdict` — current verdict packet

**B3. Review routes**
- `src/wolfpack/api/routes/review.py`
- `GET /api/review/queue` — cases awaiting review
- `POST /api/review/{case_id}/approve` — approve learning
- `POST /api/review/{case_id}/escalate` — re-route to Tracker/Flanker
- `POST /api/review/{case_id}/close_benign` — close as benign
- `POST /api/review/{case_id}/continue_hunt` — route back to Alpha
- Each action writes to evidence ledger and updates case status

**B4. Break-glass routes**
- `src/wolfpack/api/routes/breakglass.py`
- `POST /api/cases/{case_id}/show-raw` — rehydrates pseudonymized data
- Writes to `breakglass_audit` before returning; fails closed

**B5. WebSocket endpoint**
- `src/wolfpack/api/routes/ws.py`
- `/ws/cases/{case_id}` — subscribes to NATS `hunt.status.*` for the case
- Pushes real-time updates to connected analyst
- Handles connection drops and reconnection

**B6. API integration tests**
- `tests/integration/test_api.py`
- HTTP endpoint tests; WebSocket real-time update tests

---

### Track C: Analyst Console Frontend (Days 4–9)

**C1. Frontend project setup**
- `console/` directory at project root
- React + TypeScript + Vite
- Proxy API requests to FastAPI backend
- Basic layout: sidebar navigation, main content area
- Linting and type checking configured

**C2. Case queue view**
- Lists cases awaiting review
- Filter by status
- Show case ID, seed summary, confidence, time in review
- Highlight cases approaching 24-hour timeout
- Click navigates to case detail

**C3. Case detail view**
- Case summary, all branches, current verdict
- Timeline: chronological evidence ledger entries
- Branch visualization: parallel investigation paths
- Pseudonymized identifiers by default
- Policy guardrails displayed alongside verdict

**C4. Verdict review panel**
- Displays Closer verdict: decision, confidence, reasoning, evidence refs
- Four action buttons: Approve Learning, Escalate, Close Benign, Continue Hunt
- Per-case learning-approval toggle
- Confirmation dialog for each action
- Calls corresponding API endpoint; real-time status update

**C5. Break-glass "Show Raw Data"**
- Button in case detail view
- Calls break-glass API endpoint
- Confirmation dialog: "This action is audit-logged"
- On confirmation: replaces pseudonymized identifiers with raw data for current session
- Persistent banner: "Raw data view active — actions are being logged"
- Expires on navigation away or session timeout

**C6. Review timeout display**
- Countdown timer showing remaining time before auto-escalation
- Auto-escalation target visible (webhook URL, ticketing system, pager)
- Color change as deadline approaches (green → yellow → red)
- Updates via WebSocket in real time

**C7. Frontend tests**
- Unit tests with React Testing Library
- E2E tests with Playwright/Cypress:
  - Login → queue → review case → approve learning
  - Login → view case → break-glass → view raw data
  - Login → view case → observe timeout countdown

---

### Track D: Integration and E2E Tests (Days 8–11)

**D1. End-to-end flow test**
- Seed → Tracker → Flanker → Closer → verdict → analyst review → approve/escalate
- Full hash-chained ledger present
- All integration tests pass

**D2. Frontend E2E tests**
- `console/e2e/`
- Playwright or Cypress
- Key flows automated against running backend

---

## 4. Dependency Graph

```
A1 (Closer) ──→ A2 (verdict schema) ──→ A3 (policy engine) ──→ A4 (tests)
   │
   └─→ B3 (review routes need verdict packet)

B1 (FastAPI setup) ──→ B2 (cases) ──→ B3 (review) ──→ B4 (breakglass) ──→ B5 (WebSocket) ──→ B6 (tests)

C1 (frontend setup) ──→ C2 (queue) ──→ C3 (case detail) ──→ C4 (verdict panel) ──→ C5 (breakglass UI) ──→ C6 (timeout UI) ──→ C7 (tests)

B2 ──→ C3 (case detail needs case API)
B3 ──→ C4 (verdict panel needs review API)
B4 ──→ C5 (breakglass UI needs breakglass API)
B5 ──→ C6 (timeout needs WebSocket updates)
```

**Critical path:** A2 → A3 → A1 → B1 → B2 → B3 → B4 → B5 → C1 → C2 → C3 → C4 → C5 → C6 → D1

---

## 5. Parallelization

### Safe parallel lanes after Track A starts

- **Lane 1:** Closer agent and policy engine (A1–A3)
- **Lane 2:** FastAPI setup and case management API (B1–B2)

### Safe parallel lanes after Track B starts

- **Lane 1:** Review API and break-glass API (B3–B4)
- **Lane 2:** Frontend setup and case queue (C1–C2)

---

## 6. Milestones

| Milestone | Target | Exit Criteria |
|-----------|--------|---------------|
| Closer Agent Functional | Day 3 | Closer produces structured verdict packets; policy guardrails evaluated and attached; tool allowlist prevents write tools |
| API Layer Complete | Day 6 | All API endpoints return correct data; review actions update case state; break-glass audit-logged; WebSocket pushes real-time updates |
| Analyst Console Usable | Day 9 | Case queue displays cases; case detail shows timeline and verdict; review actions work end-to-end; break-glass "show raw" works; timeout countdown visible |
| Phase 5 Complete | Day 11 | End-to-end flow: seed → Tracker → Flanker → Closer → verdict → analyst review → approve/escalate; all integration tests pass; E2E tests pass for key flows |

---

## 7. Validation Checklist

```bash
uv sync
just lint
just typecheck
just test
just test-integration
cd console && npm install && npm run build && npm test
```

All must succeed before Phase 5 is marked complete.

---

## 8. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Frontend scope creep | High | V1 scope minimal: queue, case detail, verdict review, break-glass, timeout. Advanced features are V1.5+ |
| WebSocket connection drops | Medium | Implement heartbeat/ping-pong; automatic reconnection on frontend; backend handles stale connections |
| Break-glass audit completeness | High | Write audit entry before returning raw data; fail closed if audit write fails |
| Closer verdict calibration | Medium | Use Phase 3 evaluation harness to measure Closer quality; add Closer-specific golden sets if needed |
| Authentication simplicity | Low | V1 uses simple token-based auth; document clearly for V1.1 OIDC/LDAP transition |

---

## 9. Definition of Done

| Item | Proof Artifact |
|------|----------------|
| Closer emits verdict packets | `closer.py`, unit test |
| Policy guardrails are evaluated | `policy.py`, unit test |
| API endpoints work | `routes/`, integration test |
| Review actions update case state | Review API, integration test |
| Break-glass is audit-logged | Breakglass API, integration test |
| WebSocket pushes real-time updates | `ws.py`, integration test |
| Analyst Console is usable | Frontend components, E2E test |
| Break-glass UI works with audit trail | Breakglass component, E2E test |
| Review timeout is visible | Timeout UI, E2E test |

---

## 10. PR Slicing

1. `phase5-closer` — Closer agent, verdict packet, policy engine, unit tests
2. `phase5-api` — FastAPI setup, case management, review, break-glass, WebSocket routes
3. `phase5-console-setup` — Frontend project setup, case queue, case detail, timeline
4. `phase5-console-review` — Verdict review panel, break-glass UI, timeout display
5. `phase5-e2e` — End-to-end integration and E2E tests

---

## 11. Immediate Next Action

1. Define `VerdictPacket` and `PolicyGuardrail` schemas in `src/wolfpack/schemas/verdict.py`
2. Implement the policy engine in `src/wolfpack/agents/policy.py`
3. Implement the Closer agent in `src/wolfpack/agents/closer.py`

These establish the verdict contract every other track depends on.
