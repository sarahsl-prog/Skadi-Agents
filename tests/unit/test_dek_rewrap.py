"""Unit tests for KEK rotation with DEK re-wrap (crypto/dek.py)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from wolfpack.crypto.dek import generate_dek, rewrap_deks_for_kek
from wolfpack.crypto.software_kms import SoftwareKMS
from wolfpack.schemas.persistence import PersistencePool


class _FakeTxn:
    """Stand-in async context manager for ``conn.transaction()``."""

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_exc: object) -> bool:
        return False


@pytest.fixture()
def mock_pool() -> Any:
    pool = MagicMock(spec=PersistencePool)
    pool.acquire = AsyncMock()
    pool.release = AsyncMock()
    return pool


async def test_rewrap_rotates_and_rewraps_active_dek(tmp_path: Path, mock_pool: Any) -> None:
    kms = SoftwareKMS(keystore_dir=tmp_path)
    old_kek_id = kms._generate_kek()
    dek = await generate_dek()
    wrapped_old = await kms.wrap_key(dek, old_kek_id)

    conn = AsyncMock()
    conn.transaction = MagicMock(return_value=_FakeTxn())
    conn.fetch.return_value = [{"id": "row-1", "wrapped_dek": wrapped_old}]
    mock_pool.acquire.return_value = conn

    new_kek_id, count = await rewrap_deks_for_kek(mock_pool, kms, old_kek_id)

    assert count == 1
    assert new_kek_id != old_kek_id

    # The UPDATE re-wrapped the DEK under the new KEK.
    update_args = conn.execute.await_args.args
    rewrapped = update_args[1]
    assert update_args[2] == new_kek_id
    # New KEK unwraps to the original DEK...
    assert await kms.unwrap_key(rewrapped, new_kek_id) == dek
    # ...and the old KEK can no longer unwrap the re-wrapped blob.
    with pytest.raises(ValueError):
        await kms.unwrap_key(rewrapped, old_kek_id)


async def test_rewrap_no_active_deks_returns_zero(tmp_path: Path, mock_pool: Any) -> None:
    kms = SoftwareKMS(keystore_dir=tmp_path)
    old_kek_id = kms._generate_kek()

    conn = AsyncMock()
    conn.transaction = MagicMock(return_value=_FakeTxn())
    conn.fetch.return_value = []
    mock_pool.acquire.return_value = conn

    new_kek_id, count = await rewrap_deks_for_kek(mock_pool, kms, old_kek_id)

    assert count == 0
    assert new_kek_id != old_kek_id
    conn.execute.assert_not_awaited()
