"""Evidence reference models."""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class EvidenceRef(BaseModel):
    """A lightweight pointer to evidence material stored elsewhere.

    EvidenceRefs are written to the hash-chained ledger so that the
    ledger rows stay small while the actual logs, screenshots, or raw
    telemetry blobs live in object storage or adapter caches.
    """

    source_type: str = Field(..., description="Adapter or system that produced the evidence.")
    source_id: str = Field(..., description="Unique identifier within the source system.")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC time the evidence was captured or received.",
    )
    content_hash: str | None = Field(
        default=None,
        description="SHA-256 of the evidence content (if available at capture time).",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary source-specific metadata (file path, URL, size).",
    )
