"""Okta System Log telemetry adapter.

Queries Okta System Log API with pagination and rate limiting.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx

from wolfpack.adapters.base import Event, TelemetrySource, TimeWindow
from wolfpack.schemas.entity import Entity


class OktaAdapter(TelemetrySource):
    """Okta System Log API adapter with pagination."""

    name = "okta"

    def __init__(
        self,
        base_url: str,
        api_token: str | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_token = api_token

    async def query(
        self,
        entity: Entity,
        time_window: TimeWindow,
        filters: dict[str, Any] | None = None,
    ) -> list[Event]:
        if not self._api_token:
            return []

        events: list[Event] = []
        headers = {
            "Authorization": f"SSWS {self._api_token}",
            "Accept": "application/json",
        }

        params: dict[str, Any] = {
            "since": time_window.start.isoformat(),
            "until": time_window.end.isoformat(),
            "limit": 1000,
        }

        # Okta filter by actor or target
        if entity.type == "user":
            params["q"] = entity.value
        elif entity.type == "ip":
            # URL-encode entity value to prevent FQL injection
            encoded_value = quote(entity.value, safe="")
            params["filter"] = f"client.ipAddress eq '{encoded_value}'"

        if filters and "event_type" in filters:
            evt = filters["event_type"]
            # URL-encode event type to prevent filter injection
            encoded_evt = quote(evt, safe="")
            params["filter"] = (params.get("filter", "") or "") + f" and eventType eq '{encoded_evt}'"

        url: str | None = f"{self._base_url}/api/v1/logs"

        async with httpx.AsyncClient() as client:
            while url:
                resp = await client.get(url, headers=headers, params=params, timeout=30.0)
                if resp.status_code == 429:
                    return events
                resp.raise_for_status()
                data = resp.json()
                if not isinstance(data, list):
                    break

                for entry in data:
                    ts_str = entry.get("published", "")
                    try:
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    except ValueError:
                        ts = datetime.now(UTC)

                    actor = entry.get("actor", {})
                    actor_name = actor.get("displayName", "")
                    client_info = entry.get("client", {})
                    ip = client_info.get("ipAddress", "")

                    event_entities: list[Entity] = []
                    if actor_name:
                        event_entities.append(Entity(type="user", value=actor_name))
                    if ip:
                        event_entities.append(Entity(type="ip", value=ip))

                    events.append(
                        Event(
                            timestamp=ts,
                            source=self.name,
                            raw_payload=entry,
                            entities=event_entities,
                            severity=self._map_severity(entry.get("severity", "INFO")),
                        )
                    )

                # Pagination via Link header
                url = self._next_url(resp)
                params = {}  # Only use params on first request

        return events

    async def health_check(self) -> bool:
        if not self._api_token:
            return False
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self._base_url}/api/v1/logs",
                    headers={"Authorization": f"SSWS {self._api_token}"},
                    params={"limit": 1},
                    timeout=10.0,
                )
                return resp.status_code == 200
        except Exception:
            return False

    @staticmethod
    def _next_url(resp: httpx.Response) -> str | None:
        link_header = resp.headers.get("link", "")
        for part in link_header.split(","):
            if 'rel="next"' in part:
                next_url: str = part.split(";")[0].strip()
                if next_url.startswith("<") and next_url.endswith(">"):
                    return next_url[1:-1]
        return None

    @staticmethod
    def _map_severity(level: str) -> str:
        mapping = {
            "DEBUG": "info",
            "INFO": "info",
            "WARN": "medium",
            "ERROR": "high",
        }
        return mapping.get(level.upper(), "info")
