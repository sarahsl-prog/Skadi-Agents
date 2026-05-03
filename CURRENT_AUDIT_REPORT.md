# WolfPack Codebase Audit Report

**Date:** 2026-05-01  
**Branch:** main  
**Scope:** Full source tree (`src/`, `tests/`, `infra/`, `docs/`, configuration files)  
**Status:** Active audit — all issues are current as of this date  

---

## Summary

This report identifies **~120 issues** across the WolfPack codebase, categorized by severity and module. The most critical findings are:

- **3 critical bugs** in the orchestrator that would prevent async agent nodes and budget enforcement from working correctly
- **3 critical bugs** in NATS context propagation that break distributed tracing entirely
- **2 critical data bugs** that cause duplicate data in learning worker and lossy persistence
- **5 high-severity security issues** including SQL injection, API injection, PII storage in plaintext, and hardcoded auth tokens
- **7 high-severity bugs** in schema/field mismatches that will cause runtime errors
- **~15 documentation vs. implementation discrepancies**

---

## Critical Issues

### CRIT-1: Variable shadowing disables budget enforcement (`budget.py:110`)

**File:** `src/wolfpack/orchestrator/budget.py`, lines 95-118

```python
def check_and_consume(self, case_id, branch_depth, branches: int = 1):
    with self._lock:
        state = self._ensure(case_id)
        branches = state["branch_count"]       # <-- SHADOWS parameter "branches"
        ...
        state["branch_count"] += branches       # adds current count, NOT 1
```

The local assignment `branches = state["branch_count"]` shadows the method parameter `branches: int = 1`. The expression `state["branch_count"] += branches` then adds the *current branch count* to itself rather than the intended increment of 1. Starting from 0, `branches` becomes 0 and `0 += 0` leaves it at 0. **Branch budget enforcement is completely disabled for the `check_and_consume` code path.**

**Fix:** Rename the local variable to `current_count` and use the original `branches` parameter.

---

### CRIT-2: Async nodes are NOT awaited in NATS wrapper (`graph.py:121`)

**File:** `src/wolfpack/orchestrator/graph.py`, line 121

```python
async def _async_wrapped(state: CaseState) -> dict[str, Any]:
    result = node(state)          # NOT awaited — returns coroutine if node is async
    await _publish_safe(subject, result)
    return result  # type: ignore[return-value]
```

If `node` is an async function, `node(state)` returns a coroutine object, not a `dict`. This coroutine is passed to `_publish_safe` and returned to LangGraph, both of which cannot handle it. **Any async agent node wired with NATS will produce runtime errors.**

**Fix:** `result = await node(state)`

---

### CRIT-3: `_async_wrapped` is dead code; `_sync_wrapped` is always returned (`graph.py:136`)

**File:** `src/wolfpack/orchestrator/graph.py`, lines 72-136

`_wrap_with_nats` defines both wrappers but always returns `_sync_wrapped` (line 136). Combined with CRIT-2, this means async agent nodes (alpha, tracker, flanker, closer, review) will be called synchronously when NATS is wired, returning coroutine objects instead of state update dicts.

**Fix:** Use `asyncio.iscoroutinefunction(node)` to detect and return the appropriate wrapper.

---

### CRIT-4: `propagate.get_all()` uses wrong module — will crash at runtime (`nats_propagation.py:23`)

**File:** `src/wolfpack/observability/nats_propagation.py`, line 23

```python
baggage = propagate.get_all()
```

`opentelemetry.propagate` does **not** have a `get_all()` function. That function belongs to `opentelemetry.baggage`. Every call to `inject_nats_headers()` will raise `AttributeError`, **breaking all NATS message publishing that includes baggage propagation.**

**Fix:** Change to `from opentelemetry import baggage` and use `baggage.get_all()`.

---

### CRIT-5: `propagate.set_baggage()` uses wrong module — will crash at runtime (`nats_propagation.py:39`)

**File:** `src/wolfpack/observability/nats_propagation.py`, line 39

```python
propagate.set_baggage(key, value)
```

Same issue as CRIT-4. `opentelemetry.propagate` has no `set_baggage()`. Every NATS message handler that receives `wolfpack.baggage` headers will crash.

**Fix:** Use `baggage.set_baggage(key, value)` from `opentelemetry.baggage`.

---

### CRIT-6: Extracted trace context is discarded — distributed tracing is broken (`nats_propagation.py:33`, `bus.py:131-133`)

**File:** `src/wolfpack/observability/nats_propagation.py`, line 33

```python
_PROPAGATOR.extract(headers)  # return value discarded
```

`TraceContextTextMapPropagator.extract()` returns a new `Context` object. The returned context is discarded — never activated or passed to the handler. **All downstream spans from NATS message handlers start a new trace rather than continuing the distributed trace.**

Combined with `bus.py:131-133` where `extract_nats_headers()` is called but its return value (currently `None`) is unused, the entire distributed tracing across NATS is non-functional.

**Fix:** Return the extracted context from `extract_nats_headers()` and activate it in the handler via `context.attach()`/`context.detach()`.

---

### CRIT-7: Duplicate queries in learning worker produce doubled data (`worker.py:246-295`)

**File:** `src/wolfpack/learning/worker.py`, lines 246-295

The hypotheses query (lines 246-258) and evidence ref query (lines 260-267) are **executed twice** for each branch — an identical copy-paste block appears at lines 268-289. This means every branch in the learning worker will have **doubled hypotheses and evidence refs**, producing incorrect summaries and RAG ingestion.

**Fix:** Remove the duplicate query blocks at lines 268-289.

---

### CRIT-8: `from_pool` creates a broken PersistencePool (`worker.py:60-61`)

**File:** `src/wolfpack/learning/worker.py`, lines 60-61

```python
PersistencePool(dsn="", min_size=0, max_size=0)
```

The `LearningQueueWorker.from_pool()` classmethod creates a `PersistencePool` with an empty DSN and zero pool size. Any call to `self._persistence` (e.g., `persistence.get_case`) will fail because the pool cannot create connections.

**Fix:** Pass the actual DSN and pool configuration, or share the existing `asyncpg.Pool`.

---

## High Severity Issues

### HIGH-1: `CloserOutput.decision` is `str` but `VerdictPacket.decision` is `Literal` — mismatched values

**Files:** `src/wolfpack/agents/closer.py:210`, `src/wolfpack/schemas/verdict.py:26-27`

