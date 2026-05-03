"""Integration tests for replay evaluation and baseline/post-learning comparison."""

from __future__ import annotations

import os
from typing import Any

import asyncpg
import pytest

from wolfpack.eval.replay import ReplayHarness
from wolfpack.rag.base import RAGDocument
from wolfpack.rag.case_history import CaseHistoryPipeline

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_INTEGRATION") == "1",
    reason="Integration tests disabled (SKIP_INTEGRATION=1)",
)


@pytest.fixture()
async def pg_pool() -> Any:
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("pgvector/pgvector:pg16").start() as pg:
        dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)
        conn = await pool.acquire()
        try:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        finally:
            await pool.release(conn)
        yield pool
        await pool.close()


class TestReplayEvaluation:
    """End-to-end baseline vs. post-learning replay evaluation."""

    @pytest.mark.asyncio
    async def test_baseline_vs_post_learning_improvement(self, pg_pool: asyncpg.Pool) -> None:
        pipeline = CaseHistoryPipeline(pg_pool, embedder=None)
        await pipeline.ensure_schema()

        # Seed the index with some "prior learning" case summaries
        learned_cases = [
            RAGDocument(
                id="case-lateral-rdp",
                content=(
                    "Case c-1 started with a ioc seed: 10.0.0.1. "
                    "Investigated across 2 branch(es). "
                    "Closer reasoning: Confirmed lateral movement via RDP."
                ),
                metadata={
                    "verdict": "MALICIOUS",
                    "confidence": 4,
                    "false_positive": False,
                    "seed_type": "ioc",
                },
            ),
            RAGDocument(
                id="case-fp-powershell",
                content=(
                    "Case c-2 started with a alert seed: Dev script triggered. "
                    "Investigated across 1 branch(es). "
                    "Closer reasoning: Benign developer activity."
                ),
                metadata={
                    "verdict": "BENIGN",
                    "confidence": 4,
                    "false_positive": True,
                    "seed_type": "alert",
                },
            ),
        ]
        await pipeline.index(learned_cases)

        # Create a temporary golden-sets directory for the replay
        import json
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            # Learning-positive set — expects the learned lateral-movement case
            Path(tmpdir, "learning_positive.json").write_text(
                json.dumps(
                    {
                        "name": "lateral_movement",
                        "query": "lateral movement via RDP",
                        "expected_case_ids": ["case-lateral-rdp"],
                        "category": "learning_positive",
                        "top_k": 3,
                    }
                )
            )
            # Learning-neutral set — no expected cases exist
            Path(tmpdir, "learning_neutral.json").write_text(
                json.dumps(
                    {
                        "name": "dns_tunnel",
                        "query": "DNS tunneling detection",
                        "expected_case_ids": [],
                        "category": "learning_neutral",
                        "top_k": 3,
                    }
                )
            )
            # False-positive set — expects the learned benign case
            Path(tmpdir, "false_positive.json").write_text(
                json.dumps(
                    {
                        "name": "powershell_fp",
                        "query": "benign PowerShell developer script",
                        "expected_case_ids": ["case-fp-powershell"],
                        "category": "false_positive",
                        "top_k": 3,
                    }
                )
            )

            # --- Baseline: empty index ---
            # Baseline harness is trickier because PGVector doesn't let us easily
            # delete specific rows per-test; instead, we run against a *clean* pipeline
            # via a second table.
            baseline_pipeline = CaseHistoryPipeline(pg_pool, embedder=None)
            baseline_pipeline.TABLE_NAME = "wolfpack_rag_case_history_baseline"
            await baseline_pipeline.ensure_schema()

            baseline_harness = ReplayHarness(
                pipeline=baseline_pipeline,
                golden_sets_dir=tmpdir,
            )
            baseline_metrics = await baseline_harness.run_all()

            # --- Post-learning: index with learned cases ---
            post_harness = ReplayHarness(
                pipeline=pipeline,
                golden_sets_dir=tmpdir,
            )
            post_metrics = await post_harness.run_all()

        # Assertions — learning-positive and false-positive should improve
        assert baseline_metrics["count"] == 3
        assert post_metrics["count"] == 3

        # learning-positive and false_positive categories must improve
        assert (
            post_metrics["replay_ndcg"] >= baseline_metrics["replay_ndcg"]
        ), "post-learning NDCG should be >= baseline"
        assert (
            post_metrics["replay_precision"] >= baseline_metrics["replay_precision"]
        ), "post-learning precision should be >= baseline"

        # learning_positive should show improvement
        post_cats: dict[str, Any] = post_metrics["categories"]
        baseline_cats: dict[str, Any] = baseline_metrics["categories"]
        assert (
            post_cats["learning_positive"]["ndcg"] >= baseline_cats["learning_positive"]["ndcg"]
        ), "learning_positive NDCG should improve"

        # learning_neutral should not degrade (same or better)
        assert (
            post_cats["learning_neutral"]["ndcg"] >= baseline_cats["learning_neutral"]["ndcg"]
        ), "learning_neutral NDCG should not degrade"

        # false_positive should show improvement
        assert (
            post_cats["false_positive"]["ndcg"] >= baseline_cats["false_positive"]["ndcg"]
        ), "false_positive NDCG should improve"

    @pytest.mark.asyncio
    async def test_replay_harness_logs_to_mlflow_gracefully(self, pg_pool: asyncpg.Pool) -> None:
        """MLflow logging must not raise when MLflow is unavailable."""
        pipeline = CaseHistoryPipeline(pg_pool, embedder=None)
        await pipeline.ensure_schema()

        harness = ReplayHarness(pipeline=pipeline, golden_sets_dir=None)
        metrics = await harness.run_all()
        # Should not raise even with no MLflow running
        harness.log_to_mlflow(metrics)
        assert metrics["count"] == 0

    @pytest.mark.asyncio
    async def test_replay_metrics_zero_on_empty_index(self, pg_pool: asyncpg.Pool) -> None:
        pipeline = CaseHistoryPipeline(pg_pool, embedder=None)
        await pipeline.ensure_schema()

        import json
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "empty_query.json").write_text(
                json.dumps(
                    {
                        "name": "empty",
                        "query": "nonexistent query",
                        "expected_case_ids": [],
                        "category": "general",
                        "top_k": 3,
                    }
                )
            )
            harness = ReplayHarness(
                pipeline=pipeline,
                golden_sets_dir=tmpdir,
            )
            metrics = await harness.run_all()
            assert metrics["count"] == 1
            assert metrics["replay_precision"] == 0.0
            assert metrics["replay_recall"] == 0.0
            assert metrics["replay_ndcg"] == 0.0
            assert metrics["learning_delta"] == 0.0
