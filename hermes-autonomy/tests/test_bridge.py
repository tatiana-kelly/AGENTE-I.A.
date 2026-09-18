"""Fase 3 — ponte Hermes → SAL OS (sem integração): contrato final, outbox local validado e
primeiro caso real (Torre — Fechar Dia 15h15, 0x80070005) como fixture. Nenhum reparo é executado."""
from __future__ import annotations

import copy
import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from hermes_autonomy.adapters import TaskInfo
from hermes_autonomy.config import PACKAGE_ROOT
from hermes_autonomy.contract import IncidentOutbox, event_id_for, validate_event
from hermes_autonomy.registry import load_registry

from support import Clock, FakeExecutor, FakeTasks, make_orchestrator

FIXTURE = Path(__file__).parent / "fixtures" / "fechar_dia_0x80070005"


def _get(event: dict, dotted: str):
    node = event
    for part in dotted.split("."):
        node = node[part]
    return node


class FecharDiaBase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="ha-bridge-"))
        self.evidence = json.loads((FIXTURE / "evidence.json").read_text(encoding="utf-8"))
        self.expected = json.loads((FIXTURE / "expected_event.json").read_text(encoding="utf-8"))
        registry = {a["id"]: a for a in load_registry(PACKAGE_ROOT / "registry" / "automations.json")}
        self.automation = copy.deepcopy(registry["torre-fechar-dia"])  # entrada REAL do registry
        logs = self.tmp / "logs"
        logs.mkdir()
        self.automation["checks"][0]["glob"] = str(logs).replace("\\", "/") + "/fechar_dia_15h_*.log"
        fs = self.evidence["filesystem"]
        log = logs / fs["latest_log"]
        log.write_text("Fechar dia 15h iniciado\n", encoding="utf-8")
        ts = datetime.fromisoformat(fs["latest_log_mtime"]).timestamp()
        os.utime(log, (ts, ts))
        ts_ = self.evidence["task_scheduler"]
        self.tasks = FakeTasks({ts_["task_name"]: TaskInfo(
            name=ts_["task_name"], state=ts_["state"], last_run=datetime.fromisoformat(ts_["last_run"]),
            last_result=ts_["last_task_result"])})
        self.clock = Clock(datetime.fromisoformat(self.evidence["observed_at"]))
        self.executor = FakeExecutor()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def orch(self, outbox: bool = True):
        return make_orchestrator(self.tmp / "state", [self.automation], self.clock, executor=self.executor,
                                 tasks=self.tasks, live=True, overrides={"outbox": {"enabled": outbox}})


class TestFecharDiaFixture(FecharDiaBase):
    def test_first_case_detected_diagnosed_escalated_without_repair(self):
        orch = self.orch()
        summary = orch.run()
        self.assertEqual(len(summary["incidents"]), 1)
        inc = summary["incidents"][0]
        self.assertEqual(inc["outcome"], "ESCALATED_WITH_ACTION_REQUIRED")
        self.assertEqual(self.executor.calls, [], "o reparo NÃO pode ser executado (mesmo em modo LIVE)")
        self.assertEqual(summary["outbox"], {"WRITTEN": 1})

    def test_outbox_event_matches_fixture_and_contract(self):
        orch = self.orch()
        orch.run()
        events = IncidentOutbox(self.tmp / "state" / "events").events()
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(validate_event(event), [])
        self.assertEqual(event["event_id"], event_id_for(event["incident_id"], "ESCALATED"))
        for key, value in self.expected.items():
            if key == "human_action_contains":
                self.assertIn(value, event["human_action"].lower())
            elif key == "routing_context.metric_id":
                self.assertNotIn("metric_id", event["routing_context"])
            else:
                self.assertEqual(_get(event, key), value, key)

    def test_outbox_is_idempotent_and_local_only(self):
        orch = self.orch()
        orch.run()
        second = orch.run()  # mesma janela: incidente já tratado → nada novo
        self.assertEqual(second["incidents"], [])
        events_dir = self.tmp / "state" / "events"
        self.assertEqual(len(IncidentOutbox(events_dir).events()), 1)
        self.assertEqual(sorted(p.name for p in events_dir.iterdir()), ["automation_incidents.jsonl"])
        status, _ = IncidentOutbox(events_dir).emit(IncidentOutbox(events_dir).events()[0])
        self.assertEqual(status, "DUPLICATE")

    def test_outbox_disabled_by_default(self):
        orch = self.orch(outbox=False)
        summary = orch.run()
        self.assertNotIn("outbox", summary)
        self.assertFalse((self.tmp / "state" / "events").exists())