`CloserOutput.decision` is typed as `str` with description `"benign, suspicious, malicious, inconclusive"`, but `VerdictPacket.decision` is `Literal["MALICIOUS", "BENIGN", "INCONCLUSIVE", "NEEDS_MORE_INFO"]`. The value `"suspicious"` is in `CloserOutput` but not in `VerdictPacket`. The `# type: ignore[arg-type]` suppresses the type error. If the LLM produces `"suspicious"`, `VerdictPacket` construction will raise `ValidationError`.

**Fix:** Align the values. If `"suspicious"` is valid, add it to the `Literal`. Otherwise, remove it from `CloserOutput`'s description. Make `CaseState.verdict_decision` a `Literal` type.

---

### HIGH-2: `CaseState.status` and `BranchState.status` are `str` — no validation

**Files:** `src/wolfpack/schemas/case_state.py:66-68`, `case_state.py:38-39`

Both are plain `str` with valid values documented only in descriptions. Any string is accepted. A typo like `"scebted"` passes validation silently. The project plan specifies `CaseState` lifecycle states (`new -> scented -> shadowing -> decision -> review -> closed`). These should be `Literal` types.

**Fix:** Use `Literal["new", "scented", "shadowing", "decision", "review", "closed"]` for `CaseState.status` and `Literal["open", "closed", "merged", "abandoned"]` for `BranchState.status`.

---

### HIGH-3: `verdict_decision` casing inconsistency across codebase

**Affected files:**
- `src/wolfpack/schemas/case_state.py:102-105` — docstring says lowercase
- `src/wolfpack/schemas/verdict.py:26-27` — Literal uses UPPERCASE
- `src/wolfpack/orchestrator/stubs.py:93` — returns UPPERCASE `"BENIGN"`
- `tests/unit/test_graph.py:70,126` — asserts lowercase `"benign"`
- `src/wolfpack/learning/summary.py:138` — calls `.upper()` on verdict_decision

There is no consistent casing. The stubs produce UPPERCASE, tests assert lowercase, and `summary.py` does `.upper()` as a defensive measure.

**Fix:** Define a `Literal` type for verdict decisions and use it everywhere. Choose one casing (UPPERCASE recommended since `VerdictPacket` uses it).

---

### HIGH-4: `get_case()` and `get_branch()` return materially incomplete objects

**File:** `src/wolfpack/schemas/persistence.py`

- `get_case()` (lines 84-107) returns `CaseState` missing: `branches`, `hypotheses`, `evidence_refs`, `tracker_confidence`, `flanker_confidence`, `re_check_count`, `significant_findings`, `review_decision`, `verdict_decision`, `overall_confidence`, `review_started_at`.
- `get_branch()` (lines 164-190) returns `BranchState` missing: `entities`, `hypotheses`, `evidence_refs`. `updated_at` is always `datetime.now(UTC)` (fabricated).

The API route `cases.py:75` uses `get_case()` and returns an incomplete object.

**Fix:** Implement a `get_full_case()` method that loads branches, hypotheses, and evidence refs. Update the API route to use it.

---

### HIGH-5: PII token truncation to 6 hex chars creates collision risk

**File:** `src/wolfpack/schemas/pii.py:72`

```python
token = f"{identifier_type}_{digest[:6]}"
```

6 hex characters = 24 bits = ~16.7M possible tokens per identifier type. Birthday paradox gives ~50% collision probability at ~4K identifiers. The `ON CONFLICT (case_id, token) DO NOTHING` silently drops the second mapping, causing data loss.

**Fix:** Increase to at least 12 hex characters (48 bits). Change `DO NOTHING` to `DO UPDATE SET original_value = EXCLUDED.original_value` or raise an error.

---

### HIGH-6: Raw PII stored in plaintext in database

**File:** `src/wolfpack/schemas/pii.py:76-88`

The `pseudonymize` function stores `identifier` (the raw PII value) directly in `wolfpack.pii_mappings.original_value` without encryption. Crypto-shredding (destroying the DEK) does not delete the `pii_mappings` rows. A database breach of `pii_mappings` exposes all original PII values.

**Fix:** Encrypt `original_value` with the case DEK before storage. When crypto-shredding occurs, the DEK is destroyed, rendering the PII unreadable.

---

### HIGH-7: Hardcoded default API token usable in production

**File:** `src/wolfpack/api/auth.py:17`

```python
_DEFAULT_TOKEN = os.environ.get("WOLFPACK_API_TOKEN", "dev-token-do-not-use-in-production")
```

If `WOLFPACK_API_TOKEN` is not set, the default token is used. There is no check that warns or aborts in non-dev deployment modes.

**Fix:** Remove the default or raise a warning/error at startup when `deployment_mode != "dev"` and the default is active.

---

### HIGH-8: Hardcoded `analyst_id` defeats break-glass audit trail

**File:** `src/wolfpack/api/routes/breakglass.py:40`

```python
analyst_id = "analyst_session"
```

The break-glass depseudonymization endpoint is supposed to log the analyst identity, but `analyst_id` is hardcoded. This completely defeats the audit trail purpose.

**Fix:** Extract analyst identity from the authenticated session/token.

---

### HIGH-9: SQL injection via filter keys in `PGVectorStore`

**Files:** `src/wolfpack/rag/base.py:126,136,189,247`

The `table_name` is interpolated via f-strings into SQL. The `filters` dictionary keys are also interpolated: `metadata->>'{key}'`. Since RAG tools pass `filters` through from LLM-generated arguments, this is reachable from attacker-controlled input.

**Fix:** Validate `table_name` against an allowlist. Use parameterized queries for filter keys or validate keys against a schema.

---

### HIGH-10: Okta and CrowdStrike filter string injection

**Files:** `src/wolfpack/adapters/okta.py:55,59`, `src/wolfpack/adapters/crowdstrike.py:115,117,123`

Entity values are directly interpolated into Okta/CrowdStrike filter expressions. Since `entity.value` comes from LLM-generated tool arguments, this enables API injection.

**Fix:** URL-encode or escape entity values. Use parameterized filter construction.

---

### HIGH-11: Watchdog timezone mismatch crashes on naive ISO strings

**File:** `src/wolfpack/orchestrator/watchdog.py:76-78`

```python
if isinstance(started_at, str):
    started_at = datetime.fromisoformat(started_at)
if now - started_at > self._timeout:
```

`now` is timezone-aware (`datetime.now(UTC)`), but `datetime.fromisoformat()` on a timezone-naive string produces a naive datetime. Subtracting aware from naive raises `TypeError`.

**Fix:** After parsing, force UTC: `if started_at.tzinfo is None: started_at = started_at.replace(tzinfo=UTC)`.

---

### HIGH-12: `TrackerOutput` schema divergence between agent and schema file

