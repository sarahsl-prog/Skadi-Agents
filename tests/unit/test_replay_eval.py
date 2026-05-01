"""Unit tests for replay evaluation harness."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from wolfpack.eval.replay import ReplayHarness, ReplayResult, ReplaySet
from wolfpack.rag.base import RAGDocument


class TestReplaySet:
    """Loading of replay fixture files."""

    def test_load(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(
                {
                    "name": "lateral_movement",
                    "query": "lateral movement via RDP",
                    "expected_case_ids": ["case-42"],
                    "category": "learning_positive",
                    "top_k": 3,
                },
                f,
            )
            path = Path(f.name)
        rs = ReplaySet(path)
        assert rs.name == "lateral_movement"
        assert rs.query == "lateral movement via RDP"
        assert rs.expected_ids == ["case-42"]
        assert rs.category == "learning_positive"
        assert rs.top_k == 3


class TestReplayResult:
    """Metric computation for one replay set result."""

    def test_precision(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(
                {
                    "name": "test",
                    "query": "query",
                    "expected_case_ids": ["a", "b"],
                    "top_k": 3,
                },
                f,
            )
            path = Path(f.name)
        rs = ReplaySet(path)
        # 2 expected, 3 retrieved (a, c, d) => precision 1/3
        retrieved = [
            RAGDocument(id="a", content="A"),
            RAGDocument(id="c", content="C"),
            RAGDocument(id="d", content="D"),
        ]
        result = ReplayResult(rs, retrieved)
        assert result.precision == pytest.approx(1 / 3)
        assert result.recall == pytest.approx(1 / 2)

    def test_perfect_retrieval(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"name": "test", "query": "q", "expected_case_ids": ["a"], "top_k": 1}, f)
            path = Path(f.name)
        rs = ReplaySet(path)
        result = ReplayResult(rs, [RAGDocument(id="a", content="A")])
        assert result.precision == 1.0
        assert result.recall == 1.0
        assert result.ndcg == pytest.approx(1.0)

    def test_retrieval_with_no_expected(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"name": "test", "query": "q", "expected_case_ids": []}, f)
            path = Path(f.name)
        rs = ReplaySet(path)
        result = ReplayResult(rs, [RAGDocument(id="a", content="A")])
        assert result.precision == 0.0
        assert result.recall == 0.0
        assert result.ndcg == 0.0

    def test_ndcg_ranking(self) -> None:
        data = {
            "name": "test",
            "query": "q",
            "expected_case_ids": ["a", "b"],
            "top_k": 3,
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            path = Path(f.name)
        rs = ReplaySet(path)
        # ideal: a, b (dcg = 1/1 + 1/log2(3))
        # actual: b, c, a (dcg = 1/1 + 0 + 1/log2(4))
        retrieved = [
            RAGDocument(id="b", content="B"),
            RAGDocument(id="c", content="C"),
            RAGDocument(id="a", content="A"),
        ]
        result = ReplayResult(rs, retrieved)
        assert 0.0 < result.ndcg < 1.0


class TestReplayHarness:
    """End-to-end replay harness."""

    @pytest.mark.asyncio
    async def test_empty_dir(self) -> None:
        harness = ReplayHarness(pipeline=None, golden_sets_dir=None)
        metrics = await harness.run_all()
        assert metrics["count"] == 0
        assert metrics["replay_precision"] == 0.0

    @pytest.mark.asyncio
    async def test_run_with_mock_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.json"
            path.write_text(
                json.dumps(
                    {
                        "name": "test",
                        "query": "lateral movement",
                        "expected_case_ids": ["case-42"],
                        "category": "general",
                        "top_k": 2,
                    }
                )
            )

            class FakePipeline:
                async def retrieve(self, query: str, top_k: int = 5) -> list[RAGDocument]:
                    return [RAGDocument(id="case-42", content="Lateral movement via RDP.")]

            harness = ReplayHarness(
                pipeline=FakePipeline(),  # type: ignore[arg-type]
                golden_sets_dir=tmpdir,
            )
            metrics = await harness.run_all()
            assert metrics["count"] == 1
            assert metrics["replay_precision"] == 1.0
            assert metrics["replay_recall"] == 1.0
            assert metrics["replay_ndcg"] == 1.0

    def test_log_to_mlflow_graceful_fallback(self) -> None:
        harness = ReplayHarness(pipeline=None)
        # Should not raise
        harness.log_to_mlflow({"replay_precision": 0.5})
