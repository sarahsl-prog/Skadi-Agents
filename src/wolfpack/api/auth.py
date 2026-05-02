"""Simple token-based auth for the Analyst Console API.

V1 uses a static API token loaded from ``WOLFPACK_API_TOKEN``.
Future versions may switch to Postgres-backed tokens or OIDC.
"""

from __future__ import annotations

import hmac
import os
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from wolfpack.config.settings import Settings

_api_key_header = APIKeyHeader(name="X-API-Token", auto_error=False)


async def _verify_token(token: Annotated[str | None, Security(_api_key_header)]) -> str:
    """Validate the incoming API token."""
    settings = Settings()
    expected = os.environ.get("WOLFPACK_API_TOKEN")

    # In dev mode a default token is acceptable; in production the env var
    # MUST be set or authentication fails.
    if expected is None:
        if settings.deployment_mode.value == "dev":
            expected = "dev-token-do-not-use-in-production"
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="WOLFPACK_API_TOKEN environment variable not set",
            )

    if token is None or not hmac.compare_digest(token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API token",
        )
    return token


RequireAuth = Annotated[str, Depends(_verify_token)]
