"""Integration tests for the hash-chained evidence ledger."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path

import asyncpg
import pytest

from wolfpack.schemas.ledger import (
    LedgerIntegrityError,
    insert_ledger_entry,
    replay_ledger,
    verify_chain,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_INTEGRATION") == "1",
    reason="Integration tests disabled (SKIP_INTEGRATION=1)",
)


@pytest.fixture()
async def ledger_pool() -> AsyncGenerator[asyncpg.Pool]:
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("pgvector/pgvector:pg16").start() as pg:
        dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)

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

        yield pool
        await pool.close()


@pytest.fixture()
async def ledger_conn(ledger_pool: asyncpg.Pool) -> AsyncGenerator[asyncpg.Connection]:
    conn = await ledger_pool.acquire()
    try:
        yield conn
    finally:
        await ledger_pool.release(conn)


async def _create_case(conn: asyncpg.Connection, case_id: str) -> None:
    await conn.execute(
        "INSERT INTO wolfpack.cases (id, seed, status, version) " "VALUES ($1, $2, $3, $4)",
        case_id,
        '{"type": "test", "raw_payload": {}}',
        "new",
        1,
    )


class TestLedgerChainIntegrity:
    async def test_insert_and_verify_chain(self, ledger_conn: asyncpg.Connection) -> None:
        case_id = str(uuid.uuid4())
        await _create_case(ledger_conn, case_id)

        content = {
            "source_type": "test",
            "source_id": "ev-1",
            "timestamp": "2026-04-27T12:00:00Z",
            "hash": "abcd",
            "metadata": {},
        }
        entry_id1 = await insert_ledger_entry(
            ledger_conn, case_id, "evidence", content, agent_run_id="run-1"
        )
        entry_id2 = await insert_ledger_entry(
            ledger_conn, case_id, "evidence", content, agent_run_id="run-2"
        )

        assert entry_id1 < entry_id2

        is_valid, broken_at = await verify_chain(ledger_conn, case_id)
        assert is_valid is True
        assert broken_at is None

    async def test_tamper_detected(self, ledger_conn: asyncpg.Connection) -> None:
        case_id = str(uuid.uuid4())
        await _create_case(ledger_conn, case_id)

        content = {
            "source_type": "test",
            "source_id": "ev-1",
            "timestamp": "2026-04-27T12:00:00Z",
            "hash": "abcd",
            "metadata": {},
        }
        entry_id = await insert_ledger_entry(
            ledger_conn, case_id, "evidence", content, agent_run_id="run-1"
        )

        # Tamper with the stored hash directly.
        await ledger_conn.execute(
            "UPDATE wolfpack.evidence_ledger SET content_hash = 'deadbeef' WHERE id = $1",
            entry_id,
        )

        is_valid, broken_at = await verify_chain(ledger_conn, case_id)
        assert is_valid is False
        assert broken_at == entry_id

    async def test_concurrent_inserts(self, ledger_pool: asyncpg.Pool) -> None:
        case_id = str(uuid.uuid4())
        conn = await ledger_pool.acquire()
        try:
            await _create_case(conn, case_id)
        finally:
            await ledger_pool.release(conn)

        content = {
            "source_type": "test",
            "source_id": "ev-1",
            "timestamp": "2026-04-27T12:00:00Z",
            "hash": "abcd",
            "metadata": {},
        }

        async def _insert_one(idx: int) -> int:
            c = await ledger_pool.acquire()
            try:
                return await insert_ledger_entry(
                    c, case_id, "evidence", content, agent_run_id=f"run-{idx}"
                )
            finally:
                await ledger_pool.release(c)

        ids = await asyncio.gather(*[_insert_one(i) for i in range(10)])
        assert len(set(ids)) == 10

        # Verify on a fresh connection.
        verify_conn = await ledger_pool.acquire()
        try:
            is_valid, broken_at = await verify_chain(verify_conn, case_id)
            assert is_valid is True
            assert broken_at is None
        finally:
            await ledger_pool.release(verify_conn)

    async def test_replay_ledger_ordered(self, ledger_conn: asyncpg.Connection) -> None:
        case_id = str(uuid.uuid4())
        await _create_case(ledger_conn, case_id)

        contents = []
        for i in range(3):
            content = {
                "source_type": "test",
                "source_id": f"ev-{i}",
                "timestamp": "2026-04-27T12:00:00Z",
                "hash": f"hash-{i}",
                "metadata": {"seq": i},
            }
            contents.append(content)
            await insert_ledger_entry(
                ledger_conn, case_id, "evidence", content, agent_run_id=f"run-{i}"
            )

        refs = await replay_ledger(ledger_conn, case_id)
        assert len(refs) == 3
        assert [r.source_id for r in refs] == ["ev-0", "ev-1", "ev-2"]
        assert [r.metadata["seq"] for r in refs] == [0, 1, 2]

    async def test_replay_ledger_raises_on_tamper(self, ledger_conn: asyncpg.Connection) -> None:
        case_id = str(uuid.uuid4())
        await _create_case(ledger_conn, case_id)

        content = {
            "source_type": "test",
            "source_id": "ev-1",
            "timestamp": "2026-04-27T12:00:00Z",
            "hash": "abcd",
            "metadata": {},
        }
        entry_id = await insert_ledger_entry(
            ledger_conn, case_id, "evidence", content, agent_run_id="run-1"
        )

        await ledger_conn.execute(
            "UPDATE wolfpack.evidence_ledger SET content_hash = 'deadbeef' WHERE id = $1",
            entry_id,
        )

        with pytest.raises(LedgerIntegrityError):
            await replay_ledger(ledger_conn, case_id)
