"""Unit tests for the Alpha Dispatcher.

All tests use :class:`pydantic_ai.models.test.TestModel` so no real LLM
is invoked.
"""

import pytest
from pydantic_ai.models.test import TestModel

from wolfpack.agents.alpha import AlphaDeps, AlphaDispatcher
from wolfpack.schemas.agents.alpha import AlphaOutput
from wolfpack.schemas.seed import Seed


class TestAlphaDispatcher:
    """Alpha operations with mocked LLM."""

    @pytest.fixture()
    def dispatcher(self) -> AlphaDispatcher:
        model = TestModel(
            custom_output_args={
                "case_state": {
                    "case_id": "alpha-case-1",
                    "seed": {"type": "ioc", "raw_payload": {"value": "10.0.0.1"}},
                    "status": "scented",
                    "branches": [],
                    "hypotheses": [],
                    "evidence_refs": [],
                },
                "next_agent": "tracker",
                "task_description": "Investigate IP 10.0.0.1",
            }
        )
        return AlphaDispatcher(model=model)

    @pytest.mark.asyncio
    async def test_dispatch_returns_alpha_output(self, dispatcher: AlphaDispatcher) -> None:
        seed = Seed(type="ioc", raw_payload={"value": "10.0.0.1"})
        result = await dispatcher.dispatch(seed)
        assert isinstance(result, AlphaOutput)
        assert result.case_state.case_id == "alpha-case-1"
        assert result.case_state.status == "scented"
        assert result.next_agent == "tracker"
        assert result.task_description == "Investigate IP 10.0.0.1"

    def test_dispatch_sync(self, dispatcher: AlphaDispatcher) -> None:
        seed = Seed(type="ioc", raw_payload={"value": "10.0.0.1"})
        result = dispatcher.dispatch_sync(seed)
        assert isinstance(result, AlphaOutput)
        assert result.case_state.status == "scented"

    def test_init_requires_model_or_config(self) -> None:
        with pytest.raises(ValueError, match="Either model or llm_config"):
            AlphaDispatcher()

    @pytest.mark.asyncio
    async def test_create_case_tool_persists(self, dispatcher: AlphaDispatcher) -> None:
        model = TestModel(
            custom_output_args={
                "case_state": {
                    "case_id": "tool-case-1",
                    "seed": {"type": "alert", "raw_payload": {}},
                    "status": "scented",
                    "branches": [],
                    "hypotheses": [],
                    "evidence_refs": [],
                },
                "next_agent": "tracker",
                "task_description": "",
            },
            call_tools=["create_case"],
        )
        dispatcher_with_tool = AlphaDispatcher(model=model)
        seed = Seed(type="alert", raw_payload={})
        result = await dispatcher_with_tool.dispatch(seed)
        assert result.case_state.case_id == "tool-case-1"

    def test_alpha_deps(self) -> None:
        deps = AlphaDeps(pool=None)
        assert deps.pool is None
