# Phase 7 Implementation Playbook — Learning Loop

This document turns the Phase 7 plan from [`PROJECT_PLAN.md`](./PROJECT_PLAN.md) into an execution-ready implementation plan.

## 0. Outstanding Design Questions

| # | Question | Decision needed by | Default if unresolved | Notes |
|---|----------|--------------------|-----------------------|-------|
| D1 | **Learning ingestion format** — should approved entries be ingested as raw case summaries or structured feature vectors? | Start of Track A | Structured case summaries (human-readable + machine-indexable) — preserve the narrative for semantic retrieval while extracting structured fields (ATT&CK techniques, verdict, confidence, entities) for filtering | Raw summaries are easier to produce but harder to filter. Structured feature vectors are efficient but lose narrative context. Structured case summaries are the middle ground: they preserve the narrative for Haystack's semantic search while providing structured metadata for filtering. |
| D2 | **Re-ingestion trigger** — should approved entries be indexed immediately (synchronous) or via a batch worker (asynchronous)? | Start of Track A | Asynchronous batch worker (processes approved entries every N minutes) | Synchronous ingestion blocks the analyst's approval action and risks latency spikes. A batch worker is simpler, more resilient, and allows for dedup and quality checks before indexing. |
| D3 | **Replay evaluation cadence** — should replay tests run on every learning ingestion, nightly, or on-demand? | Start of Track B | Nightly + on-demand (via `just eval-replay`) | Running on every ingestion is too expensive. Nightly catches regressions. On-demand allows manual validation after significant learning events. |
| D4 | **Learning confidence floor** — should there be a minimum confidence threshold below which approved cases are not ingested into the case-history index? The Risks section flags this as a concern but it is not a formal decision. Options: no floor (ingest everything approved), `Confidence >= 2` (weak or above), or `Confidence >= 3` (plausible or above). | Before Track A1 (learning queue processor) | `Confidence >= 3` (plausible or above), configurable via `LearningConfig.min_confidence` | A low-confidence case approved by an analyst may still represent a high-quality learning signal (e.g., a confirmed false positive at Confidence.WEAK is still useful for future FP detection). The floor should be configurable so it can be lowered for false-positive-detection use cases. Default of 3 is conservative and safe. |
| D5 | **Case-history index archival strategy** — as the index grows, entries older than the retention policy period may need to be pruned. Haystack's pgvector store does not have built-in TTL. Options: (a) no pruning in V1 (let it grow until retention period is reached and crypto-shredding removes PII), (b) hard delete index entries when the retention period expires, (c) archive old entries to a cold pgvector collection. | Before Track A3 (Haystack ingestion wiring) | No pruning in V1 — document as a known limitation. When crypto-shredding erases a case's DEK, add a step to remove the corresponding case-history index entries. Archival strategy to be designed in V1.5. | Pruning and archival add complexity that is not needed for the Phase 7 learning loop. The crypto-shredding integration (DEK erasure → index entry removal) is the correct hook point, but implementing it fully belongs in a post-V1 hardening pass. |

## Status

| Track | Status | Key files | Tests |
|-------|--------|-----------|-------|
| A2 | Done | `src/wolfpack/learning/summary.py` | `tests/unit/test_learning_summary.py` (13 passed) |
| A1 | Done | `src/wolfpack/learning/worker.py` | `tests/integration/test_learning_worker.py` (4 passed) |
| A3 | Done | `src/wolfpack/rag/case_history.py` | See integration tests |
| A4 | Done | `src/wolfpack/config/settings.py`, `justfile` | See integration tests |
| A5 | Done | `tests/integration/test_learning_worker.py` | 4 passed |
| B1 | Done | `src/wolfpack/eval/replay.py` | `tests/unit/test_replay_eval.py` (8 passed) |
| B2 | Done | `tests/eval/golden_sets/replay_*.json` | See integration tests |
| B3 | Done | `docs/learning_eval_results.md` | See integration tests |
| B4 | Done | `tests/integration/test_replay_eval_integration.py` | 3 passed |

**All Phase 7 new tests: 28 passed.**

## 1. Current Baseline

The repository has (from Phases 0–6):

