"""Proxy telemetry adapter.

Parses Cloudflare JSON logs and generic proxy logs (Squid, Apache mod_proxy).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from wolfpack.adapters.base import Event, TelemetrySource, TimeWindow
from wolfpack.schemas.entity import Entity


class ProxySource(TelemetrySource):
    """Parse proxy logs and filter by entity / time window."""

    name = "proxy"

    # Squid: 1713193921.123 200 192.0.2.1 TCP_MISS/200 1234
    #   GET http://evil.com/path - HIER_DIRECT/93.184.216.34 text/html
    _SQUID_RE = re.compile(
        r"^(?P<ts>\d+\.\d+)\s+"
        r"\d+\s+"
        r"(?P<client_ip>\S+)\s+"
        r"\S+\/"
        r"(?P<status>\d+)\s+"
        r"\d+\s+"
        r"(?P<method>\S+)\s+"
        r"(?P<url>\S+)"
    )

    # Apache mod_proxy:
    # 192.0.2.1 - - [15/Apr/2026:14:32:01 +0000]
    #   "GET http://evil.com/path HTTP/1.1" 200 1234
    _APACHE_RE = re.compile(
        r"^(?P<client_ip>\S+)\s+\S+\s+\S+\s+"
        r"\[(?P<ts>[^\]]+)\]\s+"
        r"\"(?P<method>\S+)\s+(?P<url>\S+)\s+[^\"]*\"\s+"
        r"(?P<status>\d+)"
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

        text = path.read_text(encoding="utf-8", errors="replace")
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
        # Try JSON first (Cloudflare)
        if line.startswith("{"):
            return self._parse_json_line(line, entity, time_window, filters)

        match = self._SQUID_RE.match(line)
        if not match:
            match = self._APACHE_RE.match(line)
        if not match:
            return None

        gd = match.groupdict()
        url = gd.get("url", "")
        client_ip = gd.get("client_ip", "")
        status = gd.get("status", "")

        # Extract domain from URL
        domain = ""
        if url.startswith("http"):
            from urllib.parse import urlparse

            domain = urlparse(url).hostname or ""

        # Filter by entity (status code is not an entity match)
        entity_match = entity.value in (client_ip, domain, url)
        if not entity_match:
            return None

        ts = self._parse_timestamp(gd)
        if ts is None or not (time_window.start <= ts <= time_window.end):
            return None

        # Status filter
        if filters and "status_code" in filters:
            if str(filters["status_code"]) != str(status):
                return None

        severity = "info"
        if status:
            try:
                if int(status) >= 500:
                    severity = "medium"
                elif int(status) >= 400:
                    severity = "low"
            except ValueError:
                pass

        return Event(
            timestamp=ts,
            source=self.name,
            raw_payload={"line": line, **gd},
            entities=[
                Entity(type="ip", value=client_ip),
                Entity(type="domain", value=domain) if domain else Entity(type="url", value=url),
            ],
            metadata={
                "status_code": status,
                "method": gd.get("method", ""),
                "url": url,
                "format": "squid" if "ts" in gd and "." in gd.get("ts", "") else "apache",
            },
            severity=severity,
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

        client_ip = data.get("ClientIP") or data.get("client_ip") or data.get("src_ip", "")
        domain = data.get("ClientRequestHost") or data.get("host") or ""
        url = data.get("ClientRequestURI") or data.get("uri") or ""
        status = data.get("EdgeResponseStatus") or data.get("status_code") or ""
        method = data.get("ClientRequestMethod") or data.get("method") or ""

        full_url = f"https://{domain}{url}" if domain and url else (url or domain)

        if entity.value not in (client_ip, domain, full_url, str(status)):
            return None

        ts = self._parse_iso_timestamp(data.get("EdgeStartTimestamp") or data.get("ts", ""))
        if ts is None or not (time_window.start <= ts <= time_window.end):
            return None

        if filters and "status_code" in filters:
            if str(filters["status_code"]) != str(status):
                return None

        severity = "info"
        if status:
            try:
                if int(status) >= 500:
                    severity = "medium"
                elif int(status) >= 400:
                    severity = "low"
            except ValueError:
                pass

        return Event(
            timestamp=ts,
            source=self.name,
            raw_payload=data,
            entities=[
                Entity(type="ip", value=client_ip),
                Entity(type="domain", value=domain)
                if domain
                else Entity(type="url", value=full_url),
            ],
            metadata={
                "status_code": status,
                "method": method,
                "url": full_url,
                "format": "cloudflare",
                "ray_id": data.get("RayID") or data.get("ray_id", ""),
            },
            severity=severity,
        )

    def _parse_timestamp(self, gd: dict[str, str]) -> datetime | None:
        ts_str = gd.get("ts", "")
        if "." in ts_str:
            try:
                return datetime.fromtimestamp(float(ts_str), tz=UTC)
            except ValueError:
                return None
        return self._parse_iso_timestamp(ts_str)

    def _parse_iso_timestamp(self, ts_str: str) -> datetime | None:
        if not ts_str:
            return None
        try:
            return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except ValueError:
            return None