**Files:** `src/wolfpack/agents/tracker.py:32-60` vs `src/wolfpack/schemas/agents/tracker.py`

The agent's local `TrackerOutput` has `confidence` and `reasoning` fields, while the schema `TrackerOutput` has `tracker_confidence` and `updated_entities`. These are **completely different types**. Code importing from `schemas.agents.tracker` gets a different type than the agent produces.

**Fix:** Use a single source of truth. Either remove the local definitions and import from schemas, or update the schema file to match the agent's actual output.

---

### HIGH-13: `CloserDeps.rag` and `CloserDeps.adapters` never wired to agent tools

**File:** `src/wolfpack/agents/closer.py:45-56`

`CloserDeps` has `rag` and `adapters` fields, but these are never used to construct the agent's tool dependencies. Tools that try to access `ctx.deps.adapters` or `ctx.deps.case_id` will fail at runtime.

**Fix:** Wire `CloserDeps.rag` and `CloserDeps.adapters` into the agent's tool dependency context.

---

### HIGH-14: ThreatIntelPipeline alpha values are inverted

**File:** `src/wolfpack/rag/threat_intel.py:82`

```python
alpha = 0.3 if modality == "keyword" else 0.7
```

The docstring says "keyword-dominant (alpha=0.3)" but this makes keyword weight 0.3 and semantic weight 0.7 — semantic-dominant. Compare with `case_history.py` where semantic gets 0.7.

**Fix:** Change to `alpha = 0.7 if modality == "keyword" else 0.3` for keyword-dominant.

---

### HIGH-15: Alert deduplication is broken — timestamp in dedup key

**File:** `src/wolfpack/observability/alert_manager.py:94-96`

```python
canonical = json.dumps(alert, sort_keys=True)
...
hashlib.sha256(canonical.encode()).hexdigest()[:16]
```

Every alert payload includes a `timestamp` field (from `alerts.py`). Since timestamps are unique per alert, two identical alerts will have different dedup keys, making deduplication non-functional.

**Fix:** Exclude `timestamp` (and any other non-identity fields) from the canonical hash.

---

### HIGH-16: `traced_node` captures tracer at decoration time, not call time

**File:** `src/wolfpack/observability/tracing.py:86`

```python
_tracer = trace.get_tracer(TRACER_NAME)  # captured once at decoration time
```

If `traced_node` is applied to a function before `bootstrap_tracing()` sets up the global TracerProvider, the tracer will be a no-op tracer permanently. All subsequent calls will use the no-op tracer even after bootstrapping.

**Fix:** Move `trace.get_tracer(TRACER_NAME)` inside the wrapper functions so it's called at runtime.

---

### HIGH-17: `request_timeout_s` from config never passed to providers

**File:** `src/wolfpack/llm/providers.py:11-30`

`LLMConfig.request_timeout_s` is validated to be positive but never passed to `OllamaProvider` or `OpenAICompatibleProvider`. The default `httpx.Client` timeout (5s) is used instead of the user's configured 60s.

**Fix:** Pass `cfg.request_timeout_s` to the provider constructors and then to the `httpx.Client(timeout=...)`.

---

## Medium Severity Issues

### MED-1: Silent failure when pool is None in Alpha dispatcher

**File:** `src/wolfpack/agents/alpha.py:70-73`

If `ctx.deps.pool is None`, `create_case` silently skips persistence and still returns `state.case_id`. Downstream agents assume the case was created.

**Fix:** Raise an error or return an error indicator when the pool is unavailable.

---

### MED-2: `getattr(output, "reasoning_summary", "")` on non-existent field

**File:** `src/wolfpack/agents/closer.py:214`

`CloserOutput` does not have a `reasoning_summary` field. The `getattr` call always returns `""`, silently discarding any reasoning content.

**Fix:** Add `reasoning_summary` to `CloserOutput` or remove the dead code.

---

### MED-3: Flanker hypothesis filtering loop is a no-op

**File:** `src/wolfpack/agents/flanker.py:211-215`

```python
if state.hypotheses:
    for hyp in state.hypotheses:
        if hyp.branch_id:
            pass
```

The loop iterates over hypotheses but the branch-level filter is a `pass` statement. Branch-level hypotheses are never excluded from the Flanker input.

**Fix:** Collect case-level hypotheses and pass them to `FlankerInput`.

---

### MED-4: `re_check_count` has no upper bound — no circuit-breaker

**File:** `src/wolfpack/agents/flanker.py:279`

```python
"re_check_count": state.re_check_count + 1,
```

A Tracker-Flanker loop could increment this indefinitely.

**Fix:** Add a `max_re_checks` config field and enforce it in the graph router.

---

### MED-5: `asyncio.run()` in `dispatch_sync` will fail in existing event loop

**File:** `src/wolfpack/agents/alpha.py:96`

`asyncio.run()` creates a new event loop. If called from within an already-running event loop (Jupyter, another async context), it raises `RuntimeError`.

**Fix:** Use `asyncio.get_event_loop().run_until_complete()` or check for existing loop.

---

### MED-6: NATS bus sync callback wrapper doesn't await async handlers

**File:** `src/wolfpack/orchestrator/bus.py:131-133`

```python
def _wrapped_handler(msg: Msg) -> Any:
    extract_nats_headers(dict(msg.headers) if msg.headers else None)
    return handler(msg)
```

If `handler` is async, `handler(msg)` returns a coroutine that is never awaited.

**Fix:** Make `_wrapped_handler` async and await the handler.

---

### MED-7: Watchdog escalation failure aborts entire sweep

**File:** `src/wolfpack/orchestrator/watchdog.py:85`

If `_escalate(case_id)` raises for one case, the loop breaks and remaining cases are not processed.

**Fix:** Wrap each escalation in try/except with logging.

---

### MED-8: NATS `BadRequestError` silently swallowed

**File:** `src/wolfpack/orchestrator/bus.py:63-67`

```python
except nats.js.errors.BadRequestError:
    pass  # Stream likely already exists; idempotent.
```

This catches all `BadRequestError` including invalid stream configurations, masking real problems.

**Fix:** Catch `StreamAlreadyExistsError` specifically or inspect the error message.

---

### MED-9: User headers can overwrite OTel trace context in NATS

**File:** `src/wolfpack/orchestrator/bus.py:97-99`

```python
merged_headers = inject_nats_headers()
if headers:
    merged_headers.update(headers)  # user headers can overwrite traceparent/tracestate
```

**Fix:** Protect OTel headers: `for k, v in headers.items(): if k not in otel_headers: otel_headers[k] = v`.

