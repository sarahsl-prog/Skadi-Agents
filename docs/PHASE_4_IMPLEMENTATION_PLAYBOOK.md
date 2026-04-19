# Phase 4 Implementation Playbook — Flanker + Branching + Tier-2 Adapters

This document turns the Phase 4 plan from [`PROJECT_PLAN.md`](./PROJECT_PLAN.md) into an execution-ready implementation plan.

## 0. Outstanding Design Questions

| # | Question | Decision needed by | Default if unresolved | Notes |
|---|----------|--------------------|-----------------------|-------|
| D1 | **Branch-explosion hard limits** — what are the concrete values for max-depth, max-branches-per-case, and token/tool budget per branch? | Start of Track B | max-depth: 3, max-branches-per-case: 10, token-budget-per-branch: 10k tokens, tool-budget-per-branch: 15 calls | These are conservative starting values. The evaluation harness from Phase 3 should inform tuning. Document them as configuration knobs in `Settings`, not hardcoded constants. |
| D2 | **Hypothesis similarity dedup threshold** — Jaccard, cosine, or exact-match? What threshold? | Start of Track B | Cosine similarity with 0.85 threshold on hypothesis description embeddings | Cosine is robust for short text. 0.85 is aggressive but prevents near-duplicate branches. Make the threshold configurable. |
| D3 | **Feature-flag mechanism** — simple config toggle, environment variable, or LaunchDarkly-style? | Start of Track D | `Settings.feature_flags: dict[str, bool]` loaded from `.env` | Simple, auditable, and consistent with the existing `pydantic-settings` approach. No external dependency needed for V1. |
| D4 | **Branch sub-graph execution model** — B1 says "each new branch gets its own sub-graph execution with its own state" but the mechanism is unspecified. Options: (a) a completely new LangGraph graph invocation running as a separate asyncio task (true parallelism, separate checkpoints), or (b) a LangGraph sub-graph node within the parent execution (sequential within the parent, no separate checkpoint). | Start of Track B (before B1) | Separate asyncio task running a new LangGraph graph invocation per branch — each branch has its own checkpoint state and runs concurrently with sibling branches | A sub-graph node runs sequentially within the parent, which defeats the purpose of lateral pivots happening in parallel. A separate task allows true parallelism up to the branch budget. The trade-off is that branch results must be merged back into the parent case state via Postgres (not via graph state), which is correct — Postgres is the source of truth. |
| D5 | **Re-check loop "significant findings" definition** — C2 routes back to Tracker "if Flanker produced significant new findings" but does not define what "significant" means. Without a concrete definition, the routing condition cannot be implemented. | Start of Track C (before C2) | Add `significant_findings: bool` to `FlankerOutput`; the Flanker LLM sets this field based on whether it produced material new entities, pivots, or hypothesis updates. The graph routes to Tracker re-check if `significant_findings is True AND re_check_count < max_recheck`. | Leaving "significant" to the LLM's judgment (via the structured output field) is intentional: the Flanker has the context to assess materiality. An alternative is a threshold on `len(new_entities) > 0 or len(new_pivots) > N`, but this can miss high-signal low-volume findings. The structured field is the right V1 approach and can be calibrated against the golden set. |

## 1. Current Baseline

The repository has (from Phases 0–3):

- Full Pydantic domain models and Postgres schema
- LangGraph orchestration with Alpha, Tracker (real), Scribe, Review nodes
- NATS JetStream integration
- Hash-chained evidence ledger, crypto-shredding skeleton, PII store
- Haystack RAG pipelines (threat intel, case history)
- Tier-1 telemetry adapters (Syslog, Windows Event Log, CrowdStrike, Okta, Firewall)
- PII pre-processing layer (pseudonymization + NER stripping + break-glass)
- Tracker agent with confidence ordinal and tool allowlist
- Evaluation harness with golden-set hunts

The repository does **not** yet have:

- Flanker agent implementation
- Branch creation and management in the graph
- Branch-explosion controls
- Tier-2 telemetry adapters (DNS, Zeek/Suricata, Cloudflare, CloudTrail)
- Flanker re-check loop (Tracker confidence < 3 → route back to Flanker)
- Feature-flag infrastructure for Tier-2 adapters

## 2. Phase Objective

Deliver the Flanker agent and lateral-pivot capability:

- Flanker agent with pivot tools spanning Tier-1 + Tier-2 adapters
- LangGraph branch creation with per-branch sub-state
- Branch-explosion controls (depth, count, budget)
- Hypothesis dedup on similarity
- Flanker re-check loop when Tracker confidence < 3
- Tier-2 adapters behind feature flags

No Closer agent, Analyst Console, or Tier-3+ adapters should land during this phase.

## 3. Execution Strategy

Four implementation tracks:

1. Tier-2 telemetry adapters
2. Branch creation, management, and explosion controls
3. Flanker agent implementation
4. Integration tests and evaluation

The critical path is:

1. implement Tier-2 adapters (needed for Flanker tools)
2. implement branch creation in the graph
3. implement explosion controls and dedup
4. build the Flanker agent with pivot tools
5. wire the re-check loop
6. run integration tests and evaluate

## 4. Work Breakdown Structure

### Track A: Tier-2 Telemetry Adapters

Purpose: add the high-value pivot sources Flanker needs for lateral investigation.

#### A1. Implement DNS log adapter

Tasks:

- Create `src/wolfpack/adapters/dns.py`.
- Implement `DNSSource(TelemetrySource)`:
  - Parses DNS query/response logs (BIND, dnsmasq, or generic DNS log format).
  - `query()` filters by entity (domain, IP, hostname) and time window.
  - Returns structured `Event` objects with query type, response code, resolved IPs.
- This is the highest-leverage Tier-2 source for C2 beacon detection, newly-registered domains, and DGA patterns.

Deliverables:

- `src/wolfpack/adapters/dns.py`

Acceptance checks:

- adapter parses common DNS log formats
- `query()` returns events matching the entity and time window
- feature-flag gated: `feature_flags["adapter_dns"]` controls availability

#### A2. Implement Zeek/Suricata adapter

Tasks:

- Create `src/wolfpack/adapters/zeek_suricata.py`.
- Implement `ZeekSuricataSource(TelemetrySource)`:
  - Parses Zeek JSON logs (conn, dns, http, ssl, files) and Suricata EVE JSON.
  - `query()` filters by entity (IP, port, protocol) and time window.
  - Returns structured `Event` objects with network-level signal (connection metadata, DNS queries, HTTP requests, TLS details).

Deliverables:

- `src/wolfpack/adapters/zeek_suricata.py`

Acceptance checks:

- adapter parses Zeek JSON and Suricata EVE formats
- `query()` returns network-layer events
- feature-flag gated: `feature_flags["adapter_zeek_suricata"]`

#### A3. Implement Cloudflare / generic proxy adapter

Tasks:

- Create `src/wolfpack/adapters/proxy.py`.
- Implement `ProxySource(TelemetrySource)`:
  - Parses Cloudflare log format (JSON) and generic proxy logs (Squid, Apache mod_proxy).
  - `query()` filters by entity (domain, IP, URL, status code) and time window.
  - Returns structured `Event` objects with request metadata.

Deliverables:

- `src/wolfpack/adapters/proxy.py`

Acceptance checks:

- adapter parses Cloudflare and generic proxy log formats
- feature-flag gated: `feature_flags["adapter_proxy"]`

#### A4. Implement AWS CloudTrail adapter

Tasks:

- Create `src/wolfpack/adapters/cloudtrail.py`.
- Implement `CloudTrailSource(TelemetrySource)`:
  - Queries AWS CloudTrail logs (via S3 event delivery or API).
  - `query()` filters by entity (user ARN, IP, resource ARN) and time window.
  - Returns structured `Event` objects with API call metadata.

Deliverables:

- `src/wolfpack/adapters/cloudtrail.py`

Acceptance checks:

- adapter queries CloudTrail logs (mocked in tests)
- feature-flag gated: `feature_flags["adapter_cloudtrail"]`

#### A5. Register Tier-2 adapter tools

Tasks:

- Update `src/wolfpack/adapters/tools.py` to include Tier-2 adapters behind feature flags.
- Each Tier-2 adapter tool is only available when its feature flag is enabled in `Settings`.
- Update `Settings` to include `feature_flags: dict[str, bool]` with defaults for each Tier-2 adapter.

Deliverables:

- updated `src/wolfpack/adapters/tools.py`
- updated `src/wolfpack/config/settings.py`

Acceptance checks:

- Tier-2 adapter tools are registered only when their feature flag is `True`
- default configuration has all Tier-2 adapters disabled
- enabling a feature flag makes the corresponding tool available

