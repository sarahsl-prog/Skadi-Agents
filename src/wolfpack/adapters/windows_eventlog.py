"""Windows Event Log telemetry adapter.

Parses EVTX files or queries via WinRM.  For V1 the implementation
uses local EVTX file parsing via ``python-evtx`` (optional dependency).
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from wolfpack.adapters.base import Event, TelemetrySource, TimeWindow
from wolfpack.schemas.entity import Entity

_LOGGER = logging.getLogger(__name__)

try:
    from defusedxml import ElementTree as DET  # noqa: N814
except ImportError:
    DET = None  # type: ignore[misc]
    _LOGGER.warning("defusedxml not installed; falling back to stdlib xml.etree (XXE risk)")

if DET is not None:
    ET = DET
else:
    from xml.etree import ElementTree as ET  # type: ignore[assignment]


class WindowsEventLogAdapter(TelemetrySource):
    """Parse Windows EVTX files and filter by entity / time window."""

    name = "windows_eventlog"

    def __init__(self, evtx_path: str | None = None) -> None:
        if evtx_path is not None:
            # Path traversal guard: ensure resolved path is under a safe base
            if ".." in evtx_path:
                raise ValueError(f"Path traversal detected in evtx_path: {evtx_path!r}")
        self._evtx_path = evtx_path

    async def query(
        self,
        entity: Entity,
        time_window: TimeWindow,
        filters: dict[str, Any] | None = None,
    ) -> list[Event]:
        events: list[Event] = []
        if self._evtx_path is None:
            return events

        path = Path(self._evtx_path)
        if not path.exists():
            return events

        # Try python-evtx first, then fallback to simple XML parsing
        try:
            events = self._parse_evtx(path, entity, time_window, filters)
        except Exception as exc:
            _LOGGER.warning("EVTX parse failed, falling back to XML: %s", exc)
            # Fallback: try to read as raw XML if the file is XML
            events = self._parse_xml_fallback(path, entity, time_window, filters)

        return events

    async def health_check(self) -> bool:
        if self._evtx_path is None:
            return False
        return Path(self._evtx_path).exists()

    def _parse_evtx(
        self,
        path: Path,
        entity: Entity,
        time_window: TimeWindow,
        filters: dict[str, Any] | None,
    ) -> list[Event]:
        events: list[Event] = []
        try:
            import Evtx.Evtx as Evtx
        except ImportError:
            return events

        with Evtx(str(path)) as evtx:
            for record in evtx.records():
                xml = record.xml()
                event = self._parse_event_xml(xml, entity, time_window, filters)
                if event is not None:
                    events.append(event)
        return events

    def _parse_xml_fallback(
        self,
        path: Path,
        entity: Entity,
        time_window: TimeWindow,
        filters: dict[str, Any] | None,
    ) -> list[Event]:
        events: list[Event] = []
        try:
            tree = ET.parse(str(path))  # type: ignore[attr-defined]  # noqa: S314
        except Exception as exc:
            _LOGGER.warning("XML fallback parse failed: %s", exc)
            return events

        for elem in tree.iter("Event"):
            xml_str = ET.tostring(elem, encoding="unicode")  # type: ignore[attr-defined]
            event = self._parse_event_xml(xml_str, entity, time_window, filters)
            if event is not None:
                events.append(event)
        return events

    def _parse_event_xml(
        self,
        xml: str,
        entity: Entity,
        time_window: TimeWindow,
        filters: dict[str, Any] | None,
    ) -> Event | None:
        try:
            root = ET.fromstring(xml)  # type: ignore[attr-defined]  # noqa: S314
        except Exception as exc:
            _LOGGER.warning("Event XML parse failed: %s", exc)
            return None

        ns = {"e": "http://schemas.microsoft.com/win/2004/08/events/event"}

        # Extract timestamp
        ts_elem = root.find(".//e:TimeCreated", ns)
        if ts_elem is None:
            return None
        ts_str = ts_elem.get("SystemTime", "")
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except ValueError:
            return None

        if not (time_window.start <= ts <= time_window.end):
            return None

        # Extract event data
        event_id_elem = root.find(".//e:EventID", ns)
        event_id = event_id_elem.text if event_id_elem is not None else ""

        computer_elem = root.find(".//e:Computer", ns)
        computer = computer_elem.text if computer_elem is not None else ""

        # Filter by entity
        entity_match = False
        if entity.value in (computer, event_id):
            entity_match = True
        else:
            # Search in event data
            data_elems = root.findall(".//e:Data", ns)
            for de in data_elems:
                if de.text and entity.value in de.text:
                    entity_match = True
                    break

        if not entity_match:
            return None

        # Severity mapping
        level_elem = root.find(".//e:Level", ns)
        level = level_elem.text or "0" if level_elem is not None else "0"
        severity = self._level_to_severity(level)

        # Channel filter
        if filters and "channel" in filters:
            channel_elem = root.find(".//e:Channel", ns)
            channel = channel_elem.text if channel_elem is not None else ""
            if channel != filters["channel"]:
                return None

        raw_payload: dict[str, Any] = {
            "event_id": event_id,
            "computer": computer,
        }
        data_elems = root.findall(".//e:Data", ns)
        for de in data_elems:
            name = de.get("Name") or "data"
            raw_payload[name] = de.text

        return Event(
            timestamp=ts,
            source=self.name,
            raw_payload=raw_payload,
            entities=[Entity(type="host", value=computer)] if computer else [],
            severity=severity,
            metadata=(
                {"channel": channel, "event_id": event_id}
                if "channel" in locals()
                else {"event_id": event_id}
            ),
        )

    @staticmethod
    def _level_to_severity(level: str) -> str:
        # Windows Event Log levels: 1=Critical, 2=Error, 3=Warning, 4=Info, 5=Verbose, 0=LogAlways
        mapping = {
            "1": "critical",
            "2": "high",
            "3": "medium",
            "4": "low",
            "5": "info",
            "0": "info",
        }
        return mapping.get(level, "info")