---

### MED-10: Branch budget leak on persistence failure

**File:** `src/wolfpack/orchestrator/branches.py:54-55,81`

Budget is consumed before `create_branch` is called. If `create_branch` raises, the budget slot is permanently leaked.

**Fix:** Wrap persistence in try/except and roll back the consumed budget.

---

### MED-11: `threading.Lock` blocks event loop in async context

**File:** `src/wolfpack/orchestrator/budget.py:35`

`BranchBudget` uses `threading.Lock()`. The async `create_branch` calls `budget.check_and_consume()` which acquires this lock. If contended, it blocks the event loop.

**Fix:** Replace with `asyncio.Lock`.

---

### MED-12: BranchBudget `check()` and `remaining()` read without lock

**File:** `src/wolfpack/orchestrator/budget.py:44-64,66-78`

Both methods read `self._state` without acquiring `self._lock`, while `consume` and `check_and_consume` write under the lock.

**Fix:** Acquire `self._lock` in both `check()` and `remaining()`.

---

### MED-13: Stub returns UPPERCASE `"BENIGN"` but test asserts lowercase `"benign"`

**File:** `src/wolfpack/orchestrator/stubs.py:93` vs `tests/unit/test_graph.py:70,126`

The stub function returns `"BENIGN"` (uppercase) but the test asserts `== "benign"` (lowercase). The test would fail if comparison were case-sensitive.

**Fix:** Standardize casing (see HIGH-3).

---

### MED-14: `alpha` node publishes to `hunt.task.tracker` instead of `hunt.task.alpha`

**File:** `src/wolfpack/orchestrator/graph.py:204`

```python
alpha = _wrap_with_nats(alpha, "hunt.task.tracker", nats_client)
```

Alpha dispatcher publishes to the tracker's subject, which is semantically incorrect and will confuse NATS subscribers.

**Fix:** Change to `"hunt.task.alpha"` or `"hunt.task.dispatcher"`.

---

### MED-15: `scribe` not validated as non-None in graph construction

**File:** `src/wolfpack/orchestrator/graph.py:192-193`

The validation checks `alpha`, `tracker`, `flanker`, `closer`, and `review` for None, but not `scribe`. If `scribe=None` and `use_stubs=False`, LangGraph will crash when trying to call a None function.

**Fix:** Add `scribe is None` to the validation check.

---

### MED-16: `depseudonymize` writes audit before verifying token exists

**File:** `src/wolfpack/schemas/pii.py:117-145`

The audit row is written before checking whether the token exists in `pii_mappings`. Unknown tokens create phantom audit entries.

**Fix:** Check token existence first, write audit only for valid tokens, or differentiate audit entries for valid vs. unknown tokens.

---

### MED-17: Race condition in PII salt creation (TOCTOU)

**File:** `src/wolfpack/schemas/pii.py:63-65`

Two concurrent calls to `create_pii_salt` for the same `case_id` can generate different local salts. `ON CONFLICT DO NOTHING` means the second call's salt is silently discarded, but the function returns its own locally-generated salt. The token produced with the wrong salt won't match the stored salt.

**Fix:** After `create_pii_salt`, re-fetch with `get_pii_salt` to use the actually-persisted salt.

---

### MED-18: `Hypothesis.status` is unvalidated `str`

**File:** `src/wolfpack/schemas/hypothesis.py:26-29`

Should be `Literal["open", "confirmed", "rejected", "superseded"]`.

---

### MED-19: PII pipeline `token-to-identifier_type` heuristic strips entity subtype

**File:** `src/wolfpack/processing/pii_pipeline.py:121`

```python
id_type = token.strip("<>").split("_")[0].lower()
```

NER tokens like `<IP_ADDRESS_1>` produce `id_type="ip"` instead of `"ip_address"`. This creates a mismatch between NER entity types and pseudonymized token types.

**Fix:** Use `token.strip("<>").rsplit("_", 1)[0].lower()` to get the full entity type.

---

### MED-20: PII not detected by NER passes through un-pseudonymized

**File:** `src/wolfpack/processing/pii_pipeline.py:112-127`

The pipeline only pseudonymizes values that NER detects. Undetected PII remains in plaintext in the output.

**Fix:** Apply deterministic pseudonymization for known identifier types (IPs, emails) even without NER detection, or add a second-pass regex for common patterns.

---

### MED-21: Learning worker quality gate permanently blocks low-confidence cases

**File:** `src/wolfpack/learning/worker.py:137-142`

```python
if verdict.confidence < Confidence.PLAUSIBLE:
    raise RuntimeError(...)
```

Since confidence won't change between retries, this permanently fails after `retry_limit` attempts. No "ingestion_failed" status is set.

**Fix:** Handle low-confidence cases with a warning rather than error, or set a permanent failure status.

---

### MED-22: Learning worker `_get_full_case_state` doesn't populate case-level `evidence_refs`

**File:** `src/wolfpack/learning/worker.py:186-298`

Case-level `evidence_refs` remain empty even though branch-level ones are populated. `format_case_summary` uses `case_state.evidence_refs` which will always be empty.

**Fix:** Aggregate evidence from all branches into `case_state.evidence_refs`.

---

### MED-23: Score fusion uses `max()` instead of additive combination

**Files:** `src/wolfpack/rag/case_history.py:98-105`, `src/wolfpack/rag/threat_intel.py:80-87`

When a document appears in both semantic and keyword results, the fusion takes `max(existing_score, new_score * alpha)` instead of adding them. This is order-dependent and can give documents that appear in only one modality a higher score than documents in both.

**Fix:** Use additive combination: `fused_scores[doc_id] = existing + score * alpha`.

---

### MED-24: CrowdStrike adapter uses fake timestamp and only fetches detection IDs

**Files:** `src/wolfpack/adapters/crowdstrike.py:64-65,50-71`

- `timestamp=time_window.start` is used instead of actual detection timestamps
- Only detection IDs are fetched, not full detection details

**Fix:** Call `/detects/entities/detects/v1` to get full details. Use the detection's actual timestamp.

---

### MED-25: CrowdStrike API token never refreshed after expiry

**File:** `src/wolfpack/adapters/crowdstrike.py:84-101`

`_ensure_token` only fetches a token if `self._token is None`. After expiry (30 minutes default), all API calls fail with 401.

**Fix:** Track token expiry time and refresh when expired.

---

### MED-26: Okta filter concatenation produces invalid filter for user queries

**File:** `src/wolfpack/adapters/okta.py:57-59`

