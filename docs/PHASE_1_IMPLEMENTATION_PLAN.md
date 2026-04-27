# Phase 1 Implementation Plan — Contracts & Case State

**Objective:** Deliver the complete data contract layer that all subsequent phases depend on. No LangGraph nodes, agent logic, or RAG pipelines.

**Estimated Duration:** 1–2 weeks  
**Depends on:** Phase 0 (complete)  
**Blocks:** Phase 2 (orchestration skeleton), Phase 3 (agent intelligence)

---

## 1. Scope

### In Scope
- Pydantic domain models in `src/wolfpack/schemas/`
- Postgres schema with all tables, constraints, and triggers
- Hash-chained evidence ledger with integrity verification
- Crypto-shredding architecture with pluggable KMS abstraction
- PII pseudonymization store with per-case salts
- Baseline governance fixtures (retention policy defaults)

### Out of Scope
- LangGraph graph definition or node implementations
- NATS integration from application code
- Agent stubs or real agent logic
- RAG pipelines or telemetry adapters
- Frontend or API layer

---

## 2. Deliverables

| # | Deliverable | Location | Success Criteria |
|---|-------------|----------|------------------|
| 1 | Pydantic domain models | `src/wolfpack/schemas/` | All models compile, validate, and round-trip through serialization |
| 2 | LangGraph `TypedDict` derivation | `src/wolfpack/schemas/graph_state.py` | Derived from Pydantic models with no hand-maintained duplication |
| 3 | Alembic migrations | `alembic/` | `alembic upgrade head` creates all tables with correct constraints |
| 4 | Persistence helpers | `src/wolfpack/schemas/persistence.py` | Async CRUD with optimistic concurrency (`VersionConflictError` on stale writes) |
| 5 | Hash-chain trigger | Postgres migration | Inserting a ledger row auto-populates `prev_hash` and `content_hash` |
| 6 | Chain verification | `src/wolfpack/schemas/ledger.py` + SQL function | `verify_chain(case_id)` detects tampering; `replay_ledger(case_id)` returns ordered entries |
| 7 | KMS abstraction | `src/wolfpack/crypto/kms.py` | Pluggable interface: `wrap_key`, `unwrap_key`, `rotate_kek` |
| 8 | Software KMS (dev) | `src/wolfpack/crypto/software_kms.py` | AES-256-GCM wrap/unwrap; documented as dev-only |
| 9 | DEK lifecycle | `src/wolfpack/crypto/dek.py` | Generate → wrap → store → shred |
| 10 | Crypto-shredding | `src/wolfpack/crypto/shred.py` | `erase_case(case_id)` removes DEK and logs the event |
| 11 | PII pseudonymization | `src/wolfpack/schemas/pii.py` | Deterministic `HMAC(salt, type:value)` → human-readable tokens; break-glass reversal |
| 12 | Unit + integration tests | `tests/unit/`, `tests/integration/` | 100% pass; mypy strict clean |

---

## 3. Work Breakdown

### Track A: Domain Pydantic Models (Days 1–3)

**A1. Core domain models**
- `seed.py` — `Seed` (type discriminant: `ioc`, `alert`, `anomaly`, `hunt_query`; raw payload; metadata)
- `entity.py` — `Entity` (type: `host`, `user`, `ip`, `domain`, `hash`, `url`; value; context)
- `hypothesis.py` — `Hypothesis` (description, confidence, evidence_refs, status, branch_id)
- `evidence.py` — `EvidenceRef` (source_type, source_id, timestamp, hash, metadata)
- `confidence.py` — `Confidence` enum (ordinal 1–5: coincidence, weak, plausible, strong, high-fidelity)
- `case_state.py` — `CaseState` (aggregate) and `BranchState` (per-branch with `version` for optimistic concurrency)
- `branch.py` — `BranchSpec` (parent_branch, hypothesis, depth, created_by)

**A2. Per-agent input/output models**
- `src/wolfpack/schemas/agents/` package
- `AlphaInput`/`AlphaOutput`, `TrackerInput`/`TrackerOutput`, `FlankerInput`/`FlankerOutput`, `CloserInput`/`CloserOutput`, `ScribeInput`/`ScribeOutput`
- Every output model uses structured fields only — no free-text blobs

**A3. LangGraph `TypedDict` derivation**
- `graph_state.py` — derive from `CaseState` using `typing.TypedDict`
- Document the derivation strategy for automatic propagation on model changes

**A4. Unit tests**
- `tests/unit/test_schemas.py` — instantiation, serialization, validation for every model
- Test `Confidence` bounds, `CaseState`/`BranchState` aggregate relationship

---

### Track B: Postgres Schema and Persistence Layer (Days 2–5)

