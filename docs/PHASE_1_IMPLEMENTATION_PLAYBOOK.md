# Phase 1 Implementation Playbook — Contracts & Case State

This document turns the Phase 1 plan from [`PROJECT_PLAN.md`](./PROJECT_PLAN.md) into an execution-ready implementation plan. It adds sequencing, concrete deliverables, dependency order, acceptance checks, and checkpoints.

## 0. Outstanding Design Questions

| # | Question | Decision needed by | Default if unresolved | Notes |
|---|----------|--------------------|-----------------------|-------|
| D1 | **KMS implementation choice** — HashiCorp Vault (enterprise default), cloud KMS (AWS/GCP/Azure), PKCS#11 HSM (high-assurance), or software-only (dev)? | End of Track B (before crypto-shredding skeleton) | Vault for on-prem reference; software-only KMS for `dev` mode | The KMS abstraction interface should be defined in Track A so the skeleton is pluggable. The reference implementation for `dev` can be a software-only KMS that stores KEKs on disk (documented as insecure, dev-only). |
| D2 | **Migration tooling** — Alembic, raw SQL scripts, or a lightweight custom runner? | Start of Track B | Alembic with auto-generated revisions from the Pydantic models | Alembic is the most maintainable for a Postgres-heavy project with evolving schemas. Raw scripts work but lose upgrade/downgrade history. |
| D3 | **Ledger hash algorithm** — SHA-256, BLAKE3, or SHA-3? | Start of Track C | SHA-256 | SHA-256 is the safe, auditable default. BLAKE3 is faster but less familiar to security auditors. Switchable behind the hash function interface if needed. |
| D4 | **Alembic + asyncpg sync bridge** — Alembic requires a synchronous DBAPI connection for migration runs. Options: (a) use `psycopg2` only for migrations and `asyncpg` at runtime, (b) use Alembic's `run_sync` with an asyncio event loop, (c) use `asyncpg` with a sync shim. | Start of Track B (before B1) | Use `psycopg2` (sync) for Alembic `env.py` migrations only; `asyncpg` for all application code | Mixing drivers is slightly inelegant but is the standard recommendation from the Alembic maintainers for async applications. The `env.py` `DATABASE_URL` can swap the scheme (`postgresql+asyncpg` → `postgresql+psycopg2`) at migration time. |
| D5 | **Hash chain granularity** — single per-case chain (all entries across branches interleaved by insertion order) vs. per-branch independent chains? | Start of Track C (before trigger design) | Single per-case chain ordered by `id` | A single chain is simpler and covers the audit-trail use case. Per-branch chains would require multiple `prev_hash` lookups and a more complex replay tool. The downside is that concurrent branch inserts can interleave — which is correct behavior if the trigger uses a row-level lock on the latest entry. |
| D6 | **Break-glass authorization** — how is `depseudonymize` gated? Options: (a) Postgres row-level security with a superuser role, (b) application-level `breakglass_authorized_by` parameter with mandatory audit log write, (c) a separate signed break-glass token issued by the operator. | Before Track D3 | Application-level: caller must supply `authorized_by: str`; the function writes to `breakglass_audit` before returning any data and raises if the write fails | Database roles require operator involvement to grant; a signed token adds a key distribution problem. The simplest V1 control is an application-enforced audit write that cannot be bypassed without modifying source code. |
| D7 | **Evidence JSONB schema versioning** — the `evidence_ledger.content` column stores heterogeneous entry types. When entry schemas evolve, how are old rows read? Options: (a) `entry_type` + `schema_version` sibling columns, (b) embed `_schema_version` inside the JSONB, (c) treat JSONB as immutable-at-write and always read with the version that wrote it. | Before Track B3 | Add a `schema_version INTEGER NOT NULL DEFAULT 1` column alongside `entry_type`; keep JSONB content immutable after insert | A sibling column is queryable and indexable; embedding in JSONB is opaque to the query planner. Immutability-at-write aligns with the hash-chain guarantee. |

## 1. Current Baseline

The repository has (from Phase 0):

- `src/wolfpack/` package scaffold with config, LLM, observability, and smoke modules
- `src/wolfpack/schemas/` — empty `__init__.py` (placeholder)
- `src/wolfpack/orchestrator/` — empty `__init__.py` (placeholder)
- Docker Compose stack: Postgres (pgvector), NATS JetStream, OTel Collector, MLflow, Ollama
- `infra/postgres/init.sql` — creates `vector` extension, base roles
- Unit and integration test suites with `conftest.py` shared fixtures
- CI enforcing lint, typecheck, tests

