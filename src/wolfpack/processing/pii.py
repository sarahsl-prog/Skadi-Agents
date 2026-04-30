"""PII cache wrapper around deterministic pseudonymization."""

from __future__ import annotations

from wolfpack.schemas.persistence import PersistencePool
from wolfpack.schemas.pii import depseudonymize, pseudonymize


class PIICache:
    """In-memory cache for per-case pseudonymization tokens.

    Avoids repeated DB hits when the same identifier is seen
    multiple times during a single pipeline run.
    """

    def __init__(self, pool: PersistencePool) -> None:
        self._pool = pool
        self._cache: dict[str, dict[str, str]] = {}

    async def pseudonymize(
        self, case_id: str, identifier: str, identifier_type: str
    ) -> str:
        key = f"{case_id}:{identifier_type}:{identifier}"
        case_cache = self._cache.setdefault(case_id, {})
        if key not in case_cache:
            case_cache[key] = await pseudonymize(
                self._pool, case_id, identifier, identifier_type
            )
        return case_cache[key]

    async def depseudonymize(
        self, case_id: str, token: str, authorized_by: str
    ) -> str | None:
        return await depseudonymize(self._pool, case_id, token, authorized_by)

    def clear(self, case_id: str | None = None) -> None:
        if case_id is None:
            self._cache.clear()
        else:
            self._cache.pop(case_id, None)