**B1. Alembic setup**
- Add `alembic` and `asyncpg` to `pyproject.toml`
- Run `alembic init`; configure `alembic.ini` and `env.py` for asyncpg
- Add `just migrate` and `just migrate-create` targets

**B2. Core tables migration**
- `cases`: `id`, `seed`, `status`, `created_at`, `updated_at`, `version`
- `branches`: `id`, `case_id` (FK), `parent_branch_id`, `hypothesis`, `depth`, `status`, `version`, `created_at`
- `hypotheses`: `id`, `branch_id` (FK), `description`, `confidence`, `status`, `created_at`
- `pivots`: `id`, `branch_id` (FK), `from_entity`, `to_entity`, `pivot_type`, `created_at`
- Foreign keys and indexes on `case_id`, `branch_id`

**B3. Evidence ledger table**
- `evidence_ledger`: `id`, `case_id` (FK), `branch_id` (FK), `entry_type`, `content` (JSONB), `prev_hash`, `content_hash`, `created_at`, `agent_run_id`, `schema_version`
- Unique constraint on `(case_id, id)` for append-only ordering

**B4. Governance tables**
- `learning_queue`: `id`, `case_id` (FK), `verdict`, `approved_by`, `approved_at`, `ingested_at`
- `retention_policy`: `id`, `policy_key`, `policy_value`, `updated_at` — seeded with 1-year default
- `crypto_shred_keys`: `id`, `case_id` (FK), `wrapped_dek`, `kek_id`, `created_at`, `shredded_at`
- `pii_salts`: `id`, `case_id` (FK), `salt`, `created_at`
- `breakglass_audit`: `id`, `case_id` (FK), `analyst_id`, `field_accessed`, `accessed_at`

**B5. Persistence helpers**
- `src/wolfpack/schemas/persistence.py`
- Async CRUD for `CaseState`, `BranchState`, `Hypothesis`, `EvidenceRef`
- Optimistic concurrency: `UPDATE ... SET version = version + 1 WHERE version = $expected`
- Wire to `PostgresConfig` from settings

**B6. Tests**
- `tests/unit/test_persistence.py` — mocked DB tests
- `tests/integration/test_schema_persistence.py` — testcontainers for real Postgres
- Test CRUD, optimistic concurrency, foreign key enforcement, concurrent writes

---

### Track C: Hash-Chained Evidence Ledger (Days 4–6)

**C1. Hash-chain trigger**
- Postgres trigger `wolfpack.compute_ledger_hash()` on `INSERT` to `evidence_ledger`:
  - Computes `content_hash = SHA-256(row_content)`
  - Looks up previous entry's `content_hash` for same `case_id`
  - Sets `prev_hash` (NULL for first entry)
- Include in Alembic migration

**C2. Chain verification**
- SQL function `wolfpack.verify_chain(case_id UUID)` → `(is_valid BOOLEAN, broken_at BIGINT)`
- Python wrapper `src/wolfpack/schemas/ledger.py` calling the SQL function

**C3. Replay tool**
- `replay_ledger(case_id)` — fetch ordered entries, validate hash chain, return `EvidenceRef`-compatible objects
- Raise on tamper detection

**C4. Integration tests**
- `tests/integration/test_ledger.py`
- Test: insert → verify → tamper → verify fails
- Test: concurrent inserts maintain chain integrity
- Test: `replay_ledger` returns correct ordered results

---

### Track D: Crypto-Shredding Skeleton and PII Store (Days 5–8)

**D1. KMS abstraction**
- `src/wolfpack/crypto/kms.py` — `KMSInterface`:
  - `async def wrap_key(dek: bytes, kek_id: str) -> bytes`
  - `async def unwrap_key(wrapped_dek: bytes, kek_id: str) -> bytes`
  - `async def rotate_kek(kek_id: str) -> str`
- `src/wolfpack/crypto/software_kms.py` — dev-only AES-256-GCM implementation
- Wire KMS selection to `Settings.deployment_mode`

**D2. DEK lifecycle**
- `src/wolfpack/crypto/dek.py`:
  - `generate_dek()` — random 256-bit
  - `store_wrapped_dek(case_id, wrapped_dek, kek_id)` → `crypto_shred_keys`
  - `shred_dek(case_id)` — deletes DEK row
- `src/wolfpack/crypto/shred.py`:
  - `erase_case(case_id)` — calls `shred_dek`, logs to evidence ledger

**D3. PII pseudonymization**
- `src/wolfpack/schemas/pii.py`:
  - `create_pii_salt(case_id)` — generates and stores per-case salt
  - `pseudonymize(case_id, identifier, identifier_type)` → deterministic token (e.g., `user_a42`)
  - `depseudonymize(case_id, token)` → reverse lookup (break-glass only)
