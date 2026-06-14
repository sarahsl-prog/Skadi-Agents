"""Unit tests for telemetry adapters (all mocked external I/O)."""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from wolfpack.adapters.base import TimeWindow
from wolfpack.adapters.cloudtrail import CloudTrailSource
from wolfpack.adapters.crowdstrike import CrowdStrikeAdapter
from wolfpack.adapters.dns import DNSSource
from wolfpack.adapters.firewall import FirewallAdapter
from wolfpack.adapters.okta import OktaAdapter
from wolfpack.adapters.proxy import ProxySource
from wolfpack.adapters.syslog import SyslogAdapter
from wolfpack.adapters.tools import AdapterDeps, build_adapter_tools, telemetry_tool_factory
from wolfpack.adapters.windows_eventlog import WindowsEventLogAdapter
from wolfpack.adapters.zeek_suricata import ZeekSuricataSource
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
        t = now.strftime("%H:%M:%S")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write(
                f"{month_abbr} {day} {t} web01 sshd[1234]: "
                f"Accepted publickey for alice from 10.0.0.1\n"
            )
            f.write(f"{month_abbr} {day} {t} web01 kernel: " f"Critical temperature reached\n")
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
        t = now.strftime("%H:%M:%S")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write(
                f"{month_abbr} {day} {t} fw kernel: "
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
        t = now.strftime("%H:%M:%S")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write(f"{month_abbr} {day} {t} host1 sshd: test\n")
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

    def test_build_adapter_tools_tier2_disabled_by_default(self) -> None:
        adapters = [DNSSource(), ZeekSuricataSource(), ProxySource(), CloudTrailSource()]
        tools = build_adapter_tools(adapters)
        assert "dns_query" not in tools
        assert "zeek_suricata_query" not in tools
        assert "proxy_query" not in tools
        assert "cloudtrail_query" not in tools

    def test_build_adapter_tools_tier2_enabled(self) -> None:
        adapters = [DNSSource(), ZeekSuricataSource(), ProxySource(), CloudTrailSource()]
        flags = {
            "adapter_dns": True,
            "adapter_zeek_suricata": True,
            "adapter_proxy": True,
            "adapter_cloudtrail": True,
        }
        tools = build_adapter_tools(adapters, feature_flags=flags)
        assert "dns_query" in tools
        assert "zeek_suricata_query" in tools
        assert "proxy_query" in tools
        assert "cloudtrail_query" in tools

    def test_build_adapter_tools_mixed_flags(self) -> None:
        adapters = [DNSSource(), ProxySource()]
        flags = {"adapter_dns": True, "adapter_proxy": False}
        tools = build_adapter_tools(adapters, feature_flags=flags)
        assert "dns_query" in tools
        assert "proxy_query" not in tools


class TestDNSAdapter:
    """DNS log parsing."""

    @pytest.fixture()
    def bind_log_file(self) -> str:
        now = datetime.now(UTC)
        day = now.strftime("%d")
        month = now.strftime("%b")
        year = now.strftime("%Y")
        t = now.strftime("%H:%M:%S")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write(
                f"{day}-{month}-{year} {t}.123 client 192.0.2.1#12345: "
                f"query: evil.com IN A + (192.0.2.53)\n"
            )
            f.flush()
            return f.name

    @pytest.fixture()
    def json_log_file(self) -> str:
        ts = (datetime.now(UTC) - timedelta(hours=12)).isoformat().replace("+00:00", "Z")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(
                f'{{"ts":"{ts}","q":"evil.com","t":"A","src":"192.0.2.1","rcode":0,"answers":["93.184.216.34"]}}\n'
            )
            f.flush()
            return f.name

    @pytest.mark.asyncio
    async def test_query_bind_by_domain(self, bind_log_file: str, time_window: TimeWindow) -> None:
        adapter = DNSSource(log_path=bind_log_file)
        entity = Entity(type="domain", value="evil.com")
        events = await adapter.query(entity, time_window)
        assert len(events) == 1
        assert events[0].metadata["query_type"] == "A"
        assert events[0].source == "dns"

    @pytest.mark.asyncio
    async def test_query_bind_by_ip(self, bind_log_file: str, time_window: TimeWindow) -> None:
        adapter = DNSSource(log_path=bind_log_file)
        entity = Entity(type="ip", value="192.0.2.1")
        events = await adapter.query(entity, time_window)
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_query_json_by_domain(self, json_log_file: str, time_window: TimeWindow) -> None:
        adapter = DNSSource(log_path=json_log_file)
        entity = Entity(type="domain", value="evil.com")
        events = await adapter.query(entity, time_window)
        assert len(events) == 1
        assert events[0].metadata.get("resolved_ips") == ["93.184.216.34"]

    @pytest.mark.asyncio
    async def test_query_type_filter(self, bind_log_file: str, time_window: TimeWindow) -> None:
        adapter = DNSSource(log_path=bind_log_file)
        entity = Entity(type="domain", value="evil.com")
        events = await adapter.query(entity, time_window, filters={"query_type": "AAAA"})
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_health_check(self, bind_log_file: str) -> None:
        adapter = DNSSource(log_path=bind_log_file)
        assert await adapter.health_check() is True


class TestZeekSuricataAdapter:
    """Zeek / Suricata JSON log parsing."""

    @pytest.fixture()
    def zeek_log_file(self) -> str:
        ts = (datetime.now(UTC) - timedelta(hours=12)).timestamp()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(
                f'{{"_path":"conn","ts":{ts},"id.orig_h":"192.0.2.1","id.resp_h":"93.184.216.34","id.orig_p":54321,"id.resp_p":443,"proto":"tcp","conn_state":"SF"}}\n'
            )
            f.write(
                f'{{"_path":"dns","ts":{ts + 1},"id.orig_h":"192.0.2.1","query":"evil.com","qtype_name":"A","answers":["93.184.216.34"]}}\n'  # noqa: E501
            )
            f.flush()
            return f.name

    @pytest.fixture()
    def suricata_log_file(self) -> str:
        ts = (datetime.now(UTC) - timedelta(hours=12)).isoformat().replace("+00:00", "Z")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(
                f'{{"timestamp":"{ts}","event_type":"alert","src_ip":"192.0.2.1","dest_ip":"93.184.216.34","alert":{{"signature":"ET MALWARE","category":"Malware Command and Control Activity Detected"}}}}\n'  # noqa: E501
            )
            f.flush()
            return f.name

    @pytest.mark.asyncio
    async def test_query_zeek_conn(self, zeek_log_file: str, time_window: TimeWindow) -> None:
        adapter = ZeekSuricataSource(log_path=zeek_log_file)
        entity = Entity(type="ip", value="192.0.2.1")
        events = await adapter.query(entity, time_window)
        assert len(events) == 2
        conn_events = [e for e in events if e.metadata.get("log_type") == "conn"]
        assert len(conn_events) == 1
        assert conn_events[0].metadata["src_port"] == 54321

    @pytest.mark.asyncio
    async def test_query_zeek_dns(self, zeek_log_file: str, time_window: TimeWindow) -> None:
        adapter = ZeekSuricataSource(log_path=zeek_log_file)
        entity = Entity(type="domain", value="evil.com")
        events = await adapter.query(entity, time_window)
        assert len(events) == 1
        assert events[0].metadata["log_type"] == "dns"

    @pytest.mark.asyncio
    async def test_query_suricata_alert(
        self, suricata_log_file: str, time_window: TimeWindow
    ) -> None:
        adapter = ZeekSuricataSource(log_path=suricata_log_file)
        entity = Entity(type="ip", value="192.0.2.1")
        events = await adapter.query(entity, time_window)
        assert len(events) == 1
        assert events[0].severity == "high"
        assert "ET MALWARE" in events[0].metadata.get("signature", "")

    @pytest.mark.asyncio
    async def test_protocol_filter(self, zeek_log_file: str, time_window: TimeWindow) -> None:
        adapter = ZeekSuricataSource(log_path=zeek_log_file)
        entity = Entity(type="ip", value="192.0.2.1")
        events = await adapter.query(entity, time_window, filters={"protocol": "udp"})
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_health_check(self, zeek_log_file: str) -> None:
        adapter = ZeekSuricataSource(log_path=zeek_log_file)
        assert await adapter.health_check() is True


class TestProxyAdapter:
    """Proxy log parsing."""

    @pytest.fixture()
    def squid_log_file(self) -> str:
        ts = (datetime.now(UTC) - timedelta(hours=12)).timestamp()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write(
                f"{ts:.3f}    200 192.0.2.1 TCP_MISS/200 1234 GET http://evil.com/path - HIER_DIRECT/93.184.216.34 text/html\n"  # noqa: E501
            )
            f.flush()
            return f.name

    @pytest.fixture()
    def cloudflare_log_file(self) -> str:
        ts = (datetime.now(UTC) - timedelta(hours=12)).isoformat().replace("+00:00", "Z")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(
                f'{{"EdgeStartTimestamp":"{ts}","ClientIP":"192.0.2.1","ClientRequestHost":"evil.com","ClientRequestURI":"/path","ClientRequestMethod":"GET","EdgeResponseStatus":200,"RayID":"abc123"}}\n'
            )
            f.flush()
            return f.name

    @pytest.mark.asyncio
    async def test_query_squid_by_ip(self, squid_log_file: str, time_window: TimeWindow) -> None:
        adapter = ProxySource(log_path=squid_log_file)
        entity = Entity(type="ip", value="192.0.2.1")
        events = await adapter.query(entity, time_window)
        assert len(events) == 1
        assert events[0].metadata["status_code"] == "200"
        assert events[0].metadata["method"] == "GET"

    @pytest.mark.asyncio
    async def test_query_cloudflare_by_domain(
        self, cloudflare_log_file: str, time_window: TimeWindow
    ) -> None:
        adapter = ProxySource(log_path=cloudflare_log_file)
        entity = Entity(type="domain", value="evil.com")
        events = await adapter.query(entity, time_window)
        assert len(events) == 1
        assert events[0].metadata["format"] == "cloudflare"
        assert events[0].metadata["ray_id"] == "abc123"

    @pytest.mark.asyncio
    async def test_status_code_filter(self, squid_log_file: str, time_window: TimeWindow) -> None:
        adapter = ProxySource(log_path=squid_log_file)
        entity = Entity(type="ip", value="192.0.2.1")
        events = await adapter.query(entity, time_window, filters={"status_code": "404"})
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_health_check(self, squid_log_file: str) -> None:
        adapter = ProxySource(log_path=squid_log_file)
        assert await adapter.health_check() is True


class TestCloudTrailAdapter:
    """AWS CloudTrail log parsing."""

    @pytest.fixture()
    def cloudtrail_log_file(self) -> str:
        ts = (datetime.now(UTC) - timedelta(hours=12)).isoformat().replace("+00:00", "Z")
        ts2 = (
            (datetime.now(UTC) - timedelta(hours=11, minutes=55)).isoformat().replace("+00:00", "Z")
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write(
                '{"Records":['
                f'{{"eventTime":"{ts}","eventName":"PutBucketPolicy","eventSource":"s3.amazonaws.com","sourceIPAddress":"192.0.2.1","userIdentity":{{"arn":"arn:aws:iam::123456789012:user/alice"}},"requestParameters":{{"bucketName":"sensitive-bucket"}},"awsRegion":"us-east-1"}},'
                f'{{"eventTime":"{ts2}","eventName":"GetObject","eventSource":"s3.amazonaws.com","sourceIPAddress":"192.0.2.2","userIdentity":{{"arn":"arn:aws:iam::123456789012:user/bob"}},"requestParameters":{{"bucketName":"public-bucket"}},"awsRegion":"us-east-1"}}'
                "]}"
            )
            f.flush()
            return f.name

    @pytest.mark.asyncio
    async def test_query_by_user_arn(
        self, cloudtrail_log_file: str, time_window: TimeWindow
    ) -> None:
        adapter = CloudTrailSource(log_path=cloudtrail_log_file)
        entity = Entity(type="user", value="arn:aws:iam::123456789012:user/alice")
        events = await adapter.query(entity, time_window)
        assert len(events) == 1
        assert events[0].metadata["event_name"] == "PutBucketPolicy"
        assert events[0].severity == "high"

    @pytest.mark.asyncio
    async def test_query_by_source_ip(
        self, cloudtrail_log_file: str, time_window: TimeWindow
    ) -> None:
        adapter = CloudTrailSource(log_path=cloudtrail_log_file)
        entity = Entity(type="ip", value="192.0.2.1")
        events = await adapter.query(entity, time_window)
        assert len(events) == 1
        assert events[0].metadata["resource"] == "sensitive-bucket"

    @pytest.mark.asyncio
    async def test_query_by_bucket_name(
        self, cloudtrail_log_file: str, time_window: TimeWindow
    ) -> None:
        adapter = CloudTrailSource(log_path=cloudtrail_log_file)
        entity = Entity(type="domain", value="sensitive-bucket")
        events = await adapter.query(entity, time_window)
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_event_name_filter(
        self, cloudtrail_log_file: str, time_window: TimeWindow
    ) -> None:
        adapter = CloudTrailSource(log_path=cloudtrail_log_file)
        entity = Entity(type="user", value="arn:aws:iam::123456789012:user/alice")
        events = await adapter.query(entity, time_window, filters={"event_name": "GetObject"})
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_health_check(self, cloudtrail_log_file: str) -> None:
        adapter = CloudTrailSource(log_path=cloudtrail_log_file)
        assert await adapter.health_check() is True


class TestWindowsEventLogAdapter:
    """Windows Event Log adapter must use secure XML parsing only."""

    def test_uses_defusedxml_not_stdlib(self) -> None:
        """Importing the module should bind ET to defusedxml, never stdlib."""
        from wolfpack.adapters import windows_eventlog as wev_mod

        assert wev_mod.ET.__name__.startswith("defusedxml")
        assert "defusedxml" in wev_mod.ET.parse.__module__

    @pytest.mark.asyncio
    async def test_xml_fallback_parses_event(self, tmp_path: Path) -> None:
        """XML fallback path works and filters by entity/time."""
        fixed_ts = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        event_xml = f"""<?xml version="1.0"?>
        <Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">
          <System>
            <TimeCreated SystemTime="{fixed_ts}"/>
            <EventID>4624</EventID>
            <Computer>WORKSTATION01</Computer>
            <Level>4</Level>
            <Channel>Security</Channel>
          </System>
          <EventData>
            <Data Name="IpAddress">10.0.0.1</Data>
          </EventData>
        </Event>
        """
        path = tmp_path / "test.evtx"
        path.write_text(event_xml, encoding="utf-8")

        # Use a window that definitely contains the event timestamp.
        now = datetime.now(UTC)
        time_window = TimeWindow(start=now - timedelta(hours=1), end=now + timedelta(hours=1))

        adapter = WindowsEventLogAdapter(evtx_path=str(path))
        entity = Entity(type="ip", value="10.0.0.1")
        events = await adapter.query(entity, time_window)

        assert len(events) == 1
        assert events[0].source == "windows_eventlog"
        assert events[0].raw_payload["event_id"] == "4624"
        assert events[0].raw_payload["computer"] == "WORKSTATION01"
        assert events[0].raw_payload["IpAddress"] == "10.0.0.1"
        assert events[0].severity == "low"
