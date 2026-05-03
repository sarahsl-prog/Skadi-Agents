"""Red-team tests: tool-allowlist enforcement per agent.

Verifies that each agent can only invoke tools explicitly listed in its
allowlist and that unauthorized attempts are rejected.
"""

from __future__ import annotations

import pytest

from wolfpack.agents.closer import CLOSER_TOOL_ALLOWLIST
from wolfpack.agents.tracker import TRACKER_TOOL_ALLOWLIST


class TestToolAllowlist:
    """Per-agent tool restrictions."""

    def test_tracker_allowlist_is_defined(self) -> None:
        assert len(TRACKER_TOOL_ALLOWLIST) > 0
        assert "threat_intel_tool" in TRACKER_TOOL_ALLOWLIST
        assert "case_history_tool" in TRACKER_TOOL_ALLOWLIST

    def test_closer_allowlist_is_defined(self) -> None:
        assert len(CLOSER_TOOL_ALLOWLIST) > 0
        assert "threat_intel_tool" in CLOSER_TOOL_ALLOWLIST
        assert "case_history_tool" in CLOSER_TOOL_ALLOWLIST
        # Closer is read-only; no branch-creation tool
        assert "create_branch" not in CLOSER_TOOL_ALLOWLIST

    def test_tracker_allowlist_contains_telemetry_tools(self) -> None:
        telemetry_tools = {
            "syslog_query",
            "windows_eventlog_query",
            "crowdstrike_query",
            "okta_query",
            "firewall_query",
        }
        for tool in telemetry_tools:
            assert tool in TRACKER_TOOL_ALLOWLIST, f"{tool} missing from Tracker allowlist"

    def test_unauthorized_tool_call_is_blocked(self) -> None:
        """Simulate an agent trying to invoke a disallowed tool.

        In production this would be caught by the Pydantic AI runtime
        (the tool is not registered). Here we assert the allowlist check
        logic directly.
        """
        attempted_tool = "unauthorized_delete_evidence"
        assert attempted_tool not in TRACKER_TOOL_ALLOWLIST
        assert attempted_tool not in CLOSER_TOOL_ALLOWLIST

    def test_allowlist_is_frozen(self) -> None:
        """Allowlists are frozensets so they cannot be mutated at runtime."""
        with pytest.raises(AttributeError):
            TRACKER_TOOL_ALLOWLIST.add("evil_tool")  # type: ignore[attr-defined,unused-ignore]
        with pytest.raises(AttributeError):
            CLOSER_TOOL_ALLOWLIST.add("evil_tool")  # type: ignore[attr-defined,unused-ignore]

    def test_runtime_validation_rejects_disallowed_tool(self) -> None:
        """Simulate the runtime guard that would reject a tool call."""

        def _guard(tool_name: str, allowlist: frozenset[str]) -> bool:
            if tool_name not in allowlist:
                # In production this would also write to the evidence ledger
                raise PermissionError(f"Tool '{tool_name}' is not in the agent allowlist")
            return True

        assert _guard("threat_intel_tool", TRACKER_TOOL_ALLOWLIST) is True
        with pytest.raises(PermissionError):
            _guard("evil_tool", TRACKER_TOOL_ALLOWLIST)

    def test_alpha_scribe_allowlists_are_conservative(self) -> None:
        """Alpha and Scribe have minimal tool exposure."""
        # Alpha: only case creation / routing tools
        from wolfpack.agents.alpha import ALPHA_TOOL_ALLOWLIST

        assert len(ALPHA_TOOL_ALLOWLIST) <= 3
        assert "create_branch" not in ALPHA_TOOL_ALLOWLIST

        # Scribe: ledger / timeline tools only
        from wolfpack.agents.scribe import SCRIBE_TOOL_ALLOWLIST

        assert len(SCRIBE_TOOL_ALLOWLIST) <= 3
        for forbidden in ("threat_intel_tool", "case_history_tool", "syslog_query"):
            assert forbidden not in SCRIBE_TOOL_ALLOWLIST
