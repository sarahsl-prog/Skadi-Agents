"""Case management API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from wolfpack.api.auth import RequireAuth
from wolfpack.api.dependencies import get_pool
from wolfpack.schemas.persistence import CasePersistence, PersistencePool

router = APIRouter()


@router.get("/cases")
async def list_cases(
    auth: RequireAuth,
    status_filter: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    pool: PersistencePool = Depends(get_pool),
) -> dict[str, Any]:
    """List cases with optional status filter."""
    conn = await pool.acquire()
    try:
        where = "WHERE 1=1"
        params: list[Any] = []
        if status_filter:
            where += " AND status = $1"
            params.append(status_filter)
        rows = await conn.fetch(
            f"SELECT id, seed, status, version, created_at, updated_at "
            f"FROM wolfpack.cases {where} ORDER BY updated_at DESC LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}",
            *params,
            limit,
            offset,
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
        return {"cases": cases, "limit": limit, "offset": offset}
    finally:
        await pool.release(conn)


@router.get("/cases/{case_id}")
async def get_case(
    case_id: str,
    auth: RequireAuth,
    pool: PersistencePool = Depends(get_pool),
) -> dict[str, Any]:
    """Get full case details including branches, hypotheses, and evidence."""
    persistence = CasePersistence(pool)
    case = await persistence.get_full_case(case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    return {
        "case_id": case.case_id,
        "seed": case.seed.model_dump(),
        "status": case.status,
        "version": case.version,
        "tracker_confidence": case.tracker_confidence,
        "flanker_confidence": case.flanker_confidence,
        "overall_confidence": case.overall_confidence,
        "verdict_decision": case.verdict_decision,
        "review_decision": case.review_decision,
        "branches": [b.model_dump() for b in case.branches],
        "hypotheses": [h.model_dump() for h in case.hypotheses],
        "evidence_refs": [e.model_dump() for e in case.evidence_refs],
        "created_at": case.created_at.isoformat() if case.created_at else None,
        "updated_at": case.updated_at.isoformat() if case.updated_at else None,
    }


@router.get("/cases/{case_id}/timeline")
async def get_case_timeline(
    case_id: str,
    auth: RequireAuth,
    pool: PersistencePool = Depends(get_pool),
) -> dict[str, Any]:
    """Return ordered evidence ledger entries for the case."""
    conn = await pool.acquire()
    try:
        rows = await conn.fetch(
            "SELECT entry_type, content, agent_run_id, created_at "
            "FROM wolfpack.evidence_ledger WHERE case_id = $1 ORDER BY seq ASC",
            case_id,
        )
        events = [
            {
                "entry_type": row["entry_type"],
                "content": row["content"],
                "agent_run_id": str(row["agent_run_id"]) if row["agent_run_id"] else None,
                "timestamp": row["created_at"].isoformat() if row["created_at"] else None,
            }
            for row in rows
        ]
        return {"case_id": case_id, "events": events}
    finally:
        await pool.release(conn)


@router.get("/cases/{case_id}/verdict")
async def get_case_verdict(
    case_id: str,
    auth: RequireAuth,
    pool: PersistencePool = Depends(get_pool),
) -> dict[str, Any]:
    """Return the current verdict packet for the case (if present)."""
    conn = await pool.acquire()
    try:
        row = await conn.fetchrow(
            "SELECT content FROM wolfpack.evidence_ledger "
            "WHERE case_id = $1 AND entry_type = 'verdict' ORDER BY seq DESC LIMIT 1",
            case_id,
        )
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No verdict found")
        return {"case_id": case_id, "verdict": row["content"]}
    finally:
        await pool.release(conn)