The repository does **not** yet have:

- Domain Pydantic models (`Seed`, `Entity`, `Hypothesis`, etc.)
- Postgres schema for case state, evidence ledger, learning queue
- Hash-chained ledger implementation
- Crypto-shredding architecture (DEK/KEK/KMS)
- PII pseudonymization store
- Alembic migrations or any database migration tooling

## 2. Phase Objective

Deliver the complete data contract layer that all subsequent phases depend on:

- Shared Pydantic models in `schemas/` as the single source of truth
- Postgres schema with all tables, constraints, and triggers
- Hash-chained evidence ledger with integrity verification
- Crypto-shredding architecture with pluggable KMS abstraction
- PII pseudonymization store with per-case salts
- Baseline governance fixtures (retention policy defaults)

No LangGraph nodes, agent logic, or RAG pipelines should land during this phase. These are pure data contracts and persistence.

## 3. Execution Strategy

Four implementation tracks, landed in dependency order:

1. Pydantic domain models (schemas) — the single source of truth
2. Postgres schema, migrations, and persistence layer
3. Hash-chained ledger and integrity verification
4. Crypto-shredding skeleton and PII store

The critical path is:

1. define Pydantic models → derive LangGraph TypedDicts
2. create Postgres migrations → apply schema
3. implement ledger trigger and verification
4. implement KMS abstraction → crypto-shredding skeleton
5. add PII salts and governance fixtures
6. write comprehensive tests for all tracks

## 4. Work Breakdown Structure

### Track A: Domain Pydantic Models (schemas)

Purpose: establish the single source of truth for all data contracts.

#### A1. Implement core domain models

Tasks:

- Create `src/wolfpack/schemas/seed.py` with `Seed` model (type discriminant: `ioc`, `alert`, `anomaly`, `hunt_query`; raw payload; metadata).
- Create `src/wolfpack/schemas/entity.py` with `Entity` model (type: `host`, `user`, `ip`, `domain`, `hash`, `url`; value; context dict).
- Create `src/wolfpack/schemas/hypothesis.py` with `Hypothesis` model (description, confidence, evidence_refs, status, branch_id).
- Create `src/wolfpack/schemas/evidence.py` with `EvidenceRef` model (source_type, source_id, timestamp, hash, metadata).
- Create `src/wolfpack/schemas/confidence.py` with `Confidence` enum (ordinal 1–5 with docstring anchors: `1` coincidence, `2` weak, `3` plausible, `4` strong, `5` high-fidelity).
- Create `src/wolfpack/schemas/case_state.py` with `CaseState` model (aggregate view over branches) and `BranchState` model (per-branch sub-state with `version` column for optimistic concurrency).
- Create `src/wolfpack/schemas/branch.py` with `BranchSpec` model (parent_branch, hypothesis, depth, created_by).

Deliverables:

- `src/wolfpack/schemas/seed.py`
- `src/wolfpack/schemas/entity.py`
- `src/wolfpack/schemas/hypothesis.py`
- `src/wolfpack/schemas/evidence.py`
- `src/wolfpack/schemas/confidence.py`
- `src/wolfpack/schemas/case_state.py`
- `src/wolfpack/schemas/branch.py`

Acceptance checks:

- all models instantiate with valid data
- `Confidence` enum values match the 1–5 ordinal anchors
- `CaseState` is an aggregate over `BranchState` entries
- `BranchState` carries a `version` field for optimistic concurrency

#### A2. Implement per-agent input/output models

Tasks:

- Create `src/wolfpack/schemas/agents/` package.
- Define `AlphaInput` / `AlphaOutput`, `TrackerInput` / `TrackerOutput`, `FlankerInput` / `FlankerOutput`, `CloserInput` / `CloserOutput`, `ScribeInput` / `ScribeOutput`.
- Each output model includes structured fields (no free-text blobs) — e.g., `TrackerOutput` includes `hypotheses: list[Hypothesis]`, `updated_entities: list[Entity]`, `evidence_refs: list[EvidenceRef]`, `tracker_confidence: Confidence`.

Deliverables:

- `src/wolfpack/schemas/agents/__init__.py`
- per-agent input/output Pydantic models

Acceptance checks:

- every agent input/output model round-trips through serialization
- output models contain structured, typed fields only

