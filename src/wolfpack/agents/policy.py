"""Policy guardrail engine for WolfPack verdicts."""

from __future__ import annotations

from typing import Any

from wolfpack.schemas.case_state import CaseState
from wolfpack.schemas.confidence import Confidence
from wolfpack.schemas.verdict import PolicyGuardrail, VerdictPacket


class PolicyEngine:
    """Evaluate verdicts against built-in policy guardrails.

    Built-in policies for V1:

    - ``high_confidence_malicious`` — flags verdicts with ``decision == MALICIOUS``
      and ``confidence >= STRONG`` for mandatory analyst review.
    - ``low_confidence_inconclusive`` — flags ``decision == INCONCLUSIVE``
      with ``confidence <= WEAK`` as needing more investigation.
    - ``high_confidence_benign_auto_close`` — flags ``decision == BENIGN``
      with ``confidence >= STRONG`` as eligible for auto-close (still
      requires analyst acknowledgment).

    Future policies can be registered via :meth:`register`.
    """

    def __init__(self, extra_policies: list[Any] | None = None) -> None:
        """Initialize the engine with optional extra policies."""
        self._policies: list[dict[str, Any]] = []
        self._register_builtin()
        if extra_policies:
            for p in extra_policies:
                self.register(p)

    def _register_builtin(self) -> None:
        self._policies = [
            {
                "id": "high_confidence_malicious",
                "name": "High-Confidence Malicious",
                "description": (
                    "Verdict is MALICIOUS with confidence STRONG or higher. "
                    "Analyst review is mandatory."
                ),
                "check": self._check_high_confidence_malicious,
            },
            {
                "id": "low_confidence_inconclusive",
                "name": "Low-Confidence Inconclusive",
                "description": (
                    "Verdict is INCONCLUSIVE with confidence WEAK or lower. "
                    "Additional investigation is recommended."
                ),
                "check": self._check_low_confidence_inconclusive,
            },
            {
                "id": "high_confidence_benign_auto_close",
                "name": "High-Confidence Benign",
                "description": (
                    "Verdict is BENIGN with confidence STRONG or higher. "
                    "Eligible for auto-close but still requires acknowledgment."
                ),
                "check": self._check_high_confidence_benign_auto_close,
            },
        ]

    def register(self, policy: dict[str, Any]) -> None:
        """Register an additional policy dict with ``id``, ``name``,
        ``description``, and ``check`` keys."""
        required = {"id", "name", "description", "check"}
        if not required.issubset(policy.keys()):
            missing = required - policy.keys()
            raise ValueError(f"Policy missing required keys: {missing}")
        if not callable(policy["check"]):
            raise TypeError(
                f"Policy 'check' must be callable, got {type(policy['check']).__name__}"
            )
        self._policies.append(policy)

    async def evaluate(
        self,
        verdict: VerdictPacket,
        case_state: CaseState,
    ) -> list[PolicyGuardrail]:
        """Evaluate *verdict* against all registered policies."""
        triggered: list[PolicyGuardrail] = []
        for policy in self._policies:
            result = policy["check"](verdict, case_state)
            if result:
                triggered.append(
                    PolicyGuardrail(
                        id=policy["id"],
                        name=policy["name"],
                        description=policy["description"],
                        severity=result["severity"],
                        action_required=result.get("action_required"),
                    )
                )
        return triggered

    @staticmethod
    def _check_high_confidence_malicious(
        verdict: VerdictPacket, _case_state: CaseState
    ) -> dict[str, Any] | None:
        if verdict.decision == "MALICIOUS" and verdict.confidence >= Confidence.STRONG:
            return {
                "severity": "critical",
                "action_required": "Mandatory analyst review before any action.",
            }
        return None

    @staticmethod
    def _check_low_confidence_inconclusive(
        verdict: VerdictPacket, _case_state: CaseState
    ) -> dict[str, Any] | None:
        if verdict.decision == "INCONCLUSIVE" and verdict.confidence <= Confidence.WEAK:
            return {
                "severity": "warning",
                "action_required": "Re-route to Tracker for additional investigation.",
            }
        return None

    @staticmethod
    def _check_high_confidence_benign_auto_close(
        verdict: VerdictPacket, _case_state: CaseState
    ) -> dict[str, Any] | None:
        if verdict.decision == "BENIGN" and verdict.confidence >= Confidence.STRONG:
            return {
                "severity": "info",
                "action_required": "Analyst acknowledgment required before auto-close.",
            }
        return None
