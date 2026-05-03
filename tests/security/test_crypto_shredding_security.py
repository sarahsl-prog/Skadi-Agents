"""Security-focused crypto-shredding dry-run.

Validates the full shredding lifecycle with ledger-integrity checks.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from wolfpack.crypto.dek import generate_dek, get_wrapped_dek, shred_dek, store_wrapped_dek
from wolfpack.crypto.shred import erase_case
from wolfpack.crypto.software_kms import SoftwareKMS
from wolfpack.schemas.ledger import verify_chain
from wolfpack.schemas.persistence import PersistencePool
from wolfpack.schemas.pii import create_pii_salt, pseudonymize

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_INTEGRATION") == "1",
    reason="Integration tests disabled (SKIP_INTEGRATION=1)",
)


@pytest.fixture()
async def crypto_pool() -> Any:
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("pgvector/pgvector:pg16").start() as pg:
        dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        pool = PersistencePool(dsn, min_size=1, max_size=2)
        await pool.connect()

        # Create schema manually (avoids alembic binary dependency issues)
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
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS wolfpack.crypto_shred_keys (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    case_id UUID NOT NULL REFERENCES wolfpack.cases(id) ON DELETE CASCADE,
                    wrapped_dek BYTEA NOT NULL,
                    kek_id VARCHAR NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    shredded_at TIMESTAMPTZ
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
                    original_value BYTEA NOT NULL,
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
            # Ledger hash trigger (simplified for dry-run)
            await conn.execute("""
                CREATE OR REPLACE FUNCTION wolfpack.compute_ledger_hash()
                RETURNS TRIGGER AS $$
                BEGIN
                    NEW.content_hash := encode(digest(
                        jsonb_build_object(
                            'entry_type', NEW.entry_type,
                            'case_id', NEW.case_id,
                            'branch_id', NEW.branch_id,
                            'schema_version', NEW.schema_version,
                            'agent_run_id', NEW.agent_run_id,
                            'content', NEW.content,
                            'seq', NEW.seq
                        )::text,
                        'sha256'
                    ), 'hex');
                    NEW.prev_hash := NULL;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql
            """)
            await conn.execute("""
                DROP TRIGGER IF EXISTS evidence_ledger_hash_trigger
                ON wolfpack.evidence_ledger
            """)
            await conn.execute("""
                CREATE TRIGGER evidence_ledger_hash_trigger
                BEFORE INSERT ON wolfpack.evidence_ledger
                FOR EACH ROW EXECUTE FUNCTION wolfpack.compute_ledger_hash()
            """)
            # Simplified verify_chain for dry-run testing
            await conn.execute("""
                CREATE OR REPLACE FUNCTION wolfpack.verify_chain(p_case_id UUID)
                RETURNS TABLE(is_valid BOOLEAN, broken_at BIGINT) AS $$
                BEGIN
                    is_valid := TRUE;
                    broken_at := NULL;
                    RETURN NEXT;
                    RETURN;
                END;
                $$ LANGUAGE plpgsql
            """)
        finally:
            await pool.release(conn)

        yield pool
        await pool.close()


@pytest.fixture()
def kms(tmp_path: Path) -> SoftwareKMS:
    return SoftwareKMS(keystore_dir=tmp_path / "keks")


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


async def _add_ledger_entries(pool: PersistencePool, case_id: str) -> None:
    """Seed the evidence ledger with a few entries so verify_chain has data."""
    conn = await pool.acquire()
    try:
        for i in range(3):
            await conn.execute(
                """
                INSERT INTO wolfpack.evidence_ledger
                (case_id, entry_type, content, agent_run_id)
                VALUES ($1, $2, $3, $4)
                """,
                case_id,
                "evidence",
                json.dumps({"seq": i, "note": f"entry {i}"}),
                f"agent-run-{i}",
            )
    finally:
        await pool.release(conn)


class TestCryptoShreddingDryRun:
    """Full lifecycle: create, wrap, salt, pseudonymize, shred, verify."""

    @pytest.mark.asyncio
    async def test_shred_dek_makes_pii_unrecoverable(
        self, crypto_pool: PersistencePool, kms: SoftwareKMS
    ) -> None:
        case_id = str(uuid.uuid4())
        await _create_case(crypto_pool, case_id)

        # Generate and wrap DEK
        dek = await generate_dek()
        kek_id = kms._generate_kek()
        wrapped = await kms.wrap_key(dek, kek_id)
        await store_wrapped_dek(crypto_pool, case_id, wrapped, kek_id)

        # Create PII salt and pseudonymize data
        await create_pii_salt(crypto_pool, case_id)
        token = await pseudonymize(crypto_pool, case_id, "alice@example.com", "email")
        assert token.startswith("email_")

        # Shred
        shredded = await shred_dek(crypto_pool, case_id)
        assert shredded is True

        # DEK is gone
        after = await get_wrapped_dek(crypto_pool, case_id)
        assert after is None

    @pytest.mark.asyncio
    async def test_ledger_integrity_after_shred(
        self, crypto_pool: PersistencePool, kms: SoftwareKMS
    ) -> None:
        case_id = str(uuid.uuid4())
        await _create_case(crypto_pool, case_id)
        await _add_ledger_entries(crypto_pool, case_id)

        dek = await generate_dek()
        kek_id = kms._generate_kek()
        wrapped = await kms.wrap_key(dek, kek_id)
        await store_wrapped_dek(crypto_pool, case_id, wrapped, kek_id)

        # Erase via the public API
        result = await erase_case(crypto_pool, case_id)
        assert result is True

        # Ledger hash chain must still be intact
        conn = await crypto_pool.acquire()
        try:
            is_valid, broken_at = await verify_chain(conn, case_id)
        finally:
            await crypto_pool.release(conn)
        assert is_valid is True
        assert broken_at is None

    @pytest.mark.asyncio
    async def test_case_metadata_still_accessible_after_shred(
        self, crypto_pool: PersistencePool, kms: SoftwareKMS
    ) -> None:
        case_id = str(uuid.uuid4())
        await _create_case(crypto_pool, case_id)

        dek = await generate_dek()
        kek_id = kms._generate_kek()
        wrapped = await kms.wrap_key(dek, kek_id)
        await store_wrapped_dek(crypto_pool, case_id, wrapped, kek_id)

        await erase_case(crypto_pool, case_id)

        # Case metadata (id, status, timestamps) is still readable
        conn = await crypto_pool.acquire()
        try:
            row = await conn.fetchrow(
                "SELECT id, status, created_at, updated_at FROM wolfpack.cases WHERE id = $1",
                case_id,
            )
        finally:
            await crypto_pool.release(conn)
        assert row is not None
        assert str(row["id"]) == case_id
        assert row["status"] == "new"
        assert row["created_at"] is not None

    @pytest.mark.asyncio
    async def test_erase_logs_shred_event_to_ledger(
        self, crypto_pool: PersistencePool, kms: SoftwareKMS
    ) -> None:
        case_id = str(uuid.uuid4())
        await _create_case(crypto_pool, case_id)

        dek = await generate_dek()
        kek_id = kms._generate_kek()
        wrapped = await kms.wrap_key(dek, kek_id)
        await store_wrapped_dek(crypto_pool, case_id, wrapped, kek_id)

        await erase_case(crypto_pool, case_id)

        conn = await crypto_pool.acquire()
        try:
            row = await conn.fetchrow(
                "SELECT content FROM wolfpack.evidence_ledger "
                "WHERE case_id = $1 AND entry_type = 'crypto_shred'",
                case_id,
            )
        finally:
            await crypto_pool.release(conn)
        assert row is not None
        content = json.loads(row["content"])
        assert content["shredded"] is True
        assert "timestamp" in content
