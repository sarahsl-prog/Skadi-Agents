"""Unit tests for PIICache caching and the break-glass show_raw helper."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from wolfpack.processing import pii as pii_module
from wolfpack.processing.breakglass import show_raw
from wolfpack.processing.pii import PIICache


@pytest.fixture()
def pool() -> Any:
    return MagicMock()


async def test_pseudonymize_caches_repeated_identifier(pool: Any, monkeypatch: Any) -> None:
    calls: list[tuple[str, str, str]] = []

    async def fake_pseudo(_pool: Any, case_id: str, ident: str, itype: str) -> str:
        calls.append((case_id, ident, itype))
        return f"{itype}_abc123456789"

    monkeypatch.setattr(pii_module, "pseudonymize", fake_pseudo)
    cache = PIICache(pool)

    t1 = await cache.pseudonymize("c1", "1.2.3.4", "ip")
    t2 = await cache.pseudonymize("c1", "1.2.3.4", "ip")

    assert t1 == t2
    assert len(calls) == 1  # second lookup served from cache


async def test_pseudonymize_distinct_identifiers_not_cached_together(
    pool: Any, monkeypatch: Any
) -> None:
    calls: list[str] = []

    async def fake_pseudo(_pool: Any, _case_id: str, ident: str, itype: str) -> str:
        calls.append(ident)
        return f"{itype}_{len(calls)}"

    monkeypatch.setattr(pii_module, "pseudonymize", fake_pseudo)
    cache = PIICache(pool)

    await cache.pseudonymize("c1", "1.2.3.4", "ip")
    await cache.pseudonymize("c1", "5.6.7.8", "ip")

    assert len(calls) == 2


async def test_clear_forces_refetch(pool: Any, monkeypatch: Any) -> None:
    calls: list[str] = []

    async def fake_pseudo(_pool: Any, _c: str, ident: str, _t: str) -> str:
        calls.append(ident)
        return "ip_x"

    monkeypatch.setattr(pii_module, "pseudonymize", fake_pseudo)
    cache = PIICache(pool)

    await cache.pseudonymize("c1", "1.2.3.4", "ip")
    cache.clear("c1")
    await cache.pseudonymize("c1", "1.2.3.4", "ip")

    assert len(calls) == 2


async def test_show_raw_delegates_to_depseudonymize(pool: Any, monkeypatch: Any) -> None:
    async def fake_depseudo(_pool: Any, case_id: str, token: str, by: str) -> str:
        assert (case_id, token, by) == ("c1", "ip_abc", "analyst-9")
        return "1.2.3.4"

    monkeypatch.setattr(pii_module, "depseudonymize", fake_depseudo)

    result = await show_raw(pool, "c1", "analyst-9", "ip_abc")
    assert result == "1.2.3.4"
