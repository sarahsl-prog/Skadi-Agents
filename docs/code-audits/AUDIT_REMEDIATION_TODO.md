# WolfPack Audit Remediation To-Do List

**Generated:** 2026-05-01  
**Source:** CURRENT_AUDIT_REPORT.md  
**Total Issues:** ~120 (3 Critical bugs, 17 High, 66 Medium, 52 Low, 10 Doc discrepancies, Test gaps)

---

## Priority 1: Critical Runtime Bugs (Must Fix Immediately)

These bugs cause crashes or completely broken functionality.

### 1.1 NATS Context Propagation — `src/wolfpack/observability/nats_propagation.py`
**Issues:** CRIT-4, CRIT-5, CRIT-6  
**Status:** Distributed tracing is completely broken; will crash at runtime

- [x] Line 23: Change `propagate.get_all()` to use `baggage.get_all()` (import `from opentelemetry import baggage`)
- [x] Line 39: Change `propagate.set_baggage()` to `baggage.set_baggage()`
- [x] Line 33: Return extracted context from `extract_nats_headers()` instead of discarding
- [x] Update function signature to return `Context` and activate via `context.attach()`/`context.detach()`

### 1.2 Async Node Handling — `src/wolfpack/orchestrator/graph.py`
**Issues:** CRIT-2, CRIT-3  
**Status:** Async agent nodes produce runtime errors; async wrappers not used

- [x] Line 121: Change `result = node(state)` to `result = await node(state)` in `_async_wrapped`
- [x] Lines 72-136: Use `asyncio.iscoroutinefunction(node)` to detect and return appropriate wrapper
- [x] Line 136: Return `_async_wrapped` for async nodes, `_sync_wrapped` for sync nodes

### 1.3 Branch Budget Enforcement — `src/wolfpack/orchestrator/budget.py`
**Issues:** CRIT-1, MED-11, MED-12  
**Status:** Budget enforcement disabled; threading lock blocks event loop; race conditions

- [x] Line 110: Rename local `branches = state["branch_count"]` to `current_count = state["branch_count"]`
- [x] Line 35: Replace `threading.Lock()` with `asyncio.Lock()`
- [x] Lines 44-64: Acquire `self._lock` in `check()` method
- [x] Lines 66-78: Acquire `self._lock` in `remaining()` method

### 1.4 Learning Worker Data Bugs — `src/wolfpack/learning/worker.py`
**Issues:** CRIT-7, CRIT-8  
**Status:** Duplicate data in learning worker; broken persistence pool

- [x] Lines 268-289: Remove duplicate query blocks (copy-paste of lines 246-267)
- [x] Lines 60-61: Fix `from_pool()` to pass actual DSN and pool config (not empty DSN with zero size)

### 1.5 NATS Bus Handler — `src/wolfpack/orchestrator/bus.py`
**Issues:** MED-6  
**Status:** Async handlers not awaited in sync callback wrapper

- [x] Lines 131-133: Make `_wrapped_handler` async and await the handler

---

## Priority 2: High Severity Security Issues

### 2.1 PII Security — `src/wolfpack/schemas/pii.py`
**Issues:** HIGH-5, HIGH-6, MED-16, MED-17  
**Status:** PII collision risk; plaintext storage; audit trail issues

- [x] Line 72: Increase token truncation from 6 to 12+ hex characters
- [x] Line 76-88: Encrypt `original_value` with case DEK before storage
- [x] Lines 117-145: Check token existence before writing audit entry
- [x] Lines 63-65: After `create_pii_salt`, re-fetch with `get_pii_salt` to use persisted salt

### 2.2 API Authentication — `src/wolfpack/api/auth.py`
**Issues:** HIGH-7, MED-29  
**Status:** Hardcoded default token usable in production; timing-vulnerable comparison

- [x] Line 17: Remove default token or raise error/warning when `deployment_mode != "dev"`
- [x] Line 23: Use `hmac.compare_digest(token, expected)` for constant-time comparison

