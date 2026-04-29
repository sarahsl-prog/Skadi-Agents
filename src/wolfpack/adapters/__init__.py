"""Telemetry adapters for WolfPack.

Tier-1 adapters (always available): syslog, windows_eventlog, crowdstrike, okta, firewall
Tier-2 adapters (feature-flagged): dns, zeek_suricata, proxy, cloudtrail
"""

from wolfpack.adapters.cloudtrail import CloudTrailSource
from wolfpack.adapters.crowdstrike import CrowdStrikeAdapter
from wolfpack.adapters.dns import DNSSource
from wolfpack.adapters.firewall import FirewallAdapter
from wolfpack.adapters.okta import OktaAdapter
from wolfpack.adapters.proxy import ProxySource
from wolfpack.adapters.syslog import SyslogAdapter
from wolfpack.adapters.windows_eventlog import WindowsEventLogAdapter
from wolfpack.adapters.zeek_suricata import ZeekSuricataSource

__all__ = [
    "CloudTrailSource",
    "CrowdStrikeAdapter",
    "DNSSource",
    "FirewallAdapter",
    "OktaAdapter",
    "ProxySource",
    "SyslogAdapter",
    "WindowsEventLogAdapter",
    "ZeekSuricataSource",
]
