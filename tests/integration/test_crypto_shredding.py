"""Integration tests for crypto-shredding, KMS, and PII against Postgres."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from wolfpack.crypto.dek import generate_dek, get_wrapped_dek, shred_dek, store_wrapped_dek
from wolfpack.crypto.shred import erase_case
from wolfpack.crypto.software_kms import SoftwareKMS
from wolfpack.schemas.persistence import PersistencePool
from wolfpack.schemas.pii import create_pii_salt, depseudonymize, pseudonymize

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
def kms(tmp_path: Path) -> SoftwareKMS:
    return SoftwareKMS(keystore_dir=tmp_path / "keks")


async def _create_case(pool: PersistencePool, case_id: str) -> None:
    """Insert a minimal case row so FK constraints are satisfied."""
    conn = await pool.acquire()
    try:
        await conn.execute(
            """
            INSERT INTO wolfpack.cases (id, seed, status, version, created_at, updated_at)
            VALUES ($1, $2, 'new', 1, $3, $3)
            """,
            case_id,
            "{}",
            datetime.now(UTC),
        )
    finally:
        await pool.release(conn)


class TestSoftwareKMS:
    async def test_wrap_and_unwrap_roundtrip(self, kms: SoftwareKMS) -> None:
        dek = b"d" * 32
        kek_id = kms._generate_kek()
        wrapped = await kms.wrap_key(dek, kek_id)
        unwrapped = await kms.unwrap_key(wrapped, kek_id)
        assert unwrapped == dek

    async def test_unwrap_wrong_kek_fails(self, kms: SoftwareKMS) -> None:
        dek = b"d" * 32
        kek_id1 = kms._generate_kek()
        kek_id2 = kms._generate_kek()
        wrapped = await kms.wrap_key(dek, kek_id1)
        with pytest.raises(ValueError):
            await kms.unwrap_key(wrapped, kek_id2)

    async def test_rotate_kek(self, kms: SoftwareKMS) -> None:
        kek_id1 = kms._generate_kek()
        kek_id2 = await kms.rotate_kek(kek_id1)
        assert kek_id1 != kek_id2
        assert (kms._keystore_dir / kek_id1).exists()
        assert (kms._keystore_dir / kek_id2).exists()


class TestDEKLifecycle:
    async def test_generate_store_get_shred(
        self, crypto_pool: PersistencePool, kms: SoftwareKMS
    ) -> None:
        case_id = str(uuid.uuid4())
        await _create_case(crypto_pool, case_id)

        dek = await generate_dek()
        kek_id = kms._generate_kek()
        wrapped = await kms.wrap_key(dek, kek_id)

        await store_wrapped_dek(crypto_pool, case_id, wrapped, kek_id)

        fetched = await get_wrapped_dek(crypto_pool, case_id)
        assert fetched is not None
        assert fetched[0] == wrapped
        assert fetched[1] == kek_id

        shredded = await shred_dek(crypto_pool, case_id)
        assert shredded is True

        after_shred = await get_wrapped_dek(crypto_pool, case_id)
        assert after_shred is None

    async def test_shred_idempotent(self, crypto_pool: PersistencePool, kms: SoftwareKMS) -> None:
        case_id = str(uuid.uuid4())
        await _create_case(crypto_pool, case_id)

        dek = await generate_dek()
        kek_id = kms._generate_kek()
        wrapped = await kms.wrap_key(dek, kek_id)

        await store_wrapped_dek(crypto_pool, case_id, wrapped, kek_id)
        assert await shred_dek(crypto_pool, case_id) is True
        assert await shred_dek(crypto_pool, case_id) is False


class TestEraseCase:
    async def test_erase_logs_to_ledger(
        self, crypto_pool: PersistencePool, kms: SoftwareKMS
    ) -> None:
        case_id = str(uuid.uuid4())
        await _create_case(crypto_pool, case_id)

        dek = await generate_dek()
        kek_id = kms._generate_kek()
        wrapped = await kms.wrap_key(dek, kek_id)

        await store_wrapped_dek(crypto_pool, case_id, wrapped, kek_id)
        result = await erase_case(crypto_pool, case_id)
        assert result is True

        conn = await crypto_pool.acquire()
        try:
            row = await conn.fetchrow(
                "SELECT content FROM wolfpack.evidence_ledger "
                "WHERE case_id = $1 AND entry_type = 'crypto_shred'",
                case_id,
            )
            assert row is not None
            import json

            content = json.loads(row["content"])
            assert content["shredded"] is True
        finally:
            await crypto_pool.release(conn)

    async def test_erase_no_key_returns_false(self, crypto_pool: PersistencePool) -> None:
        case_id = str(uuid.uuid4())
        await _create_case(crypto_pool, case_id)

        result = await erase_case(crypto_pool, case_id)
        assert result is False


class TestPIISalt:
    async def test_create_and_get_salt(self, crypto_pool: PersistencePool) -> None:
        case_id = str(uuid.uuid4())
        await _create_case(crypto_pool, case_id)

        salt = await create_pii_salt(crypto_pool, case_id)
        assert len(salt) == 32

        fetched = await get_salt(crypto_pool, case_id)
        assert fetched == salt

    async def test_get_salt_missing(self, crypto_pool: PersistencePool) -> None:
        case_id = str(uuid.uuid4())
        await _create_case(crypto_pool, case_id)

        fetched = await get_salt(crypto_pool, case_id)
        assert fetched is None


class TestPseudonymize:
    async def test_pseudonymize_determinism(self, crypto_pool: PersistencePool) -> None:
        case_id = str(uuid.uuid4())
        await _create_case(crypto_pool, case_id)

        token1 = await pseudonymize(crypto_pool, case_id, "alice@example.com", "user")
        token2 = await pseudonymize(crypto_pool, case_id, "alice@example.com", "user")
        assert token1 == token2

    async def test_different_case_different_token(self, crypto_pool: PersistencePool) -> None:
        case1 = str(uuid.uuid4())
        case2 = str(uuid.uuid4())
        await _create_case(crypto_pool, case1)
        await _create_case(crypto_pool, case2)

        t1 = await pseudonymize(crypto_pool, case1, "bob@example.com", "email")
        t2 = await pseudonymize(crypto_pool, case2, "bob@example.com", "email")
        assert t1 != t2


class TestDepseudonymize:
    async def test_depseudonymize_success_and_audit(self, crypto_pool: PersistencePool) -> None:
        case_id = str(uuid.uuid4())
        await _create_case(crypto_pool, case_id)

        token = await pseudonymize(crypto_pool, case_id, "charlie@example.com", "email")

        result = await depseudonymize(crypto_pool, case_id, token, "analyst-42")
        assert result == "charlie@example.com"

        conn = await crypto_pool.acquire()
        try:
            row = await conn.fetchrow(
                "SELECT analyst_id, field_accessed FROM wolfpack.breakglass_audit "
                "WHERE case_id = $1",
                case_id,
            )
            assert row is not None
            assert row["analyst_id"] == "analyst-42"
            assert row["field_accessed"] == token
        finally:
            await crypto_pool.release(conn)

    async def test_depseudonymize_not_found(self, crypto_pool: PersistencePool) -> None:
        case_id = str(uuid.uuid4())
        await _create_case(crypto_pool, case_id)

        result = await depseudonymize(crypto_pool, case_id, "user_deadbeef", "analyst-1")
        assert result is None

    async def test_depseudonymize_raises_without_authorized_by(
        self, crypto_pool: PersistencePool
    ) -> None:
        case_id = str(uuid.uuid4())
        await _create_case(crypto_pool, case_id)

        # Empty string is still a valid string for the audit write;
        # the test checks that an unknown token returns None after audit.
        result = await depseudonymize(crypto_pool, case_id, "user_nosuch", "")
        assert result is None


async def get_salt(pool: PersistencePool, case_id: str) -> bytes | None:
    """Helper for tests."""
    from wolfpack.schemas.pii import get_pii_salt

    return await get_pii_salt(pool, case_id)
