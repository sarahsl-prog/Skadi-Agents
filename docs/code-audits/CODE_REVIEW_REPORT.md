# CODE REVIEW REPORT — Skadi-Agents / WolfPack

**Branch:** `review-kimi`  
**Reviewed:** 2026-06-13  
**Reviewer:** Grf (Hermes Agent)  
**Scope:** Full source review of `src/wolfpack/` plus cross-check against `docs/`. Security emphasis: auth, injection surfaces, secrets/PII handling, trust boundaries, and concurrency.

---

## 1. Executive Summary

| Baseline | Result |
|---|---|
| `mypy src` | ✅ No issues (97 files) |
| `ruff check src tests` | ✅ All checks passed |
| Unit + security tests | ✅ 363 passed in ~54 s (with `--no-cov`) |
| Full pytest with coverage | ⚠️ Hangs/timeouts; coverage run is very slow |
| Integration tests | ⚠️ Not executed (require live Postgres/NATS/Ollama) |

**Bottom line:** The project has a solid skeleton, clean static analysis, and broad test coverage for a V1. The most serious remaining issue is that **crypto-shredding does not actually destroy the DEK row** — it only timestamps it, leaving encrypted PII recoverable. Several other medium-severity bugs around learning-queue failure handling, review-state persistence, async event-loop misuse, and adapter XML parsing also need fixes before this is production-trustworthy.

---

## 2. Scope & Methodology

- Read primary docs: `architecture.md`, `configuration.md`, `PROJECT_PLAN.md`, existing audit reports (used for context only).
- Manually reviewed security-critical modules: auth, breakglass, PII/crypto, RAG base, adapters, API routes, orchestrator graph/budget/branches/watchdog, all agents, learning/eval, observability.
- Used parallel subagents for broad module passes, then independently verified the highest-impact claims.
- Ran targeted pytest subsets to confirm environment behavior and identify coverage holes.

---

## 3. Critical Security Findings

### 3.1 Crypto-shredding only marks the DEK as shredded; it does not delete it
- **Severity:** HIGH
- **Location:** `src/wolfpack/crypto/dek.py::shred_dek()`, `src/wolfpack/crypto/shred.py::erase_case()`
- **Issue:** `shred_dek()` executes `UPDATE wolfpack.crypto_shred_keys SET shredded_at = NOW() ...`. The wrapped DEK remains in the table. The architecture doc explicitly says the row is *deleted*. Because PII mappings are encrypted under a per-case DEK derived from the wrapped DEK + salt, an attacker with DB access and the KEK can still recover original PII values for “shredded” cases.
- **Recommended fix:** Actually delete the DEK row(s) in `shred_dek()` (or move them to a separate tombstone table if audit retention is required). Ensure `get_wrapped_dek()` already excludes shredded rows, and add a security test that proves the row is gone and depseudonymization fails.

### 3.2 Windows Event Log adapter falls back to stdlib `xml.etree` when `defusedxml` is absent
- **Severity:** MEDIUM
- **Location:** `src/wolfpack/adapters/windows_eventlog.py:19-28` and `_parse_xml_fallback()`
- **Issue:** If `defusedxml` is not installed, the adapter logs a warning and imports `xml.etree.ElementTree`. The fallback calls `ET.parse()` on attacker-controlled EVTX/XML files, which is vulnerable to XXE/billion-laughs-style attacks (`# noqa: S314` is already present, acknowledging the issue). In an airgapped SOC product, “optional” secure parsing is not acceptable.
- **Recommended fix:** Make `defusedxml` a hard dependency, or refuse to parse XML entirely if it is missing. Remove the stdlib fallback path.

---

## 4. Logic / Code Bugs

### 4.1 `AlphaDispatcher.dispatch_sync()` uses `get_event_loop().run_until_complete()`
- **Severity:** MEDIUM
- **Location:** `src/wolfpack/agents/alpha.py:99-100`
- **Issue:** `asyncio.get_event_loop().run_until_complete(...)` fails when called from inside an already-running event loop (common in async servers, tests, and modern LangGraph async runners). This will raise `RuntimeError: This event loop is already running`.
- **Recommended fix:** Remove `dispatch_sync()` and require callers to use `await dispatch()`, or use `asyncio.run()` / `anyio` with proper loop detection. If LangGraph truly needs a sync entry point, wrap with `asyncio.to_thread()` or an executor.

### 4.2 Learning worker marks failed entries as ingested
- **Severity:** MEDIUM
- **Location:** `src/wolfpack/learning/worker.py:180-192` (`_set_failure_status`)
- **Issue:** The “permanently failed” helper sets `ingested_at = NOW()`. A row with `ingested_at` populated looks successfully ingested to any status query or dashboard. There is also no `status` column to distinguish failure from success.
- **Recommended fix:** Add a `status` column (e.g., `pending`, `ingested`, `failed`) and set it to `failed` in `_set_failure_status`, leaving `ingested_at` NULL. Update `_fetch_entries()` to filter by status.

