# Phase 4 Implementation Plan — Flanker + Branching + Tier-2 Adapters

**Objective:** Deliver lateral-pivot capability with the Flanker agent, branch creation/management, Tier-2 adapters, and re-check loop.

**Estimated Duration:** 2–3 weeks  
**Depends on:** Phase 3 (Tracker + RAG + Tier-1 adapters)  
**Blocks:** Phase 5 (Closer + Analyst Review UI)

---

## 1. Scope

### In Scope
- Tier-2 telemetry adapters: DNS, Zeek/Suricata, Cloudflare/proxy, AWS CloudTrail
- Feature-flag infrastructure for gating Tier-2 adapters
- Branch creation and management in LangGraph
- Branch-explosion controls (depth, count, token/tool budget)
- Hypothesis deduplication via cosine similarity
- Flanker agent with pivot tools spanning Tier-1 + enabled Tier-2 adapters
- Re-check loop (Tracker confidence < 3 → Flanker → back to Tracker)
- Integration tests for branching, pivoting, and feature flags
- Updated golden sets covering branching scenarios

### Out of Scope
- Closer agent or verdict assembly
- Analyst Console or API layer
- Tier-3+ adapters
- Blocker or Post-Hunt Analyst agents (V1.5)

---

## 2. Deliverables

| # | Deliverable | Location | Success Criteria |
|---|-------------|----------|------------------|
| 1 | DNS adapter | `src/wolfpack/adapters/dns.py` | Parses BIND/dnsmasq; filters by domain/IP/hostname; feature-flag gated |
| 2 | Zeek/Suricata adapter | `src/wolfpack/adapters/zeek_suricata.py` | Parses Zeek JSON (conn, dns, http, ssl, files) and Suricata EVE JSON |
| 3 | Proxy adapter | `src/wolfpack/adapters/proxy.py` | Parses Cloudflare JSON and Squid/Apache proxy logs |
| 4 | CloudTrail adapter | `src/wolfpack/adapters/cloudtrail.py` | Queries AWS CloudTrail via S3 or API |
| 5 | Feature-flag infrastructure | `src/wolfpack/config/settings.py` + `adapters/tools.py` | `Settings.feature_flags: dict[str, bool]`; Tier-2 tools only registered when enabled |
| 6 | Branch creation | `src/wolfpack/orchestrator/branches.py` + graph updates | Creates `BranchState` row; links parent; publishes `hunt.branch.created` NATS message |
| 7 | Branch budget | `src/wolfpack/orchestrator/budget.py` | Max-depth: 3; max-branches-per-case: 10; token budget: 10k; tool budget: 15 |
| 8 | Hypothesis dedup | `src/wolfpack/orchestrator/dedup.py` | Cosine similarity ≥ 0.85 merges similar hypotheses; threshold configurable |
| 9 | Flanker agent | `src/wolfpack/agents/flanker.py` | Pydantic AI agent; `FlankerInput` → `FlankerOutput`; all Tier-1 + enabled Tier-2 tools |
| 10 | Re-check loop | `src/wolfpack/orchestrator/graph.py` | Low confidence → Flanker; significant findings → back to Tracker; max 2 iterations |
| 11 | Branch integration tests | `tests/integration/test_branching.py` | Branch creation → DB → sub-graph execution → completion; budget enforcement; dedup |
| 12 | Flanker pivot tests | `tests/integration/test_flanker_pivot.py` | Low confidence → Flanker re-check → improved findings; lateral pivot branches |
| 13 | Feature-flag tests | `tests/integration/test_feature_flags.py` | Disabled adapters unavailable; enabled adapters accessible |
| 14 | Updated golden sets | `tests/eval/golden_sets/` | 3–5 new fixtures: lateral movement, multi-branch budget, re-check loop, feature-flag disabled |

---

## 3. Work Breakdown

### Track A: Tier-2 Telemetry Adapters (Days 1–5)

**A1. DNS adapter**
- `src/wolfpack/adapters/dns.py`
- `DNSSource(TelemetrySource)`: parses BIND, dnsmasq, generic DNS logs
- Query filters: domain, IP, hostname; returns query type, response code, resolved IPs
- Highest-priority Tier-2 for C2 beacon detection, newly-registered domains, DGA patterns

