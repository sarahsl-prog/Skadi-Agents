"""Integration tests for RAG pipelines backed by pgvector."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from typing import Any

import asyncpg
import pytest

from wolfpack.rag.base import PGVectorStore, RAGDocument
from wolfpack.rag.case_history import CaseHistoryPipeline
from wolfpack.rag.threat_intel import ThreatIntelPipeline

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_INTEGRATION") == "1",
    reason="Integration tests disabled (SKIP_INTEGRATION=1)",
)


@pytest.fixture()
async def pg_pool() -> AsyncGenerator[dict[str, Any]]:
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("pgvector/pgvector:pg16").start() as pg:
        dsn = pg.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)

        # Ensure pgvector extension exists
        conn = await pool.acquire()
        try:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        finally:
            await pool.release(conn)

        yield {"pool": pool, "dsn": dsn}
        await pool.close()


class TestPGVectorStore:
    """Direct pgvector storage and retrieval."""

    @pytest.mark.asyncio
    async def test_ensure_schema_creates_table(self, pg_pool: dict[str, Any]) -> None:
        pool = pg_pool["pool"]
        store = PGVectorStore(pool, table_name="test_rag_docs", vector_dim=3)
        await store.ensure_schema()

        conn = await pool.acquire()
        try:
            row = await conn.fetchrow(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'test_rag_docs'
                )
                """
            )
            assert row is not None
            assert row["exists"] is True
        finally:
            await pool.release(conn)

    @pytest.mark.asyncio
    async def test_write_and_keyword_search(self, pg_pool: dict[str, Any]) -> None:
        pool = pg_pool["pool"]
        store = PGVectorStore(pool, table_name="test_rag_docs", vector_dim=3)
        await store.ensure_schema()

        docs = [
            RAGDocument(id="d1", content="lateral movement via RDP"),
            RAGDocument(id="d2", content="phishing email with malicious attachment"),
        ]
        await store.write_documents(docs)

        results = await store.keyword_search("phishing", top_k=5)
        assert len(results) >= 1
        assert any("phishing" in r.content for r in results)

    @pytest.mark.asyncio
    async def test_filter_by_metadata(self, pg_pool: dict[str, Any]) -> None:
        pool = pg_pool["pool"]
        store = PGVectorStore(pool, table_name="test_rag_filter", vector_dim=3)
        await store.ensure_schema()

        docs = [
            RAGDocument(id="f1", content="doc A", metadata={"source": "mitre"}),
            RAGDocument(id="f2", content="doc B", metadata={"source": "cve"}),
        ]
        await store.write_documents(docs)

        results = await store.keyword_search(
            "doc", top_k=5, filters={"source": "mitre"}
        )
        assert len(results) == 1
        assert results[0].id == "f1"


class TestThreatIntelPipeline:
    """Threat-intel hybrid retrieval."""

    @pytest.mark.asyncio
    async def test_index_and_retrieve(self, pg_pool: dict[str, Any]) -> None:
        pool = pg_pool["pool"]
        pipeline = ThreatIntelPipeline(pool, embedder=None)
        await pipeline.ensure_schema()

        docs = [
            RAGDocument(
                id="t1566",
                content="T1566 - Phishing: adversary uses deceptive messages.",
                metadata={"technique": "T1566", "source": "mitre-attack"},
            ),
            RAGDocument(
                id="cve-2024-0001",
                content="CVE-2024-0001: buffer overflow in example service.",
                metadata={"source": "cve"},
            ),
        ]
        await pipeline.index(docs)

        results = await pipeline.retrieve("phishing", top_k=2)
        assert len(results) >= 1
        ids = {r.id for r in results}
        assert "t1566" in ids


class TestCaseHistoryPipeline:
    """Case-history hybrid retrieval."""

    @pytest.mark.asyncio
    async def test_index_and_retrieve(self, pg_pool: dict[str, Any]) -> None:
        pool = pg_pool["pool"]
        pipeline = CaseHistoryPipeline(pool, embedder=None)
        await pipeline.ensure_schema()

        docs = [
            RAGDocument(
                id="case-42",
                content="Case 42: confirmed lateral movement via RDP from 10.0.0.1.",
                metadata={"outcome": "confirmed"},
            ),
            RAGDocument(
                id="case-99",
                content="Case 99: benign PowerShell activity — developer script.",
                metadata={"outcome": "benign"},
            ),
        ]
        await pipeline.index(docs)

        results = await pipeline.retrieve("lateral movement", top_k=2)
        assert len(results) >= 1
        ids = {r.id for r in results}
        assert "case-42" in ids

    @pytest.mark.asyncio
    async def test_filter_by_outcome(self, pg_pool: dict[str, Any]) -> None:
        pool = pg_pool["pool"]
        pipeline = CaseHistoryPipeline(pool, embedder=None)
        await pipeline.ensure_schema()

        docs = [
            RAGDocument(
                id="c1",
                content="Malware infection.",
                metadata={"outcome": "confirmed"},
            ),
            RAGDocument(
                id="c2",
                content="False positive alert.",
                metadata={"outcome": "benign"},
            ),
        ]
        await pipeline.index(docs)

        results = await pipeline.retrieve(
            "alert", top_k=5, filters={"outcome": "benign"}
        )
        assert len(results) == 1
        assert results[0].id == "c2"