- Full LangGraph orchestration with all agents and review flow
- Analyst Console with verdict review, break-glass, and timeout display
- `learning_queue` table in Postgres (created in Phase 1 but unused until now)
- Hash-chained evidence ledger with `verify_chain()` and `replay_ledger()`
- Case-history RAG pipeline (from Phase 3, seeded with synthetic data)
- Evaluation harness with golden-set hunts and MLflow tracking
- Full OTel instrumentation and MLflow dashboards
- Alerting on operational signals

The repository does **not** yet have:

- Learning queue worker that moves approved entries into the case-history index
- Replay tests that validate learned lessons improve retrieval
- Any mechanism to close the learning loop

## 2. Phase Objective

Close the learning loop:

- Learning queue worker: approved entries → Haystack ingestion for case-history index
- Structured case summaries from approved cases
- Replay tests: prior cases with learned lessons produce improved similar-case retrieval
- Evaluation metrics showing the learning loop's impact on case-history retrieval quality

No new agents, adapters, or UI features should land during this phase.

## 3. Execution Strategy

Two implementation tracks:

1. Learning queue worker and case-history ingestion
2. Replay evaluation and learning validation

The critical path is:

1. implement the learning queue worker
2. format approved cases as structured summaries
3. ingest into the case-history RAG pipeline
4. build replay tests
5. run evaluation and measure improvement

## 4. Work Breakdown Structure

### Track A: Learning Queue Worker and Case-History Ingestion

Purpose: move approved analyst decisions into the case-history knowledge base.

#### A1. Implement learning queue processor

Tasks:

- Create `src/wolfpack/learning/worker.py`.
- Implement `LearningQueueWorker`:
  - Runs on a configurable schedule (default: every 5 minutes).
  - Queries the `learning_queue` table for entries with `approved_by IS NOT NULL AND ingested_at IS NULL`.
  - For each approved entry, fetches the full case state from Postgres.
  - Formats the case as a structured summary (see A2).
  - Ingests the summary into the Haystack case-history pipeline.
  - Updates `learning_queue.ingested_at` with the current timestamp.
  - Logs each ingestion to the evidence ledger.
- Implement error handling: if ingestion fails for an entry, skip it and log the error. Do not block the entire batch.

Deliverables:

- `src/wolfpack/learning/worker.py`

Acceptance checks:

- worker processes approved entries from the learning queue
- entries are ingested into the case-history index
- `ingested_at` is updated after successful ingestion
- failed entries are skipped without blocking the batch
- ingestion events are logged to the evidence ledger

#### A2. Implement structured case summary format

Tasks:

- Create `src/wolfpack/learning/summary.py`.
- Implement `format_case_summary(case_state: CaseState, verdict: VerdictPacket, evidence: list[EvidenceRef]) -> CaseSummary`:
  - `CaseSummary` is a Pydantic model with:
    - `case_id: UUID`
    - `seed_type: str` — type of seed that started the case
    - `seed_summary: str` — human-readable summary of the original seed
    - `verdict: DecisionType` — final decision
    - `confidence: Confidence` — final confidence
    - `attack_techniques: list[str]` — ATT&CK technique IDs referenced
    - `entities: list[EntitySummary]` — key entities involved (pseudonymized)
    - `branches: int` — number of branches investigated
    - `duration_hours: float` — time from case creation to closure
    - `narrative: str` — human-readable case narrative (for semantic retrieval)
    - `key_findings: list[str]` — bullet-point list of key findings
    - `false_positive: bool` — whether the case was closed as benign
  - The narrative field is the primary target for semantic retrieval.
  - Structured fields are indexed for filtering (by verdict, ATT&CK technique, entity type, etc.).

Deliverables:

- `src/wolfpack/learning/summary.py`

Acceptance checks:

- `format_case_summary()` produces a valid `CaseSummary` from case state
- narrative field is human-readable
- structured fields are populated from case state and verdict
- ATT&CK techniques are extracted from evidence refs

#### A3. Wire summary ingestion into Haystack

Tasks:

- Update `src/wolfpack/rag/case_history.py`:
  - Add an `ingest_case_summary(summary: CaseSummary)` method.
  - Index the narrative field for semantic search.
  - Index structured fields as Haystack metadata for filtering.
  - Dedup: if a case summary with the same `case_id` already exists, update it rather than creating a duplicate.