#### A3. Derive LangGraph TypedDict from Pydantic models

Tasks:

- Create `src/wolfpack/schemas/graph_state.py`.
- Derive the LangGraph `TypedDict` from `CaseState` Pydantic model using `typing.TypedDict` or pass the Pydantic model directly (modern LangGraph supports this).
- Document the derivation strategy so future model changes propagate to the graph state automatically.

Deliverables:

- `src/wolfpack/schemas/graph_state.py`

Acceptance checks:

- the graph state TypedDict matches the Pydantic model fields
- no hand-maintained duplication between schemas and graph state

#### A4. Add schema unit tests

Tasks:

- Create `tests/unit/test_schemas.py`.
- Test model instantiation, serialization, and validation for every model.
- Test `Confidence` enum bounds and anchor descriptions.
- Test `CaseState` / `BranchState` aggregate relationship.

Deliverables:

- `tests/unit/test_schemas.py`

Acceptance checks:

- all models pass round-trip serialization tests
- validation errors are raised for invalid data (e.g., confidence out of range)

### Track B: Postgres Schema and Persistence Layer

Purpose: create the persistent store that the ledger, case state, and governance features depend on.

#### B1. Set up Alembic migration tooling

Tasks:

- Add `alembic` and `asyncpg` to `pyproject.toml` dependencies (if not already present).
- Run `alembic init` to create the migration directory structure under `src/wolfpack/` or project root (prefer project root `alembic/` directory).
- Configure `alembic.ini` and `env.py` to use the `asyncpg` async driver and the `PostgresConfig` from settings.
- Add `just migrate` and `just migrate-create` targets to the `justfile`.

Deliverables:

- `alembic/` directory structure
- `alembic.ini`
- `justfile` updates

Acceptance checks:

- `alembic upgrade head` runs against the local Postgres container
- `just migrate` succeeds

#### B2. Create initial migration — core tables

Tasks:

- Create migration for `cases` table: `id`, `seed`, `status`, `created_at`, `updated_at`, `version`.
- Create migration for `branches` table: `id`, `case_id` (FK), `parent_branch_id`, `hypothesis`, `depth`, `status`, `version`, `created_at`.
- Create migration for `hypotheses` table: `id`, `branch_id` (FK), `description`, `confidence`, `status`, `created_at`.
- Create migration for `pivots` table: `id`, `branch_id` (FK), `from_entity`, `to_entity`, `pivot_type`, `created_at`.
- Add foreign key constraints and indexes on `case_id`, `branch_id`.
- Update `infra/postgres/init.sql` to also create the `wolfpack` application schema if not present.

Deliverables:

- Alembic migration file(s) for core case-state tables

Acceptance checks:

- `alembic upgrade head` creates all tables with correct constraints
- foreign key violations are caught by the database
- indexes exist on `case_id` and `branch_id`

#### B3. Create migration — evidence ledger table

Tasks:

- Create migration for `evidence_ledger` table: `id`, `case_id` (FK), `branch_id` (FK), `entry_type`, `content` (JSONB), `prev_hash`, `content_hash`, `created_at`, `agent_run_id`.
- `prev_hash` references the previous row's `content_hash` for the same `case_id` (ordered by `id`).
- Add a unique constraint on `(case_id, id)` to enforce append-only ordering.

Deliverables:

- Migration for `evidence_ledger`

Acceptance checks:

- table exists with correct columns and types
- JSONB `content` column accepts structured data
- `prev_hash` and `content_hash` columns are nullable on the first entry

#### B4. Create migration — governance tables

Tasks:

- Create migration for `learning_queue` table: `id`, `case_id` (FK), `verdict`, `approved_by`, `approved_at`, `ingested_at`.
- Create migration for `retention_policy` table: `id`, `policy_key`, `policy_value`, `updated_at`.
- Seed `retention_policy` with default 1-year retention row.
- Create migration for `crypto_shred_keys` table: `id`, `case_id` (FK), `wrapped_dek`, `kek_id`, `created_at`, `shredded_at`.
- Create migration for `pii_salts` table: `id`, `case_id` (FK), `salt`, `created_at`.
- Create migration for `breakglass_audit` table: `id`, `case_id` (FK), `analyst_id`, `field_accessed`, `accessed_at`.

Deliverables:

- Migrations for `learning_queue`, `retention_policy`, `crypto_shred_keys`, `pii_salts`, `breakglass_audit`