class TestContractRules(FecharDiaBase):
    def _event(self) -> dict:
        orch = self.orch()
        orch.run()
        return IncidentOutbox(self.tmp / "state" / "events").events()[0]

    def test_metric_id_optional_absent_on_technical_incident(self):
        event = self._event()
        self.assertFalse(event["requires_business_decision"])
        self.assertNotIn("metric_id", event["routing_context"])
        self.assertEqual(validate_event(event), [])

    def test_metric_id_only_with_business_impact(self):
        event = self._event()
        event["routing_context"]["metric_id"] = "torre.painel_competencia_atualizado"
        self.assertTrue(any("metric_id" in e for e in validate_event(event)))
        event["requires_business_decision"] = True
        self.assertEqual(validate_event(event), [])

    def test_forbidden_keys_go_to_rejected_not_outbox(self):
        event = self._event()
        outbox = IncidentOutbox(self.tmp / "state" / "events")
        for key in ("verified_ok", "approved_decision", "execute_action"):
            bad = copy.deepcopy(event)
            bad["diagnosis"][key] = True
            status, errors = outbox.emit(bad)
            self.assertEqual(status, "REJECTED", key)
            self.assertTrue(any("PROIBIDA" in e for e in errors), key)
        self.assertEqual(len(outbox.events()), 1)
        self.assertEqual(len(outbox.rejected.read_text(encoding="utf-8").splitlines()), 3)

    def test_semantic_rules(self):
        event = self._event()
        for mutate, expected in [
            (lambda e: e.__setitem__("event_id", "sha256:" + "0" * 64), "event_id"),
            (lambda e: e["ai_review_signals"].__setitem__("confidence", 0.1), "confidence"),
            (lambda e: e["validation"].__setitem__("status", "TECHNICAL_OK"), "TECHNICAL_OK"),
            (lambda e: e.__setitem__("human_action", "token=abcdefghijklmnop123456"), "segredo"),
        ]:
            bad = copy.deepcopy(event)
            mutate(bad)
            self.assertTrue(any(expected in e for e in validate_event(bad)), expected)

    def test_published_example_is_valid(self):
        example = json.loads((PACKAGE_ROOT / "contracts" / "automation_incident.example.json").read_text(encoding="utf-8"))
        self.assertEqual(validate_event(example), [])


class TestBoundaries(unittest.TestCase):
    """Decision Router = único roteador de decisão empresarial; AI Orchestrator = único runtime de IA."""

    def _sources(self):
        return {p.name: p.read_text(encoding="utf-8") for p in (PACKAGE_ROOT / "hermes_autonomy").glob("*.py")}

    def test_hermes_does_not_route_business_decisions(self):
        import re
        forbidden = re.compile(r"decision_router|DecisionRouter|decision_cycle|agent_bridge|ApprovalService")
        for name, text in self._sources().items():
            self.assertIsNone(forbidden.search(text), name)

    def test_contract_module_has_no_transport(self):
        text = self._sources()["contract.py"]
        for token in ("urllib", "requests", "subprocess", "socket", "http.client", "smtplib"):
            self.assertNotIn(token, text)

    def test_outbox_disabled_in_shipped_config(self):
        shipped = json.loads((PACKAGE_ROOT / "config" / "autonomy.json").read_text(encoding="utf-8"))
        self.assertIs(shipped["outbox"]["enabled"], False)
        self.assertIs(shipped["dry_run"], True)
        self.assertIs(shipped["autonomous_repair"], False)


if __name__ == "__main__":
    unittest.main()
