"""Unit tests for PII pipeline (no external DB)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from wolfpack.adapters.base import Event
from wolfpack.processing.ner import strip_pii
from wolfpack.processing.pii import PIICache
from wolfpack.schemas.entity import Entity


class FakePool:
    """In-memory pool that skips Postgres."""

    def __init__(self) -> None:
        self._salts: dict[str, bytes] = {}
        self._mappings: dict[tuple[str, str], str] = {}
        self._audit: list[dict[str, str]] = []

    async def acquire(self) -> FakePool:
        return self

    async def release(self, conn: Any) -> None:
        pass

    async def execute(self, sql: str, *args: Any) -> None:
        if "pii_salts" in sql:
            case_id = args[0]
            salt = args[1]
            self._salts[case_id] = salt
        elif "pii_mappings" in sql:
            case_id, token, original, _id_type = args
            self._mappings[(case_id, token)] = original
        elif "breakglass_audit" in sql:
            self._audit.append(
                {
                    "case_id": args[0],
                    "analyst_id": args[1],
                    "field": args[2],
                }
            )

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
        if "pii_salts" in sql:
            case_id = args[0]
            salt = self._salts.get(case_id)
            if salt:
                return {"salt": salt}
            return None
        elif "pii_mappings" in sql:
            case_id, token = args
            original = self._mappings.get((case_id, token))
            if original:
                return {"original_value": original}
            return None
        elif "evidence_ledger" in sql:
            return {"id": 1}
        return None


class TestPIICache:
    """In-memory caching of pseudonymization tokens."""

    @pytest.mark.asyncio
    async def test_cache_avoids_duplicate_db_calls(self) -> None:
        pool = FakePool()
        cache = PIICache(pool)  # type: ignore[arg-type]

        t1 = await cache.pseudonymize("case-1", "alice", "user")
        t2 = await cache.pseudonymize("case-1", "alice", "user")
        assert t1 == t2
        # Only one salt created
        assert len(pool._salts) == 1

    @pytest.mark.asyncio
    async def test_different_cases_different_tokens(self) -> None:
        pool = FakePool()
        cache = PIICache(pool)  # type: ignore[arg-type]

        t1 = await cache.pseudonymize("case-a", "10.0.0.1", "ip")
        t2 = await cache.pseudonymize("case-b", "10.0.0.1", "ip")
        assert t1 != t2

    @pytest.mark.asyncio
    async def test_depseudonymize(self) -> None:
        pool = FakePool()
        cache = PIICache(pool)  # type: ignore[arg-type]

        token = await cache.pseudonymize("case-1", "secret", "user")
        raw = await cache.depseudonymize("case-1", token, "analyst-1")
        assert raw == "secret"
        assert len(pool._audit) == 1

    def test_clear_case(self) -> None:
        pool = FakePool()
        cache = PIICache(pool)  # type: ignore[arg-type]
        # Just exercise the sync clear path
        cache.clear("case-1")
        cache.clear()


class TestNERStripper:
    """NER stripping with regex fallback."""

    def test_strip_ipv4(self) -> None:
        text = "Connection from 192.168.1.1 to 10.0.0.2"
        stripped, mapping = strip_pii(text)
        assert "192.168.1.1" not in stripped
        assert "10.0.0.2" not in stripped
        assert len(mapping) == 2
        assert "<IP_ADDRESS_1>" in mapping
        assert mapping["<IP_ADDRESS_1>"] == "192.168.1.1"

    def test_strip_email_and_hostname(self) -> None:
        text = "User alice@corp.com logged in from workstation01.corp.local"
        stripped, mapping = strip_pii(text)
        assert "alice@corp.com" not in stripped
        assert "workstation01.corp.local" not in stripped
        assert any("EMAIL" in k for k in mapping)
        assert any("HOSTNAME" in k for k in mapping)

    def test_strip_cidr(self) -> None:
        text = "Allowed traffic from 10.0.0.0/24"
        stripped, mapping = strip_pii(text)
        assert "10.0.0.0/24" not in stripped
        assert any("CIDR" in k for k in mapping)

    def test_strip_mac(self) -> None:
        text = "MAC address aa:bb:cc:dd:ee:ff detected"
        stripped, mapping = strip_pii(text)
        assert "aa:bb:cc:dd:ee:ff" not in stripped
        assert any("MAC" in k for k in mapping)

    def test_no_pii_no_change(self) -> None:
        text = "System restarted successfully"
        stripped, mapping = strip_pii(text)
        assert stripped == text
        assert mapping == {}


class TestPIIPipeline:
    """Orchestrator: pseudonymize identifiers + NER-strip text."""

    @pytest.mark.asyncio
    async def test_sanitize_event_entities(self) -> None:
        pool = FakePool()
        from wolfpack.processing.pii_pipeline import PIIPipeline

        pipeline = PIIPipeline(pool)  # type: ignore[arg-type]
        event = Event(
            timestamp=datetime.now(UTC),
            source="syslog",
            raw_payload={"message": "OK"},
            entities=[Entity(type="ip", value="192.168.1.1")],
            severity="low",
        )
        result = await pipeline.sanitize_events([event], "case-1")
        assert len(result) == 1
        assert result[0].entities[0].type == "ip"
        assert result[0].entities[0].value != "192.168.1.1"
        assert result[0].entities[0].value.startswith("ip_")

    @pytest.mark.asyncio
    async def test_sanitize_payload_text(self) -> None:
        pool = FakePool()
        from wolfpack.processing.pii_pipeline import PIIPipeline

        pipeline = PIIPipeline(pool)  # type: ignore[arg-type]
        event = Event(
            timestamp=datetime.now(UTC),
            source="syslog",
            raw_payload={"message": "Connection from 192.168.1.1"},
            entities=[],
            severity="low",
        )
        result = await pipeline.sanitize_events([event], "case-2")
        assert "192.168.1.1" not in result[0].raw_payload["message"]

    @pytest.mark.asyncio
    async def test_no_pii_event_unchanged_payload(self) -> None:
        pool = FakePool()
        from wolfpack.processing.pii_pipeline import PIIPipeline

        pipeline = PIIPipeline(pool)  # type: ignore[arg-type]
        event = Event(
            timestamp=datetime.now(UTC),
            source="syslog",
            raw_payload={"status": "ok", "count": 42},
            entities=[Entity(type="host", value="web01")],
            severity="info",
        )
        result = await pipeline.sanitize_events([event], "case-3")
        assert result[0].raw_payload["status"] == "ok"
        assert result[0].raw_payload["count"] == 42

    @pytest.mark.asyncio
    async def test_empty_events(self) -> None:
        pool = FakePool()
        from wolfpack.processing.pii_pipeline import PIIPipeline

        pipeline = PIIPipeline(pool)  # type: ignore[arg-type]
        result = await pipeline.sanitize_events([], "case-4")
        assert result == []
