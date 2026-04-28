"""Break-glass endpoint for depseudonymization."""

from __future__ import annotations

from wolfpack.processing.pii import PIICache
from wolfpack.schemas.persistence import PersistencePool


async def show_raw(
    pool: PersistencePool,
    case_id: str,
    analyst_id: str,
    field: str,
) -> str | None:
    """Reverse a pseudonymized token back to its raw value.

    Args:
        pool: Postgres connection pool.
        case_id: Owning case identifier.
        analyst_id: Analyst requesting the raw value (logged to audit).
        field: The pseudonymized token to reverse.

    Returns:
        The original value, or ``None`` if the token is unknown.
    """
    cache = PIICache(pool)
    return await cache.depseudonymize(case_id, field, analyst_id)
