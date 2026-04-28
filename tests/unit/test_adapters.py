"""Unit tests for telemetry adapters (all mocked external I/O)."""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime, timedelta

import pytest

from wolfpack.adapters.base import TimeWindow
from wolfpack.adapters.crowdstrike import CrowdStrikeAdapter
from wolfpack.adapters.firewall import FirewallAdapter
from wolfpack.adapters.okta import OktaAdapter
from wolfpack.adapters.syslog import SyslogAdapter
from wolfpack.adapters.tools import AdapterDeps, build_adapter_tools, telemetry_tool_factory
from wolfpack.schemas.entity import Entity


@pytest.fixture()
def time_window() -> TimeWindow:
    now = datetime.now(UTC)
    return TimeWindow(start=now - timedelta(hours=24), end=now)


class TestSyslogAdapter:
    """Syslog file parsing."""

    @pytest.fixture()
    def log_file(self) -> str:
        now = datetime.now(UTC)
        month_abbr = now.strftime("%b")
        day = now.strftime("%d")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write(
                f"{month_abbr} {day} 10:23:45 web01 sshd[1234]: "
                f"Accepted publickey for alice from 10.0.0.1\n"
            )
            f.write(
                f"{month_abbr} {day} 10:24:01 web01 kernel: "
                f"Critical temperature reached\n"
            )
            f.flush()
            return f.name

    @pytest.mark.asyncio
    async def test_query_by_host(self, log_file: str, time_window: TimeWindow) -> None:
        adapter = SyslogAdapter(log_path=log_file)
        entity = Entity(type="host", value="web01")
        events = await adapter.query(entity, time_window)
        assert len(events) == 2
        assert all(e.source == "syslog" for e in events)

    @pytest.mark.asyncio
    async def test_query_by_ip(self, log_file: str, time_window: TimeWindow) -> None:
        adapter = SyslogAdapter(log_path=log_file)
        entity = Entity(type="ip", value="10.0.0.1")
        events = await adapter.query(entity, time_window)
        assert len(events) == 1
        assert "Accepted publickey" in events[0].raw_payload["message"]

    @pytest.mark.asyncio
    async def test_severity_inference(self, log_file: str, time_window: TimeWindow) -> None:
        adapter = SyslogAdapter(log_path=log_file)
        entity = Entity(type="host", value="web01")
        events = await adapter.query(entity, time_window)
        severities = {e.severity for e in events}
        assert "high" in severities  # Critical temperature
        assert "info" in severities  # Accepted publickey

    @pytest.mark.asyncio
    async def test_health_check(self, log_file: str) -> None:
        adapter = SyslogAdapter(log_path=log_file)
        assert await adapter.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_missing_file(self) -> None:
        adapter = SyslogAdapter(log_path="/nonexistent/path.log")
        assert await adapter.health_check() is False


class TestFirewallAdapter:
    """Firewall log parsing."""

    @pytest.fixture()
    def log_file(self) -> str:
        now = datetime.now(UTC)
        month_abbr = now.strftime("%b")
        day = now.strftime("%d")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write(
                f"{month_abbr} {day} 10:23:45 fw kernel: "
                f"[UFW BLOCK] IN=eth0 SRC=192.168.1.1 DST=10.0.0.2\n"
            )
            f.flush()
            return f.name

    @pytest.mark.asyncio
    async def test_query_by_src_ip(self, log_file: str, time_window: TimeWindow) -> None:
        adapter = FirewallAdapter(log_path=log_file)
        entity = Entity(type="ip", value="192.168.1.1")
        events = await adapter.query(entity, time_window)
        assert len(events) == 1
        assert events[0].severity == "medium"  # BLOCK

    @pytest.mark.asyncio
    async def test_query_by_dst_ip(self, log_file: str, time_window: TimeWindow) -> None:
        adapter = FirewallAdapter(log_path=log_file)
        entity = Entity(type="ip", value="10.0.0.2")
        events = await adapter.query(entity, time_window)
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_no_match(self, log_file: str, time_window: TimeWindow) -> None:
        adapter = FirewallAdapter(log_path=log_file)
        entity = Entity(type="ip", value="1.2.3.4")
        events = await adapter.query(entity, time_window)
        assert len(events) == 0


class TestCrowdStrikeAdapter:
    """CrowdStrike API (mocked)."""

    @pytest.mark.asyncio
    async def test_query_without_credentials(self, time_window: TimeWindow) -> None:
        adapter = CrowdStrikeAdapter()
        entity = Entity(type="host", value="WORKSTATION-01")
        events = await adapter.query(entity, time_window)
        assert events == []

    @pytest.mark.asyncio
    async def test_health_check_without_credentials(self) -> None:
        adapter = CrowdStrikeAdapter()
        assert await adapter.health_check() is False


class TestOktaAdapter:
    """Okta API (mocked)."""

    @pytest.mark.asyncio
    async def test_query_without_token(self, time_window: TimeWindow) -> None:
        adapter = OktaAdapter(base_url="https://example.okta.com")
        entity = Entity(type="user", value="alice@example.com")
        events = await adapter.query(entity, time_window)
        assert events == []

    @pytest.mark.asyncio
    async def test_health_check_without_token(self) -> None:
        adapter = OktaAdapter(base_url="https://example.okta.com")
        assert await adapter.health_check() is False


class TestAdapterTools:
    """Tool factory for adapters."""

    @pytest.mark.asyncio
    async def test_tool_factory(self, time_window: TimeWindow) -> None:
        now = datetime.now(UTC)
        month_abbr = now.strftime("%b")
        day = now.strftime("%d")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write(f"{month_abbr} {day} 10:23:45 host1 sshd: test\n")
            f.flush()
            log_path = f.name

        adapter = SyslogAdapter(log_path=log_path)
        tool = telemetry_tool_factory(adapter)

        deps = AdapterDeps(adapters={"syslog": adapter})
        from pydantic_ai import RunContext

        ctx = RunContext(deps=deps, model=None, usage=None, prompt=None)  # type: ignore[arg-type]
        start_iso = time_window.start.isoformat()
        end_iso = time_window.end.isoformat()
        events = await tool(ctx, "host", "host1", start_iso, end_iso, top_k=5)
        assert len(events) == 1
        assert events[0].source == "syslog"

    def test_build_adapter_tools(self) -> None:
        adapter = SyslogAdapter()
        tools = build_adapter_tools([adapter])
        assert "syslog_query" in tools
