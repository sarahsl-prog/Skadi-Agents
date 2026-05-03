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
    # Re-fetch to get the persisted salt (handles race conditions where
    # another concurrent call created the salt first).
    persisted = await get_pii_salt(pool, case_id)
    return persisted if persisted is not None else salt


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

    The token format is ``{identifier_type}_{12_hex_chars}``.
    If no salt exists for *case_id* one is created automatically.
    The original value is encrypted with a per-case DEK derived from the
    salt and stored in ``wolfpack.pii_mappings`` for break-glass reverse
    lookup.
    """
    salt = await get_pii_salt(pool, case_id)
    if salt is None:
        salt = await create_pii_salt(pool, case_id)

    digest = hmac.new(
        salt,
        f"{identifier_type}:{identifier}".encode(),
        hashlib.sha256,
    ).hexdigest()
    token = f"{identifier_type}_{digest[:12]}"

    # Encrypt original_value before storage using AES-256-GCM with a
    # separate derived key (different HMAC context from token derivation).
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    enc_key = hmac.new(salt, b"pii-encryption-v1", hashlib.sha256).digest()
    nonce = secrets.token_bytes(12)  # 96-bit nonce for AES-GCM
    aesgcm = AESGCM(enc_key)
    # AAD: case_id binds ciphertext to this specific case
    encrypted_value = aesgcm.encrypt(nonce, identifier.encode(), case_id.encode())
    # Store as binary: nonce (12 bytes) | ciphertext | tag (16 bytes)
    stored_value = nonce + encrypted_value

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
            stored_value,
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
        # 1. Check token exists before writing audit trail.
        row = await conn.fetchrow(
            "SELECT original_value FROM wolfpack.pii_mappings " "WHERE case_id = $1 AND token = $2",
            case_id,
            token,
        )
        if row is None:
            return None

        # 2. Write audit trail — if this fails, block everything.
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
            raise BreakGlassError("Audit write failed — depseudonymization blocked") from exc

        # 3. Decrypt original_value
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        stored_value = row["original_value"]
        salt = await get_pii_salt(pool, case_id)
        if salt is None:
            raise BreakGlassError("Salt not found for case")
        enc_key = hmac.new(salt, b"pii-encryption-v1", hashlib.sha256).digest()
        nonce = stored_value[:12]
        ciphertext = stored_value[12:]
        aesgcm = AESGCM(enc_key)
        identifier = aesgcm.decrypt(nonce, ciphertext, case_id.encode()).decode()
        return identifier
    finally:
        await pool.release(conn)