#### A6. Add Tier-2 adapter unit tests

Tasks:

- Add tests to `tests/unit/test_adapters.py` for each Tier-2 adapter.
- Test with mocked data sources.
- Test feature-flag gating: adapter is unavailable when flag is `False`.

Deliverables:

- updated `tests/unit/test_adapters.py`

Acceptance checks:

- all Tier-2 adapters pass unit tests with mocked data
- feature-flag gating works correctly

### Track B: Branch Creation, Management, and Explosion Controls

Purpose: enable the Flanker to create branches and prevent runaway branching.

#### B1. Implement branch creation in the graph

Tasks:

- Update `src/wolfpack/orchestrator/graph.py`:
  - Add a `create_branch` function that:
    - Creates a new `BranchState` row in Postgres (via persistence helpers).
    - Links it to the parent branch via `parent_branch_id`.
    - Publishes a `hunt.branch.created` NATS message.
  - Add a graph edge from `flanker` that can create branches.
  - Each new branch gets its own sub-graph execution with its own state.
- Implement the `BranchSpec` creation logic in `src/wolfpack/orchestrator/branches.py`.

Deliverables:

- updated `src/wolfpack/orchestrator/graph.py`
- `src/wolfpack/orchestrator/branches.py`

Acceptance checks:

- creating a branch produces a new `BranchState` row
- branch depth and parent are recorded correctly
- NATS message is published on branch creation

#### B2. Implement branch-explosion controls

Tasks:

- Create `src/wolfpack/orchestrator/budget.py`.
- Implement `BranchBudget`:
  - `max_depth: int` — maximum branch nesting depth (default: 3).
  - `max_branches_per_case: int` — maximum number of branches per case (default: 10).
  - `token_budget_per_branch: int` — maximum tokens per branch (default: 10k).
  - `tool_budget_per_branch: int` — maximum tool calls per branch (default: 15).
  - `check(case_id, branch_depth) -> bool` — returns `False` if budget is exceeded.
  - `remaining(case_id) -> BudgetRemaining` — returns remaining budget for a case.
- Values are loaded from `Settings.branch_budget` (configurable via `.env`).

Deliverables:

- `src/wolfpack/orchestrator/budget.py`

Acceptance checks:

- budget check prevents branch creation when limits are exceeded
- remaining budget is computed correctly
- values are configurable via settings

#### B3. Implement hypothesis dedup

Tasks:

- Create `src/wolfpack/orchestrator/dedup.py`.
- Implement `hypothesis_dedup(existing_hypotheses: list[Hypothesis], new_hypothesis: Hypothesis) -> bool`:
  - Returns `True` if the new hypothesis is too similar to any existing one.
  - Uses cosine similarity on hypothesis description embeddings (from the RAG pipeline's embedding model).
  - Threshold is configurable (default: 0.85).
  - If similar, the new hypothesis is merged with the existing one (updated confidence, combined evidence refs).

Deliverables:

- `src/wolfpack/orchestrator/dedup.py`

Acceptance checks:

- duplicate hypotheses are detected and merged
- distinct hypotheses are kept
- threshold is configurable

#### B4. Wire budget checks into the graph

Tasks:

- Update the graph to check `BranchBudget` before creating a branch:
  - If budget is exceeded, log the event and skip branch creation.
  - Flanker is notified that the branch was not created (via the graph state).
- Update the Flanker node to check remaining budget before proposing branches.
- Wire hypothesis dedup into the Flanker node: new hypotheses are checked against existing ones before branch creation.

Deliverables:

- updated graph with budget checks and dedup

Acceptance checks:

- branches are not created when budget is exceeded
- Flanker skips branch creation gracefully
- duplicate hypotheses are merged, not duplicated

### Track C: Flanker Agent Implementation

Purpose: build the Flanker agent with lateral-pivot tools.

#### C1. Implement Flanker agent

Tasks:

- Create `src/wolfpack/agents/flanker.py`.
- Implement `FlankerAgent` as a Pydantic AI agent:
  - Input: `FlankerInput` (case state, tracker findings, branch context).
  - Output: `FlankerOutput` (pivots, updated hypotheses, `branches_to_create`, evidence refs).
  - Tools available (with allowlist):
    - All Tier-1 telemetry query tools (inherited from Tracker).
    - All enabled Tier-2 telemetry query tools (DNS, Zeek/Suricata, Cloudflare, CloudTrail — behind feature flags).
    - `threat_intel_tool` and `case_history_tool` (shared RAG tools).
    - `create_branch` tool — proposes a new branch for lateral pivots.
  - Uses the same LLM model as Tracker (Llama 3.3 70B Instruct via Ollama).
- Wire Flanker into the LangGraph graph, replacing `stub_flanker`.

Deliverables:

- `src/wolfpack/agents/flanker.py`

Acceptance checks:

- Flanker processes tracker findings and returns structured `FlankerOutput`
- Flanker can propose new branches via `create_branch` tool
- tool allowlist prevents Flanker from using Closer-only or case-modification tools

#### C2. Implement Flanker re-check loop

Tasks:

- Update the LangGraph graph routing logic:
  - After Tracker returns, if `tracker_confidence < 3` (i.e., `Confidence.WEAK` or `Confidence.COINCIDENCE`), route to Flanker for additional pivots before Closer runs.
  - After Flanker returns, if Flanker produced significant new findings, route back to Tracker for re-assessment.
  - The re-check loop has a maximum iteration count (default: 2) to prevent infinite loops.
  - Each iteration is budgeted against the case's total token/tool budget.
- Update `src/wolfpack/orchestrator/graph.py` with conditional routing.

Deliverables:

- updated graph routing logic

Acceptance checks:

- low-confidence Tracker results trigger Flanker re-check
- re-check loop has a maximum iteration count
- budget is consumed across iterations

#### C3. Add Flanker unit tests

Tasks:

- Add `tests/unit/test_flanker.py`.
- Test: Flanker output with mocked LLM and tools.
- Test: tool allowlist enforcement for Flanker.
- Test: branch proposal via `create_branch` tool.
- Test: re-check loop routing (confidence < 3 → Flanker, then back to Tracker).

Deliverables:

- `tests/unit/test_flanker.py`

Acceptance checks:

- Flanker produces structured output with mocked LLM
- tool allowlist blocks unauthorized tools
- branch proposals are structured correctly
- re-check loop routes correctly

### Track D: Integration Tests and Evaluation

Purpose: prove the branching and Flanker work end-to-end.

#### D1. Branch creation integration test

Tasks:

- Add `tests/integration/test_branching.py`.
- Test: Flanker proposes a branch → branch is created in Postgres → sub-graph executes → branch completes.
- Test: branch-explosion controls prevent excessive branching.
- Test: hypothesis dedup merges similar branches.

Deliverables:

- `tests/integration/test_branching.py`

Acceptance checks:

- branches are created and tracked in the database
- budget limits are enforced
- duplicate hypotheses are merged

#### D2. Flanker pivot integration test

Tasks:

- Add `tests/integration/test_flanker_pivot.py`.
- Test: Tracker produces low-confidence finding → Flanker re-checks with Tier-2 adapters → produces higher-confidence finding.
- Test: Flanker creates a lateral pivot branch → branch completes → case state is updated.

Deliverables:

- `tests/integration/test_flanker_pivot.py`

Acceptance checks:

- re-check loop produces improved results
- lateral pivot branches are created and completed
- case state reflects all branches

#### D3. Feature-flag integration test

Tasks:

- Add `tests/integration/test_feature_flags.py`.
- Test: with all Tier-2 flags disabled, Flanker only has Tier-1 tools.
- Test: enabling a Tier-2 flag makes the corresponding adapter tool available.
- Test: Flanker gracefully handles unavailable adapters.

Deliverables:

- `tests/integration/test_feature_flags.py`

Acceptance checks:

- feature flags correctly gate adapter availability
- Flanker works with a subset of adapters enabled

#### D4. Update evaluation golden sets

Tasks:

- Add 3–5 new golden-set hunts to `tests/eval/golden_sets/`:
  - Lateral movement detection requiring DNS pivot.
  - Multi-branch investigation with budget enforcement.
  - Re-check loop scenario (low Tracker confidence → Flanker re-check).
  - Feature-flag scenario (Tier-2 adapter disabled).
- Update the evaluation harness to include branch metrics: branch count, branch depth, budget utilization.

Deliverables:

- new golden-set fixtures
- updated evaluation harness

Acceptance checks:

- new golden sets cover branching scenarios
- evaluation harness reports branch metrics

## 5. Recommended Delivery Sequence

1. DNS adapter (A1) — highest-leverage Tier-2 source
2. Feature-flag infrastructure (A5) — needed before other Tier-2 adapters
3. Remaining Tier-2 adapters (A2–A4)
4. Branch creation in graph (B1)
5. Branch-explosion controls (B2)
6. Hypothesis dedup (B3)
7. Budget checks in graph (B4)
8. Flanker agent (C1)
9. Re-check loop (C2)
10. Integration tests (D1–D3)
11. Evaluation updates (D4)

## 6. Parallelization Plan

### Safe parallel lanes at the start

- Lane 1: All Tier-2 adapters (A1–A4)
- Lane 2: Branch creation logic (B1–B2)

### Safe parallel lanes after Track B

- Lane 1: Flanker agent (C1)
- Lane 2: Integration tests (D1–D3)

### Work that should stay on the critical path

- Feature-flag infrastructure must land before Tier-2 adapter tools
- Branch creation must land before Flanker (Flanker creates branches)
- Budget checks must land before integration tests
- Flanker agent must land before re-check loop wiring

## 7. Milestones and Exit Criteria

### Milestone 1: Tier-2 Adapters Available

Exit criteria:

- all four Tier-2 adapters implement `TelemetrySource`
- adapters are feature-flag gated
- unit tests pass with mocked data

### Milestone 2: Branching Works

Exit criteria:

- branches are created in the database
- budget limits are enforced
- hypothesis dedup merges similar branches

### Milestone 3: Flanker Agent Functional

Exit criteria:

- Flanker processes tracker findings and produces structured output
- Flanker can create branches via `create_branch` tool
- tool allowlist prevents unauthorized access

### Milestone 4: Phase 4 Complete

Exit criteria:

- re-check loop works (low confidence → Flanker → improved findings)
- integration tests pass for branching, pivoting, and feature flags
- evaluation golden sets cover branching scenarios
- no Tier-3+ adapters or Closer agent has landed

## 8. Command-Level Validation Checklist

```bash
uv sync
just lint
just typecheck
just test
just test-integration
just eval
```

All of these should succeed before Phase 4 is marked complete.

## 9. Risks to Watch During Execution

### Branch-explosion risk in production

The conservative defaults (max-depth 3, max-branches 10) may be too aggressive for complex hunts. Monitor branch metrics during evaluation and adjust. The values are configurable, so tuning is easy.

### Tier-2 adapter data format variability

DNS logs, Zeek/Suricata output, and Cloudflare logs have highly variable formats across deployments. Each adapter should handle format detection and report format-specific issues clearly.

### Re-check loop convergence risk

The Tracker → Flanker → Tracker loop may not converge if the LLM produces inconsistent confidence values. The maximum iteration count (default: 2) is a hard stop, but the loop may still produce diminishing returns. Monitor iteration metrics.

### Feature-flag complexity

Each Tier-2 adapter behind a feature flag adds a dimension to the test matrix. Test the combinations that matter (all disabled, each individually enabled, all enabled) rather than exhaustive combinations.

### Cosine similarity dedup threshold

A threshold of 0.85 may be too aggressive or too lenient depending on the embedding model. Calibrate against the golden set and adjust. Document the threshold as configurable.

## 10. Definition of Done Mapping

| Definition of done item | Proof artifact |
|---|---|
| Tier-2 adapters implement `TelemetrySource` | all four adapters, unit tests |
| Feature flags gate adapter availability | `Settings.feature_flags`, tool registration |
| Branches are created and tracked | `branches.py`, database rows, integration test |
| Budget limits are enforced | `budget.py`, integration test |
| Hypothesis dedup works | `dedup.py`, unit test |
| Flanker produces structured output | `flanker.py`, unit test |
| Re-check loop routes correctly | graph routing, unit and integration tests |
| Evaluation covers branching | new golden sets, updated harness |

## 11. Suggested PR Slicing

1. `phase4-tier2-adapters` — All four Tier-2 adapters, feature-flag infrastructure, unit tests
2. `phase4-branching` — Branch creation, budget controls, dedup, graph updates
3. `phase4-flanker` — Flanker agent, re-check loop, tool allowlist
4. `phase4-eval-branching` — Integration tests, updated golden sets, branch metrics

## 12. Immediate Next Action

The first implementation step should be:

1. add `feature_flags` to `Settings` in `src/wolfpack/config/settings.py`
2. implement the DNS adapter (highest-priority Tier-2 source)
3. implement branch creation in the graph