**A2. Zeek/Suricata adapter**
- `src/wolfpack/adapters/zeek_suricata.py`
- Parses Zeek JSON (conn, dns, http, ssl, files) and Suricata EVE JSON
- Returns network-layer events with connection metadata, DNS queries, HTTP requests, TLS details

**A3. Proxy adapter**
- `src/wolfpack/adapters/proxy.py`
- Parses Cloudflare JSON and generic proxy logs (Squid, Apache mod_proxy)
- Returns request metadata filtered by domain, IP, URL, status code

**A4. CloudTrail adapter**
- `src/wolfpack/adapters/cloudtrail.py`
- Queries AWS CloudTrail via S3 event delivery or API
- Returns API call metadata filtered by user ARN, IP, resource ARN

**A5. Feature-flag infrastructure**
- Update `src/wolfpack/config/settings.py`: `feature_flags: dict[str, bool]` loaded from `.env`
- Update `src/wolfpack/adapters/tools.py`: Tier-2 adapter tools only registered when flag is `True`
- Defaults: all Tier-2 adapters disabled

**A6. Unit tests**
- Update `tests/unit/test_adapters.py` for Tier-2 adapters
- Mocked data; feature-flag gating verified

---

### Track B: Branch Creation, Management, and Explosion Controls (Days 3–6)

**B1. Branch creation in graph**
- `src/wolfpack/orchestrator/branches.py`
- `create_branch(case_id, parent_branch_id, hypothesis, depth)`:
  - Creates `BranchState` row in Postgres
  - Publishes `hunt.branch.created` NATS message
- Graph edge from Flanker for branch creation
- Each branch runs as separate asyncio task with its own LangGraph checkpoint

**B2. Branch-explosion controls**
- `src/wolfpack/orchestrator/budget.py`
- `BranchBudget`:
  - `max_depth: int = 3`
  - `max_branches_per_case: int = 10`
  - `token_budget_per_branch: int = 10_000`
  - `tool_budget_per_branch: int = 15`
  - `check(case_id, branch_depth) -> bool`
  - `remaining(case_id) -> BudgetRemaining`
- Configurable via `Settings.branch_budget`

**B3. Hypothesis dedup**
- `src/wolfpack/orchestrator/dedup.py`
- `hypothesis_dedup(existing, new) -> bool`
- Cosine similarity on description embeddings (threshold: 0.85, configurable)
- Similar hypotheses merged (updated confidence, combined evidence refs)

**B4. Wire controls into graph**
- Budget check before branch creation; log and skip if exceeded
- Flanker checks remaining budget before proposing branches
- Dedup runs on new hypotheses before branch creation

---

### Track C: Flanker Agent and Re-Check Loop (Days 5–8)

**C1. Flanker agent**
- `src/wolfpack/agents/flanker.py`
- Pydantic AI agent: `FlankerInput` → `FlankerOutput`
- Input: case state, tracker findings, branch context
- Output: pivots, updated hypotheses, `branches_to_create`, evidence refs
- Tools: all Tier-1 + enabled Tier-2 adapters, threat-intel, case-history, `create_branch`
- LLM: same as Tracker (Llama 3.3 70B Instruct via Ollama)
- Tool allowlist: no write tools, no case-modification tools

**C2. Re-check loop**
- Update `src/wolfpack/orchestrator/graph.py`
- Routing: `tracker_confidence < 3` → Flanker before Closer
- After Flanker: if `significant_findings is True` and `re_check_count < max_recheck` (default: 2) → back to Tracker
- Budget consumed across iterations

**C3. Unit tests**
- `tests/unit/test_flanker.py`
- Mocked LLM and tools; tool allowlist; branch proposals; re-check loop routing

---

### Track D: Integration Tests and Evaluation (Days 7–10)

**D1. Branch creation integration test**
- `tests/integration/test_branching.py`
- Flanker proposes branch → branch created in Postgres → sub-graph executes → branch completes
- Branch-explosion controls prevent excessive branching
- Hypothesis dedup merges similar branches

**D2. Flanker pivot integration test**
- `tests/integration/test_flanker_pivot.py`
- Tracker low-confidence → Flanker re-checks with Tier-2 → produces higher-confidence finding
- Flanker creates lateral pivot branch → branch completes → case state updated

