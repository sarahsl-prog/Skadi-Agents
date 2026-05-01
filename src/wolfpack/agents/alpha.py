"""Alpha Dispatcher — Pydantic AI agent for seed normalization.

Alpha receives a raw :class:`Seed`, normalises it into a structured
:class:`CaseState`, and publishes the initial task list.  In Phase 2 the
agent skeleton uses the LLM factory but does not yet perform deep
enrichment — the goal is to prove the Pydantic AI wiring is correct.
"""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic_ai import Agent, RunContext

from wolfpack.llm.factory import get_model
from wolfpack.observability.agents import traced_agent_run
from wolfpack.schemas.agents.alpha import AlphaOutput
from wolfpack.schemas.case_state import CaseState
from wolfpack.schemas.persistence import CasePersistence, PersistencePool
from wolfpack.schemas.seed import Seed


class AlphaDeps:
    """Dependencies injected into Alpha tools at run time."""

    def __init__(self, pool: PersistencePool | None = None) -> None:
        self.pool = pool


class AlphaDispatcher:
    """Pydantic AI agent that turns a raw seed into a hunt case.

    Args:
        model: A Pydantic AI :class:`Model` (e.g. ``TestModel`` in tests).
        llm_config: :class:`LLMConfig` used to build a model when *model*
            is not supplied directly.

    Raises:
        ValueError: If neither *model* nor *llm_config* is provided.
    """

    def __init__(
        self,
        model: Any | None = None,
        llm_config: Any | None = None,
    ) -> None:
        if model is None:
            if llm_config is None:
                raise ValueError("Either model or llm_config must be provided")
            model = get_model(llm_config)

        self._agent = Agent(
            model,
            output_type=AlphaOutput,
            instructions=(
                "You are the Alpha Dispatcher. Normalise hunt seeds into "
                "structured CaseState objects. Use the create_case tool to "
                "persist the case in the database."
            ),
        )

        @self._agent.tool  # type: ignore[arg-type]
        async def create_case(ctx: RunContext[AlphaDeps], state: CaseState) -> str:
            """Persist a :class:`CaseState` to the database."""
            if ctx.deps.pool is not None:
                persistence = CasePersistence(ctx.deps.pool)
                await persistence.create_case(state)
            return state.case_id

    async def dispatch(
        self,
        seed: Seed,
        pool: PersistencePool | None = None,
    ) -> AlphaOutput:
        """Run Alpha on a seed and return the normalised output."""
        deps = AlphaDeps(pool=pool)
        result = await traced_agent_run(
            "alpha",
            self._agent,
            f"Normalise this hunt seed into a CaseState: {seed.model_dump_json()}",
            deps=deps,  # type: ignore[call-overload]
        )
        return result.output  # type: ignore[no-any-return]

    def dispatch_sync(
        self,
        seed: Seed,
        pool: PersistencePool | None = None,
    ) -> AlphaOutput:
        """Synchronous wrapper around :meth:`dispatch` for LangGraph wiring."""
        return asyncio.run(self.dispatch(seed, pool=pool))


