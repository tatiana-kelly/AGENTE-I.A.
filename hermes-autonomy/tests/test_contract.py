"""Contrato AUTOMATION_INCIDENT (sal.automation-incident/1.0): coerência estrutural e governança.
Sem dependência de jsonschema — verifica o que o contrato exige e o que ele proíbe."""
from __future__ import annotations

import json
import re
import unittest

from hermes_autonomy.config import PACKAGE_ROOT
from hermes_autonomy.models import IncidentType, Lifecycle, Outcome

CONTRACTS = PACKAGE_ROOT / "contracts"
FORBIDDEN = re.compile(r"^(approved_?decision|execute_?action|executed_?action|verified_?ok)$", re.IGNORECASE)


def _keys(node, path=""):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key, f"{path}.{key}"
            yield from _keys(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _keys(value, f"{path}[{i}]")


class TestAutomationIncidentContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads((CONTRACTS / "automation_incident.v1.schema.json").read_text(encoding="utf-8"))
        cls.example = json.loads((CONTRACTS / "automation_incident.example.json").read_text(encoding="utf-8"))

    def test_required_fields_requested_by_governance(self):
        for field in ("event_id", "automation_id", "timestamp", "severity", "incident_type", "expected", "actual",
                      "evidence", "diagnosis", "confidence", "actions_attempted", "validation", "recurrence",
                      "requires_human", "requires_business_decision"):
            self.assertIn(field, self.schema["required"], field)

    def test_example_satisfies_required_and_no_extra_top_level_keys(self):
        props = set(self.schema["properties"])
        self.assertTrue(set(self.schema["required"]) <= set(self.example))
        self.assertTrue(set(self.example) <= props, set(self.example) - props)
        self.assertRegex(self.example["event_id"], self.schema["properties"]["event_id"]["pattern"])

    def test_enums_match_engine(self):
        props = self.schema["properties"]
        self.assertEqual(set(props["incident_type"]["enum"]), {t.value for t in IncidentType})
        self.assertEqual(set(props["lifecycle_state"]["enum"]), {s.value for s in Lifecycle})
        self.assertEqual(set(props["outcome"]["enum"]) - {None}, {o.value for o in Outcome})

    def test_no_business_decision_keys_anywhere(self):
        for document in (self.schema, self.example):
            offending = [path for key, path in _keys(document) if FORBIDDEN.match(key)]
            self.assertEqual(offending, [], offending)

    def test_authority_forbids_business_decision(self):
        authority = self.schema["properties"]["authority"]["properties"]
        for key in ("can_approve_business_decision", "can_execute_business_action", "can_declare_business_verified"):
            self.assertIs(authority[key]["const"], False)
            self.assertIs(self.example["authority"][key], False)
        self.assertEqual(self.schema["properties"]["validation"]["properties"]["scope"]["const"], "technical")


if __name__ == "__main__":
    unittest.main()