**D3. Feature-flag integration test**
- `tests/integration/test_feature_flags.py`
- All Tier-2 disabled → Flanker only has Tier-1 tools
- Enabling a Tier-2 flag makes corresponding adapter available
- Flanker gracefully handles unavailable adapters

**D4. Updated golden sets**
- 3–5 new fixtures:
  - Lateral movement detection requiring DNS pivot
  - Multi-branch investigation with budget enforcement
  - Re-check loop scenario (low Tracker confidence → Flanker re-check)
  - Feature-flag scenario (Tier-2 adapter disabled)
- Update evaluation harness with branch metrics: branch count, branch depth, budget utilization

---

## 4. Dependency Graph

```
A1 (DNS) ──→ A2 (Zeek/Suricata) ──→ A3 (Proxy) ──→ A4 (CloudTrail)
   │
   └─→ A5 (feature flags) ──→ A6 (tests)

B1 (branch creation) ──→ B2 (budget) ──→ B3 (dedup) ──→ B4 (graph updates)

C1 (Flanker) ──→ C2 (re-check loop) ──→ C3 (tests)

D1 (branch tests) ──→ D2 (pivot tests) ──→ D3 (feature-flag tests) ──→ D4 (golden sets)

A5 ──→ C1 (Flanker needs feature-flag-gated tools)
B4 ──→ C1 (Flanker needs branch creation)
C2 ──→ D2 (pivot tests need re-check loop)
```

**Critical path:** A1 → A5 → B1 → B2 → B3 → B4 → C1 → C2 → D1 → D2 → D4

---

## 5. Parallelization

### Safe parallel lanes at start

- **Lane 1:** All Tier-2 adapters (A1–A4)
- **Lane 2:** Branch creation logic (B1–B2)

### Safe parallel lanes after Track B

- **Lane 1:** Flanker agent (C1)
- **Lane 2:** Integration tests (D1–D3)

---

## 6. Milestones

| Milestone | Target | Exit Criteria |
|-----------|--------|---------------|
| Tier-2 Adapters Available | Day 5 | All four adapters implement `TelemetrySource`; feature-flag gated; unit tests pass |
| Branching Works | Day 6 | Branches created in database; budget limits enforced; hypothesis dedup merges similar branches |
| Flanker Agent Functional | Day 8 | Flanker processes tracker findings and produces structured output; can create branches via `create_branch` tool; tool allowlist enforced |
| Phase 4 Complete | Day 10 | Re-check loop works; integration tests pass for branching, pivoting, and feature flags; evaluation golden sets cover branching scenarios |

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

All must succeed before Phase 4 is marked complete.

---

## 8. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Branch-explosion in production | Medium | Conservative defaults (depth 3, max 10 branches); monitor metrics; values configurable |
| Tier-2 adapter data format variability | Medium | Handle format detection; report format-specific issues clearly |
| Re-check loop convergence | Medium | Hard max iteration count (2); monitor iteration metrics; budget consumed across iterations |
| Feature-flag test matrix | Low | Test key combinations (all disabled, each enabled, all enabled) not exhaustive |
| Cosine similarity threshold | Low | Calibrate against golden set; threshold configurable |

---

## 9. Definition of Done

| Item | Proof Artifact |
|------|----------------|
| Tier-2 adapters implement `TelemetrySource` | All four adapters, unit tests |
| Feature flags gate adapter availability | `Settings.feature_flags`, tool registration |
| Branches are created and tracked | `branches.py`, database rows, integration test |
| Budget limits are enforced | `budget.py`, integration test |
| Hypothesis dedup works | `dedup.py`, unit test |
| Flanker produces structured output | `flanker.py`, unit test |
| Re-check loop routes correctly | Graph routing, unit and integration tests |
| Evaluation covers branching | New golden sets, updated harness |

---

## 10. PR Slicing

1. `phase4-tier2-adapters` — All four Tier-2 adapters, feature-flag infrastructure, unit tests
2. `phase4-branching` — Branch creation, budget controls, dedup, graph updates
3. `phase4-flanker` — Flanker agent, re-check loop, tool allowlist
4. `phase4-eval-branching` — Integration tests, updated golden sets, branch metrics

---

## 11. Immediate Next Action

1. Add `feature_flags` to `Settings` in `src/wolfpack/config/settings.py`
2. Implement the DNS adapter (highest-priority Tier-2 source)
3. Implement branch creation in the graph
