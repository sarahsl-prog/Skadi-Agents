"""Evaluation harness for Tracker agent golden sets.

Runs fixture cases through the Tracker, computes metrics, and logs
results to MLflow (with graceful fallback if MLflow is unavailable).
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from wolfpack.agents.tracker import TrackerDeps, run_tracker
from wolfpack.schemas.case_state import CaseState
from wolfpack.schemas.confidence import Confidence
from wolfpack.schemas.seed import Seed


class GoldenSet:
    """Single golden-set fixture."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))

    @property
    def name(self) -> str:
        return str(self.data["name"])

    @property
    def seed(self) -> Seed:
        return Seed.model_validate(self.data["seed"])

    @property
    def expected_confidence(self) -> Confidence:
        return Confidence(int(self.data["expected_confidence"]))

    @property
    def expected_hypotheses(self) -> list[dict[str, Any]]:
        return list(self.data.get("expected_hypotheses", []))

    @property
    def expected_evidence(self) -> list[dict[str, Any]]:
        return list(self.data.get("expected_evidence", []))

    def to_case_state(self) -> CaseState:
        return CaseState(
            case_id=f"eval-{self.name}",
            seed=self.seed,
        )


class EvalResult:
    """Result of running a single golden set."""

    def __init__(
        self,
        golden_set: GoldenSet,
        tracker_output: dict[str, Any],
    ) -> None:
        self.golden_set = golden_set
        self.tracker_output = tracker_output

    @property
    def confidence_error(self) -> int:
        """Absolute difference between expected and actual confidence."""
        expected = int(self.golden_set.expected_confidence)
        actual = int(self.tracker_output.get("tracker_confidence", expected))
        return abs(expected - actual)

    @property
    def hypothesis_precision(self) -> float:
        """Proportion of expected hypotheses matched in output."""
        expected = self.golden_set.expected_hypotheses
        actual = self.tracker_output.get("hypotheses", [])
        if not expected:
            return 1.0 if not actual else 0.0
        # Simple string containment match on description
        matched = 0
        for eh in expected:
            desc = eh.get("description", "").lower()
            for ah in actual:
                actual_desc = ah.get("description", "").lower()
                if desc in actual_desc or actual_desc in desc:
                    matched += 1
                    break
        return matched / len(expected)

    @property
    def evidence_recall(self) -> float:
        """Proportion of expected evidence sources found in output."""
        expected = self.golden_set.expected_evidence
        actual = self.tracker_output.get("evidence_refs", [])
        if not expected:
            return 1.0 if not actual else 0.0
        expected_sources = {e.get("source_type", "") for e in expected}
        actual_sources = {a.get("source_type", "") for a in actual}
        if not expected_sources:
            return 1.0
        return len(expected_sources & actual_sources) / len(expected_sources)


class EvalHarness:
    """Run golden sets through Tracker and compute aggregate metrics."""

    def __init__(
        self,
        golden_sets_dir: Path | str,
        tracker_deps: TrackerDeps | None = None,
        model: Any | None = None,
    ) -> None:
        self._dir = Path(golden_sets_dir)
        self._tracker_deps = tracker_deps or TrackerDeps()
        self._model = model
        self._results: list[EvalResult] = []

    async def run_all(self) -> dict[str, Any]:
        """Run every golden set and return aggregate metrics."""
        self._results = []
        for path in sorted(self._dir.glob("*.json")):
            gs = GoldenSet(path)
            state = gs.to_case_state()
            output = await run_tracker(state, deps=self._tracker_deps, model=self._model)
            self._results.append(EvalResult(gs, output))

        return self._aggregate()

    def _aggregate(self) -> dict[str, Any]:
        if not self._results:
            return {
                "count": 0,
                "mean_confidence_error": 0.0,
                "mean_hypothesis_precision": 0.0,
                "mean_evidence_recall": 0.0,
                "confidence_distribution": {c.name: 0 for c in Confidence},
            }

        count = len(self._results)
        confidence_errors = [r.confidence_error for r in self._results]
        precisions = [r.hypothesis_precision for r in self._results]
        recalls = [r.evidence_recall for r in self._results]

        conf_dist: dict[str, int] = {c.name: 0 for c in Confidence}
        for r in self._results:
            raw = r.tracker_output.get("tracker_confidence")
            try:
                if raw is not None:
                    conf = Confidence(int(raw))
                    conf_dist[conf.name] += 1
            except (ValueError, TypeError):
                pass

        return {
            "count": count,
            "mean_confidence_error": sum(confidence_errors) / count,
            "mean_hypothesis_precision": sum(precisions) / count,
            "mean_evidence_recall": sum(recalls) / count,
            "confidence_distribution": conf_dist,
            "rmse_confidence": math.sqrt(sum(e**2 for e in confidence_errors) / count),
        }

    def log_to_mlflow(self, metrics: dict[str, Any]) -> None:
        """Log metrics to MLflow if available."""
        try:
            import mlflow

            mlflow.log_metrics(
                {k: v for k, v in metrics.items() if isinstance(v, (int, float))}
            )
            mlflow.log_dict(
                metrics.get("confidence_distribution", {}),
                artifact_file="confidence_distribution.json",
            )
        except Exception:  # noqa: S110
            # Graceful fallback — MLflow may not be running
            pass