- Document that NER-based stripping is Phase 3

**D4. Tests**
- `tests/integration/test_crypto_shredding.py` — full flow: create → wrap → store → shred → verify
- `tests/unit/test_pii.py` — determinism, salt-dependency, token format

---

## 4. Dependency Graph

```
A1 (core models) ─────────────────────────────────────────┐
   │                                                        │
   ├─→ A2 (agent I/O) ──→ A3 (graph_state) ──→ A4 (tests)   │
   │                                                        │
   ├─→ B2 (core tables) ──→ B3 (ledger) ──→ B4 (governance)│
   │                              │                         │
   │                              └─→ C1 (trigger) ──→ C2   │
   │                                     │        │         │
   │                                     └─→ C3 ──┘         │
   │                                                        │
   ├─→ B5 (persistence) ──→ B6 (tests)                       │
   │                                                        │
   └─→ D1 (KMS) ──→ D2 (DEK/shred) ──→ D3 (PII) ──→ D4     │
```

**Critical path:** A1 → B2 → B3 → C1 → C2 → C3 → B5 → D1 → D2 → D3

---

## 5. Parallelization

### Safe parallel lanes after A1

- **Lane 1:** B1–B4 (migrations)
- **Lane 2:** C1 trigger logic (offline design)
- **Lane 3:** D1 KMS abstraction (no DB dependency for interface)

### Safe parallel lanes after B1

- **Lane 1:** B2–B4 + B5 (persistence)
- **Lane 2:** D1 (KMS impl)
- **Lane 3:** D3 (PII core logic — no DB for unit tests)

---

## 6. Milestones

| Milestone | Target | Exit Criteria |
|-----------|--------|---------------|
| Schema Models Defined | Day 3 | All domain Pydantic models compile and pass unit tests; `graph_state.py` derives from models |
| Database Schema Applied | Day 5 | `alembic upgrade head` creates all tables; foreign keys and indexes enforced; governance fixtures seeded |
| Ledger Integrity Proven | Day 6 | Trigger populates hashes; `verify_chain` detects tampering; `replay_ledger` returns ordered entries |
| Crypto-Shredding Ready | Day 8 | KMS abstraction pluggable; software KMS works; DEK lifecycle tested; PII pseudonymization deterministic |
| Phase 1 Complete | Day 8–10 | All integration tests pass; persistence works against real Postgres; optimistic concurrency tested; Phase 2 handoff note written |

---

## 7. Validation Checklist

```bash
uv sync
just lint
just typecheck
just test
alembic upgrade head
alembic downgrade base && alembic upgrade head
just test-integration
```

All must succeed before Phase 1 is marked complete.

---

## 8. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Pydantic model evolution | Medium | Design for extension: `Optional` fields, version through migrations |
| KMS complexity | Medium | Ship `SoftwareKMS` for dev; stub Vault reference; defer real integration to Phase 8 |
| Migration ordering | Medium | Put trigger/function migrations after base tables; test downgrade paths |
| Concurrent branch writes | High | Test optimistic concurrency explicitly before Phase 2 relies on it |

---

## 9. Definition of Done

| Item | Proof Artifact |
|------|----------------|
| Pydantic models are single source of truth | `src/wolfpack/schemas/` models, `graph_state.py` derivation |
| Postgres schema matches models | Alembic migrations, passing `alembic upgrade head` |
| Hash-chain ledger is tamper-evident | Trigger, `verify_chain` SQL function, integration tests |
| Crypto-shredding skeleton works | `crypto/` module, `SoftwareKMS`, integration test |
| PII pseudonymization is deterministic | `pii.py`, unit and integration tests |
| Optimistic concurrency prevents stale writes | persistence helpers, integration test |
| Governance fixtures seeded | `retention_policy` default row, migration |

---

## 10. PR Slicing

1. `phase1-schemas` — Pydantic models, TypedDict derivation, unit tests
2. `phase1-migrations` — Alembic setup, core and governance migrations
3. `phase1-persistence` — CRUD helpers, optimistic concurrency
4. `phase1-ledger` — Hash-chain trigger, verification, replay tool
5. `phase1-crypto-pii` — KMS abstraction, DEK lifecycle, PII store, integration tests

---

## 11. Immediate Next Action

1. Create `src/wolfpack/schemas/seed.py` with the `Seed` model
2. Create `src/wolfpack/schemas/confidence.py` with the `Confidence` enum
3. Create `src/wolfpack/schemas/case_state.py` with `CaseState` and `BranchState`
4. Add unit tests for these core models

These establish the data contracts every other Phase 1 track depends on.
