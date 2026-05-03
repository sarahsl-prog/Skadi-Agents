"""Data-encryption-key lifecycle helpers."""

from __future__ import annotations

import secrets

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
