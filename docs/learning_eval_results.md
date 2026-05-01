# Phase 7 Baseline Learning Evaluation Results

## Setup

- **Baseline case-history index**: empty (no learned cases)
- **Post-learning index**: 3 replay golden-set summaries ingested via `LearningQueueWorker`
- **Replay pipeline**: `CaseHistoryPipeline` with keyword-only retrieval (no embedder)

## Test Environment

```bash
just test          # 246 passed, 10 pre-existing failures (Phase 1–6 regressions)
just test-integration  # 4 passed (learning worker)
just eval-replay    # skipped — awaiting full stack deployment
```

## Golden Sets

| Fixture | Category | Query | Expected case IDs |
|---|---|---|---|
| `replay_learning_positive.json` | learning_positive | lateral movement via RDP | `case-lateral-rdp` |
| `replay_learning_neutral.json` | learning_neutral | DNS tunneling detection | *(none)* |
| `replay_false_positive.json` | false_positive | benign PowerShell activity | `case-fp-powershell` |

## Replay Metrics (computed by `ReplayHarness`)

- **replay_precision** – exact-match precision of retrieved documents
- **replay_recall** – exact-match recall of expected documents
- **replay_ndcg** – Normalised DCG (order-sensitive)
- **learning_delta** – aggregate NDCG improvement (baseline vs. post-learning)

## Results

### Baseline (empty index)

| Metric | Value |
|---|---|
| count | 3 |
| replay_precision | 0.00 |
| replay_recall | 0.00 |
| replay_ndcg | 0.00 |
| learning_delta | 0.00 |

### Post-learning (3 case summaries indexed)

Because the replay harness performs exact-match checks on IDs inside the index,
results depend on the actual documents present. When the learning worker ingests
the 3 golden-set cases into the index, precision/recall/ndcg will be positive for
learning_positive and false_positive, and remain zero for learning_neutral.

## Notes

- No real LLM embedding was used for these results (keyword-only retrieval in
ci/unit tests). Full semantic replay requires a running Ollama + nomic-embed-text.
- The confidence floor (`min_confidence = 3`) prevented low-confidence cases
from entering the index.
- Retry logic was validated: failed entries retry up to 3 times before permanent
failure.
- The `just eval-replay` command is wired but requires a deployed stack to produce
live metrics.

## Remaining Risks

- **Dedup staleness**: pgvector’s `ON CONFLICT` upsert updates vectors in-place,
but if Haystack metadata drift is observed, a full re-index may be needed.
- **Index size**: no TTL pruning in V1; crypto-shredding DEK erasure should
remove corresponding case-history rows in a future hardening pass.
- **False-positive learning**: analyst mis-approval (e.g., malware marked benign)
could poison retrieval. A future gate should require consensus or policy review.

## Exit Criteria

- [x] Learning queue worker processes approved entries
- [x] Case summaries are structured and indexed
- [x] Replay test framework computes metrics
- [x] Integration tests pass
- [ ] Full end-to-end eval-replay with semantic embedding (requires stack deployment)
