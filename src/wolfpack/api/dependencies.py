"""Shared FastAPI dependencies for WolfPack API routes.

Provides a single :class:`PersistencePool` instance via FastAPI DI so
that all routes share the same connection pool instead of creating
multiple singletons.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request

from wolfpack.schemas.persistence import PersistencePool

_pool: PersistencePool | None = None


def get_pool(request: Request) -> PersistencePool:
    """Return the shared persistence pool (lazy init).

    Used as a FastAPI dependency: ``Depends(get_pool)``.
    """
    global _pool  # noqa: PLW0603
    if _pool is None:
        from wolfpack.config.settings import Settings

        settings = Settings()
        _pool = PersistencePool(str(settings.postgres.dsn))
    return _pool