Acceptance checks:

- all governance tables exist after `alembic upgrade head`
- `retention_policy` has a seeded default row
- `breakglass_audit` is append-only (no update/delete triggers needed — insert only)

#### B5. Implement persistence helper module

Tasks:

- Create `src/wolfpack/schemas/persistence.py` with async CRUD helpers for `CaseState`, `BranchState`, `Hypothesis`, and `EvidenceRef`.
- Use `asyncpg` for database access.
- Implement optimistic concurrency: `UPDATE ... SET version = version + 1 WHERE version = $expected_version`.
- Wire the persistence layer to `PostgresConfig` from settings.

Deliverables:

- `src/wolfpack/schemas/persistence.py`

Acceptance checks:

- CRUD helpers work against the local Postgres container
- optimistic concurrency rejects stale writes with a `VersionConflictError`
- no raw SQL strings in application code — use parameterized queries

#### B6. Add persistence unit and integration tests

Tasks:

- Add `tests/unit/test_persistence.py` with mocked database tests.
- Add `tests/integration/test_schema_persistence.py` using testcontainers for real Postgres.
- Test CRUD, optimistic concurrency, and foreign key enforcement.

Deliverables:

- persistence test modules

Acceptance checks:

- unit tests pass without database
- integration tests pass against real Postgres
- optimistic concurrency is tested with concurrent write scenarios

### Track C: Hash-Chained Evidence Ledger

Purpose: implement tamper-evidence for the audit trail.

#### C1. Implement hash-chain trigger

Tasks:

- Create a Postgres trigger function `wolfpack.compute_ledger_hash()` that:
  - On `INSERT` to `evidence_ledger`, computes `content_hash = hash(row_content)` using SHA-256 (or chosen algorithm from D3).
  - Looks up the previous entry's `content_hash` for the same `case_id` (ordered by `id`).
  - Sets `prev_hash` to the previous entry's `content_hash` (NULL for the first entry in a case).
- Create the trigger on the `evidence_ledger` table.
- Add the trigger to the Alembic migration (or a new migration if Track B already landed).

Deliverables:

- Postgres trigger function and trigger in a migration

Acceptance checks:

- inserting a ledger row automatically populates `prev_hash` and `content_hash`
- the first entry in a case has `prev_hash = NULL`
- subsequent entries have `prev_hash` matching the previous entry's `content_hash`

#### C2. Implement chain verification function

Tasks:

- Create a Postgres function `wolfpack.verify_chain(case_id UUID)` that:
  - Walks the ledger rows for the given `case_id` in insertion order.
  - Recomputes each `content_hash` and verifies it matches the stored value.
  - Verifies each `prev_hash` links correctly to the prior row.
  - Returns `(is_valid BOOLEAN, broken_at BIGINT)` — the ID of the first broken link, or NULL if valid.
- Create a Python wrapper in `src/wolfpack/schemas/ledger.py` that calls the SQL function.

Deliverables:

- Postgres `verify_chain` function in a migration
- `src/wolfpack/schemas/ledger.py`

Acceptance checks:

- `verify_chain` returns `is_valid = true` for an unmodified chain
- `verify_chain` returns `is_valid = false` and `broken_at` ID for a tampered row
- the Python wrapper works end-to-end against the local Postgres

#### C3. Implement replay tool

Tasks:

- Add a `replay_ledger(case_id)` Python function in `src/wolfpack/schemas/ledger.py` that:
  - Fetches all ledger entries for a case in insertion order.
  - Returns them as a list of structured `EvidenceRef`-compatible objects.
  - Validates the hash chain before returning (raises on tamper detection).
- This will be the foundation for the "replay a prior case" feature (Phase 2+).

Deliverables:

- `replay_ledger()` in `src/wolfpack/schemas/ledger.py`

Acceptance checks:

- replay returns entries in correct order
- replay raises an error if the chain is broken

#### C4. Add ledger integration tests

Tasks:

- Add `tests/integration/test_ledger.py`.
- Test: insert entries → verify chain → tamper with a row → verify chain fails.
- Test: concurrent inserts to the same case maintain chain integrity.
- Test: `replay_ledger` returns correct ordered results.

Deliverables:

- `tests/integration/test_ledger.py`

Acceptance checks:

- all tests pass against real Postgres
- concurrent write scenario does not break the chain

### Track D: Crypto-Shredding Skeleton and PII Store

Purpose: implement the erasure architecture and pseudonymization store.