- Wire the `LearningQueueWorker` to call `ingest_case_summary()` after formatting.

Deliverables:

- updated `src/wolfpack/rag/case_history.py`

Acceptance checks:

- case summaries are indexed for semantic search
- structured fields are filterable
- duplicate summaries update rather than create duplicates
- ingestion updates `ingested_at` in the learning queue

#### A4. Implement batch scheduling and error handling

Tasks:

- Add `LearningConfig` to `Settings`:
  - `learning_schedule_minutes: int = 5`
  - `learning_batch_size: int = 50`
  - `learning_retry_delay_minutes: int = 15`
- Update the worker to use these settings.
- Implement retry logic: failed entries are retried on the next batch run (up to 3 retries, then logged as permanently failed).
- Add a `just learning-worker` command to start the worker manually (for testing).
- Add the learning worker to the Docker Compose stack (optional, as a background service).

Deliverables:

- `src/wolfpack/config/settings.py` update
- `justfile` update

Acceptance checks:

- worker runs on the configured schedule
- batch size is respected
- failed entries are retried up to 3 times
- permanently failed entries are logged

#### A5. Add learning worker integration tests

Tasks:

- Add `tests/integration/test_learning_worker.py`.
- Test: approve a case entry → worker processes it → summary appears in case-history index.
- Test: worker skips entries that are not approved.
- Test: worker retries failed entries.
- Test: worker does not block on individual entry failures.

Deliverables:

- `tests/integration/test_learning_worker.py`

Acceptance checks:

- approved entries are ingested into case-history
- unapproved entries are skipped
- failed entries are retried
- batch processing is resilient

### Track B: Replay Evaluation and Learning Validation

Purpose: prove that learned lessons improve retrieval quality.

#### B1. Implement replay test framework

Tasks:

- Create `src/wolfpack/eval/replay.py`.
- Implement `ReplayTest`:
  - Takes a golden-set hunt from `tests/eval/golden_sets/`.
  - Runs the Tracker against the case-history index (with and without learned cases).
  - Measures retrieval quality: similarity of retrieved cases to the expected ground truth.
  - Logs metrics to MLflow: `replay_precision`, `replay_recall`, `replay_ndcg`, `learning_delta` (improvement from learning).
- Create `just eval-replay` command.

Deliverables:

- `src/wolfpack/eval/replay.py`
- `justfile` update

Acceptance checks:

- replay test runs against the case-history index
- metrics are computed and logged to MLflow
- `just eval-replay` works

#### B2. Create replay golden sets

Tasks:

- Add replay-specific golden sets to `tests/eval/golden_sets/`:
  - Cases where similar prior cases exist (expect improved retrieval after learning).
  - Cases where no similar prior cases exist (expect no degradation after learning).
  - Cases where false positives were identified (expect the learning loop to improve false-positive detection).
- Each golden set includes: seed, expected similar cases, expected retrieval quality metrics.

Deliverables:

- replay golden-set fixtures

Acceptance checks:

- golden sets cover learning-positive, learning-neutral, and false-positive scenarios
- each golden set has expected retrieval quality metrics

#### B3. Run baseline and post-learning evaluations

Tasks:

- Run the evaluation harness (Phase 3) without any learned cases in the case-history index → baseline metrics.
- Ingest a batch of approved cases into the case-history index.
- Run the evaluation harness again → post-learning metrics.
- Compare baseline vs. post-learning metrics:
  - `replay_precision` improvement
  - `replay_recall` improvement
  - `replay_ndcg` improvement
  - `learning_delta` (aggregate improvement)
- Document results in `docs/learning_eval_results.md`.

Deliverables:

- baseline and post-learning evaluation results
- `docs/learning_eval_results.md`

Acceptance checks:

- post-learning metrics show improvement over baseline
- results are documented and reproducible
- `learning_delta` is positive for learning-positive scenarios

#### B4. Add replay evaluation tests

Tasks:

- Add `tests/integration/test_replay_eval.py`.
- Test: replay test framework computes metrics correctly.
- Test: learning-positive scenarios show improvement.
- Test: learning-neutral scenarios do not degrade.

