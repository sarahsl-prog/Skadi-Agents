"""Replay evaluation framework.

Measures whether the case-history index improves retrieval quality after
learning ingestion.  Computes standard IR metrics and logs them to MLflow.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from wolfpack.rag.case_history import CaseHistoryPipeline
from wolfpack.rag.base import RAGDocument


class ReplaySet:
    """Single replay fixture — a golden set focused on case-history retrieval."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))

    @property
    def name(self) -> str:
        return str(self.data.get("name", self.path.stem))

    @property
    def query(self) -> str:
        return str(self.data.get("query", ""))

    @property
    def expected_ids(self) -> list[str]:
        return list(self.data.get("expected_case_ids", []))

    @property
    def category(self) -> str:
        return str(self.data.get("category", "general"))

    @property
    def top_k(self) -> int:
        return int(self.data.get("top_k", 5))


class ReplayResult:
    """Result of evaluating one replay set against the case-history index."""

    def __init__(
        self,
        replay_set: ReplaySet,
        retrieved: list[RAGDocument],
    ) -> None:
        self.replay_set = replay_set
        self.retrieved = retrieved

    @property
    def precision(self) -> float:
        expected = set(self.replay_set.expected_ids)
        if not expected:
            return 0.0
        retrieved = set(d.id for d in self.retrieved)
        return len(expected & retrieved) / len(self.retrieved) if self.retrieved else 0.0

    @property
    def recall(self) -> float:
        expected = set(self.replay_set.expected_ids)
        if not expected:
            return 0.0
        retrieved = set(d.id for d in self.retrieved)
        return len(expected & retrieved) / len(expected)

    @property
    def ndcg(self) -> float:
        """Compute NDCG@k for the retrieved list."""
        expected_set = set(self.replay_set.expected_ids)
        if not expected_set:
            return 0.0
        dcg = 0.0
        for i, doc in enumerate(self.retrieved):
            rel = 1.0 if doc.id in expected_set else 0.0
            dcg += rel / math.log2(i + 2)  # rank is i+1, so denominator is log2(i+2)
        # Ideal DCG: all relevant docs at top
        ideal_rels = [1.0] * len(expected_set) + [0.0] * (len(self.retrieved) - len(expected_set))
        ideal_dcg = sum(
            rel / math.log2(i + 2) for i, rel in enumerate(ideal_rels[: len(self.retrieved)])
        )
        if ideal_dcg == 0.0:
            return 0.0
        return dcg / ideal_dcg


class ReplayHarness:
    """Run replay golden sets against the case-history pipeline and log metrics."""

    def __init__(
        self,
        pipeline: CaseHistoryPipeline | None = None,
        golden_sets_dir: Path | str | None = None,
    ) -> None:
        self._pipeline = pipeline
        self._dir = Path(golden_sets_dir) if golden_sets_dir else None
        self._results: list[ReplayResult] = []

    async def run_all(self) -> dict[str, Any]:
        """Run every replay set and return aggregate metrics."""
        self._results = []
        if self._dir is None or self._pipeline is None:
            return self._aggregate()  # empty
        for path in sorted(self._dir.glob("*.json")):
            rs = ReplaySet(path)
            docs = await self._pipeline.retrieve(rs.query, top_k=rs.top_k)
            self._results.append(ReplayResult(rs, docs))

        return self._aggregate()

    def _aggregate(self) -> dict[str, Any]:
        if not self._results:
            return {
                "count": 0,
                "replay_precision": 0.0,
                "replay_recall": 0.0,
                "replay_ndcg": 0.0,
                "learning_delta": 0.0,
                "categories": {},
            }

        count = len(self._results)
        precisions = [r.precision for r in self._results]
        recalls = [r.recall for r in self._results]
        ndcgs = [r.ndcg for r in self._results]

        categories: dict[str, dict[str, float]] = {}
        for r in self._results:
            cat = r.replay_set.category
            if cat not in categories:
                categories[cat] = {"precision": 0.0, "recall": 0.0, "ndcg": 0.0, "count": 0}
            categories[cat]["precision"] += r.precision
            categories[cat]["recall"] += r.recall
            categories[cat]["ndcg"] += r.ndcg
            categories[cat]["count"] += 1

        for cat in categories:
            c = categories[cat]["count"]
            categories[cat]["precision"] /= c
            categories[cat]["recall"] /= c
            categories[cat]["ndcg"] /= c

        return {
            "count": count,
            "replay_precision": sum(precisions) / count,
            "replay_recall": sum(recalls) / count,
            "replay_ndcg": sum(ndcgs) / count,
            "learning_delta": sum(ndcgs) / count,  # alias for aggregate improvement
            "categories": categories,
        }

    def log_to_mlflow(self, metrics: dict[str, Any]) -> None:
        """Log scalar metrics to MLflow, if available."""
        try:
            import mlflow

            scalar = {k: v for k, v in metrics.items() if isinstance(v, (int, float))}
            mlflow.log_metrics(scalar)
            mlflow.log_dict(metrics.get("categories", {}), artifact_file="replay_categories.json")
        except Exception:  # noqa: S110
            pass