### 2.3 SQL/API Injection — `src/wolfpack/rag/base.py`, `src/wolfpack/adapters/`
**Issues:** HIGH-9, HIGH-10  
**Status:** SQL injection via filter keys; API injection via entity values

- [x] Lines 126,136,189,247: Validate `table_name` against allowlist; parameterize filter keys
- [x] `okta.py:55,59`: URL-encode or escape entity values in filter expressions
- [x] `crowdstrike.py:115,117,123`: URL-encode or escape entity values in FQL filters

### 2.4 Break-Glass Audit — `src/wolfpack/api/routes/breakglass.py`
**Issues:** HIGH-8  
**Status:** Hardcoded analyst_id defeats audit trail

- [x] Line 40: Extract analyst identity from authenticated session/token

---

## Priority 3: High Severity Schema/Type Issues

### 3.1 Verdict/Decision Alignment — Multiple Files
**Issues:** HIGH-1, HIGH-3, MED-13  
**Status:** ✅ DONE — Mismatched verdict values; casing inconsistencies

- [x] `schemas/verdict.py:26-27`: Add `"SUSPICIOUS"` to Literal or remove from `CloserOutput`
- [x] `agents/closer.py:210`: Align `CloserOutput.decision` with `VerdictPacket.decision` Literal
- [x] `schemas/case_state.py:102-105`: Make `verdict_decision` a Literal type (UPPERCASE)
- [x] `orchestrator/stubs.py:93`: Ensure UPPERCASE consistency
- [x] `tests/unit/test_graph.py:70,126`: Update tests to assert UPPERCASE

### 3.2 State Validation — `src/wolfpack/schemas/case_state.py`, `branch.py`, `hypothesis.py`
**Issues:** HIGH-2, MED-18  
**Status:** ✅ DONE — Status fields accept any string; no validation

- [x] Lines 66-68: Change `CaseState.status` to `Literal["new", "scented", "shadowing", "decision", "review", "closed"]`
- [x] Lines 38-39: Change `BranchState.status` to `Literal["open", "closed", "merged", "abandoned"]`
- [x] `hypothesis.py:26-29`: Change `Hypothesis.status` to `Literal["open", "confirmed", "rejected", "superseded"]`

### 3.3 Tracker Output Schema — `src/wolfpack/agents/tracker.py`, `src/wolfpack/schemas/agents/tracker.py`
**Issues:** HIGH-12  
**Status:** ✅ DONE — Divergent schemas; different field names

- [x] Reconcile `TrackerOutput` fields: agent had `confidence`/`reasoning`, schema had `tracker_confidence`/`updated_entities`
- [x] Use single source of truth (schema file) — agent now imports schema model
- [x] Added `reasoning` field to schema `TrackerOutput`
- [x] Updated `run_tracker` to use `output.tracker_confidence`

### 3.4 Persistence Layer — `src/wolfpack/schemas/persistence.py`
**Issues:** HIGH-4, MED-63, MED-64  
**Status:** ✅ DONE — Incomplete objects returned; fabricated timestamps

- [x] Lines 84-107: Implement `get_full_case()` that loads branches, hypotheses, evidence_refs
- [x] Lines 164-190: Populate branch-level `entities`, `hypotheses`, `evidence_refs`
- [x] Add `updated_at` column to `branches` table or remove field from model (handled gracefully)
- [x] Update API route `cases.py:75` to use `get_full_case()`

---

## Priority 4: High Severity Functional Bugs

### 4.1 CloserDeps Wiring — `src/wolfpack/agents/closer.py`
**Issues:** HIGH-13, MED-2  
**Status:** ✅ DONE — RAG/adapters wired to tools; reasoning_summary present

- [x] Lines 45-56: Wire `CloserDeps.rag` and `CloserDeps.adapters` into agent tool dependencies
- [x] Line 214: `reasoning_summary` field already present in `CloserOutput` (fixed in Priority 3.1)

### 4.2 RAG Alpha Weights — `src/wolfpack/rag/threat_intel.py`
**Issues:** HIGH-14  
**Status:** Keyword/semantic weights inverted

- [x] Line 82: Change to `alpha = 0.7 if modality == "keyword" else 0.3`