Deliverables:

- `tests/integration/test_replay_eval.py`

Acceptance checks:

- replay test framework works end-to-end
- learning-positive scenarios show improvement
- learning-neutral scenarios do not degrade

## 5. Recommended Delivery Sequence

1. Structured case summary format (A2)
2. Learning queue processor (A1)
3. Case-history ingestion update (A3)
4. Batch scheduling and error handling (A4)
5. Replay test framework (B1)
6. Replay golden sets (B2)
7. Learning worker integration tests (A5)
8. Baseline and post-learning evaluations (B3)
9. Replay evaluation tests (B4)

## 6. Parallelization Plan

### Safe parallel lanes after A2

- Lane 1: Learning queue processor (A1)
- Lane 2: Replay test framework (B1)

### Safe parallel lanes after A3

- Lane 1: Batch scheduling (A4)
- Lane 2: Replay golden sets (B2)

### Work that should stay on the critical path

- Structured summary format must land before ingestion
- Learning queue worker must land before replay tests
- Baseline evaluation must run before post-learning evaluation

## 7. Milestones and Exit Criteria

### Milestone 1: Learning Queue Worker Operational

Exit criteria:

- worker processes approved entries on schedule
- case summaries are ingested into case-history
- error handling and retry logic work

### Milestone 2: Replay Evaluation Proven

Exit criteria:

- replay test framework computes retrieval quality metrics
- post-learning metrics show improvement over baseline
- results are documented

### Milestone 3: Phase 7 Complete

Exit criteria:

- all integration tests pass
- learning loop is closed (approve → ingest → improved retrieval)
- evaluation results are documented

## 8. Command-Level Validation Checklist

```bash
uv sync
just lint
just typecheck
just test
just test-integration
just eval-replay
```

All of these should succeed before Phase 7 is marked complete.

## 9. Risks to Watch During Execution

### Learning quality risk

Ingesting low-quality case summaries (e.g., incomplete narratives, missing ATT&CK techniques) can degrade retrieval quality. Implement a quality check: require minimum narrative length and at least one key finding before ingestion.

### Case-history index size risk

As more cases are ingested, the case-history index grows. Monitor index size and query latency. If latency exceeds acceptable bounds, implement index rotation or archival (cold cases older than the retention policy).

### Replay test cost risk

Running replay tests against a large case-history index can be expensive (token cost for embedding and retrieval). Start with a small golden set and scale up incrementally. Use `just eval-replay` for manual runs, not CI.

### False-positive learning risk

If a case is incorrectly approved (e.g., a benign case incorrectly marked as malicious), the learning loop will ingest it and potentially degrade future retrieval. Implement a "confidence floor" — only ingest cases with `Confidence >= 3` (plausible or above).

### Dedup staleness risk

Updating an existing case summary (when a case is re-approved or updated) must update the vector embedding. Haystack's indexing may not update in-place efficiently. Test dedup thoroughly and consider a full re-index if staleness is observed.

## 10. Definition of Done Mapping

| Definition of done item | Proof artifact |
|---|---|
| Learning queue worker processes approved entries | `worker.py`, integration test |
| Case summaries are structured and indexed | `summary.py`, `CaseSummary` model |
| Case-history ingestion works with dedup | updated `case_history.py`, integration test |
| Replay test framework computes metrics | `replay.py`, unit test |
| Post-learning metrics show improvement | evaluation results, `learning_eval_results.md` |
| Batch processing is resilient | error handling, retry logic, integration test |

## 11. Suggested PR Slicing

1. `phase7-learning-worker` — Summary format, queue processor, ingestion update, batch scheduling
2. `phase7-replay-eval` — Replay test framework, golden sets, baseline/post-learning evaluations
3. `phase7-integration` — Integration tests, evaluation results documentation

## 12. Immediate Next Action

The first implementation step should be:

1. define the `CaseSummary` Pydantic model in `src/wolfpack/learning/summary.py`
2. implement `format_case_summary()` that converts case state + verdict into a structured summary
3. implement the `LearningQueueWorker` that processes approved entries

That establishes the data format and processing pipeline the rest of the phase depends on.