When entity.type is "user", `params["q"]` is used. But if `event_type` is also specified, `params["filter"]` produces `" and eventType eq 'Y'"` with a leading ` and `. Okta does not support `q` and `filter` together.

**Fix:** Reconstruct the filter for user queries; don't combine `q` and `filter`.

---

### MED-27: Okta pagination has no limit — potential infinite loop

**File:** `src/wolfpack/adapters/okta.py:64-103`

The `while url:` pagination loop has no maximum iteration or event count guard.

**Fix:** Add a `max_pages` or `max_events` limit.

---

### MED-28: CORS `allow_origins=["*"]` with `allow_credentials=True`

**File:** `src/wolfpack/api/app.py:28-34`

According to the CORS spec, `allow_credentials=True` with `allow_origins=["*"]` causes the browser to refuse credentialed requests. FastAPI/Starlette will reflect the `Origin` header, effectively allowing any origin.

**Fix:** Set `allow_origins` to a specific allowlist, or remove `allow_credentials=True`.

---

### MED-29: Non-constant-time token comparison in API auth

**File:** `src/wolfpack/api/auth.py:23`

```python
token != expected
```

String comparison with `!=` is timing-vulnerable. An attacker can determine the correct token character by character.

**Fix:** Use `hmac.compare_digest(token, expected)`.

---

### MED-30: No status precondition check before review state transitions

**File:** `src/wolfpack/api/routes/review.py:83-140`

The `approve_case`, `escalate_case`, `close_benign`, and `continue_hunt` endpoints unconditionally update case status. A case in `"new"` or `"scented"` status could be "approved".

**Fix:** Add a `WHERE status = 'review'` clause to the UPDATE, or validate status first.

---

### MED-31: Non-atomic ledger insert + status update

**File:** `src/wolfpack/api/routes/review.py:54-80`

Two SQL operations (INSERT + UPDATE) without a transaction. If the UPDATE fails, an orphaned ledger entry remains.

**Fix:** Wrap both operations in a transaction.

---

### MED-32: No idempotency protection on review actions

**File:** `src/wolfpack/api/routes/review.py:83-140`

POST endpoints for approve/escalate/close/continue can be called multiple times, creating duplicate ledger entries.

**Fix:** Add idempotency keys or conditional UPDATEs.

---

### MED-33: `limit` and `offset` query params not validated

**File:** `src/wolfpack/api/routes/cases.py:33-34`

A client can pass `limit=-1` (PostgreSQL "no limit") or huge values.

**Fix:** Use `Query(50, ge=1, le=500)` and `Query(0, ge=0)`.

---

### MED-34: WebSocket claimed heartbeat not implemented

**File:** `src/wolfpack/api/routes/ws.py:44-53`

The docstring says "For V1 we send a heartbeat every 30s" but the implementation only echoes received messages.

**Fix:** Implement an actual heartbeat with `asyncio.sleep(30)` in a background task, or update the docstring.

---

### MED-35: WebSocket auth has no timeout

**File:** `src/wolfpack/api/routes/ws.py:29-36`

A client can hold the connection open indefinitely without authenticating, consuming server resources.

**Fix:** Add `asyncio.wait_for(websocket.receive_text(), timeout=5.0)`.

---

### MED-36: Global mutable pool singleton per route module

**Files:** `src/wolfpack/api/routes/cases.py:15-26`, `review.py`, `breakglass.py`

Each route module has its own `_pool: PersistencePool | None = None`, creating multiple connection pools to the same database.

**Fix:** Use FastAPI dependency injection to share a single pool instance.

---

### MED-37: AES-GCM without AAD in crypto-shredding

**File:** `src/wolfpack/crypto/software_kms.py:42,68`

```python
aesgcm.encrypt(nonce, dek, None)  # no AAD
```

AES-GCM without Additional Authenticated Data means the ciphertext is not bound to the context (case ID, KEK ID). An attacker with DB access could swap wrapped DEKs between cases.

**Fix:** Include `kek_id` and `case_id` as AAD: `aesgcm.encrypt(nonce, dek, f"{kek_id}:{case_id}".encode())`.

---

### MED-38: KEK rotation doesn't re-wrap existing DEKs

**File:** `src/wolfpack/crypto/software_kms.py:71-77`

`rotate_kek` generates a new KEK but does not re-encrypt existing DEKs. If the old KEK is compromised, all DEKs wrapped with it can be decrypted.

**Fix:** Re-wrap all DEKs associated with the old KEK. Document this limitation.

---

### MED-39: `get_wrapped_dek` may return wrong row for multiple active DEKs

**File:** `src/wolfpack/crypto/dek.py:37-56`

`WHERE case_id = $1 AND shredded_at IS NULL` can return multiple rows. `fetchrow` returns only one, undefined which.

**Fix:** Add `ORDER BY created_at DESC LIMIT 1`.

---

### MED-40: Alert severity mismatch between spec and payload

**File:** `src/wolfpack/observability/alerts.py:142-168`

`ReviewTimeoutEscalationAlert` SPEC defines severity as `"info"` but the alert payload uses `"warning"`.

**Fix:** Align spec and payload.

---

### MED-41: `LedgerHashMismatchAlert` omitted from `get_builtin_alerts()`

**File:** `src/wolfpack/observability/alerts.py:204-217`

The hash-chain integrity alert is critical for security but not included in the default alert list.

**Fix:** Add `LedgerHashMismatchAlert` to `get_builtin_alerts()`.

---

### MED-42: `_instrument_tools` is effectively dead code

**File:** `src/wolfpack/observability/agents.py:152-181`

`pydantic_ai.Agent` does not have an `on_tool_call` attribute. The `hasattr(agent, "on_tool_call")` check at line 180 will always be False for current Pydantic AI agents, making tool instrumentation a no-op.

**Fix:** Remove the dead code or find the correct Pydantic AI hook for tool instrumentation.

---

### MED-43: AlertManager webhook timeout hardcoded instead of using config

**File:** `src/wolfpack/observability/alert_manager.py:122`

Hardcoded `timeout=30.0` instead of using `settings.webhook_config.timeout_s`.

**Fix:** Read timeout from config.

---

### MED-44: AlertManager creates new httpx.AsyncClient per dispatch

**File:** `src/wolfpack/observability/alert_manager.py:116-123`

Creates and destroys a connection pool for every alert. For high-frequency alerting, this wastes resources.

**Fix:** Create the client once in `__init__` or `start()`.

---

### MED-45: `AlertManager._webhook_url` condition always truthy

**File:** `src/wolfpack/observability/alert_manager.py:47`

