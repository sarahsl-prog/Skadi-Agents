"""Scribe agent — non-LLM ledger and timeline writer.

Scribe is a structural translator: it receives structured events and
persists them as immutable evidence-ledger rows.  It never calls an LLM.
"""

from __future__ import annotations

from typing import Any

from wolfpack.schemas.agents.scribe import ScribeInput, ScribeOutput
from wolfpack.schemas.ledger import insert_ledger_entry
from wolfpack.schemas.persistence import PersistencePool


class ScribeInterface:
    """Async facade for writing to the evidence ledger and timeline."""

    def __init__(self, pool: PersistencePool) -> None:
        self._pool = pool

    async def write_ledger_entry(
        self,
        case_id: str,
        entry_type: str,
        content: dict[str, Any],
        agent_run_id: str | None = None,
    ) -> int:
        """Insert a row into the evidence ledger.

        Returns:
            The generated ``id`` of the new ledger entry.
        """
        conn = await self._pool.acquire()
        try:
            return await insert_ledger_entry(
                conn,
                case_id,
                entry_type,
                content,
                agent_run_id=agent_run_id,
            )
        finally:
            await self._pool.release(conn)

    async def write_timeline_event(
        self,
        case_id: str,
        event_type: str,
        description: str,
    ) -> int:
        """Append a structured timeline event to the ledger.

        Timeline events are stored as ``entry_type='timeline_event'`` rows
        so that the full audit trail remains in one table.

        Returns:
            The generated ``id`` of the new ledger entry.
        """
        return await self.write_ledger_entry(
            case_id,
            "timeline_event",
            {"event_type": event_type, "description": description},
        )

    async def process(self, input: ScribeInput) -> ScribeOutput:
        """Process a :class:`ScribeInput` and persist it.

        This is the high-level entry-point used by the orchestrator when
        wiring Scribe as a graph node.
        """
        entry_id = await self.write_ledger_entry(
            input.case_id,
            input.event_type,
            input.payload,
            agent_run_id=input.agent_run_id,
        )
        return ScribeOutput(
            ledger_entry_id=str(entry_id),
            summary=f"Wrote {input.event_type} for case {input.case_id}",
        )
