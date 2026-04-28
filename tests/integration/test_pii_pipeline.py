"""Integration tests for PII pipeline with real Postgres."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
import pytest

from wolfpack.adapters.base import Event
from wolfpack.processing.breakglass import show_raw
from wolfpack.processing.pii_pipeline import PIIPipeline
from wolfpack.schemas.entity import Entity
from wolfpack.schemas.persistence import PersistencePool

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_INTEGRATION") == "1",
    reason="Integration tests disabled (SKIP_INTEGRATION=1)",
)


@pytest.fixture()
async def pii_pool() -> AsyncGenerator[PersistencePool]:
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("pgvector/pgvector:pg16").start() as pg:
        dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")

        import subprocess
        import sys

        sync_dsn = dsn.replace("postgresql://", "postgresql+psycopg2://")
        env = {**os.environ, "DATABASE_URL": sync_dsn}
        for key in list(env.keys()):
            if key.startswith("WOLFPACK_"):
                env.pop(key, None)
        alembic_path = str((Path(sys.executable).parent / "alembic").resolve())
        subprocess.run(  # noqa: S603
            [alembic_path, "upgrade", "head"],
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )

        pool = PersistencePool(dsn, min_size=1, max_size=2)
        await pool.connect()
        yield pool
        await pool.close()


async def _create_case(conn: asyncpg.Connection, case_id: str) -> None:
    await conn.execute(
        "INSERT INTO wolfpack.cases (id, seed, status, version) "
        "VALUES ($1, $2, $3, $4)",
        case_id,
        '{"type": "test", "raw_payload": {}}',
        "new",
        1,
    )


class TestPIIPipelineIntegration:
    """End-to-end PII sanitization with real DB."""

    @pytest.mark.asyncio
    async def test_sanitize_event_pseudonymizes_entities(self, pii_pool: PersistencePool) -> None:
        case_id = str(uuid.uuid4())
        conn = await pii_pool.acquire()
        try:
            await _create_case(conn, case_id)
        finally:
            await pii_pool.release(conn)

        pipeline = PIIPipeline(pii_pool)
        event = Event(
            timestamp=datetime.now(UTC),
            source="syslog",
            raw_payload={"message": "Connection from 10.0.0.1"},
            entities=[Entity(type="ip", value="10.0.0.1")],
            severity="low",
        )
        result = await pipeline.sanitize_events([event], case_id)
        assert len(result) == 1
        assert result[0].entities[0].type == "ip"
        assert result[0].entities[0].value != "10.0.0.1"
        assert result[0].entities[0].value.startswith("ip_")

    @pytest.mark.asyncio
    async def test_breakglass_reverse(self, pii_pool: PersistencePool) -> None:
        case_id = str(uuid.uuid4())
        conn = await pii_pool.acquire()
        try:
            await _create_case(conn, case_id)
        finally:
            await pii_pool.release(conn)

        pipeline = PIIPipeline(pii_pool)
        event = Event(
            timestamp=datetime.now(UTC),
            source="syslog",
            raw_payload={"message": "OK"},
            entities=[Entity(type="user", value="alice@corp.com")],
            severity="info",
        )
        result = await pipeline.sanitize_events([event], case_id)
        token = result[0].entities[0].value

        raw = await show_raw(pii_pool, case_id, "analyst-1", token)
        assert raw == "alice@corp.com"

        # Audit row should exist
        conn = await pii_pool.acquire()
        try:
            row = await conn.fetchrow(
                "SELECT COUNT(*) as cnt FROM wolfpack.breakglass_audit "
                "WHERE case_id = $1 AND analyst_id = $2",
                case_id,
                "analyst-1",
            )
            assert row is not None
            assert row["cnt"] == 1
        finally:
            await pii_pool.release(conn)