`settings.webhook_config` is always a `WebhookConfig` instance (never falsy). The `else None` branch is unreachable.

**Fix:** Check `settings.webhook_config.url` instead of `settings.webhook_config`.

---

### MED-46: `configure_logfire()` has no guard against pre-bootstrap call

**File:** `src/wolfpack/observability/logfire.py:13-22`

No warning or error if called before `bootstrap_tracing()`.

**Fix:** Add a check that the global TracerProvider has been set.

---

### MED-47: `_extract_token_count()` swallows all exceptions silently

**File:** `src/wolfpack/observability/agents.py:143-149`

Returns `None` on any exception, making it impossible to debug extraction failures.

**Fix:** Log a warning before returning `None`.

---

### MED-48: Prompt injection defense is bypassable

**File:** `src/wolfpack/rag/tools.py:50-65`

The `_instruction_repetition_defense` regex is trivially evadable. Unicode homoglyphs, paraphrases, and `"summarize all previous messages"` are not caught. Metadata is not sanitized (line 85-87).

**Fix:** Use a multi-layer defense: strict input/output validation, explicit delimiters, and consider a more robust regex set.

---

### MED-49: XML bomb / XXE vulnerability in Windows EventLog adapter

**File:** `src/wolfpack/adapters/windows_eventlog.py:84,103`

`ET.fromstring(xml)` is used on potentially untrusted XML. Python's `ElementTree` is vulnerable to billion-laughs attacks.

**Fix:** Use `defusedxml.ElementTree` instead.

---

### MED-50: All file-based adapters block the event loop

**Files:** All adapters in `src/wolfpack/adapters/`

`path.read_text()` is called synchronously inside `async def query()`. For large log files, this blocks the event loop.

**Fix:** Use `asyncio.to_thread(path.read_text, ...)` or `aiofiles`.

---

### MED-51: No validation on `top_k` in RAG tools

**Files:** `src/wolfpack/rag/tools.py:103-142`

An LLM can pass `top_k=1000000` causing excessive DB load.

**Fix:** Add bounds: `top_k: int = Query(10, ge=1, le=200)`.

---

### MED-52: `telemetry_tool_factory` doesn't validate `entity_type` against `Entity` Literal

**File:** `src/wolfpack/adapters/tools.py:40-48`

The tool accepts any `entity_type` string, but `Entity` restricts `type` to `Literal["host", "user", "ip", "domain", "hash", "url"]`.

**Fix:** Validate `entity_type` against the Literal or use a constrained type in the tool description.

---

### MED-53: `Confidence.calibrate()` docstring contradicts implementation

**File:** `src/wolfpack/schemas/confidence.py:46`

The docstring says "A possibly upgraded (never downgraded) confidence" but the `else` branch gives `corr_boost = -1`, which can downgrade confidence below the original level.

**Fix:** Fix the docstring, or change the logic to never downgrade.

---

### MED-54: Syslog regex doesn't handle RFC 5424

**File:** `src/wolfpack/adapters/syslog.py:22-27`

The docstring says "Supports RFC 3164 and RFC 5424" but the regex only matches RFC 3164 format.

**Fix:** Add RFC 5424 regex pattern, or update the docstring.

---

### MED-55: PII pipeline `import` inside loop

**File:** `src/wolfpack/processing/pii_pipeline.py:48`

`from wolfpack.schemas.entity import Entity` is imported inside a for loop. Move to module level.

---

### MED-56: Learning summary uses hardcoded pseudonymization salt

**File:** `src/wolfpack/learning/summary.py:33-35`

```python
salt = "wolfpack-learning"
```

A hardcoded salt in source code. An attacker who knows the salt can brute-force identifiers, especially low-entropy ones like IPs.

**Fix:** Use the per-case PII salt from `wolfpack.pii_salts`.

---

### MED-57: SHA-256 truncated to 12 hex chars in learning summary

**File:** `src/wolfpack/learning/summary.py:34`

```python
hashlib.sha256(...).hexdigest()[:12]
```

48 bits of entropy. Birthday paradox gives ~2^24 work for collision.

**Fix:** Use at least 16 hex characters (64 bits).

---

### MED-58: `GoldenSet.name` can raise `KeyError`

**File:** `src/wolfpack/eval/harness.py:29`

Uses `self.data["name"]` unlike `ReplaySet.name` which uses `.get("name", self.path.stem)`.

**Fix:** Use `.get("name", self.path.stem)`.

---

### MED-59: Eval hypothesis matching is overly lenient

**File:** `src/wolfpack/eval/harness.py:79-87`

Uses substring containment (`desc in actual_desc or actual_desc in desc`). "password" matches "password spray" and vice versa.

**Fix:** Use token overlap (Jaccard similarity) or embedding-based similarity with a threshold.

---

### MED-60: `PersistencePool.acquire()` has no retry logic

**File:** `src/wolfpack/schemas/persistence.py:43-48`

If the first `connect()` fails, there's no retry. The second `if self._pool is None` check is marked `# pragma: no cover`.

**Fix:** Add retry with backoff for transient connection failures.

---

### MED-61: `insert_ledger_entry` doesn't validate `content` against `EvidenceRef`

**File:** `src/wolfpack/schemas/ledger.py:63-94`

Arbitrary `dict[str, Any]` can be stored, but `replay_ledger` tries `EvidenceRef.model_validate(content)`. Invalid content causes `ValidationError` on read.

**Fix:** Validate `content` against `EvidenceRef` before insertion.

---

### MED-62: `json.dumps()` on `model_dump()` may fail on datetime objects

**Files:** `src/wolfpack/schemas/persistence.py:75,155`

`json.dumps(case.seed.model_dump())` and `json.dumps(branch.spec.model_dump())` can fail if `Seed.metadata` contains datetime objects, since `json.dumps` doesn't handle `datetime` by default.

**Fix:** Use asyncpg's native JSONB serialization, or add a custom JSON encoder.

---

### MED-63: Case-level `evidence_refs` never populated in `get_case()`

See HIGH-4. The persistence layer returns empty `evidence_refs` at the case level.

---

### MED-64: `BranchState.updated_at` always fabricated (no DB column)

The `branches` table has no `updated_at` column, so `BranchState.updated_at` is always `datetime.now(UTC)`.

**Fix:** Add an `updated_at` column to the `branches` table, or remove the field from the model.

---

### MED-65: `Confidence._missing_` has re-entrant call pattern

**File:** `src/wolfpack/schemas/confidence.py:26-29`

`_missing_` calls `cls(value)` which triggers `_missing_` again if the value is out of range. Python's `IntEnum` handles this correctly (returns `None` which raises `ValueError`), but the re-entrant pattern is a design smell.

