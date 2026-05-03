"""Alpha Dispatcher agent I/O models."""

from pydantic import BaseModel, Field

from wolfpack.schemas.case_state import CaseState


class AlphaOutput(BaseModel):
    """Output from the Alpha Dispatcher.

    Alpha returns the newly created case state and the first task
    routing decision.
    """

    case_state: CaseState = Field(..., description="Initial case state after creation.")
    next_agent: str = Field(
        default="tracker",
        description="Agent that should receive the next task.",
    )
    task_description: str = Field(default="", description="Human-readable task for the next agent.")
