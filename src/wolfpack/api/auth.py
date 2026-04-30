"""Simple token-based auth for the Analyst Console API.

V1 uses a static API token loaded from ``WOLFPACK_API_TOKEN``.
Future versions may switch to Postgres-backed tokens or OIDC.
"""

from __future__ import annotations

import os
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

_api_key_header = APIKeyHeader(name="X-API-Token", auto_error=False)

_DEFAULT_TOKEN = os.environ.get("WOLFPACK_API_TOKEN", "dev-token-do-not-use-in-production")


async def _verify_token(token: Annotated[str | None, Security(_api_key_header)]) -> str:
    """Validate the incoming API token."""
    expected = _DEFAULT_TOKEN
    if token is None or token != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API token",
        )
    return token


RequireAuth = Annotated[str, Depends(_verify_token)]