#### D1. Implement KMS abstraction

Tasks:

- Create `src/wolfpack/crypto/__init__.py`.
- Create `src/wolfpack/crypto/kms.py` with `KMSInterface` abstract base class:
  - `async def wrap_key(dek: bytes, kek_id: str) -> bytes`
  - `async def unwrap_key(wrapped_dek: bytes, kek_id: str) -> bytes`
  - `async def rotate_kek(kek_id: str) -> str` (returns new KEK ID)
- Create `src/wolfpack/crypto/software_kms.py` implementing `KMSInterface` for dev mode:
  - Stores KEKs as files on disk (documented as insecure, dev-only).
  - Uses AES-256-GCM for wrap/unwrap.
- Wire KMS selection to `Settings.deployment_mode` (dev → software KMS; on-prem → Vault reference, stubbed).

Deliverables:

- `src/wolfpack/crypto/kms.py`
- `src/wolfpack/crypto/software_kms.py`

Acceptance checks:

- `SoftwareKMS` can wrap and unwrap a DEK
- wrapped DEK cannot be unwrapped with a wrong KEK
- KMS selection is driven by deployment mode

#### D2. Implement DEK lifecycle

Tasks:

- Create `src/wolfpack/crypto/dek.py` with:
  - `async def generate_dek() -> bytes` — generates a random 256-bit DEK.
  - `async def store_wrapped_dek(case_id, wrapped_dek, kek_id)` — persists to `crypto_shred_keys` table.
  - `async def shred_dek(case_id)` — deletes the DEK row from `crypto_shred_keys`.
- Create `src/wolfpack/crypto/shred.py` with:
  - `async def erase_case(case_id)` — calls `shred_dek`, logs the event to the evidence ledger.
- Wire the DEK lifecycle to the persistence layer from Track B.

Deliverables:

- `src/wolfpack/crypto/dek.py`
- `src/wolfpack/crypto/shred.py`

Acceptance checks:

- DEK generation produces a 256-bit key
- `store_wrapped_dek` persists to the database
- `shred_dek` removes the row and logs the event
- `erase_case` orchestrates the full flow

#### D3. Implement PII pseudonymization store

Tasks:

- Create `src/wolfpack/schemas/pii.py` with:
  - `async def create_pii_salt(case_id) -> str` — generates and stores a per-case salt in `pii_salts`.
  - `async def pseudonymize(case_id, identifier, identifier_type) -> str` — deterministic hash: `HMAC(salt, f"{type}:{value}")` → truncated to a human-readable token like `user_a42`.
  - `async def depseudonymize(case_id, token) -> str | None` — reverse lookup (limited to the salt-holder; for break-glass only).
- Document that NER-based stripping of free-text fields is a Phase 3 responsibility — this module handles identifier pseudonymization only.

Deliverables:

- `src/wolfpack/schemas/pii.py`

Acceptance checks:

- pseudonymization is deterministic (same input + salt → same token)
- different salts produce different tokens for the same input
- tokens follow a human-readable format (e.g., `user_a42`, `host_b17`)

#### D4. Add crypto and PII integration tests

Tasks:

- Add `tests/integration/test_crypto_shredding.py`.
- Test: create case → generate DEK → wrap → store → shred → verify DEK row is gone and ledger has the event.
- Test: create PII salt → pseudonymize → verify determinism → verify different salt → different token.
- Add `tests/unit/test_pii.py` for pure pseudonymization logic.

Deliverables:

- `tests/integration/test_crypto_shredding.py`
- `tests/unit/test_pii.py`

Acceptance checks:

- full crypto-shredding flow works end-to-end
- PII pseudonymization is deterministic and salt-dependent
- unit tests pass without database

## 5. Recommended Delivery Sequence

Land the work in this order:

1. Pydantic domain models (Track A1–A3)
2. Schema unit tests (Track A4)
3. Alembic setup and initial migrations (Track B1–B4)
4. Persistence helpers (Track B5)
5. Hash-chain trigger and verification (Track C1–C2)
6. Ledger replay tool (Track C3)
7. KMS abstraction and software KMS (Track D1)
8. DEK lifecycle and shred (Track D2)
9. PII pseudonymization (Track D3)
10. Integration tests (Tracks B6, C4, D4)

## 6. Parallelization Plan

### Safe parallel lanes after Track A

- Lane 1: Postgres migrations (Track B1–B4)
- Lane 2: Hash-chain design work (Track C trigger logic, offline)

