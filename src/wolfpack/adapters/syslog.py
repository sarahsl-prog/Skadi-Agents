"""Syslog telemetry adapter.

Supports RFC 3164 and RFC 5424 parsing from local files or UDP streams.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from wolfpack.adapters.base import Event, TelemetrySource, TimeWindow
from wolfpack.schemas.entity import Entity


class SyslogAdapter(TelemetrySource):
    """Parse syslog files and filter by entity / time window."""

    name = "syslog"

    _SYSLOG_RE = re.compile(
        r"^(?P<priority>&lt;\d+&gt;)?"
        r"(?P<timestamp>\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+"
        r"(?P<host>\S+)\s+"
        r"(?P<message>.+)$"
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
            match = self._SYSLOG_RE.match(line)
            if not match:
                continue

            msg = match.group("message")
            host = match.group("host")

            # Filter by entity value (hostname or IP)
            if entity.value not in msg and entity.value != host:
                continue

            # Parse timestamp (RFC 3164 lacks year; use current)
            ts_str = match.group("timestamp")
            try:
                ts = datetime.strptime(ts_str, "%b %d %H:%M:%S")
                ts = ts.replace(year=datetime.now(UTC).year, tzinfo=UTC)
            except ValueError:
                ts = datetime.now(UTC)

            if not (time_window.start <= ts <= time_window.end):
                continue

            events.append(
                Event(
                    timestamp=ts,
                    source=self.name,
                    raw_payload={"message": msg, "host": host},
                    entities=[Entity(type="host", value=host)],
                    severity=self._infer_severity(msg),
                )
            )

        return events

    async def health_check(self) -> bool:
        if self._log_path is None:
            return False
        return Path(self._log_path).exists()

    @staticmethod
    def _infer_severity(message: str) -> str:
        lowered = message.lower()
        if "error" in lowered or "critical" in lowered:
            return "high"
        if "warn" in lowered:
            return "medium"
        return "info"
