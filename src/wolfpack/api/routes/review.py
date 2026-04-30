"""Review action API routes."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from wolfpack.api.auth import RequireAuth
from wolfpack.schemas.persistence import CasePersistence, PersistencePool

router = APIRouter()

_pool: PersistencePool | None = None


def _get_pool() -> PersistencePool:
    global _pool  # noqa: PLW0603
    if _pool is None:
        from wolfpack.config.settings import Settings

        settings = Settings()
        _pool = PersistencePool(str(settings.postgres.dsn))
    return _pool


@router.get("/review/queue")
async def review_queue(auth: RequireAuth) -> dict[str, Any]:  # noqa: ARG001
    """Return cases awaiting analyst review."""
    pool = _get_pool()
    conn = await pool.acquire()
    try:
        rows = await conn.fetch(
            "SELECT id, seed, status, version, created_at, updated_at "
            "FROM wolfpack.cases WHERE status = 'review' ORDER BY updated_at DESC"
        )
        cases = [
            {
                "case_id": str(row["id"]),
                "status": row["status"],
                "version": row["version"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            }
            for row in rows
        ]
        return {"cases": cases}
    finally:
        await pool.release(conn)


async def _write_ledger_and_update(
    case_id: str,
    new_status: str,
    entry_type: str,
    content: dict[str, Any],
) -> None:
    """Write a ledger entry and update the case status optimistically."""
    pool = _get_pool()
    conn = await pool.acquire()
    try:
        await conn.execute(
            """
            INSERT INTO wolfpack.evidence_ledger
            (case_id, entry_type, content, created_at)
            VALUES ($1, $2, $3, NOW())
            """,
            case_id,
            entry_type,
            json.dumps({**content, "timestamp": datetime.now(UTC).isoformat()}),
        )
        await conn.execute(
            "UPDATE wolfpack.cases SET status = $1, updated_at = NOW() WHERE id = $2",
            new_status,
            case_id,
        )
    finally:
        await pool.release(conn)


@router.post("/review/{case_id}/approve")
async def approve_case(
    case_id: str,
    auth: RequireAuth,  # noqa: ARG001
) -> dict[str, Any]:
    """Approve learning for a case (moves to learning queue)."""
    await _write_ledger_and_update(
        case_id,
        "approved",
        "review_action",
        {"action": "approve", "review_decision": "approved"},
    )
    return {"case_id": case_id, "status": "approved"}


@router.post("/review/{case_id}/escalate")
async def escalate_case(
    case_id: str,
    auth: RequireAuth,  # noqa: ARG001
) -> dict[str, Any]:
    """Escalate a case (re-route to Tracker/Flanker)."""
    await _write_ledger_and_update(
        case_id,
        "escalation",
        "review_action",
        {"action": "escalate", "review_decision": "escalate"},
    )
    return {"case_id": case_id, "status": "escalation"}


@router.post("/review/{case_id}/close_benign")
async def close_benign(
    case_id: str,
    auth: RequireAuth,  # noqa: ARG001
) -> dict[str, Any]:
    """Close a case as benign."""
    await _write_ledger_and_update(
        case_id,
        "closed",
        "review_action",
        {"action": "close_benign", "review_decision": "close_benign"},
    )
    return {"case_id": case_id, "status": "closed"}


@router.post("/review/{case_id}/continue_hunt")
async def continue_hunt(
    case_id: str,
    auth: RequireAuth,  # noqa: ARG001
) -> dict[str, Any]:
    """Continue hunting (route back to Alpha Dispatcher)."""
    await _write_ledger_and_update(
        case_id,
        "scented",
        "review_action",
        {"action": "continue_hunt", "review_decision": "continue"},
    )
    return {"case_id": case_id, "status": "scented"}
