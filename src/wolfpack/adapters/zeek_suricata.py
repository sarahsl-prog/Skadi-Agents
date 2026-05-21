"""Zeek / Suricata telemetry adapter.

Parses Zeek JSON logs (conn, dns, http, ssl, files) and Suricata EVE JSON.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from wolfpack.adapters.base import Event, TelemetrySource, TimeWindow
from wolfpack.schemas.entity import Entity


class ZeekSuricataSource(TelemetrySource):
    """Parse Zeek and Suricata JSON logs and filter by entity / time window."""

    name = "zeek_suricata"

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
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return None

        # Determine log type
        log_type = self._detect_type(data)
        if log_type is None:
            return None

        # Extract common fields
        ts = self._extract_timestamp(data)
        if ts is None or not (time_window.start <= ts <= time_window.end):
            return None

        # Extract IPs / entities
        src_ip = data.get("id.orig_h") or data.get("src_ip") or ""
        dst_ip = data.get("id.resp_h") or data.get("dest_ip") or ""
        src_port = data.get("id.orig_p") or data.get("src_port") or ""
        dst_port = data.get("id.resp_p") or data.get("dest_port") or ""
        proto = data.get("proto", "")

        # Filter by entity
        entity_match = entity.value in (
            src_ip,
            dst_ip,
            str(src_port),
            str(dst_port),
            proto,
        )
        if not entity_match:
            # For DNS events, also match query name
            if log_type == "dns":
                query = data.get("query", "")
                if entity.value != query:
                    return None
            else:
                return None

        # Protocol filter
        if filters and "protocol" in filters:
            if filters["protocol"].upper() != str(proto).upper():
                return None

        severity = self._infer_severity(data, log_type)

        entities = []
        if src_ip:
            entities.append(Entity(type="ip", value=str(src_ip)))
        if dst_ip:
            entities.append(Entity(type="ip", value=str(dst_ip)))
        if log_type == "dns" and data.get("query"):
            entities.append(Entity(type="domain", value=str(data["query"])))

        metadata = {
            "log_type": log_type,
            "src_port": src_port,
            "dst_port": dst_port,
            "protocol": proto,
        }

        # Add type-specific metadata
        if log_type == "http":
            metadata["host"] = data.get("host", "")
            metadata["uri"] = data.get("uri", "")
            metadata["status_code"] = data.get("status_code", "")
        elif log_type == "ssl":
            metadata["subject"] = data.get("subject", "")
            metadata["issuer"] = data.get("issuer", "")
        elif log_type == "files":
            metadata["mime_type"] = data.get("mime_type", "")
            metadata["filename"] = data.get("filename", "")
        elif log_type == "alert":
            metadata["signature"] = data.get("alert", {}).get("signature", "")
            metadata["category"] = data.get("alert", {}).get("category", "")

        return Event(
            timestamp=ts,
            source=self.name,
            raw_payload=data,
            entities=entities,
            metadata=metadata,
            severity=severity,
        )

    def _detect_type(self, data: dict[str, Any]) -> str | None:
        if "alert" in data:
            return "alert"
        if "_path" in data:
            return str(data["_path"])
        if "event_type" in data:
            return str(data["event_type"])
        # Fallback heuristics
        if "query" in data and "answers" in data:
            return "dns"
        if "uri" in data and "host" in data:
            return "http"
        if "subject" in data and "issuer" in data:
            return "ssl"
        if "conn_state" in data:
            return "conn"
        return None

    def _extract_timestamp(self, data: dict[str, Any]) -> datetime | None:
        ts_raw = data.get("ts") or data.get("timestamp") or data.get("start")
        if ts_raw is None:
            return None
        if isinstance(ts_raw, (int, float)):
            # Zeek timestamps are Unix floats
            return datetime.fromtimestamp(float(ts_raw), tz=UTC)
        if isinstance(ts_raw, str):
            try:
                return datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None

    def _infer_severity(self, data: dict[str, Any], log_type: str) -> str:
        if log_type == "alert":
            return "high"
        if log_type == "files" and data.get("mime_type") in (
            "application/x-dosexec",
            "application/x-executable",
        ):
            return "medium"
        if log_type == "http" and data.get("status_code", 0) >= 400:
            return "low"
        return "info"
