"""Break-glass API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from wolfpack.api.auth import RequireAuth
from wolfpack.api.dependencies import get_pool
from wolfpack.processing.breakglass import show_raw
from wolfpack.schemas.persistence import PersistencePool

router = APIRouter()


@router.post("/cases/{case_id}/show-raw")
async def show_raw_data(
    case_id: str,
    field: str,
    auth: RequireAuth,  # RequireAuth is the validated token — use as analyst identifier
    pool: PersistencePool = Depends(get_pool),
) -> dict[str, Any]:
    """Rehydrate a pseudonymized token for the current analyst session.

    Every invocation writes to ``breakglass_audit`` before returning.
    """
    # The validated API token serves as the analyst identifier for audit.
    analyst_id = auth
    raw = await show_raw(pool, case_id, analyst_id, field)
    if raw is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Token not found or audit write failed",
        )
    return {"case_id": case_id, "field": field, "raw": raw}