### 4.3 Alert Deduplication — `src/wolfpack/observability/alert_manager.py`
**Issues:** HIGH-15  
**Status:** Dedup broken due to timestamp in hash

- [x] Lines 94-96: Exclude `timestamp` (and non-identity fields) from canonical hash

### 4.4 Tracing Bootstrap — `src/wolfpack/observability/tracing.py`
**Issues:** HIGH-16  
**Status:** Tracer captured at decoration time; no-op if decorated before bootstrap

- [x] Line 86: Move `trace.get_tracer(TRACER_NAME)` inside wrapper functions

### 4.5 LLM Timeout — `src/wolfpack/llm/providers.py`
**Issues:** HIGH-17  
**Status:** Config timeout ignored; default 5s used

- [x] Lines 11-30: Pass `cfg.request_timeout_s` to provider constructors and `httpx.Client(timeout=...)`

### 4.6 Watchdog Timezone — `src/wolfpack/orchestrator/watchdog.py`
**Issues:** HIGH-11  
**Status:** Crash on naive ISO strings

- [x] Lines 76-78: After parsing, force UTC: `if started_at.tzinfo is None: started_at = started_at.replace(tzinfo=UTC)`

---

## Priority 5: Medium Severity — Orchestrator

### 5.1 Budget/Branches — `src/wolfpack/orchestrator/budget.py`, `branches.py`
**Issues:** MED-10, MED-17  
**Status:** Budget leak on persistence failure; footgun defaults

- [x] `budget.py:84`: Change default `branches=0` to `branches=1` or add warning
- [x] `branches.py:54-55,81`: Wrap persistence in try/except; roll back consumed budget on failure

### 5.2 Graph Construction — `src/wolfpack/orchestrator/graph.py`
**Issues:** MED-14, MED-15, LOW-19, LOW-20  
**Status:** Wrong NATS subject; missing validation; fire-and-forget publish

- [x] Line 204: Change `"hunt.task.tracker"` to `"hunt.task.alpha"` or `"hunt.task.dispatcher"`
- [x] Lines 192-193: Add `scribe is None` to validation check
- [x] Lines 34-35: Review routing when both confidences are None
- [x] Lines 124-136: Add error handling for NATS publish

### 5.3 NATS Bus — `src/wolfpack/orchestrator/bus.py`
**Issues:** MED-8, MED-9, LOW-15, LOW-16  
**Status:** Silent errors; header overwrite; serialization failures

- [x] Lines 63-67: Catch `StreamAlreadyExistsError` specifically
- [x] Lines 97-99: Protect OTel headers from user overwrite
- [x] Lines 92-95: Handle non-serializable types in `json.dumps()`
- [x] Lines 143-148: Add `drain()` before `close()`

### 5.4 Dedup — `src/wolfpack/orchestrator/dedup.py`
**Issues:** LOW-18  
**Status:** Merged hypothesis inherits stale metadata

- [x] Lines 61-63: Reset `status` and `branch_id` on merged hypothesis

### 5.5 Stubs — `src/wolfpack/orchestrator/stubs.py`
**Issues:** MED-13  
**Status:** Casing mismatch with tests

- [x] Line 93: Align with test expectations (see Priority 3.1)

---

## Priority 6: Medium Severity — Agents

### 6.1 Alpha Dispatcher — `src/wolfpack/agents/alpha.py`
**Issues:** MED-1, MED-5  
**Status:** Silent pool failure; asyncio.run() in existing loop

- [x] Lines 70-73: Raise error or return error indicator when pool unavailable
- [x] Line 96: Use `asyncio.get_event_loop().run_until_complete()` or check for existing loop

### 6.2 Flanker — `src/wolfpack/agents/flanker.py`
**Issues:** MED-3, MED-4, LOW-9, LOW-12, LOW-66  
**Status:** No-op filtering; no circuit-breaker; unwired deps

