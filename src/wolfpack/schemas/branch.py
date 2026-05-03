"""Branch specification models."""

from pydantic import BaseModel, Field

from wolfpack.schemas.hypothesis import Hypothesis


class BranchSpec(BaseModel):
    """Describes a new branch to be created inside a case.

    Branches are created by Flanker when a lateral pivot yields a
    significantly different hypothesis that warrants independent
    investigation.
    """

    parent_branch_id: str | None = Field(
        default=None,
        description="Branch from which this branch was spawned (NULL for root).",
    )
    hypothesis: Hypothesis = Field(..., description="The hypothesis that justifies the branch.")
    depth: int = Field(
        default=0,
        ge=0,
        description="Branch depth from the root (0 = root branch).",
    )
    created_by: str = Field(..., description="Agent or analyst that created the branch.")
