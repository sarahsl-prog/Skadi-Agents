"""Hash-chained evidence ledger helpers."""

from __future__ import annotations

import json
from typing import Any

import asyncpg

from wolfpack.schemas.evidence import EvidenceRef


class LedgerIntegrityError(Exception):
    """Raised when the evidence ledger chain fails verification."""


async def verify_chain(conn: asyncpg.Connection, case_id: str) -> tuple[bool, int | None]:
    """Verify the integrity of a case's evidence ledger chain.

    Calls the Postgres ``wolfpack.verify_chain`` SQL function which
    recomputes every ``content_hash`` and checks ``prev_hash`` linkage.
    """
    row = await conn.fetchrow(
        "SELECT is_valid, broken_at FROM wolfpack.verify_chain($1)",
        case_id,
    )
    if row is None:
        return True, None
    is_valid: bool = row["is_valid"]
    broken_at: int | None = row["broken_at"]
    return is_valid, broken_at


async def replay_ledger(conn: asyncpg.Connection, case_id: str) -> list[EvidenceRef]:
    """Fetch and return a case's *evidence* ledger entries, validating chain integrity.

    The ledger holds heterogeneous rows (``evidence``, ``timeline_event``,
    ``verdict``, ...). Integrity is verified across the whole chain, but only
    rows with ``entry_type = 'evidence'`` are EvidenceRef-shaped, so only those
    are validated and returned here.

    Raises:
        LedgerIntegrityError: If the hash chain is broken or tampered.
    """
    is_valid, broken_at = await verify_chain(conn, case_id)
    if not is_valid:
        raise LedgerIntegrityError(f"Ledger chain broken for case {case_id} at entry {broken_at}")

    rows = await conn.fetch(
        "SELECT content FROM wolfpack.evidence_ledger "
        "WHERE case_id = $1 AND entry_type = 'evidence' ORDER BY seq ASC",
        case_id,
    )
    return [
        EvidenceRef.model_validate(
            json.loads(row["content"]) if isinstance(row["content"], str) else row["content"]
        )
        for row in rows
    ]


async def insert_ledger_entry(
    conn: asyncpg.Connection,
    case_id: str,
    entry_type: str,
    content: dict[str, Any],
    branch_id: str | None = None,
    agent_run_id: str | None = None,
) -> int:
    """Insert a new evidence ledger row.

    The Postgres trigger ``compute_ledger_hash`` automatically computes
    ``content_hash`` and ``prev_hash`` before the row is persisted.

    Returns:
        The generated ``id`` of the new ledger entry.
    """
    row = await conn.fetchrow(
        """
        INSERT INTO wolfpack.evidence_ledger
        (case_id, branch_id, entry_type, content, agent_run_id)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id
        """,
        case_id,
        branch_id,
        entry_type,
        json.dumps(content, default=str),
        agent_run_id,
    )
    if row is None:
        raise RuntimeError("Insert into evidence_ledger did not return an id")
    return int(row["id"])