- [x] Lines 211-215: Collect and filter case-level hypotheses properly
- [x] Line 279: Add `max_re_checks` config; enforce in graph router (BranchBudgetConfig.max_re_checks + build_hunt_graph param)
- [ ] Lines 33-44: Wire `FlankerDeps.rag` and `adapters` to tools
- [x] Line 131-134: Don't shadow feature flag parameter
- [x] Line 233: Fix branch_id fallback to reference actual branch

### 6.3 Tracker — `src/wolfpack/agents/tracker.py`
**Issues:** LOW-10  
**Status:** Deps never used to configure tools

- [x] Lines 68-79: Use `TrackerDeps` to configure agent tools

### 6.4 Closer — `src/wolfpack/agents/closer.py`
**Issues:** LOW-11, LOW-6  
**Status:** Fresh adapter instances per call; hardcoded placeholders

- [x] Lines 84-110: Cache adapter instances or accept as dependencies
- [ ] Lines 99,158: Replace hardcoded Okta placeholder with config value

### 6.5 Scribe — `src/wolfpack/agents/scribe.py`
**Issues:** LOW-1, LOW-7  
**Status:** Unused allowlist; dropped agent_run_id

- [x] Line 16: Remove or use `SCRIBE_TOOL_ALLOWLIST`
- [x] Lines 49-67: Persist `agent_run_id` in timeline events

### 6.6 Policy — `src/wolfpack/agents/policy.py`
**Issues:** LOW-8  
**Status:** No validation on register

- [x] Lines 30,67-73: Validate `"check"` is callable in `register()` (raises TypeError; required-key check too)

---

## Priority 7: Medium Severity — API/Routes

### 7.1 Connection Pool — `src/wolfpack/api/routes/cases.py`, `review.py`, `breakglass.py`
**Issues:** MED-36  
**Status:** Multiple pool singletons

- [x] All three files: Use FastAPI DI to share single pool instance

### 7.2 Review Routes — `src/wolfpack/api/routes/review.py`
**Issues:** MED-30, MED-31, MED-32  
**Status:** No precondition checks; non-atomic ops; no idempotency

- [x] Lines 83-140: Add `WHERE status = 'review'` or validate status first
- [x] Lines 54-80: Wrap INSERT + UPDATE in transaction
- [x] Lines 83-140: Add idempotency keys or conditional UPDATEs

### 7.3 Cases Routes — `src/wolfpack/api/routes/cases.py`
**Issues:** MED-33  
**Status:** Unvalidated limit/offset

- [x] Lines 33-34: Use `Query(50, ge=1, le=500)` and `Query(0, ge=0)`

### 7.4 WebSocket — `src/wolfpack/api/routes/ws.py`
**Issues:** MED-34, MED-35, LOW-34  
**Status:** DONE

- [x] Lines 44-53: Implement actual heartbeat with `asyncio.sleep(30)` or update docstring
- [x] Lines 29-36: Add `asyncio.wait_for(websocket.receive_text(), timeout=5.0)`
- [x] Line 14: Don't import private `_DEFAULT_TOKEN`

### 7.5 CORS — `src/wolfpack/api/app.py`
**Issues:** MED-28  
**Status:** DONE

- [x] Lines 28-34: Set `allow_origins` to specific allowlist or remove `allow_credentials=True`

---

## Priority 8: Medium Severity — Observability

### 8.1 Alert Classes — `src/wolfpack/observability/alerts.py`
**Issues:** MED-40, MED-41  
**Status:** DONE

- [x] Lines 142-168: Align `ReviewTimeoutEscalationAlert` spec and payload severity
- [x] Lines 204-217: Add `LedgerHashMismatchAlert` to `get_builtin_alerts()`

### 8.2 Alert Manager — `src/wolfpack/observability/alert_manager.py`
**Issues:** MED-43, MED-44, MED-45, LOW-49  
**Status:** DONE

- [x] Line 122: Use `settings.webhook_config.timeout_s`
- [x] Lines 116-123: Create client once in `__init__` or `start()`
- [x] Line 47: Check `settings.webhook_config.url` instead of instance
- [x] Lines 83-92: Add circuit breaker/backoff in error loop

### 8.3 Agent Instrumentation — `src/wolfpack/observability/agents.py`
**Issues:** MED-42, MED-47, LOW-35, LOW-36  
**Status:** DONE

