"""Integration tests for Tier-2 adapter feature flags."""

from __future__ import annotations

import pytest

from wolfpack.adapters import (
    CloudTrailSource,
    CrowdStrikeAdapter,
    DNSSource,
    FirewallAdapter,
    OktaAdapter,
    ProxySource,
    SyslogAdapter,
    WindowsEventLogAdapter,
    ZeekSuricataSource,
)
from wolfpack.adapters.tools import build_adapter_tools


class TestFeatureFlagGating:
    """Tier-2 adapters are only available when feature flags are enabled."""

    def test_all_tier2_disabled_by_default(self) -> None:
        adapters = [
            DNSSource(),
            ZeekSuricataSource(),
            ProxySource(),
            CloudTrailSource(),
        ]
        tools = build_adapter_tools(adapters)
        assert tools == {}

    def test_tier1_always_available(self) -> None:
        adapters = [
            SyslogAdapter(),
            FirewallAdapter(),
            CrowdStrikeAdapter(),
            OktaAdapter(base_url="https://example.okta.com"),
            WindowsEventLogAdapter(),
        ]
        tools = build_adapter_tools(adapters)
        assert "syslog_query" in tools
        assert "firewall_query" in tools
        assert "crowdstrike_query" in tools
        assert "okta_query" in tools
        assert "windows_eventlog_query" in tools

    def test_individual_tier2_flags(self) -> None:
        adapters = [DNSSource(), ZeekSuricataSource(), ProxySource(), CloudTrailSource()]

        # Only DNS enabled
        tools = build_adapter_tools(adapters, feature_flags={"adapter_dns": True})
        assert "dns_query" in tools
        assert "zeek_suricata_query" not in tools
        assert "proxy_query" not in tools
        assert "cloudtrail_query" not in tools

        # Only CloudTrail enabled
        tools = build_adapter_tools(adapters, feature_flags={"adapter_cloudtrail": True})
        assert "dns_query" not in tools
        assert "cloudtrail_query" in tools

    def test_all_tier2_enabled(self) -> None:
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

    def test_partial_flags_mixed_with_tier1(self) -> None:
        adapters = [
            SyslogAdapter(),
            DNSSource(),
            ProxySource(),
        ]
        flags = {"adapter_dns": True, "adapter_proxy": False}
        tools = build_adapter_tools(adapters, feature_flags=flags)
        assert "syslog_query" in tools
        assert "dns_query" in tools
        assert "proxy_query" not in tools

    def test_unknown_adapter_ignored(self) -> None:
        """Adapters without a known flag mapping are silently skipped."""
        # Create a custom adapter
        from wolfpack.adapters.base import Event, TelemetrySource, TimeWindow
        from wolfpack.schemas.entity import Entity

        class CustomAdapter(TelemetrySource):
            name = "custom"

            async def query(self, entity: Entity, time_window: TimeWindow, filters=None):
                return []

            async def health_check(self):
                return True

        tools = build_adapter_tools([CustomAdapter()])
        assert "custom_query" not in tools
