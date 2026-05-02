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

    # RFC 3164 (legacy): <priority>timestamp host message
    _SYSLOG_RE = re.compile(
        r"^(?P<priority><\d+>)?"
        r"(?P<timestamp>\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+"
        r"(?P<host>\S+)\s+"
        r"(?P<message>.+)$"
    )

    # RFC 5424: <priority>version timestamp hostname app procid msgid structured-data msg
    _SYSLOG_RFC5424_RE = re.compile(
        r"^(?P<priority><\d+>)?(?P<version>\d+)\s+"
        r"(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}))\s+"
        r"(?P<host>\S+)\s+"
        r"(?P<app>\S+)\s+"
        r"(?P<procid>\S+)\s+"
        r"(?P<msgid>\S+)\s+"
        r"(?P<sd>-|\[.+?\])\s*"
        r"(?P<message>.*)$"
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

            match = self._SYSLOG_RFC5424_RE.match(line)
            if match:
                msg = match.group("message")
                host = match.group("host")
                ts_str = match.group("timestamp")
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                except ValueError:
                    ts = datetime.now(UTC)
            else:
                match = self._SYSLOG_RE.match(line)
                if not match:
                    continue
                msg = match.group("message")
                host = match.group("host")
                ts_str = match.group("timestamp")
                try:
                    ts = datetime.strptime(ts_str, "%b %d %H:%M:%S")
                    ts = self._apply_year(ts)
                except ValueError:
                    ts = datetime.now(UTC)

            # Filter by entity value (hostname or IP)
            if entity.value not in msg and entity.value != host:
                continue

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
    def _apply_year(ts: datetime) -> datetime:
        """Assign year to RFC-3164 timestamps, correcting for year boundary."""
        now = datetime.now(UTC)
        ts = ts.replace(year=now.year, tzinfo=UTC)
        # If the resulting timestamp is in the future, it belongs to last year
        if ts > now:
            ts = ts.replace(year=now.year - 1)
        return ts

    @staticmethod
    def _infer_severity(message: str) -> str:
        lowered = message.lower()
        if "error" in lowered or "critical" in lowered:
            return "high"
        if "warn" in lowered:
            return "medium"
        return "info"