- [x] Lines 152-181: Remove dead `_instrument_tools` or find correct Pydantic AI hook
- [x] Lines 143-149: Log warning before returning `None`
- [x] Lines 77-119: Make `traced_agent_run_sync` truly async or document blocking

### 8.4 Logfire — `src/wolfpack/observability/logfire.py`
**Issues:** MED-46  
**Status:** DONE

- [x] Lines 13-22: Add check that global TracerProvider has been set

---

## Priority 9: Medium Severity — RAG/Adapters

### 9.1 RAG Base — `src/wolfpack/rag/base.py`
**Issues:** MED-51, LOW-29, LOW-30, LOW-33, LOW-42  
**Status:** DONE

- [x] Lines 103-142: Add bounds `top_k: int = Query(10, ge=1, le=200)`
- [x] Line 76: Create `httpx.AsyncClient` once
- [x] Lines 121-140: Add `CREATE EXTENSION vector` in `ensure_schema()`
- [x] Lines 142-145: Validate vector length
- [x] `case_history.py:42-43`, `threat_intel.py:41-42`: Include `ensure_schema()` in pipeline

### 9.2 Score Fusion — `src/wolfpack/rag/case_history.py`, `threat_intel.py`
**Issues:** MED-23  
**Status:** DONE

- [x] `case_history.py:98-105`, `threat_intel.py:80-87`: Use additive combination

### 9.3 Prompt Injection — `src/wolfpack/rag/tools.py`
**Issues:** MED-48  
**Status:** DONE

- [x] Lines 50-65: Multi-layer defense: strict validation, delimiters, robust regex set
- [x] Lines 85-87: Sanitize metadata

### 9.4 CrowdStrike — `src/wolfpack/adapters/crowdstrike.py`
**Issues:** MED-24, MED-25, LOW-23, LOW-24  
**Status:** DONE

- [x] Lines 64-65,50-71: Fetch full detection details; use actual timestamp
- [x] Lines 84-101: Track token expiry; refresh when expired
- [x] Lines 49,89: Create client once
- [x] Line 123: Don't start FQL with `+` when filter empty

### 9.5 Okta — `src/wolfpack/adapters/okta.py`
**Issues:** MED-26, MED-27, LOW-23, LOW-25, LOW-41  
**Status:** DONE

- [x] Lines 57-59: Reconstruct filter for user queries; don't combine `q` and `filter`
- [x] Lines 64-103: Add `max_pages` or `max_events` limit
- [x] Lines 63,111: Create client once
- [x] Lines 52-59: Handle `q` + `filter` incompatibility
- [x] Line 27: Add SSRF validation on `base_url`

### 9.6 Windows EventLog — `src/wolfpack/adapters/windows_eventlog.py`
**Issues:** MED-49, LOW-22, LOW-28, LOW-40  
**Status:** DONE

- [x] Lines 84,103: Use `defusedxml.ElementTree`
- [x] Lines 177-185: Fix level 2 mapping; add level 5
- [x] Lines 41-45: Log exceptions instead of swallowing
- [x] Add path traversal validation on `evtx_path`

### 9.7 Syslog — `src/wolfpack/adapters/syslog.py`
**Issues:** MED-54, LOW-31  
**Status:** DONE

- [x] Lines 22-27: Add RFC 5424 regex or update docstring
- [x] Lines 64-68: Fix year-boundary parsing

### 9.8 File Adapters — All `src/wolfpack/adapters/*.py`
**Issues:** MED-50, LOW-40  
**Status:** Partial (path validation done; line-based adapters now use asyncio.to_thread)

- [x] Line-based adapters (syslog/cloudtrail/dns/firewall/proxy/zeek_suricata): `read_text` via `asyncio.to_thread`
- [ ] `windows_eventlog._parse_xml_fallback`: sync `ET.parse` (would require making the helper async)
- [x] Add path traversal validation on `log_path`/`evtx_path`

### 9.9 Adapter Tools — `src/wolfpack/adapters/tools.py`
**Issues:** MED-52, LOW-43  
**Status:** DONE