---

### MED-66: `branch_id` fallback references non-existent branch

**File:** `src/wolfpack/agents/flanker.py:233`

```python
branch_id=state.branches[0].branch_id if state.branches else state.case_id,
```

When there are no branches, the fallback uses `state.case_id` as a branch_id that doesn't actually exist as a branch.

---

## Low Severity Issues

| ID | File | Issue |
|---|---|---|
| LOW-1 | `agents/scribe.py:16` | `SCRIBE_TOOL_ALLOWLIST` defined but never used |
| LOW-2 | `schemas/agents/alpha.py:9-16` | `AlphaInput` never used |
| LOW-3 | `schemas/evidence.py:27` | `EvidenceRef.hash` shadows Python built-in `hash()` |
| LOW-4 | `schemas/entity.py:8-22` | `Entity` has no `id` field for dedup/cross-reference |
| LOW-5 | `schemas/seed.py:8-25` | `Seed` has no `id` field |
| LOW-6 | `agents/closer.py:99`, `agents/flanker.py:158` | Hardcoded `https://example.okta.com` placeholder |
| LOW-7 | `agents/scribe.py:49-67` | `write_timeline_event` silently drops `agent_run_id` |
| LOW-8 | `agents/policy.py:30,67-73` | `register()` doesn't validate `"check"` is callable |
| LOW-9 | `agents/flanker.py:33-44` | `FlankerDeps.rag` and `FlankerDeps.adapters` stored but unwired |
| LOW-10 | `agents/tracker.py:68-79` | `TrackerDeps` never used to configure agent tools |
| LOW-11 | `agents/closer.py:84-110` | `_build_tools` creates fresh adapter instances on every call |
| LOW-12 | `agents/flanker.py:131-134` | Feature flag reassignment shadows parameter |
| LOW-13 | `schemas/branch.py:20-21` | `BranchSpec.hypothesis` vs `BranchState.hypotheses` naming collision |
| LOW-14 | `schemas/case_state.py:50-52` | `updated_at` never auto-updated on Pydantic model mutation |
| LOW-15 | `orchestrator/bus.py:92-95` | `json.dumps()` fails on non-serializable types |
| LOW-16 | `orchestrator/bus.py:143-148` | Missing `drain()` before `close()` |
| LOW-17 | `orchestrator/budget.py:84` | `consume()` default `branches=0` is a footgun |
| LOW-18 | `orchestrator/dedup.py:61-63` | Merged hypothesis inherits old `status` and `branch_id` |
| LOW-19 | `orchestrator/graph.py:34-35` | `None` confidence routes to closer (should route to flanker?) |
| LOW-20 | `orchestrator/graph.py:124-136` | Fire-and-forget NATS publish may lose messages |
| LOW-21 | `orchestrator/watchdog.py:78` | `>` instead of `>=` for timeout boundary |
| LOW-22 | `adapters/windows_eventlog.py:177-185` | Level 2 mapped to "critical" (should be "high"); level 5 missing |
| LOW-23 | `adapters/okta.py:63,111`, `adapters/crowdstrike.py:49,89` | `httpx.AsyncClient` created per request |
| LOW-24 | `adapters/crowdstrike.py:123` | FQL filter starts with `+` when filter is empty |
| LOW-25 | `adapters/okta.py:52-59` | `q` + `filter` incompatibility |
| LOW-26 | `adapters/proxy.py:109` | Entity matched against HTTP status code |
| LOW-27 | `adapters/dns.py:174` | Can create Entity with empty `value` |
| LOW-28 | `adapters/windows_eventlog.py:41-45` | All exceptions silently swallowed |
| LOW-29 | `rag/base.py:76` | `OllamaEmbedder` creates `httpx.AsyncClient` per call |
| LOW-30 | `rag/base.py:121-140` | `ensure_schema()` doesn't `CREATE EXTENSION vector` |
| LOW-31 | `adapters/syslog.py:64-68`, `adapters/firewall.py:88-95` | Year-boundary issue in timestamp parsing |
| LOW-32 | `schemas/evidence.py:23-25` | `EvidenceRef.timestamp` non-deterministic default |
| LOW-33 | `rag/base.py:142-145` | `_format_vector` doesn't validate vector length |
| LOW-34 | `api/routes/ws.py:14` | Imports private `_DEFAULT_TOKEN` |
| LOW-35 | `observability/agents.py:143-149` | `_extract_token_count()` swallows all exceptions |
| LOW-36 | `observability/agents.py:77-119` | `traced_agent_run_sync` blocks event loop from async |
| LOW-37 | `crypto/software_kms.py:87` | KEK ID leaks first 8 bytes of key |
| LOW-38 | `crypto/dek.py:10-12` | `async def generate_dek()` has no await |
| LOW-39 | `observability/tracing.py:23` | `_bootstrapped` flag not thread-safe |
| LOW-40 | All file adapters | No path traversal validation on `log_path`/`evtx_path` |
| LOW-41 | `adapters/okta.py:27`, `adapters/crowdstrike.py:24` | No SSRF validation on `base_url` |
| LOW-42 | `rag/case_history.py:42-43`, `rag/threat_intel.py:41-42` | `RAGPipeline` doesn't include `ensure_schema()` |
| LOW-43 | `adapters/tools.py:25` | `AdapterDeps.pii_pipeline` typed as `Any \| None` |
| LOW-44 | `config/settings.py:59,63,69` | No URL validation on NATS, OTel, MLflow config |
| LOW-45 | `config/settings.py:85,88-95,72-78` | No positive-value validation on Webhook/Learning/BranchBudget fields |
| LOW-46 | `config/deployment.py:30` | `is_loopback_or_private()` accepts link-local/carrier-grade NAT |
| LOW-47 | `observability/tracing.py:23` | `_bootstrapped` cannot be reset for re-bootstrap |
| LOW-48 | `observability/tracing.py:66-69` | `traced_node` decorator fragile without parentheses |
| LOW-49 | `observability/alert_manager.py:83-92` | No circuit breaker or backoff in error loop |
| LOW-50 | `llm/factory.py:23` | Both providers produce `OpenAIChatModel` — fragile coupling |
| LOW-51 | `llm/providers.py:11-20` | `hosted` flag ignored in provider construction |
| LOW-52 | `config/settings.py:88-95` | `LearningConfig` fields lack validation |

---

## Documentation vs. Implementation Discrepancies

