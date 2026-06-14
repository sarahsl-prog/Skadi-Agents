"""Integration tests for the learning queue worker and case-history ingestion."""

from __future__ import annotations

import json
from typing import Any

import asyncpg
import pytest

from wolfpack.learning.worker import LearningQueueWorker
from wolfpack.rag.case_history import CaseHistoryPipeline

pytestmark = pytest.mark.skipif(
    __import__("os").environ.get("SKIP_INTEGRATION") == "1",
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
            await conn.execute("CREATE SCHEMA IF NOT EXISTS wolfpack")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS wolfpack.learning_queue (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    case_id UUID NOT NULL,
                    verdict VARCHAR,
                    approved_by VARCHAR,
                    approved_at TIMESTAMPTZ,
                    ingested_at TIMESTAMPTZ,
                    retry_count INTEGER DEFAULT 0,
                    last_error TEXT,
                    status VARCHAR DEFAULT 'pending'
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS wolfpack.cases (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    seed JSONB NOT NULL,
                    status VARCHAR NOT NULL DEFAULT 'new',
                    version INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    verdict_decision VARCHAR,
                    overall_confidence INTEGER
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS wolfpack.branches (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    case_id UUID NOT NULL REFERENCES wolfpack.cases(id) ON DELETE CASCADE,
                    parent_branch_id UUID,
                    hypothesis JSONB NOT NULL,
                    depth INTEGER NOT NULL DEFAULT 0,
                    status VARCHAR NOT NULL DEFAULT 'open',
                    version INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS wolfpack.hypotheses (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    branch_id UUID NOT NULL REFERENCES wolfpack.branches(id) ON DELETE CASCADE,
                    description TEXT NOT NULL,
                    confidence INTEGER NOT NULL,
                    status VARCHAR NOT NULL DEFAULT 'open',
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS wolfpack.pii_salts (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    case_id UUID NOT NULL UNIQUE REFERENCES wolfpack.cases(id) ON DELETE CASCADE,
                    salt BYTEA NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS wolfpack.evidence_ledger (
                    id BIGSERIAL PRIMARY KEY,
                    case_id UUID NOT NULL,
                    branch_id UUID,
                    entry_type VARCHAR NOT NULL,
                    content JSONB NOT NULL,
                    prev_hash VARCHAR,
                    content_hash VARCHAR,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    agent_run_id VARCHAR,
                    schema_version INTEGER NOT NULL DEFAULT 1,
                    seq BIGINT
                )
            """)
        finally:
            await pool.release(conn)
        yield pool
        await pool.close()


class TestLearningQueueWorker:
    """End-to-end learning worker tests."""

    @pytest.mark.asyncio
    async def test_process_approved_entry(self, pg_pool: asyncpg.Pool) -> None:
        pipeline = CaseHistoryPipeline(pg_pool, embedder=None)
        await pipeline.ensure_schema()
        worker = LearningQueueWorker(
            pool=pg_pool,
            pipeline=pipeline,
            schedule_minutes=5,
            batch_size=10,
            retry_limit=3,
        )

        # Seed a case
        case_id = await pg_pool.fetchval(
            """
            INSERT INTO wolfpack.cases (seed, status, verdict_decision, overall_confidence)
            VALUES ($1, 'closed', $2, $3)
            RETURNING id
            """,
            json.dumps({"type": "ioc", "raw_payload": {"value": "10.0.0.1"}, "metadata": {}}),
            "BENIGN",
            3,
        )
        # Seed a branch
        hyp = {
            "hypothesis": {"description": "test", "confidence": 2},
            "created_by": "alpha",
            "depth": 0,
        }
        await pg_pool.execute(
            """
            INSERT INTO wolfpack.branches (case_id, hypothesis, depth, status)
            VALUES ($1, $2, 0, 'closed')
            """,
            case_id,
            json.dumps(hyp),
        )

        # Create a learning queue entry
        entry_id = await pg_pool.fetchval(
            """
            INSERT INTO wolfpack.learning_queue (case_id, approved_by, approved_at)
            VALUES ($1, 'analyst-1', NOW())
            RETURNING id
            """,
            case_id,
        )
        assert entry_id is not None

        # Run worker
        await worker.run_tick()

        # Verify ingested_at is set and status is ingested
        row = await pg_pool.fetchrow(
            (
                "SELECT ingested_at, retry_count, status, last_error "
                "FROM wolfpack.learning_queue WHERE id = $1"
            ),
            entry_id,
        )
        assert row is not None
        assert row["ingested_at"] is not None
        assert row["retry_count"] == 0
        assert row["status"] == "ingested"

        # Verify case-history index contains the summary
        results = await pipeline.retrieve("10.0.0.1", top_k=5)
        case_id_str = str(case_id)
        assert any(case_id_str in r.id for r in results)

    @pytest.mark.asyncio
    async def test_skip_unapproved(self, pg_pool: asyncpg.Pool) -> None:
        worker = LearningQueueWorker(
            pool=pg_pool,
            pipeline=None,
            batch_size=10,
            retry_limit=3,
        )
        case_id = await pg_pool.fetchval(
            "INSERT INTO wolfpack.cases (seed) VALUES ($1) RETURNING id",
            json.dumps({"type": "ioc", "raw_payload": {}, "metadata": {}}),
        )
        entry_id = await pg_pool.fetchval(
            "INSERT INTO wolfpack.learning_queue (case_id) VALUES ($1) RETURNING id",
            case_id,
        )
        await worker.run_tick()
        row = await pg_pool.fetchrow(
            "SELECT ingested_at, status FROM wolfpack.learning_queue WHERE id = $1", entry_id
        )
        assert row is not None
        assert row["ingested_at"] is None
        assert row["status"] in (None, "pending")

    @pytest.mark.asyncio
    async def test_retry_and_fail(self, pg_pool: asyncpg.Pool) -> None:
        # Case missing so worker will error
        worker = LearningQueueWorker(
            pool=pg_pool,
            pipeline=None,
            retry_limit=2,
        )
        from uuid import uuid4

        case_id = uuid4()
        entry_id = await pg_pool.fetchval(
            """
            INSERT INTO wolfpack.learning_queue (case_id, approved_by, approved_at, retry_count)
            VALUES ($1, 'a1', NOW(), 0)
            RETURNING id
            """,
            case_id,
        )
        # Run the worker retry_limit times; the last run should mark the entry failed.
        for _ in range(2):
            await worker.run_tick()
        row = await pg_pool.fetchrow(
            (
                "SELECT retry_count, last_error, status, ingested_at "
                "FROM wolfpack.learning_queue WHERE id = $1"
            ),
            entry_id,
        )
        assert row is not None
        assert row["retry_count"] == 2
        assert row["last_error"] is not None
        assert row["status"] == "failed"
        assert row["ingested_at"] is None

    @pytest.mark.asyncio
    async def test_batch_does_not_block_on_failure(self, pg_pool: asyncpg.Pool) -> None:
        pipeline = CaseHistoryPipeline(pg_pool, embedder=None)
        worker = LearningQueueWorker(pool=pg_pool, pipeline=pipeline, batch_size=10, retry_limit=3)

        # Valid approved case
        case_id_1 = await pg_pool.fetchval(
            """
            INSERT INTO wolfpack.cases (seed, status, verdict_decision, overall_confidence)
            VALUES ($1, 'closed', 'BENIGN', 3)
            RETURNING id
            """,
            json.dumps({"type": "ioc", "raw_payload": {"value": "1.1.1.1"}, "metadata": {}}),
        )
        hyp2 = {
            "hypothesis": {"description": "h", "confidence": 2},
            "created_by": "alpha",
            "depth": 0,
        }
        await pg_pool.execute(
            """
            INSERT INTO wolfpack.branches (case_id, hypothesis, depth, status)
            VALUES ($1, $2, 0, 'closed')
            """,
            case_id_1,
            json.dumps(hyp2),
        )

        # Invalid entry (case missing)
        from uuid import uuid4

        bad_case = uuid4()

        for cid in (case_id_1, bad_case):
            await pg_pool.execute(
                """
                INSERT INTO wolfpack.learning_queue (case_id, approved_by, approved_at)
                VALUES ($1, 'a1', NOW())
                """,
                cid,
            )

        await worker.run_tick()

        # The valid case should be ingested
        row = await pg_pool.fetchrow(
            ("SELECT ingested_at FROM wolfpack.learning_queue" " WHERE case_id = $1"),
            str(case_id_1),
        )
        assert row is not None
        assert row["ingested_at"] is not None

        # The invalid one should have retry_count > 0
        row2 = await pg_pool.fetchrow(
            ("SELECT retry_count, last_error" " FROM wolfpack.learning_queue WHERE case_id = $1"),
            str(bad_case),
        )
        assert row2 is not None
        assert row2["retry_count"] >= 1
