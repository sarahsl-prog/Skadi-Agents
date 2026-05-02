"""Break-glass API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from wolfpack.api.auth import RequireAuth
from wolfpack.processing.breakglass import show_raw
from wolfpack.schemas.persistence import PersistencePool

router = APIRouter()

_pool: PersistencePool | None = None


def _get_pool() -> PersistencePool:
    global _pool  # noqa: PLW0603
    if _pool is None:
        from wolfpack.config.settings import Settings

        settings = Settings()
        _pool = PersistencePool(str(settings.postgres.dsn))
    return _pool


@router.post("/cases/{case_id}/show-raw")
async def show_raw_data(
    case_id: str,
    field: str,
    auth: RequireAuth,  # RequireAuth is the validated token — use as analyst identifier
) -> dict[str, Any]:
    """Rehydrate a pseudonymized token for the current analyst session.

    Every invocation writes to ``breakglass_audit`` before returning.
    """
    pool = _get_pool()
    # The validated API token serves as the analyst identifier for audit.
    analyst_id = auth
    raw = await show_raw(pool, case_id, analyst_id, field)
    if raw is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Token not found or audit write failed",
        )
    return {"case_id": case_id, "field": field, "raw": raw}
