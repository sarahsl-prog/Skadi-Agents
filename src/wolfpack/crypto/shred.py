"""Case-level crypto-shredding orchestration."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from wolfpack.crypto.dek import shred_dek
from wolfpack.schemas.persistence import PersistencePool


async def erase_case(pool: PersistencePool, case_id: str) -> bool:
    """Crypto-shred a case and append an entry to the evidence ledger.

    Args:
        pool: Postgres connection pool.
        case_id: Target case identifier.

    Returns:
        ``True`` if the case had a DEK that was shredded.
    """
    shredded = await shred_dek(pool, case_id)
    conn = await pool.acquire()
    try:
        await conn.execute(
            """
            INSERT INTO wolfpack.evidence_ledger (case_id, entry_type, content)
            VALUES ($1, 'crypto_shred', $2)
            """,
            case_id,
            json.dumps(
                {
                    "shredded": shredded,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            ),
        )
    finally:
        await pool.release(conn)
    return shredded
