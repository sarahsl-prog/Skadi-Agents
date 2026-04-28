"""PII pipeline orchestrator.

Applies pseudonymization to structured identifiers and NER stripping
to free-text fields, logging every step to the evidence ledger.
"""

from __future__ import annotations

from typing import Any

from wolfpack.adapters.base import Event
from wolfpack.processing.ner import NERStripper
from wolfpack.processing.pii import PIICache
from wolfpack.schemas.ledger import insert_ledger_entry
from wolfpack.schemas.persistence import PersistencePool


class PIIPipeline:
    """Orchestrates identifier pseudonymization + free-text NER stripping."""

    def __init__(self, pool: PersistencePool) -> None:
        self._pool = pool
        self._cache = PIICache(pool)
        self._ner = NERStripper()

    async def sanitize_events(
        self,
        events: list[Event],
        case_id: str,
        agent_run_id: str | None = None,
    ) -> list[Event]:
        """Return a new list of events with PII sanitized.

        Pseudonymization is applied to:
        - ``entity.value`` for every entity in ``event.entities``
        - ``event.raw_payload`` string values that look like identifiers

        NER stripping is applied to:
        - Any free-text string fields inside ``event.raw_payload``
        """
        sanitized: list[Event] = []
        for event in events:
            new_entities = []
            for ent in event.entities:
                token = await self._cache.pseudonymize(
                    case_id, ent.value, ent.type
                )
                from wolfpack.schemas.entity import Entity

                new_entities.append(Entity(type=ent.type, value=token))

            new_payload = await self._sanitize_payload(
                case_id, event.raw_payload
            )

            sanitized.append(
                Event(
                    timestamp=event.timestamp,
                    source=event.source,
                    raw_payload=new_payload,
                    entities=new_entities,
                    severity=event.severity,
                    metadata=event.metadata,
                )
            )

            await self._log_step(
                case_id,
                "pii_sanitize",
                {
                    "source": event.source,
                    "entity_count": len(event.entities),
                    "timestamp": event.timestamp.isoformat(),
                },
                agent_run_id,
            )

        return sanitized

    async def _sanitize_payload(
        self, case_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Recursively sanitize dict values — pseudonymize identifiers,
        NER-strip free text."""
        result: dict[str, Any] = {}
        for key, value in payload.items():
            if isinstance(value, str):
                result[key] = await self._sanitize_string(case_id, key, value)
            elif isinstance(value, dict):
                result[key] = await self._sanitize_payload(case_id, value)
            elif isinstance(value, list):
                result[key] = await self._sanitize_list(case_id, value)
            else:
                result[key] = value
        return result

    async def _sanitize_list(
        self, case_id: str, items: list[Any]
    ) -> list[Any]:
        result: list[Any] = []
        for item in items:
            if isinstance(item, str):
                # Heuristic: if the list item looks like an IP/hostname/email,
                # pseudonymize it; otherwise NER-strip it.
                result.append(await self._sanitize_string(case_id, "list_item", item))
            elif isinstance(item, dict):
                result.append(await self._sanitize_payload(case_id, item))
            else:
                result.append(item)
        return result

    async def _sanitize_string(
        self, case_id: str, key: str, value: str
    ) -> str:
        """Apply NER stripping; any tokens produced are then pseudonymized."""
        stripped, mapping = self._ner.strip(value)
        # Pseudonymize the mapped original values so the ledger never
        # stores raw PII.
        for token, original in mapping.items():
            # Guess identifier type from the placeholder name
            id_type = token.strip("<>").split("_")[0].lower()
            if id_type in ("ip", "cidr", "mac", "hostname", "email", "url"):
                replacement = await self._cache.pseudonymize(
                    case_id, original, id_type
                )
                stripped = stripped.replace(token, replacement)
        return stripped

    async def _log_step(
        self,
        case_id: str,
        entry_type: str,
        content: dict[str, Any],
        agent_run_id: str | None = None,
    ) -> None:
        conn = await self._pool.acquire()
        try:
            await insert_ledger_entry(
                conn, case_id, entry_type, content, agent_run_id=agent_run_id
            )
        finally:
            await self._pool.release(conn)