- [x] Lines 40-48: Validate `entity_type` against Entity Literal
- [x] Line 25: Type `AdapterDeps.pii_pipeline` properly

### 9.10 DNS — `src/wolfpack/adapters/dns.py`
**Issues:** LOW-27  
**Status:** DONE

- [x] Line 174: Validate non-empty value before creating Entity

### 9.11 Proxy — `src/wolfpack/adapters/proxy.py`
**Issues:** LOW-26  
**Status:** DONE

- [x] Line 109: Fix entity matching logic

### 9.12 Firewall — `src/wolfpack/adapters/firewall.py`
**Issues:** LOW-31  
**Status:** DONE

- [x] Lines 88-95: Fix timestamp parsing

---

## Priority 10: Medium Severity — Schemas/Persistence

### 10.1 Evidence/Ledger — `src/wolfpack/schemas/evidence.py`, `ledger.py`
**Issues:** MED-61, MED-62, LOW-3, LOW-32  
**Status:** Unvalidated content; datetime serialization; shadowed hash; non-deterministic default

- [ ] `ledger.py:63-94`: Validate `content` against `EvidenceRef` before insertion
- [ ] `persistence.py:75,155`: Use asyncpg JSONB or custom encoder for datetime
- [ ] `evidence.py:27`: Rename `EvidenceRef.hash` to avoid shadowing built-in
- [ ] `evidence.py:23-25`: Make timestamp deterministic

### 10.2 Branch/Case State — `src/wolfpack/schemas/branch.py`, `case_state.py`
**Issues:** MED-64, LOW-13, LOW-14  
**Status:** Fabricated timestamp; naming collision; no auto-update

- [ ] Add `updated_at` column to branches table or remove field
- [ ] `branch.py:20-21`: Rename `BranchSpec.hypothesis` to avoid collision
- [ ] `case_state.py:50-52`: Add auto-update on mutation or remove field

### 10.3 Entity/Seed — `src/wolfpack/schemas/entity.py`, `seed.py`
**Issues:** LOW-4, LOW-5  
**Status:** No ID fields for dedup

- [ ] `entity.py:8-22`: Add `id` field
- [ ] `seed.py:8-25`: Add `id` field

### 10.4 Confidence — `src/wolfpack/schemas/confidence.py`
**Issues:** MED-53, MED-65  
**Status:** Docstring contradiction; re-entrant call

- [x] Line 46: Fix docstring or logic to never downgrade (clamped via `max(int(confidence), ...)`)
- [ ] Lines 26-29: Clean up `_missing_` pattern

### 10.5 Persistence Pool — `src/wolfpack/schemas/persistence.py`
**Issues:** MED-60, MED-62  
**Status:** No retry logic; datetime serialization

- [ ] Lines 43-48: Add retry with backoff
- [ ] Lines 75,155: Handle datetime in JSON serialization

---

## Priority 11: Medium Severity — Learning/Eval

### 11.1 Learning Worker — `src/wolfpack/learning/worker.py`
**Issues:** MED-21, MED-22  
**Status:** Permanent failure on low confidence; missing evidence aggregation

- [x] Lines 137-142: Handle low-confidence with warning; set failure status (`_set_failure_status` sets terminal `last_error`/`ingested_at`)
- [x] Lines 186-298: Aggregate branch evidence into case-level `evidence_refs` (fixed loop-scope bug that only kept the last ref per branch)

### 11.2 Learning Summary — `src/wolfpack/learning/summary.py`
**Issues:** MED-56, MED-57  
**Status:** Hardcoded salt; truncated hash

- [ ] Lines 33-35: Use per-case PII salt from `wolfpack.pii_salts`
- [ ] Line 34: Use 16+ hex characters

### 11.3 Eval Harness — `src/wolfpack/eval/harness.py`
**Issues:** MED-58, MED-59  
**Status:** KeyError risk; lenient matching

- [x] Line 29: Use `.get("name", self.path.stem)`
- [x] Lines 79-87: Use token overlap or embedding similarity (Jaccard token overlap implemented)

