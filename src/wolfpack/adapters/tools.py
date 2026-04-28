"""Pydantic AI tool factory for telemetry adapters.

Each registered adapter gets a scoped query tool that returns
structured :class:`Event` objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic_ai import RunContext

from wolfpack.adapters.base import Event, TelemetrySource, TimeWindow
from wolfpack.schemas.entity import Entity


class AdapterDeps:
    """Dependencies injected into adapter tools."""

    def __init__(self, adapters: dict[str, TelemetrySource]) -> None:
        self.adapters = adapters


def telemetry_tool_factory(adapter: TelemetrySource) -> Any:
    """Create a Pydantic AI tool function for *adapter*.

    The returned function has a scoped name like ``syslog_query``
    and accepts ``entity_type``, ``entity_value``, and optional
    ``start`` / ``end`` ISO timestamps.
    """

    async def _tool(
        ctx: RunContext[AdapterDeps],
        entity_type: str,
        entity_value: str,
        start_iso: str,
        end_iso: str,
        top_k: int = 20,
    ) -> list[Event]:
        entity = Entity(type=entity_type, value=entity_value)
        start = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
        end = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
        time_window = TimeWindow(start=start, end=end)
        events = await adapter.query(entity, time_window)
        return events[:top_k]

    _tool.__name__ = f"{adapter.name}_query"
    _tool.__doc__ = (
        f"Query the {adapter.name} telemetry source for events "
        f"related to the given entity."
    )
    return _tool


def build_adapter_tools(adapters: list[TelemetrySource]) -> dict[str, Any]:
    """Return a mapping of tool name → tool function for all adapters."""
    return {
        f"{adapter.name}_query": telemetry_tool_factory(adapter)
        for adapter in adapters
    }
