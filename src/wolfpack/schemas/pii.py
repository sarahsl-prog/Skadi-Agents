"""PII pseudonymization with strict break-glass auditing."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from wolfpack.schemas.persistence import PersistencePool


class BreakGlassError(Exception):
    """Raised when break-glass audit requirements are not met."""


async def create_pii_salt(pool: PersistencePool, case_id: str) -> bytes:
    """Generate and persist a 32-byte random salt for *case_id*."""
    salt = secrets.token_bytes(32)
    conn = await pool.acquire()
    try:
        await conn.execute(
            """
            INSERT INTO wolfpack.pii_salts (id, case_id, salt)
            VALUES (gen_random_uuid(), $1, $2)
            ON CONFLICT (case_id) DO NOTHING
            """,
            case_id,
            salt,
        )
    finally:
        await pool.release(conn)
    return salt


async def get_pii_salt(pool: PersistencePool, case_id: str) -> bytes | None:
    """Fetch the salt for *case_id*, or ``None`` if not present."""
    conn = await pool.acquire()
    try:
        row = await conn.fetchrow(
            "SELECT salt FROM wolfpack.pii_salts WHERE case_id = $1",
            case_id,
        )
        if row is None:
            return None
        return bytes(row["salt"])
    finally:
        await pool.release(conn)


async def pseudonymize(
    pool: PersistencePool,
    case_id: str,
    identifier: str,
    identifier_type: str,
) -> str:
    """Return a deterministic token for *identifier*.

    The token format is ``{identifier_type}_{6_hex_chars}``.
    If no salt exists for *case_id* one is created automatically.
    The original value is stored in ``wolfpack.pii_mappings`` for break-glass
    reverse lookup.
    """
    salt = await get_pii_salt(pool, case_id)
    if salt is None:
        salt = await create_pii_salt(pool, case_id)

    digest = hmac.new(
        salt,
        f"{identifier_type}:{identifier}".encode(),
        hashlib.sha256,
    ).hexdigest()
    token = f"{identifier_type}_{digest[:6]}"

    conn = await pool.acquire()
    try:
        await conn.execute(
            """
            INSERT INTO wolfpack.pii_mappings (id, case_id, token, original_value, identifier_type)
            VALUES (gen_random_uuid(), $1, $2, $3, $4)
            ON CONFLICT (case_id, token) DO NOTHING
            """,
            case_id,
            token,
            identifier,
            identifier_type,
        )
    finally:
        await pool.release(conn)

    return token


async def depseudonymize(
    pool: PersistencePool,
    case_id: str,
    token: str,
    authorized_by: str,
) -> str | None:
    """Reverse a PII token back to the original value.

    This is a **break-glass** operation.  An audit row is written to
    ``wolfpack.breakglass_audit`` before the value is returned.  If the
    audit write fails for any reason a :class:`BreakGlassError` is raised.

    Args:
        pool: Postgres connection pool.
        case_id: Owning case identifier.
        token: Token produced by :func:`pseudonymize`.
        authorized_by: Analyst identifier for the audit trail.

    Returns:
        The original value, or ``None`` if the token is unknown.

    Raises:
        BreakGlassError: If the audit row cannot be written.
    """
    conn = await pool.acquire()
    try:
        # 1. Write audit trail first — if this fails, block everything.
        try:
            await conn.execute(
                """
                INSERT INTO wolfpack.breakglass_audit
                (id, case_id, analyst_id, field_accessed)
                VALUES (gen_random_uuid(), $1, $2, $3)
                """,
                case_id,
                authorized_by,
                token,
            )
        except Exception as exc:
            raise BreakGlassError(
                "Audit write failed — depseudonymization blocked"
            ) from exc

        # 2. Reverse lookup
        row = await conn.fetchrow(
            "SELECT original_value FROM wolfpack.pii_mappings "
            "WHERE case_id = $1 AND token = $2",
            case_id,
            token,
        )
        if row is None:
            return None
        return str(row["original_value"])
    finally:
        await pool.release(conn)
