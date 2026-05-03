"""Review action API routes."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from wolfpack.api.auth import RequireAuth
from wolfpack.api.dependencies import get_pool
from wolfpack.schemas.persistence import PersistencePool

router = APIRouter()


@router.get("/review/queue")
async def review_queue(
    auth: RequireAuth,  # noqa: ARG001
    pool: PersistencePool = Depends(get_pool),
) -> dict[str, Any]:
    """Return cases awaiting analyst review."""
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
    conn: Any,
    case_id: str,
    new_status: str,
    entry_type: str,
    content: dict[str, Any],
) -> None:
    """Write a ledger entry and update the case status atomically."""
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


async def _assert_case_in_review(conn: Any, case_id: str) -> None:
    """Raise 409 if the case is not in 'review' status."""
    row = await conn.fetchrow("SELECT status FROM wolfpack.cases WHERE id = $1", case_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    if row["status"] != "review":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Case status is '{row['status']}', expected 'review'",
        )


@router.post("/review/{case_id}/approve")
async def approve_case(
    case_id: str,
    auth: RequireAuth,  # noqa: ARG001
    pool: PersistencePool = Depends(get_pool),
) -> dict[str, Any]:
    """Approve learning for a case (moves to learning queue)."""
    conn = await pool.acquire()
    try:
        await _assert_case_in_review(conn, case_id)
        async with conn.transaction():
            await _write_ledger_and_update(
                conn,
                case_id,
                "approved",
                "review_action",
                {"action": "approve", "review_decision": "approved"},
            )
    finally:
        await pool.release(conn)
    return {"case_id": case_id, "status": "approved"}


@router.post("/review/{case_id}/escalate")
async def escalate_case(
    case_id: str,
    auth: RequireAuth,  # noqa: ARG001
    pool: PersistencePool = Depends(get_pool),
) -> dict[str, Any]:
    """Escalate a case (re-route to Tracker/Flanker)."""
    conn = await pool.acquire()
    try:
        await _assert_case_in_review(conn, case_id)
        async with conn.transaction():
            await _write_ledger_and_update(
                conn,
                case_id,
                "escalation",
                "review_action",
                {"action": "escalate", "review_decision": "escalate"},
            )
    finally:
        await pool.release(conn)
    return {"case_id": case_id, "status": "escalation"}


@router.post("/review/{case_id}/close_benign")
async def close_benign(
    case_id: str,
    auth: RequireAuth,  # noqa: ARG001
    pool: PersistencePool = Depends(get_pool),
) -> dict[str, Any]:
    """Close a case as benign."""
    conn = await pool.acquire()
    try:
        await _assert_case_in_review(conn, case_id)
        async with conn.transaction():
            await _write_ledger_and_update(
                conn,
                case_id,
                "closed",
                "review_action",
                {"action": "close_benign", "review_decision": "close_benign"},
            )
    finally:
        await pool.release(conn)
    return {"case_id": case_id, "status": "closed"}


@router.post("/review/{case_id}/continue_hunt")
async def continue_hunt(
    case_id: str,
    auth: RequireAuth,  # noqa: ARG001
    pool: PersistencePool = Depends(get_pool),
) -> dict[str, Any]:
    """Continue hunting (route back to Alpha Dispatcher)."""
    conn = await pool.acquire()
    try:
        await _assert_case_in_review(conn, case_id)
        async with conn.transaction():
            await _write_ledger_and_update(
                conn,
                case_id,
                "scented",
                "review_action",
                {"action": "continue_hunt", "review_decision": "continue"},
            )
    finally:
        await pool.release(conn)
    return {"case_id": case_id, "status": "scented"}
