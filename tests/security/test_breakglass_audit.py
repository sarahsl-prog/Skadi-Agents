"""Break-glass audit trail validation.

Verifies completeness, accuracy, and access restrictions.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from wolfpack.schemas.persistence import PersistencePool
from wolfpack.schemas.pii import create_pii_salt, depseudonymize, pseudonymize

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_INTEGRATION") == "1",
    reason="Integration tests disabled (SKIP_INTEGRATION=1)",
)


@pytest.fixture()
async def audit_pool() -> Any:
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("pgvector/pgvector:pg16").start() as pg:
        dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        pool = PersistencePool(dsn, min_size=1, max_size=2)
        await pool.connect()

        conn = await pool.acquire()
        try:
            await conn.execute("CREATE SCHEMA IF NOT EXISTS wolfpack")
            await conn.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS wolfpack.cases (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    seed JSONB NOT NULL DEFAULT '{}',
                    status VARCHAR NOT NULL DEFAULT 'new',
                    version INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
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
                CREATE TABLE IF NOT EXISTS wolfpack.pii_mappings (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    case_id UUID NOT NULL REFERENCES wolfpack.cases(id) ON DELETE CASCADE,
                    token VARCHAR NOT NULL,
                    original_value VARCHAR NOT NULL,
                    identifier_type VARCHAR NOT NULL,
                    UNIQUE(case_id, token)
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS wolfpack.breakglass_audit (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    case_id UUID NOT NULL REFERENCES wolfpack.cases(id) ON DELETE CASCADE,
                    analyst_id VARCHAR NOT NULL,
                    field_accessed VARCHAR NOT NULL,
                    accessed_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
        finally:
            await pool.release(conn)

        yield pool
        await pool.close()


async def _create_case(pool: PersistencePool, case_id: str) -> None:
    conn = await pool.acquire()
    try:
        await conn.execute(
            """
            INSERT INTO wolfpack.cases (id, seed, status, version, created_at, updated_at)
            VALUES ($1::uuid, $2, 'new', 1, $3, $3)
            """,
            case_id,
            json.dumps({"type": "ioc", "raw_payload": {"value": "10.0.0.1"}}),
            datetime.now(UTC),
        )
    finally:
        await pool.release(conn)


class TestBreakGlassAudit:
    """End-to-end break-glass audit validation."""

    @pytest.mark.asyncio
    async def test_every_invocation_is_recorded(self, audit_pool: PersistencePool) -> None:
        case_id = "550e8400-e29b-41d4-a716-446655440001"
        await _create_case(audit_pool, case_id)
        await create_pii_salt(audit_pool, case_id)

        fields = [
            ("alice@example.com", "email"),
            ("10.0.0.1", "ip"),
            ("WIN-HOST-01", "host"),
        ]
        tokens: list[str] = []
        for value, ftype in fields:
            token = await pseudonymize(audit_pool, case_id, value, ftype)
            tokens.append(token)

        analysts = ["analyst-A", "analyst-B", "analyst-A"]
        for token, analyst in zip(tokens, analysts, strict=True):
            await depseudonymize(audit_pool, case_id, token, analyst)

        conn = await audit_pool.acquire()
        try:
            rows = await conn.fetch(
                "SELECT analyst_id, field_accessed FROM wolfpack.breakglass_audit "
                "WHERE case_id = $1 ORDER BY accessed_at ASC",
                case_id,
            )
        finally:
            await audit_pool.release(conn)

        assert len(rows) == 3
        assert rows[0]["analyst_id"] == "analyst-A"
        assert rows[1]["analyst_id"] == "analyst-B"
        assert rows[2]["analyst_id"] == "analyst-A"
        # Each row records the token that was accessed
        for row, token in zip(rows, tokens, strict=True):
            assert row["field_accessed"] == token

    @pytest.mark.asyncio
    async def test_depseudonymize_returns_none_for_unknown_token(
        self, audit_pool: PersistencePool
    ) -> None:
        case_id = "550e8400-e29b-41d4-a716-446655440002"
        await _create_case(audit_pool, case_id)

        # Even for unknown tokens, the audit row is still written
        result = await depseudonymize(audit_pool, case_id, "nosuch_token", "analyst-X")
        assert result is None

        conn = await audit_pool.acquire()
        try:
            row = await conn.fetchrow(
                "SELECT analyst_id, field_accessed FROM wolfpack.breakglass_audit "
                "WHERE case_id = $1",
                case_id,
            )
        finally:
            await audit_pool.release(conn)
        assert row is not None
        assert row["analyst_id"] == "analyst-X"
        assert row["field_accessed"] == "nosuch_token"

    @pytest.mark.asyncio
    async def test_no_missing_invocations(self, audit_pool: PersistencePool) -> None:
        """Completeness check: every depseudonymize call leaves an audit row."""
        case_id = "550e8400-e29b-41d4-a716-446655440003"
        await _create_case(audit_pool, case_id)
        await create_pii_salt(audit_pool, case_id)
        token = await pseudonymize(audit_pool, case_id, "sensitive_value", "secret")

        # 5 calls
        for i in range(5):
            await depseudonymize(audit_pool, case_id, token, f"analyst-{i}")

        conn = await audit_pool.acquire()
        try:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM wolfpack.breakglass_audit WHERE case_id = $1",
                case_id,
            )
        finally:
            await audit_pool.release(conn)
        assert count == 5

    @pytest.mark.asyncio
    async def test_audit_records_have_required_fields(
        self, audit_pool: PersistencePool
    ) -> None:
        case_id = "550e8400-e29b-41d4-a716-446655440004"
        await _create_case(audit_pool, case_id)
        await create_pii_salt(audit_pool, case_id)
        token = await pseudonymize(audit_pool, case_id, "bob@example.com", "email")

        await depseudonymize(audit_pool, case_id, token, "analyst-007")

        conn = await audit_pool.acquire()
        try:
            row = await conn.fetchrow(
                "SELECT * FROM wolfpack.breakglass_audit WHERE case_id = $1",
                case_id,
            )
        finally:
            await audit_pool.release(conn)
        assert row is not None
        assert str(row["case_id"]) == case_id
        assert row["analyst_id"] == "analyst-007"
        assert row["field_accessed"] == token
        assert row["accessed_at"] is not None
        # The row has an auto-generated id
        assert row["id"] is not None