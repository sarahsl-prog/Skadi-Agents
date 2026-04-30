"""Telemetry source interface and base models.

All Tier-1 and Tier-2 adapters implement :class:`TelemetrySource`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from wolfpack.schemas.entity import Entity


class TimeWindow(BaseModel):
    """Inclusive time range for telemetry queries."""

    start: datetime = Field(..., description="Start of the time window (inclusive).")
    end: datetime = Field(..., description="End of the time window (inclusive).")


class Event(BaseModel):
    """Normalised telemetry event produced by any adapter."""

    timestamp: datetime = Field(..., description="Event timestamp (UTC).")
    source: str = Field(..., description="Adapter name that produced this event.")
    raw_payload: dict[str, Any] = Field(
        default_factory=dict, description="Original event data (sanitised)."
    )
    entities: list[Entity] = Field(
        default_factory=list,
        description="Entities extracted from the event.",
    )
    severity: Literal["info", "low", "medium", "high", "critical"] = Field(
        default="info",
        description="Severity classification.",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Adapter-specific metadata (log type, API version, etc.).",
    )


class TelemetrySource(ABC):
    """Abstract base for all telemetry adapters.

    Implementations must be stateless (or hold only configuration)
    so they can be reused across agent runs.
    """

    name: str

    @abstractmethod
    async def query(
        self,
        entity: Entity,
        time_window: TimeWindow,
        filters: dict[str, Any] | None = None,
    ) -> list[Event]:
        """Query the telemetry source for events related to *entity*.

        Args:
            entity: The entity to pivot on (IP, host, user, etc.).
            time_window: Inclusive time range.
            filters: Adapter-specific filters (e.g. event types, severity thresholds).

        Returns:
            Sanitised, normalised events.
        """

    @abstractmethod
    async def health_check(self) -> bool:
        """Return ``True`` if the adapter can reach its data source."""
