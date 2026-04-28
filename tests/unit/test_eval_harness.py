"""Unit tests for evaluation harness."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from wolfpack.eval.harness import EvalHarness, EvalResult, GoldenSet
from wolfpack.schemas.confidence import Confidence
from wolfpack.schemas.seed import Seed


class TestGoldenSet:
    """Loading and parsing of fixture files."""

    def test_load_simple_ioc(self) -> None:
        path = Path("tests/eval/golden_sets/simple_ioc.json")
        gs = GoldenSet(path)
        assert gs.name == "simple_ioc"
        assert gs.expected_confidence == Confidence.STRONG
        assert len(gs.expected_hypotheses) == 1
        state = gs.to_case_state()
        assert state.case_id == "eval-simple_ioc"
        assert state.seed.type == "ioc"

    def test_to_case_state(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(
                {
                    "name": "test",
                    "seed": {
                        "type": "ioc",
                        "raw_payload": {"entities": []},
                        "metadata": {},
                    },
                    "expected_confidence": 3,
                },
                f,
            )
            path = Path(f.name)
        gs = GoldenSet(path)
        state = gs.to_case_state()
        assert state.seed == Seed(type="ioc", raw_payload={"entities": []})


class TestEvalResult:
    """Metric computation for a single result."""

    def test_confidence_error(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(
                {
                    "name": "test",
                    "seed": {"type": "ioc", "raw_payload": {}, "metadata": {}},
                    "expected_confidence": 4,
                },
                f,
            )
            path = Path(f.name)
        gs = GoldenSet(path)
        output = {"tracker_confidence": 2}
        result = EvalResult(gs, output)
        assert result.confidence_error == 2

    def test_hypothesis_precision_full_match(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(
                {
                    "name": "test",
                    "seed": {"type": "ioc", "raw_payload": {}, "metadata": {}},
                    "expected_confidence": 3,
                    "expected_hypotheses": [
                        {"description": "Malware detected on host"}
                    ],
                },
                f,
            )
            path = Path(f.name)
        gs = GoldenSet(path)
        output = {"hypotheses": [{"description": "Malware detected on host"}]}
        result = EvalResult(gs, output)
        assert result.hypothesis_precision == 1.0

    def test_hypothesis_precision_partial(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(
                {
                    "name": "test",
                    "seed": {"type": "ioc", "raw_payload": {}, "metadata": {}},
                    "expected_confidence": 3,
                    "expected_hypotheses": [
                        {"description": "Malware detected"},
                        {"description": "Lateral movement observed"},
                    ],
                },
                f,
            )
            path = Path(f.name)
        gs = GoldenSet(path)
        output = {"hypotheses": [{"description": "Malware detected on host"}]}
        result = EvalResult(gs, output)
        assert result.hypothesis_precision == 0.5

    def test_evidence_recall(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(
                {
                    "name": "test",
                    "seed": {"type": "ioc", "raw_payload": {}, "metadata": {}},
                    "expected_confidence": 3,
                    "expected_evidence": [
                        {"source_type": "firewall"},
                        {"source_type": "syslog"},
                    ],
                },
                f,
            )
            path = Path(f.name)
        gs = GoldenSet(path)
        output = {
            "evidence_refs": [
                {"source_type": "firewall"},
                {"source_type": "crowdstrike"},
            ]
        }
        result = EvalResult(gs, output)
        assert result.evidence_recall == 0.5


class TestEvalHarness:
    """End-to-end harness with mocked Tracker."""

    @pytest.mark.asyncio
    async def test_run_all_produces_metrics(self, monkeypatch: pytest.MonkeyPatch) -> None:
        call_count = 0

        async def _mock_run_tracker(
            state: Any, deps: Any = None, model: Any = None
        ) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return {
                "tracker_confidence": 3,
                "hypotheses": [{"description": "Test hypothesis"}],
                "evidence_refs": [{"source_type": "firewall"}],
            }

        monkeypatch.setattr(
            "wolfpack.eval.harness.run_tracker", _mock_run_tracker
        )
        harness = EvalHarness("tests/eval/golden_sets/")
        metrics = await harness.run_all()
        assert metrics["count"] >= 5
        assert metrics["mean_confidence_error"] >= 0.0
        assert 0.0 <= metrics["mean_hypothesis_precision"] <= 1.0
        assert 0.0 <= metrics["mean_evidence_recall"] <= 1.0
        assert metrics["rmse_confidence"] >= 0.0
        assert "confidence_distribution" in metrics
        assert call_count >= 5

    def test_log_to_mlflow_graceful_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Monkeypatch mlflow to avoid network hangs in CI
        monkeypatch.setattr("mlflow.log_metrics", lambda **kwargs: None)
        monkeypatch.setattr("mlflow.log_dict", lambda **kwargs: None)
        harness = EvalHarness("tests/eval/golden_sets/")
        harness.log_to_mlflow({"mean_confidence_error": 0.5})
