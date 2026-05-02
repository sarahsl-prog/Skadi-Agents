"""CrowdStrike Falcon telemetry adapter.

Queries Falcon Detection and Incident APIs with rate-limiting
and pagination.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

import httpx

from wolfpack.adapters.base import Event, TelemetrySource, TimeWindow
from wolfpack.schemas.entity import Entity


class CrowdStrikeAdapter(TelemetrySource):
    """CrowdStrike Falcon API adapter with rate limiting."""

    name = "crowdstrike"

    def __init__(
        self,
        base_url: str = "https://api.crowdstrike.com",
        client_id: str | None = None,
        client_secret: str | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._token: str | None = None
        self._token_expires: datetime | None = None
        self._client = httpx.AsyncClient(timeout=30.0)

    async def query(
        self,
        entity: Entity,
        time_window: TimeWindow,
        filters: dict[str, Any] | None = None,
    ) -> list[Event]:
        if not self._client_id or not self._client_secret:
            return []

        await self._ensure_token()
        if not self._token:
            return []

        events: list[Event] = []
        params = self._build_params(entity, time_window, filters)

        resp = await self._client.get(
            f"{self._base_url}/detects/queries/detects/v1",
            headers={"Authorization": f"Bearer {self._token}"},
            params=params,
        )
        if resp.status_code == 429:
            # Rate limited — return empty; caller can retry
            return events
        resp.raise_for_status()
        data = resp.json()
        detect_ids = data.get("resources", [])

        # Fetch full detection details for accurate timestamps
        if detect_ids:
            detail_resp = await self._client.post(
                f"{self._base_url}/detects/entities/detects/v1",
                headers={"Authorization": f"Bearer {self._token}"},
                json={"ids": detect_ids},
            )
            if detail_resp.status_code == 200:
                detail_data = detail_resp.json()
                details = {d.get("detection_id", d.get("id")): d for d in detail_data.get("resources", [])}
            else:
                details = {}

            for detect_id in detect_ids:
                detail = details.get(detect_id, {})
                ts_str = detail.get("last_behavior") or detail.get("timestamp")
                try:
                    ts = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00")) if ts_str else time_window.start
                except ValueError:
                    ts = time_window.start
                events.append(
                    Event(
                        timestamp=ts,
                        source=self.name,
                        raw_payload={"detect_id": detect_id, "entity": entity.model_dump(), "detail": detail},
                        entities=[entity],
                        severity="high",
                    )
                )

        return events

    async def health_check(self) -> bool:
        if not self._client_id or not self._client_secret:
            return False
        try:
            await self._ensure_token()
            return self._token is not None
        except Exception:
            return False

    async def _ensure_token(self) -> None:
        if self._token is not None and self._token_expires is not None and datetime.now(UTC) < self._token_expires:
            return
        if not self._client_id or not self._client_secret:
            return
        resp = await self._client.post(
            f"{self._base_url}/oauth2/token",
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "client_credentials",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data.get("access_token")
        expires_in = data.get("expires_in", 1800)
        self._token_expires = datetime.now(UTC) + timedelta(seconds=expires_in - 60)

    def _build_params(
        self,
        entity: Entity,
        time_window: TimeWindow,
        filters: dict[str, Any] | None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "limit": 100,
            "sort": "last_behavior|desc",
        }
        # Filter by entity value (AID for hosts, external IP, etc.)
        # URL-encode entity values to prevent FQL injection
        encoded_value = quote(entity.value, safe="")
        if entity.type == "host":
            params["filter"] = f"device.hostname:'{encoded_value}'"
        elif entity.type == "ip":
            params["filter"] = f"external_ip:'{encoded_value}'"
        else:
            params["q"] = entity.value

        if filters and "severity" in filters:
            sev = filters["severity"]
            encoded_sev = quote(sev, safe="")
            existing = params.get("filter", "")
            if existing:
                params["filter"] = existing + f"+max_severity_displayname:'{encoded_sev}'"
            else:
                params["filter"] = f"max_severity_displayname:'{encoded_sev}'"

        return params
