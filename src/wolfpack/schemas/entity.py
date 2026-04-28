"""Entity models for tracked objects of interest."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class Entity(BaseModel):
    """An entity is a discrete object of interest inside a hunt.

    Entities are produced by agents ( Tracker, Flanker) and are the nodes
    in pivot graphs.  The ``type`` field controls how adapters query
    telemetry sources and how the NER/PII layer treats the value.
    """

    type: Literal["host", "user", "ip", "domain", "hash", "url"] = Field(
        ..., description="Telemetry category used for adapter routing."
    )
    value: str = Field(..., description="Canonical string representation of the entity.")
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Agent-supplied context (first_seen, enrichment_source, etc.).",
    )
