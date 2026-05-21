"""Firewall telemetry adapter.

Parses iptables, pfSense, and Palo Alto log formats from files.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from wolfpack.adapters.base import Event, TelemetrySource, TimeWindow
from wolfpack.schemas.entity import Entity


class FirewallAdapter(TelemetrySource):
    """Parse firewall logs and filter by entity / time window."""

    name = "firewall"

    # iptables: Jan 15 10:23:45 fw kernel: [UFW BLOCK] IN=eth0 SRC=10.0.0.1 ...
    _IPTABLES_RE = re.compile(
        r"^(?P<month>\w{3})\s+(?P<day>\d{1,2})\s+(?P<time>\d{2}:\d{2}:\d{2})\s+"
        r"(?P<host>\S+)\s+.*SRC=(?P<src>\S+).*DST=(?P<dst>\S+)"
    )

    # Palo Alto: ... src=10.0.0.1 dst=10.0.0.2 ...
    _PALOALTO_RE = re.compile(r"src=(?P<src>\S+)\s+dst=(?P<dst>\S+)")

    def __init__(self, log_path: str | None = None) -> None:
        self._log_path = log_path

    async def query(
        self,
        entity: Entity,
        time_window: TimeWindow,
        filters: dict[str, Any] | None = None,
    ) -> list[Event]:
        events: list[Event] = []
        if self._log_path is None:
            return events

        path = Path(self._log_path)
        if not path.exists():
            return events

        text = await asyncio.to_thread(path.read_text, encoding="utf-8", errors="replace")
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue

            event = self._parse_line(line, entity, time_window, filters)
            if event is not None:
                events.append(event)

        return events

    async def health_check(self) -> bool:
        if self._log_path is None:
            return False
        return Path(self._log_path).exists()

    def _parse_line(
        self,
        line: str,
        entity: Entity,
        time_window: TimeWindow,
        filters: dict[str, Any] | None,
    ) -> Event | None:
        match = self._IPTABLES_RE.match(line)
        if not match:
            match = self._PALOALTO_RE.search(line)
        if not match:
            return None

        src_ip = match.groupdict().get("src", "")
        dst_ip = match.groupdict().get("dst", "")

        # Filter by entity
        if entity.value not in (src_ip, dst_ip):
            return None

        # Parse timestamp
        now = datetime.now(UTC)
        ts = now
        if "month" in match.groupdict():
            ts_str = f"{match.group('month')} {match.group('day')} {match.group('time')}"
            try:
                ts = datetime.strptime(ts_str, "%b %d %H:%M:%S")
                ts = ts.replace(year=now.year, tzinfo=UTC)
                if ts > now:
                    ts = ts.replace(year=now.year - 1)
            except ValueError:
                pass

        if not (time_window.start <= ts <= time_window.end):
            return None

        # Action filter
        if filters and "action" in filters:
            if filters["action"].lower() not in line.lower():
                return None

        severity = "low"
        if "block" in line.lower() or "deny" in line.lower():
            severity = "medium"
        if "alert" in line.lower():
            severity = "high"

        return Event(
            timestamp=ts,
            source=self.name,
            raw_payload={"src_ip": src_ip, "dst_ip": dst_ip, "line": line},
            entities=[
                Entity(type="ip", value=src_ip),
                Entity(type="ip", value=dst_ip),
            ],
            severity=severity,
        )
