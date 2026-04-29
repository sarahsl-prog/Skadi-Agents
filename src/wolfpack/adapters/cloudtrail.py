"""AWS CloudTrail telemetry adapter.

Parses CloudTrail logs from S3 event delivery or API response JSON.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from wolfpack.adapters.base import Event, TelemetrySource, TimeWindow
from wolfpack.schemas.entity import Entity


class CloudTrailSource(TelemetrySource):
    """Parse CloudTrail JSON logs and filter by entity / time window."""

    name = "cloudtrail"

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

        # CloudTrail S3 delivery: each file is a JSON object with "Records" array
        try:
            doc = json.loads(text)
            records = doc.get("Records", [])
        except json.JSONDecodeError:
            # Fall back to newline-delimited JSON
            records = []
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        for record in records:
            event = self._parse_record(record, entity, time_window, filters)
            if event is not None:
                events.append(event)

        return events

    async def health_check(self) -> bool:
        if self._log_path is None:
            return False
        return Path(self._log_path).exists()

    def _parse_record(
        self,
        record: dict[str, Any],
        entity: Entity,
        time_window: TimeWindow,
        filters: dict[str, Any] | None,
    ) -> Event | None:
        event_time = record.get("eventTime", "")
        ts = self._parse_iso_timestamp(event_time)
        if ts is None or not (time_window.start <= ts <= time_window.end):
            return None

        user = record.get("userIdentity", {})
        user_arn = user.get("arn") or user.get("userName") or ""
        source_ip = record.get("sourceIPAddress", "")
        resource = self._extract_resource(record)
        event_name = record.get("eventName", "")
        event_source = record.get("eventSource", "")
        error_code = record.get("errorCode", "")
        error_message = record.get("errorMessage", "")

        # Filter by entity
        entity_match = entity.value in (user_arn, source_ip, resource, event_name)
        if not entity_match:
            return None

        # Event name filter
        if filters and "event_name" in filters:
            if filters["event_name"] != event_name:
                return None

        severity = "info"
        if error_code:
            severity = "medium"
        if event_name in ("PutBucketPolicy", "PutBucketAcl", "CreateAccessKey", "AttachUserPolicy"):
            severity = "high"

        return Event(
            timestamp=ts,
            source=self.name,
            raw_payload=record,
            entities=[
                Entity(type="user", value=user_arn)
                if user_arn
                else Entity(type="ip", value=source_ip),
            ],
            metadata={
                "event_name": event_name,
                "event_source": event_source,
                "user_arn": user_arn,
                "source_ip": source_ip,
                "resource": resource,
                "error_code": error_code,
                "error_message": error_message,
                "region": record.get("awsRegion", ""),
            },
            severity=severity,
        )

    def _extract_resource(self, record: dict[str, Any]) -> str:
        resources = record.get("resources", [])
        if resources:
            return str(resources[0].get("ARN") or resources[0].get("arn", ""))
        # Fallback: look in requestParameters
        req = record.get("requestParameters", {})
        for key in ("bucketName", "roleArn", "policyArn", "name", "instanceId"):
            if key in req:
                return str(req[key])
        return ""

    def _parse_iso_timestamp(self, ts_str: str) -> datetime | None:
        if not ts_str:
            return None
        try:
            return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except ValueError:
            return None