### 4.3 Learning worker never escalates to permanent failure
- **Severity:** MEDIUM
- **Location:** `src/wolfpack/learning/worker.py:194-206` (`_handle_failure`)
- **Issue:** `_handle_failure()` increments `retry_count` but does not compare it to `self.retry_limit`. `_set_failure_status()` is defined but, from the reviewed code path, never called, so entries can retry forever.
- **Recommended fix:** In `_handle_failure()`, fetch the current `retry_count`, and if it reaches `retry_limit`, call `_set_failure_status()` (after fixing the status/ingested_at semantics above).

### 4.4 Review API routes do not persist `review_decision`
- **Severity:** MEDIUM
- **Location:** `src/wolfpack/api/routes/review.py`
- **Issue:** `approve_case()` and `escalate_case()` update `cases.status` and write ledger entries, but they do not update `cases.review_decision`. The LangGraph review node looks at `state.review_decision` to route after review, so a case advanced via the API will not carry a decision value.
- **Recommended fix:** Add `review_decision` to the `UPDATE wolfpack.cases` statement in each review action, and also set `review_started_at = NULL` or appropriate closed state.

### 4.5 Default hunt graph uses a stub review node that auto-approves everything
- **Severity:** MEDIUM
- **Location:** `src/wolfpack/orchestrator/stubs.py:116-125`, `src/wolfpack/orchestrator/graph.py:164-185`
- **Issue:** `build_hunt_graph(use_stubs=True)` (the default) wires `stub_review`, which returns `review_decision="approved"` and `status="closed"` unconditionally. This is fine for skeleton tests, but it is dangerous if anyone deploys with `use_stubs=True`. The graph should not have an auto-approving default.
- **Recommended fix:** Make `use_stubs=False` the default for any non-test entry point, and raise a clear error if nodes are missing. Document that `use_stubs=True` is test-only.

### 4.6 Branch budget has a TOCTOU race when `branches_so_far` is supplied
- **Severity:** LOW–MEDIUM
- **Location:** `src/wolfpack/orchestrator/branches.py:48-89`
- **Issue:** If `branches_so_far` is provided, `create_branch()` calls `budget.check(...)` using the caller’s count, creates the branch, and then calls `budget.consume(...)`. Two concurrent callers using the same `branches_so_far` value can both pass the check and exceed `max_branches_per_case`.
- **Recommended fix:** Always use the atomic `check_and_consume()` path in production; remove the `branches_so_far` shortcut or treat it as a hint that is re-verified inside the atomic DB operation.

### 4.7 `BranchBudget.remaining()` returns total `max_depth` regardless of current depth
- **Severity:** LOW
- **Location:** `src/wolfpack/orchestrator/budget.py:105-121`
- **Issue:** `depth_remaining` is always `self._config.max_depth`; it does not subtract the current branch depth. The name and docstring imply a real remaining value.
- **Recommended fix:** Track per-case current depth or accept `current_depth` as a parameter and return `max(0, max_depth - current_depth)`.

### 4.8 `PGVectorStore._ALLOWED_TABLES` is a class-level mutable allowlist
- **Severity:** LOW
- **Location:** `src/wolfpack/rag/base.py:117-130`
- **Issue:** The constructor mutates a class variable. The allowlist set by one instance affects all instances, which is surprising and not thread-safe.
- **Recommended fix:** Store the allowlist per-instance (`self._allowed_tables`) and validate against that.

### 4.9 RAG vector formatter does not validate numeric values
- **Severity:** LOW
- **Location:** `src/wolfpack/rag/base.py:161-164`
- **Issue:** `_format_vector()` uses `str(v)` on each float. If an embedding ever contains `nan`/`inf`, pgvector will reject the query at runtime.
- **Recommended fix:** Validate each value is a finite float before formatting.

### 4.10 PII pipeline leaves `Event.metadata` unsanitized
- **Severity:** MEDIUM
- **Location:** `src/wolfpack/processing/pii_pipeline.py:27-73`
- **Issue:** `sanitize_events()` rebuilds `Event` objects with sanitized `raw_payload` and `entities`, but copies `metadata` through unchanged. Adapters often put PII in metadata (hostnames, usernames, IP addresses).
- **Recommended fix:** Recursively sanitize `metadata` with the same `_sanitize_payload()` logic.

### 4.11 Regex-based NER fallback misses many identifier types
- **Severity:** MEDIUM
- **Location:** `src/wolfpack/processing/ner.py:25-40`
- **Issue:** The Presidio-free fallback only strips IPv4/IPv6/CIDR, MAC, email, URL, hostname. It misses phone numbers, SSNs, credit cards, usernames, windows SIDs, file paths, etc. In airgapped deployments Presidio may not be installed, so this fallback becomes the primary defense.
- **Recommended fix:** Expand the regex set or make Presidio a hard dependency for production. Add tests that exercise the fallback path with representative SOC telemetry.

---

## 5. Test Coverage & Gaps

- **Unit + security tests:** 363 passed. Good breadth for agents, schemas, auth, PII, RAG tools, graph stubs, policy, ledger integrity.
- **Overall source coverage:** ~39 % with coverage enabled. Many critical paths are only exercised by integration tests:
  - `orchestrator/review.py` — 0 %
  - `orchestrator/watchdog.py` — 0 %
  - `orchestrator/stubs.py` — 0 %
  - `rag/base.py`, `rag/case_history.py`, `rag/threat_intel.py` — ~30 %
  - `schemas/persistence.py` — ~22 %
  - `processing/pii_pipeline.py` — ~26 %
  - `adapters/*` — mixed, several real adapters not covered
