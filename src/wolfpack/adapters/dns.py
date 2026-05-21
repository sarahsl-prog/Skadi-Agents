"""DNS telemetry adapter.

Parses BIND, dnsmasq, and generic DNS query/response logs.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from wolfpack.adapters.base import Event, TelemetrySource, TimeWindow
from wolfpack.schemas.entity import Entity


class DNSSource(TelemetrySource):
    """Parse DNS logs and filter by entity / time window."""

    name = "dns"

    # BIND: 15-Apr-2026 14:32:01.123 client 192.0.2.1#12345:
    #   query: evil.com IN A + (192.0.2.1)
    _BIND_RE = re.compile(
        r"^(?P<day>\d{1,2})-(?P<month>\w{3})-(?P<year>\d{4})\s+"
        r"(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})[\d.]*\s+"
        r"client\s+(?P<client_ip>\S+)#\d+:\s+"
        r"query:\s+(?P<domain>\S+)\s+"
        r"(?P<class>\S+)\s+(?P<qtype>\S+)\s+"
        r"(?P<flags>[+\-]+)\s+"
        r"\((?P<server_ip>[^)]+)\)"
    )

    # Generic / dnsmasq:
    # Apr 15 14:32:01 dnsmasq[123]: query[A] evil.com from 192.0.2.1
    _GENERIC_RE = re.compile(
        r"^(?P<month>\w{3})\s+(?P<day>\d{1,2})\s+(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})\s+"
        r".*query\[(?P<qtype>\w+)\]\s+(?P<domain>\S+)\s+"
        r"from\s+(?P<client_ip>\S+)"
    )

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
        # Try JSON first
        if line.startswith("{"):
            return self._parse_json_line(line, entity, time_window, filters)

        match = self._BIND_RE.match(line)
        if not match:
            match = self._GENERIC_RE.match(line)
        if not match:
            return None

        gd = match.groupdict()
        domain = gd.get("domain", "")
        client_ip = gd.get("client_ip", "")
        qtype = gd.get("qtype", "")

        # Filter by entity value
        if entity.value not in (domain, client_ip):
            return None

        ts = self._parse_timestamp(gd)
        if ts is None or not (time_window.start <= ts <= time_window.end):
            return None

        # Qtype filter
        if filters and "query_type" in filters:
            if filters["query_type"].upper() != qtype.upper():
                return None

        return Event(
            timestamp=ts,
            source=self.name,
            raw_payload={"line": line, **gd},
            entities=[
                (
                    Entity(type="domain", value=domain)
                    if domain
                    else Entity(type="ip", value=client_ip)
                ),
            ],
            metadata={
                "query_type": qtype,
                "format": "bind" if "server_ip" in gd else "generic",
            },
            severity="low",
        )

    def _parse_json_line(
        self,
        line: str,
        entity: Entity,
        time_window: TimeWindow,
        filters: dict[str, Any] | None,
    ) -> Event | None:
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return None

        # Accept multiple key conventions
        domain = (
            data.get("q") or data.get("query") or data.get("query_name") or data.get("domain", "")
        )
        src_ip = data.get("src") or data.get("client_ip") or data.get("src_ip", "")
        qtype = data.get("t") or data.get("qtype") or data.get("type", "")
        rcode = data.get("rcode")
        answers = data.get("answers", [])

        if entity.value not in (domain, src_ip) and not any(
            entity.value == str(a) for a in answers
        ):
            return None

        ts = self._parse_iso_timestamp(data.get("ts", ""))
        if ts is None or not (time_window.start <= ts <= time_window.end):
            return None

        if filters and "query_type" in filters:
            if filters["query_type"].upper() != qtype.upper():
                return None

        return Event(
            timestamp=ts,
            source=self.name,
            raw_payload=data,
            entities=[
                (
                    Entity(type="domain", value=domain)
                    if domain
                    else (
                        Entity(type="ip", value=src_ip)
                        if src_ip
                        else Entity(type="domain", value="unknown")
                    )
                ),
            ],
            metadata={
                "query_type": qtype,
                "response_code": rcode,
                "resolved_ips": answers,
                "format": "json",
            },
            severity="low",
        )

    def _parse_timestamp(self, gd: dict[str, str]) -> datetime | None:
        try:
            ts = datetime.strptime(
                f"{gd.get('day')} {gd.get('month')} {gd.get('year', datetime.now(UTC).year)} "
                f"{gd.get('hour')}:{gd.get('minute')}:{gd.get('second')}",
                "%d %b %Y %H:%M:%S",
            )
            return ts.replace(tzinfo=UTC)
        except (ValueError, KeyError):
            pass
        try:
            ts = datetime.strptime(
                f"{gd.get('month')} {gd.get('day')} {datetime.now(UTC).year} "
                f"{gd.get('hour')}:{gd.get('minute')}:{gd.get('second')}",
                "%b %d %Y %H:%M:%S",
            )
            return ts.replace(tzinfo=UTC)
        except (ValueError, KeyError):
            return None

    def _parse_iso_timestamp(self, ts_str: str) -> datetime | None:
        if not ts_str:
            return None
        try:
            return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except ValueError:
            return None
