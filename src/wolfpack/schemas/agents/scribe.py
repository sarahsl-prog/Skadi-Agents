"""Scribe agent I/O models."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class ScribeInput(BaseModel):
    """Input to the Scribe service.

    Scribe transforms structured events into immutable ledger entries
    and timeline updates.  In V1 it is non-LLM; the input is
    already a structured event dictionary.
    """

    case_id: str = Field(..., description="Case the event belongs to.")
    branch_id: str | None = Field(default=None, description="Branch scope (NULL for case-level).")
    event_type: Literal[
        "agent_action",
        "tool_call",
        "document_retrieved",
        "state_transition",
        "analyst_decision",
    ] = Field(..., description="Event category for ledger routing.")
    payload: dict[str, Any] = Field(
        ..., description="Structured event data (agent name, args, result)."
    )
    agent_run_id: str | None = Field(default=None, description="OTel trace/span correlation ID.")


class ScribeOutput(BaseModel):
    """Output from the Scribe service.

    Scribe returns the ledger entry ID and a human-readable summary.
    """

    ledger_entry_id: str = Field(..., description="ID of the written ledger row.")
    summary: str = Field(default="", description="Human-readable timeline summary.")