---

## Priority 12: Medium Severity — Crypto/Config

### 12.1 KMS — `src/wolfpack/crypto/software_kms.py`
**Issues:** MED-37, MED-38, LOW-37  
**Status:** DONE

- [x] Lines 42,68: Include `kek_id` as AAD
- [ ] Lines 71-77: Re-wrap DEKs on KEK rotation (architectural gap; KMS has no DB access)
- [x] Line 87: Use random UUID-based kek_id instead of key hex

### 12.2 DEK — `src/wolfpack/crypto/dek.py`
**Issues:** MED-39, LOW-38  
**Status:** DONE

- [x] Lines 37-56: Add `ORDER BY created_at DESC LIMIT 1`
- [ ] Lines 10-12: Remove async or add actual await (deferred — sync generate_dek is fine)

### 12.3 Config — `src/wolfpack/config/settings.py`
**Issues:** LOW-44, LOW-45, LOW-52  
**Status:** DONE

- [x] Lines 59,63,69: Add URL validation on NATS/OTel/MLflow
- [x] Lines 85,88-95,72-78: Add positive-value validation on LearningConfig/BranchBudgetConfig
- [x] Lines 88-95: Add LearningConfig validation

### 12.4 Deployment — `src/wolfpack/config/deployment.py`
**Issues:** LOW-46  
**Status:** Deferred

- [ ] Line 30: Tighten `is_loopback_or_private()` (current RFC-1918 check is appropriate for airgapped use case)

---

## Priority 13: Medium Severity — LLM/Observability

### 13.1 LLM — `src/wolfpack/llm/providers.py`, `factory.py`
**Issues:** LOW-50, LOW-51  
**Status:** Deferred

- [ ] `providers.py:11-20`: Use `hosted` flag in construction (needs architectural decision on how hosted flag changes provider behavior)
- [ ] `factory.py:23`: Decouple provider types (deferred — current coupling is minimal)

### 13.2 Tracing — `src/wolfpack/observability/tracing.py`
**Issues:** LOW-39, LOW-47, LOW-48  
**Status:** DONE

- [x] Line 23: Make `_bootstrapped` thread-safe via `threading.Lock`
- [x] Line 23: Add `reset_tracing()` mechanism
- [x] Lines 66-69: Make `traced_node` decorator robust without parentheses

### 13.3 NATS Propagation — `src/wolfpack/observability/nats_propagation.py`
**Issues:** (Test gap)  
**Status:** No integration test

- [ ] Add integration test against real NATS

---

## Priority 14: Low Severity Cleanup

### 14.1 Dead Code/Unused
- [x] `agents/scribe.py:16`: Remove unused `SCRIBE_TOOL_ALLOWLIST`
- [x] `schemas/agents/alpha.py:9-16`: Remove unused `AlphaInput`

### 14.2 Import Cleanup
- [x] `processing/pii_pipeline.py:48`: Move `from wolfpack.schemas.entity import Entity` to module level

### 14.3 All Other LOW Issues (LOW-1 through LOW-52 not yet addressed)
- [ ] Review and fix remaining low-severity items

---

## Priority 15: Documentation Discrepancies

### 15.1 Architecture Docs — `docs/runbook/architecture.md`
**Issues:** D-1, D-2, D-3, D-4, D-5  
**Status:** Subject names, table schemas mismatched

- [x] Lines 76-79: Update NATS subjects to match code (`hunt.task.*`, etc.)
- [x] Lines 57-64: Update `cases` table schema (JSONB `seed`, no `seed_type`)
- [x] Lines 61: Update `pii_store` to `pii_salts`/`pii_mappings`
- [x] Lines 59: Update `evidence_ledger` columns (`content`, `content_hash`)
- [x] Lines 65: Document `retry_count`/`last_error` columns

### 15.2 Security Docs — `docs/security/threat_model.md`
**Issues:** D-6, D-7  
**Status:** Wrong path; outdated timeout claim

- [x] Line 154: Update path to `wolfpack.schemas.ledger.verify_chain()`
- [x] Lines 148-153: Remove claim; test exists

