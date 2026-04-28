"""Seed models for hunt initiation."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class Seed(BaseModel):
    """A seed is the initial input that starts a hunt.

    Seeds can be IOCs, alerts, anomalies, or analyst-driven hunt queries.
    The ``type`` field discriminates the seed format so the Alpha Dispatcher
    can normalise and route without hard-coding parsers.
    """

    type: Literal["ioc", "alert", "anomaly", "hunt_query"] = Field(
        ..., description="Discriminant for seed format and routing logic."
    )
    raw_payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Original seed content as received from the source system.",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Source-system metadata (receipt time, source ID, severity).",
    )
