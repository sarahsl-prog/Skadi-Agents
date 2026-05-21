"""Data-encryption-key lifecycle helpers."""

from __future__ import annotations

import secrets

from wolfpack.crypto.kms import KMSInterface
from wolfpack.schemas.persistence import PersistencePool


async def generate_dek() -> bytes:
    """Generate a new 256-bit data encryption key."""
    return secrets.token_bytes(32)


async def store_wrapped_dek(
    pool: PersistencePool,
    case_id: str,
    wrapped_dek: bytes,
    kek_id: str,
) -> None:
    """Persist a wrapped DEK for *case_id*."""
    conn = await pool.acquire()
    try:
        await conn.execute(
            """
            INSERT INTO wolfpack.crypto_shred_keys (id, case_id, wrapped_dek, kek_id)
            VALUES (gen_random_uuid(), $1, $2, $3)
            """,
            case_id,
            wrapped_dek,
            kek_id,
        )
    finally:
        await pool.release(conn)


async def get_wrapped_dek(
    pool: PersistencePool,
    case_id: str,
) -> tuple[bytes, str] | None:
    """Fetch the active (non-shredded) wrapped DEK for *case_id*.

    Returns ``(wrapped_dek, kek_id)`` or ``None`` if no active key exists.
    """
    conn = await pool.acquire()
    try:
        row = await conn.fetchrow(
            "SELECT wrapped_dek, kek_id FROM wolfpack.crypto_shred_keys "
            "WHERE case_id = $1 AND shredded_at IS NULL "
            "ORDER BY created_at DESC LIMIT 1",
            case_id,
        )
        if row is None:
            return None
        return row["wrapped_dek"], row["kek_id"]
    finally:
        await pool.release(conn)


async def rewrap_deks_for_kek(
    pool: PersistencePool,
    kms: KMSInterface,
    old_kek_id: str,
) -> tuple[str, int]:
    """Rotate the KEK and re-wrap every active DEK currently wrapped by it.

    The KMS abstraction has no database access, so the re-wrap is orchestrated
    here: a new KEK is generated, then each active (non-shredded) DEK wrapped
    by *old_kek_id* is unwrapped with the old KEK and re-wrapped with the new
    one in a single transaction. After this completes, no active DEK is
    recoverable with the old KEK — so the old KEK can be retired/destroyed via
    the operator's KMS procedure (Vault/HSM key deletion; for SoftwareKMS,
    remove the old key file). Shredded rows are intentionally left untouched.

    Returns ``(new_kek_id, number_of_deks_rewrapped)``.
    """
    new_kek_id = await kms.rotate_kek(old_kek_id)
    conn = await pool.acquire()
    try:
        async with conn.transaction():
            rows = await conn.fetch(
                "SELECT id, wrapped_dek FROM wolfpack.crypto_shred_keys "
                "WHERE kek_id = $1 AND shredded_at IS NULL",
                old_kek_id,
            )
            count = 0
            for row in rows:
                dek = await kms.unwrap_key(row["wrapped_dek"], old_kek_id)
                rewrapped = await kms.wrap_key(dek, new_kek_id)
                await conn.execute(
                    "UPDATE wolfpack.crypto_shred_keys "
                    "SET wrapped_dek = $1, kek_id = $2 WHERE id = $3",
                    rewrapped,
                    new_kek_id,
                    row["id"],
                )
                count += 1
    finally:
        await pool.release(conn)
    return new_kek_id, count


async def shred_dek(pool: PersistencePool, case_id: str) -> bool:
    """Mark the DEK for *case_id* as shredded.

    Returns ``True`` if a row was updated, ``False`` if no active key existed.
    """
    conn = await pool.acquire()
    try:
        result = await conn.execute(
            "UPDATE wolfpack.crypto_shred_keys SET shredded_at = NOW() "
            "WHERE case_id = $1 AND shredded_at IS NULL",
            case_id,
        )
        # asyncpg returns e.g. "UPDATE 1"
        return str(result).split()[1] != "0"
    finally:
        await pool.release(conn)