- **Integration tests exist** for most of those modules, but they require live Postgres/NATS/Ollama and are skipped via `SKIP_INTEGRATION=1`. They should be run in CI with the full compose stack.
- **Coverage tool itself is problematic:** running pytest with coverage hangs/times out. This is a friction issue, not a code bug, but it discourages coverage gating in CI.
- **Missing tests I did not find:**
  - A test proving that `shred_dek()` deletes the DEK row and makes PII unrecoverable.
  - A test proving the Windows Event Log adapter refuses unsafe XML parsing without `defusedxml`.
  - A test for `AlphaDispatcher.dispatch_sync()` being called inside an existing event loop.
  - A test for the review API persisting `review_decision`.
  - A test for concurrent branch creation not exceeding the budget.

---

## 6. Documentation vs Implementation Drift

| Doc Claim | Implementation | Gap |
|---|---|---|
| Architecture doc: crypto-shred “delete the DEK row” | `shred_dek()` sets `shredded_at` but keeps row | HIGH — data still recoverable |
| Architecture doc: break-glass audit logs `justification` | `breakglass.py::show_raw()` and API route accept no justification field | MEDIUM — audit trail incomplete |
| Architecture doc / runbook: full NATS subject list (`hunt.task.alpha`, `hunt.finding.tracker`, etc.) | `NATSClient.ensure_streams()` uses `hunt.task.*`, `hunt.finding.*`, `hunt.branch.*`, `hunt.status.*` | LOW — wildcard streams cover the listed subjects, but exact subject wiring in `graph.py` differs (`hunt.branch.created`, etc.) |
| Configuration doc: alert thresholds are “compile-time constants in `alert_manager.py`” | No `alert_manager.py` exists in `src/wolfpack/observability/` | MEDIUM — doc references a module/file that is not implemented |
| PROJECT_PLAN / architecture: Scribe is a non-LLM service writing to ledger | `stub_scribe()` returns `{}`; real `ScribeInterface` not present | MEDIUM — Scribe is not wired into the graph to write ledger entries |
| PROJECT_PLAN: “LangGraph TypedDicts derived from Pydantic models” | `CaseState` is a Pydantic model used directly; no generated TypedDict visible | LOW — works in practice with LangGraph’s `MessagesState`/dict conversion, but the documented derivation is not explicit |
| Architecture doc: NATS payload sanitization strips `raw_payload` | `_sanitize_payload()` recursively redacts keys named exactly `raw_payload` | LOW — robust enough, but any other PII-key names are not redacted |

---

## 7. Lower-Priority Hardening Notes

- **API auth dev fallback:** `src/wolfpack/api/auth.py:30` hardcodes `dev-token-do-not-use-in-production` when `WOLFPACK_API_TOKEN` is unset in dev mode. This is acceptable for local dev but should be removed or made opt-in via an explicit `WOLFPACK_DEV_TOKEN` env var.
- **CORS:** `create_app()` allows `http://localhost:3000` and `:5173` with credentials. Fine for local frontend; production deployments must override this via settings, not hardcoded origins.
- **NATS publish:** `_wrap_with_nats()` publishes node outputs without confirming the NATS client is connected. If a client is passed but not connected, publication will fail and be logged, but the node result still proceeds.
- **Tool name validation:** `_validate_tools()` uses `getattr(tool, "__name__", str(tool))`. Wrapped tools generally preserve `__name__`, but decorators that fail to use `functools.wraps` could bypass the allowlist. This is mitigated by the fact that tools are built by trusted factory code, but worth a unit test.
- **Confidence enum drift:** `CaseState.verdict_decision` allows `SUSPICIOUS`; `CloserOutput` allows `SUSPICIOUS`; the architecture doc’s verdict list does not mention `SUSPICIOUS`. Align docs or remove the value.
- **Review watchdog:** `datetime.fromisoformat()` is called on strings; Python 3.11+ handles the `Z` suffix, but older runtimes or unexpected formats could raise. The `review_started_at` field is never set by the review API routes, so the watchdog currently has no data to act on.

---

## 8. Recommended Fix Priority

1. **Fix crypto-shredding** (delete DEK rows; add irreversibility test).
2. **Remove the stdlib XML fallback** in the Windows Event Log adapter.
3. **Fix learning worker failure handling** (status column, retry-limit enforcement).
4. **Fix review API state persistence** (`review_decision`, `review_started_at`).
5. **Make `use_stubs=False` the default** for the hunt graph, or at least fail loudly if deployed with stubs.
6. **Sanitize `Event.metadata`** in the PII pipeline.
7. **Fix `AlphaDispatcher.dispatch_sync()`** event-loop fragility.
8. **Harden branch budget concurrency** and correct `remaining()` depth math.
9. **Add Presidio as a production dependency** or expand regex NER.
10. **Run integration tests in CI** and address the coverage-run hang.