### Safe parallel lanes after Track B1 (Alembic is set up)

- Lane 1: Remaining migrations (B2–B4) and persistence (B5)
- Lane 2: KMS abstraction (D1)
- Lane 3: PII pseudonymization (D3) — no database dependency for core logic

### Work that should stay on the critical path

- Pydantic models must land before migrations (migrations depend on the model shape)
- Ledger trigger depends on the `evidence_ledger` table existing (Track B3)
- Crypto-shredding depends on the `crypto_shred_keys` table and KMS abstraction (Track B4 + D1)

## 7. Milestones and Exit Criteria

### Milestone 1: Schema Models Defined

Exit criteria:

- all domain Pydantic models compile and pass unit tests
- LangGraph TypedDict is derived from Pydantic models
- no hand-maintained duplication

### Milestone 2: Database Schema Applied

Exit criteria:

- `alembic upgrade head` creates all tables
- foreign keys and indexes are enforced
- seeded governance fixtures exist

### Milestone 3: Ledger Integrity Proven

Exit criteria:

- hash-chain trigger populates `prev_hash` and `content_hash`
- `verify_chain` detects tampering
- `replay_ledger` returns ordered entries

### Milestone 4: Crypto-Shredding and PII Store Ready

Exit criteria:

- KMS abstraction is pluggable
- software KMS works for dev mode
- DEK lifecycle (generate → wrap → store → shred) is tested
- PII pseudonymization is deterministic and salt-dependent

### Milestone 5: Phase 1 Complete

Exit criteria:

- all integration tests pass
- persistence layer works against real Postgres
- optimistic concurrency is tested
- Phase 2 handoff note exists

## 8. Command-Level Validation Checklist

```bash
uv sync
just lint
just typecheck
just test
alembic upgrade head
alembic downgrade base && alembic upgrade head   # test idempotency
just test-integration
```

All of these should succeed before Phase 1 is marked complete.

## 9. Risks to Watch During Execution

### Pydantic model evolution risk

Models will change as agents are implemented (Phase 2+). Design models for extension: use `Optional` fields for data that may not be available at creation time, and version the model shapes through the migration system.

### KMS complexity risk

The KMS abstraction needs to be thin enough to not become a project in itself. Ship the `SoftwareKMS` for dev, stub the Vault reference, and defer the real Vault integration to Phase 8 release readiness.

### Migration ordering risk

Alembic auto-generates migrations from model changes, but hand-written SQL (triggers, functions) must be carefully ordered. Put all trigger/function migrations after the base table migrations, and test `downgrade` paths.

### Optimistic concurrency edge cases

Flanker and Tracker writing to the same branch simultaneously is the primary contention scenario. Test this explicitly in integration tests before Phase 2 relies on it.

## 10. Definition of Done Mapping

| Definition of done item | Proof artifact |
|---|---|
| Pydantic models are single source of truth | `src/wolfpack/schemas/` models, `graph_state.py` derivation |
| Postgres schema matches models | Alembic migrations, passing `alembic upgrade head` |
| Hash-chain ledger is tamper-evident | Trigger, `verify_chain` SQL function, integration tests |
| Crypto-shredding skeleton works | `crypto/` module, `SoftwareKMS`, integration test |
| PII pseudonymization is deterministic | `pii.py`, unit and integration tests |
| Optimistic concurrency prevents stale writes | persistence helpers, integration test |
| Governance fixtures seeded | `retention_policy` default row, migration |
| Phase 2 handoff note exists | updated `docs/PROJECT_PLAN.md` |

## 11. Suggested PR Slicing

1. `phase1-schemas` — Pydantic models, TypedDict derivation, unit tests
2. `phase1-migrations` — Alembic setup, core and governance migrations
3. `phase1-persistence` — CRUD helpers, optimistic concurrency
4. `phase1-ledger` — Hash-chain trigger, verification, replay tool
5. `phase1-crypto-pii` — KMS abstraction, DEK lifecycle, PII store, integration tests

## 12. Immediate Next Action

The first implementation step should be:

1. create `src/wolfpack/schemas/seed.py` with the `Seed` model
2. create `src/wolfpack/schemas/confidence.py` with the `Confidence` enum
3. create `src/wolfpack/schemas/case_state.py` with `CaseState` and `BranchState`
4. add unit tests for these core models

That establishes the data contracts every other Phase 1 track depends on.