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


def validate(node, schema, path="$") -> list[str]:
    """Validador mínimo (subset JSON Schema usado no contrato): type, const, enum, required,
    properties, additionalProperties, propertyNames, items, minimum/maximum, pattern."""
    errors: list[str] = []
    types = schema.get("type")
    if types:
        allowed = types if isinstance(types, list) else [types]
        mapping = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None),
                   "integer": int, "number": (int, float)}
        ok = any(isinstance(node, mapping[t]) and not (t in ("integer", "number") and isinstance(node, bool))
                 for t in allowed)
        if not ok:
            return [f"{path}: tipo {type(node).__name__} ∉ {allowed}"]
    if "const" in schema and node != schema["const"]:
        errors.append(f"{path}: {node!r} != const {schema['const']!r}")
    if "enum" in schema and node not in schema["enum"]:
        errors.append(f"{path}: {node!r} fora do enum")
    if isinstance(node, (int, float)) and not isinstance(node, bool):
        if "minimum" in schema and node < schema["minimum"]:
            errors.append(f"{path}: < minimum")
        if "maximum" in schema and node > schema["maximum"]:
            errors.append(f"{path}: > maximum")
    if isinstance(node, str) and "pattern" in schema and not re.search(schema["pattern"], node):
        errors.append(f"{path}: não casa pattern")
    if isinstance(node, dict):
        for key in schema.get("required", []):
            if key not in node:
                errors.append(f"{path}: falta {key}")
        props = schema.get("properties", {})
        for key, value in node.items():
            if FORBIDDEN.match(key):
                errors.append(f"{path}.{key}: chave proibida")
            if "propertyNames" in schema:
                errors.extend(validate(key, schema["propertyNames"], f"{path}.<key {key}>"))
            if key in props:
                errors.extend(validate(value, props[key], f"{path}.{key}"))
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}.{key}: propriedade não permitida")
            elif isinstance(schema.get("additionalProperties"), dict):
                errors.extend(validate(value, schema["additionalProperties"], f"{path}.{key}"))
    if isinstance(node, list) and "items" in schema:
        for i, item in enumerate(node):
            errors.extend(validate(item, schema["items"], f"{path}[{i}]"))
    return errors


def _object_nodes(schema, path="$"):
    if isinstance(schema, dict):
        if schema.get("type") == "object" or "properties" in schema:
            yield path, schema
        for key, value in schema.items():
            yield from _object_nodes(value, f"{path}.{key}")
    elif isinstance(schema, list):
        for i, value in enumerate(schema):
            yield from _object_nodes(value, f"{path}[{i}]")


class TestAutomationIncidentContract(unittest.TestCase):
    def test_example_is_valid_against_schema(self):
        self.assertEqual(validate(self.example, self.schema), [])

    def test_every_object_is_closed(self):
        """Nenhum objeto aceita chave livre — senão 'verified_ok' poderia entrar por ali."""
        for path, node in _object_nodes(self.schema):
            if path == "$":
                continue
            closed = node.get("additionalProperties") is False or "propertyNames" in node
            self.assertTrue(closed, f"objeto aberto em {path}")

    def test_forbidden_keys_rejected_at_any_depth(self):
        import copy
        injections = [
            lambda d: d.__setitem__("verified_ok", True),
            lambda d: d.__setitem__("approved_decision", {"id": 1}),
            lambda d: d.__setitem__("executeAction", "x"),
            lambda d: d["validation"].__setitem__("verified_ok", True),
            lambda d: d["diagnosis"].__setitem__("approvedDecision", True),
            lambda d: d["actual"]["criteria_results"].__setitem__("VERIFIED_OK", "pass"),
            lambda d: d["ai_review_signals"].__setitem__("should_call_ai", True),
            lambda d: d["authority"].__setitem__("can_approve_business_decision", True),
            lambda d: d["validation"].__setitem__("status", "VERIFIED_OK"),
        ]
        for inject in injections:
            doc = copy.deepcopy(self.example)
            inject(doc)
            self.assertNotEqual(validate(doc, self.schema), [], "injeção aceita indevidamente")

    def test_ai_signals_are_evidence_not_decision(self):
        signals = self.schema["properties"]["ai_review_signals"]
        self.assertEqual(set(signals["required"]), {"unknown_cause", "confidence", "conflicting_evidence",
                                                    "repeated_failure", "actions_attempted"})
        decision_like = re.compile(r"call|invoke|should|recommend|decide|trigger", re.IGNORECASE)
        for _, path in _keys(signals.get("properties", {})):
            self.assertIsNone(decision_like.search(path.split(".")[-1]), path)

    def test_routing_context_covers_decision_router_envelope(self):
        """Campos que o SAL OS precisa para montar AlertEnvelope (entity/period/rules_version/quality/missing_data)."""
        ctx = self.schema["properties"]["routing_context"]["required"]
        for field in ("entity_type", "entity_id", "period", "registry_version", "last_success_at", "missing_data",
                      "evidence_completeness_pct", "affected_outputs"):
            self.assertIn(field, ctx)

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