| # | Doc Location | Doc Claim | Actual Implementation | Severity |
|---|---|---|---|---|
| D-1 | `docs/runbook/architecture.md:76-79` | NATS subjects are `wolfpack.cases.<case_id>.tasks` | Code uses `hunt.task.*`, `hunt.finding.*`, `hunt.status.*`, `hunt.branch.*` | Medium |
| D-2 | `docs/runbook/architecture.md:57-64` | `cases` table has `seed_type` column | Seed stored as JSONB `seed` column; no `seed_type` column | Medium |
| D-3 | `docs/runbook/architecture.md:61` | `pii_store` table with cols `field_name`, `salt_hash`, `pseudonym` | Actual tables are `pii_salts` and `pii_mappings` with different columns | Medium |
| D-4 | `docs/runbook/architecture.md:59` | `evidence_ledger` has cols `payload_json`, `entry_hash` | Actual columns are `content`, `content_hash` | Medium |
| D-5 | `docs/runbook/architecture.md:65` | `learning_queue` described without `retry_count`/`last_error` | These columns exist and are used by worker | Low |
| D-6 | `docs/security/threat_model.md:154` | `wolfpack.verify_chain()` path | Actual path is `wolfpack.schemas.ledger.verify_chain()` | Medium |
| D-7 | `docs/security/threat_model.md:148-153` | "No formal timeout test exists" | `tests/integration/test_review_timeout.py` exists | Medium |
| D-8 | `docs/runbook/configuration.md:68-73` | Implies Learning config not settable via env vars | `LEARNING__*` env vars work via pydantic-settings | Low |
| D-9 | `.env.example` | Missing `LEARNING__*`, `BRANCH_BUDGET__*`, `OTEL__SERVICE_NAMESPACE` | These are valid config fields | Low |
| D-10 | `docker-compose.yml:83` | MLflow connects to `postgres:5432/mlflow` | The `mlflow` database not created by init script | Medium |

---

## Test Gaps

### Modules with No Dedicated Test File

| Module | Notes |
|---|---|
| `observability/logfire.py` | Only trivial call in `test_observability.py` |
| `observability/alerts.py` | Individual alert classes not unit-tested |
| `crypto/kms.py` | KMS protocol class has no tests |
| `api/auth.py` | No unit test for auth middleware |
| `api/routes/ws.py` | Zero test coverage |
| `api/routes/cases.py`, `review.py`, `breakglass.py` | Only mocked integration tests |
| `processing/breakglass.py` | No unit test |
| `learning/worker.py` | No unit test for error handling |
| `observability/nats_propagation.py` | No integration test against real NATS |
| `adapters/windows_eventlog.py` | Complex XML parsing, zero test coverage |
| `adapters/okta.py`, `crowdstrike.py` | No unit tests (require API mocking) |
| `config/validators.py` | No tests (file is a placeholder) |

### Tests Asserting Incorrect Behavior

| File | Line | Issue |
|---|---|---|
| `test_closer.py` | 44 | `Confidence.PLUSIBLE` — should be `Confidence.PLAUSIBLE` |
| `test_closer.py` | 62 | `tool.__name__` comparison is fragile |
| `test_prompt_injection_rag.py` | 20-42 | Tests a local helper, NOT the production `_sanitize()` function |

### Missing Edge Case Coverage

| Area | Missing Test |
|---|---|
| Confidence calibration | `calibrate()` with 0 evidence, max values, negative corroboration |
| PII pipeline | Non-ASCII text, None pool, empty events |
| NATS propagation | Empty/None baggage values |
| Watchdog | Timezone-naive ISO strings, empty case dicts |
| Graph routing | Both confidences None, re_check_count at maximum |
| API | Error cases (DB failure, malformed input), negative limit/offset |
| Learning worker | Invalid config, zero batch size |
| AlertManager | Empty monitors list, circuit breaker behavior |

### Integration Test Schema Inconsistencies

| Test File | Issue |
|---|---|
| `test_breakglass_audit.py` | Missing `verdict_decision`, `overall_confidence`, `seq` columns |
| `test_crypto_shredding.py` | Same as above plus simplified hash trigger |
| `test_learning_worker.py` | Missing `seq` on `evidence_ledger` |

---

## Previous Audit Status

The previous audit report (`CODEBASE_AUDIT_REPORT.md`) listed 11 issues, all marked as "Resolved." However, several have incomplete implementations or new regressions:

| Previous Issue | Current Status |
|---|---|
| IPv6 loopback | Verified resolved |
| Docker Compose comments | Verified resolved |
| Duplicate dev deps | ✅ REMOVED — Poetry configuration stripped; consolidated to PEP 621 + `[dependency-groups].dev` |
| `request_timeout_s` validation | Verified resolved |
| Pool size cross-validation | Verified resolved |
| `validators.py` comment | Verified resolved |
| URL scheme validation | Only `LLMConfig.base_url` validated; NATS/OTel/MLflow/Webhook still unvalidated |
| Stale minimal profile refs | Verified resolved |
| OTel Collector tag pinned | Verified resolved |
| NATS auth documented | Verified resolved |
| Test gaps | New gaps identified (see above) |

---

## Prioritized Remediation Plan

### Must Fix (Blocks production readiness)

1. **CRIT-1 through CRIT-8** — Critical runtime bugs that break core functionality
2. **HIGH-1 through HIGH-3** — Schema inconsistencies that cause validation errors
3. **HIGH-7, HIGH-8** — Security: hardcoded auth tokens defeat audit
4. **HIGH-9, HIGH-10** — Security: SQL/API injection vectors reachable from LLM
5. **HIGH-5, HIGH-6** — Security: PII collision risk and plaintext storage
6. **HIGH-11** — Watchdog crash on timezone mismatch
7. **HIGH-12** — Schema divergence will cause runtime errors
8. **HIGH-14** — Inverted alpha weights produce wrong RAG results
9. **HIGH-15** — Alert deduplication is non-functional
10. **HIGH-16** — Tracing instrumentation broken for decorated nodes
11. **HIGH-17** — Configured timeout silently ignored

### Should Fix (Before V1 deployment)

1. **HIGH-4** — Lossy persistence
2. **HIGH-13** — CloserDeps not wired to tools
3. **MED-1 through MED-66** — All medium-severity items
4. **D-1 through D-10** — Documentation discrepancies
5. Test gaps for untested modules
6. Integration test schema inconsistencies

### Nice to Have (Ongoing improvement)

1. **LOW-1 through LOW-52** — All low-severity items
2. Edge case test coverage
3. Performance optimizations (connection pooling, async file I/O)

---

*Report generated by comprehensive codebase analysis on 2026-05-01.*