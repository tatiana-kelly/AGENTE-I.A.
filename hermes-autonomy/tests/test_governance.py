"""Governança (Fase 2): Hermes = DETECT → DIAGNOSE → REPAIR → VALIDATE → RECORD, nada além."""
from __future__ import annotations

import re
import unittest

from hermes_autonomy.config import PACKAGE_ROOT
from hermes_autonomy.models import Diagnosis, Lifecycle, Outcome
from hermes_autonomy.registry import ACTION_RISK

from support import Clock, FakeExecutor, Sandbox, make_orchestrator

BUSINESS_STATES = re.compile(r"APPROVED|VERIFIED_OK|DECISION|EXECUTE_ACTION", re.IGNORECASE)
LOW_RISK_TECHNICAL = {"rerun_task", "rerun_command", "restart_task", "cleanup_temp", "validate_output"}


class TestGovernance(unittest.TestCase):
    def test_engine_vocabulary_has_no_business_decision_states(self):
        for value in [s.value for s in Lifecycle] + [o.value for o in Outcome]:
            self.assertIsNone(BUSINESS_STATES.search(value), value)

    def test_low_risk_actions_are_only_technical(self):
        self.assertEqual({a for a, r in ACTION_RISK.items() if r == "low"}, LOW_RISK_TECHNICAL)

    def test_risk_ceiling_cannot_be_raised_by_config(self):
        sb = Sandbox("gov")
        try:
            automation = sb.automation(allowed_recovery_actions=["adjust_timeout"])
            orch = make_orchestrator(sb.root / "state", [automation], Clock(), executor=FakeExecutor(), live=True,
                                     overrides={"max_repair_risk": "high"})
            diagnosis = Diagnosis(cause_code="X", probable_cause="x", evidence=[], confidence=0.9, impact="",
                                  recommended_action="", auto_action="adjust_timeout", risk="low", transient=True,
                                  human_action_required=None, cause_key="X@gov")
            check = orch.guardian.evaluate(automation)
            decision = orch.repair.plan(automation, diagnosis, check)
            self.assertFalse(decision.allowed)
            self.assertIn("risco baixo", decision.reason)
        finally:
            sb.cleanup()

    def test_engine_code_never_calls_ai(self):
        forbidden = re.compile(r"anthropic|openai|agent-runs|/orchestrate|chat\.completions|messages\.create",
                               re.IGNORECASE)
        for path in (PACKAGE_ROOT / "hermes_autonomy").glob("*.py"):
            self.assertIsNone(forbidden.search(path.read_text(encoding="utf-8")), path.name)

    def test_engine_code_has_no_business_approval_writes(self):
        forbidden = re.compile(r"verified_ok|approved_decision|execute_action|executed_action", re.IGNORECASE)
        for path in (PACKAGE_ROOT / "hermes_autonomy").glob("*.py"):
            self.assertIsNone(forbidden.search(path.read_text(encoding="utf-8")), path.name)


if __name__ == "__main__":
    unittest.main()
