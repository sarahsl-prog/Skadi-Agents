# WolfPack Core Logic Remediation - May 8

This document tracks the fixes for the issues identified during the core agent logic audit.

## Priority 1: Critical Logic & Stability
- [x] **TRACK-01: Fix Tracker Entity Fallout** *(Completed 2026-05-08 in commit `1e8aa99`)*
    - **Problem:** Tracker receives empty entity lists when seed is raw text and no branches exist, causing agent failure.
    - **Fix:** Implement initial entity extraction in `AlphaDispatcher` and refine `Tracker` fallback logic.
    - **Validation:** Unit tests in `tests/unit/test_alpha.py` and `tests/unit/test_tracker.py` passed.

- [x] **ORCH-01: Fix NATS "Fire-and-Forget" Race Condition** *(Completed 2026-05-08 in commit `729aa21`)*
    - **Problem:** Sync nodes in the graph use `create_task` for NATS publishing, risking log loss on process exit.
    - **Fix:** Migrate all graph nodes to `async` or implement a blocking publish for critical transitions.
    - **Validation:** Integration test ensuring ledger/event consistency during rapid process shutdown.

## Priority 2: Architecture & Reliability
- [x] **BUDG-01: Externalize Branch Budget State** *(Completed 2026-05-08)*
    - **Problem:** Budget state is in-memory, causing inconsistency in multi-worker environments.
    - **Fix:** Migrate `BranchBudget` state from Python `dict` to Redis or Postgres.
    - **Validation:** Multi-process simulation test verifying budget is shared.

- [x] **SEC-01: Telemetry Source Prompt-Injection Defense** *(Completed 2026-05-08 in commit `dcff69f`)*
    - **Problem:** Potential for prompt injection via attacker-controlled log data.
    - **Fix:** Implemented explicit delimiters (`<WOLFPACK_PROMPT>`) and instruction-repetition guards in `traced_agent_run` via `defend_agent_prompt`.
    - **Validation:** New tests in `tests/security/test_telemetry_prompt_injection.py` (11 tests passed).

## Priority 3: Test Coverage & Verification
- [x] **TEST-01: Implement Ledger Integrity Verification Test** *(Completed 2026-05-08)*
    - **Problem:** No automated test for the hash-chain tampering detection.
    - **Fix:** Create a test that manually alters a ledger entry and asserts `verify_chain()` failure.
    - **Validation:** Successful execution of the new integrity test.

- [ ] **TEST-02: Expand Agent Edge-Case Testing**
    - **Problem:** General lack of "empty state" or "extreme input" tests for agents.
    - **Fix:** Add boundary tests for `Alpha`, `Tracker`, and `Closer` (e.g., 0 entities, 100+ entities).
    - **Validation:** Pytest coverage report increase.

---
**Status:**
- Total items: 6
- Completed: 5
- In Progress: 0
- Remaining: 1