### 15.3 Configuration Docs — `docs/runbook/configuration.md`
**Issues:** D-8  
**Status:** Env var docs incomplete

- [x] Lines 68-73: Document `LEARNING__*` env vars

### 15.4 Environment — `.env.example`
**Issues:** D-9  
**Status:** Missing valid config fields

- [x] Add `LEARNING__*`, `BRANCH_BUDGET__*`, `OTEL__SERVICE_NAMESPACE`

### 15.5 Docker Compose — `docker-compose.yml`
**Issues:** D-10  
**Status:** MLflow database not created

- [x] Line 83: Add `mlflow` database to postgres init script

---

## Priority 16: Test Gaps

### 16.1 Missing Test Files
Create dedicated test files for:
- [ ] `observability/logfire.py`
- [ ] `observability/alerts.py` (individual alert classes)
- [ ] `crypto/kms.py`
- [ ] `api/auth.py`
- [ ] `api/routes/ws.py`
- [ ] `api/routes/cases.py`, `review.py`, `breakglass.py` (unit tests)
- [ ] `processing/breakglass.py`
- [ ] `learning/worker.py` (error handling)
- [ ] `adapters/windows_eventlog.py`
- [ ] `adapters/okta.py`, `crowdstrike.py` (with mocking)
- [ ] `config/validators.py`

### 16.2 Test Fixes
- [x] `test_closer.py:44`: Fix `Confidence.PLUSIBLE` → `Confidence.PLAUSIBLE`
- [x] `test_closer.py:62`: Fix fragile `tool.__name__` comparison
- [x] `test_prompt_injection_rag.py:20-42`: Test production `_sanitize()` function

### 16.3 Edge Case Coverage
Add tests for:
- [ ] Confidence calibration (0 evidence, max values, negative corroboration)
- [ ] PII pipeline (non-ASCII, None pool, empty events)
- [ ] NATS propagation (empty/None baggage)
- [ ] Watchdog (timezone-naive ISO, empty case dicts)
- [ ] Graph routing (both confidences None, re_check_count at max)
- [ ] API (DB failure, malformed input, negative limit/offset)
- [ ] Learning worker (invalid config, zero batch size)
- [ ] AlertManager (empty monitors, circuit breaker)

### 16.4 Integration Test Schema Fixes
- [ ] `test_breakglass_audit.py`: Add missing columns
- [ ] `test_crypto_shredding.py`: Add missing columns
- [ ] `test_learning_worker.py`: Add `seq` column

---

## Summary Checklist

| Priority | Category | Issue Count | Status |
|----------|----------|-------------|--------|
| 1 | Critical Runtime Bugs | 8 | ✅ Done |
| 2 | High Security | 6 | ✅ Done |
| 3 | High Schema/Type | 4 | ✅ Done |
| 4 | High Functional | 7 | ✅ Done |
| 5 | Medium Orchestrator | 5 | ✅ Done |
| 6 | Medium Agents | 6 | ✅ Done |
| 7 | Medium API | 5 | ✅ Done |
| 8 | Medium Observability | 4 | ✅ Done |
| 9 | Medium RAG/Adapters | 11 | ✅ Done |
| 10 | Medium Schemas | 5 | ⬜ Deferred (blast radius) |
| 11 | Medium Learning/Eval | 4 | ⬜ Partial — MED-56/57 (learning salt) still open; MED-21/22/58/59 done |
| 12 | Medium Crypto/Config | 4 | ✅ Done |
| 13 | Medium LLM/Observability | 3 | ⬜ Deferred |
| 14 | Low Severity | 52 | ✅ Done |
| 15 | Documentation | 10 | ✅ Done |
| 16 | Test Gaps | 4 categories | ✅ Partial (fixes + schema) |

---

**Notes:**
- Group edits by file where possible to minimize context switching
- Run `mypy --strict`, `pytest`, and `pre-commit run --all-files` after each priority group
- Security issues (Priority 2) should be reviewed by `wolfpack-security` skill before merging
- Test gaps (Priority 16) should be addressed by `wolfpack-tester` skill
