"""Os 12 testes obrigatórios do PRP §38 + dry-run e guarda de entrega."""
from __future__ import annotations

import json
import unittest
from datetime import timedelta
from pathlib import Path

from hermes_autonomy.adapters import TaskInfo
from hermes_autonomy.models import CheckStatus, IncidentType, Outcome

from support import NOW, Clock, FakeExecutor, FakeTasks, Sandbox, make_orchestrator

RUN = NOW.replace(hour=7, minute=0, second=30)


class ScenarioBase(unittest.TestCase):
    def setUp(self) -> None:
        self.sb = Sandbox("job")
        self.state = self.sb.root / "state"
        self.clock = Clock()

    def tearDown(self) -> None:
        self.sb.cleanup()

    def orch(self, automations=None, **kw):
        return make_orchestrator(self.state, automations or [self.sb.automation()], self.clock, **kw)

    def evaluate(self, automation=None, tasks=None):
        automation = automation or self.sb.automation()
        orch = self.orch([automation], tasks=tasks)
        return orch.guardian.evaluate(automation, now=self.clock())


class TestPrpScenarios(ScenarioBase):
    def test_01_success(self):
        self.sb.good_run(RUN)
        result = self.evaluate()
        self.assertEqual(result.status, CheckStatus.SUCCESS.value)
        for criterion in ("PROCESS_STARTED", "PROCESS_FINISHED", "OUTPUT_EXISTS", "OUTPUT_VALID", "DATA_UPDATED",
                          "DELIVERY_COMPLETED"):
            self.assertIn(criterion, result.validated_by())

    def test_02_missed_execution(self):
        automation = self.sb.automation(source="windows_task", task_name="\\Job", checks=[])
        tasks = FakeTasks({"\\Job": TaskInfo(name="\\Job", state="Ready", last_run=NOW - timedelta(days=1),
                                             last_result=0)})
        result = self.evaluate(automation, tasks)
        self.assertEqual(result.incident_type, IncidentType.MISSED_EXECUTION.value)

    def test_03_partial_execution(self):
        automation = self.sb.automation(source="windows_task", task_name="\\Job")
        tasks = FakeTasks({"\\Job": TaskInfo(name="\\Job", state="Ready", last_run=RUN, last_result=0)})
        self.sb.good_run(RUN, finish=False, data=False)  # iniciou, gerou saída, parou no meio
        result = self.evaluate(automation, tasks)
        self.assertEqual(result.incident_type, IncidentType.PARTIAL_EXECUTION.value)

    def test_04_missing_output(self):
        self.sb.good_run(RUN, output=False)
        result = self.evaluate()
        self.assertEqual(result.incident_type, IncidentType.MISSING_OUTPUT.value)

    def test_05_data_not_updated(self):
        self.sb.good_run(RUN, data=False)
        from support import write
        write(self.sb.paths(RUN)["data"], "[]", NOW - timedelta(days=2))  # banco parado há 2 dias
        result = self.evaluate()
        self.assertEqual(result.incident_type, IncidentType.DATA_NOT_UPDATED.value)

    def test_06_api_failure(self):
        self.sb.failed_run(RUN, "POST /rest/v1/x: HTTP Error 503: Service Unavailable")
        result = self.evaluate()
        self.assertEqual(result.incident_type, IncidentType.API_FAILURE.value)
        self.assertEqual(result.cause_hint, "HTTP_5XX")

    def test_07_retry_resolves_auto_recovered(self):
        self.sb.failed_run(RUN, "sb_select: <urlopen error [WinError 10060] timed out>")
        executor = FakeExecutor(effect=lambda now: self.sb.good_run(now) or True, clock=self.clock)
        orch = self.orch(executor=executor, live=True)
        summary = orch.run()
        inc = summary["incidents"][0]
        self.assertEqual(inc["outcome"], Outcome.AUTO_RECOVERED.value)
        self.assertEqual(len(executor.calls), 1)
        stored = orch.store.get_incident(inc["incident_id"])
        self.assertEqual(stored["state"], "RESOLVED")
        self.assertEqual(stored["cause_code"], "NETWORK_TIMEOUT")
        self.assertIsNotNone(stored["recovery_seconds"])
        states = [e["to_state"] for e in orch.store.events(inc["incident_id"])]
        for state in ("DETECTED", "CLASSIFIED", "DIAGNOSING", "DIAGNOSED", "REPAIRING", "VALIDATING", "RESOLVED"):
            self.assertIn(state, states)
        self.assertEqual(orch.store.skill_candidates()[0]["action"], "rerun_command")
        # memória: "como resolvemos da última vez?"
        self.assertIn("rerun_command", orch.store.last_resolution("job", "NETWORK_TIMEOUT")["resolution"])

    def test_07b_repair_in_same_second_as_failure(self):
        """Regressão: falha e reparo no mesmo segundo — o Validador não pode ler a linha de ERRO antiga."""
        self.sb.failed_run(NOW, "<urlopen error [WinError 10060] timed out>")
        automation = self.sb.automation(schedule={"type": "daily", "times": ["10:00"]})

        def effect(now):
            self.sb.good_run(NOW)  # mesmo carimbo de tempo da falha
            return True

        clock = self.clock
        executor = FakeExecutor(effect=effect, clock=clock)
        orch = self.orch([automation], executor=executor, live=True)
        summary = orch.run()
        self.assertEqual(summary["incidents"][0]["outcome"], Outcome.AUTO_RECOVERED.value)
        self.assertEqual(len(executor.calls), 1)

    def test_08_retry_fails_escalated(self):
        self.sb.failed_run(RUN, "HTTP Error 503: Service Unavailable")
        executor = FakeExecutor(effect=lambda now: self.sb.failed_run(now, "HTTP Error 503") or False, clock=self.clock)
        orch = self.orch(executor=executor, live=True, overrides={"notification": {"channels": ["outbox"]}})
        summary = orch.run()
        inc = summary["incidents"][0]
        self.assertEqual(inc["outcome"], Outcome.ESCALATED.value)
        self.assertEqual(len(executor.calls), 3)  # max_repair_attempts
        stored = orch.store.get_incident(inc["incident_id"])
        self.assertEqual(stored["state"], "ESCALATED")
        self.assertEqual(stored["attempts"], 3)
        outbox = list((self.state / "outbox").glob("*.md"))
        self.assertEqual(len(outbox), 1)
        body = outbox[0].read_text(encoding="utf-8")
        for header in ("AUTOMAÇÃO:", "STATUS:", "HORÁRIO ESPERADO:", "PROBLEMA:", "DIAGNÓSTICO:",
                       "AÇÕES EXECUTADAS:", "RESULTADO:", "IMPACTO:", "AÇÃO NECESSÁRIA:", "TENTATIVAS:\n3"):
            self.assertIn(header, body)

    def test_09_root_cause_incident(self):
        automations = []
        for name in ("a", "b", "c"):
            sb = Sandbox(name)
            sb.root = self.sb.root
            sb.failed_run(RUN, "<urlopen error [WinError 10060] timed out>")
            automations.append(sb.automation())
        orch = self.orch(automations)
        summary = orch.run()
        self.assertEqual(len(summary["root_causes"]), 1)
        root = orch.store.get_incident(summary["root_causes"][0]["id"])
        self.assertEqual(root["type"], IncidentType.ROOT_CAUSE_INCIDENT.value)
        self.assertEqual(summary["root_causes"][0]["members"], 3)
        members = [orch.store.get_incident(i["incident_id"]) for i in summary["incidents"]]
        self.assertTrue(all(m["root_cause_id"] == root["id"] for m in members))
        audit = orch.store.audit_entries(limit=100)
        self.assertEqual(sum(1 for a in audit if a["action"] == "escalate_root"), 1)
        self.assertEqual(sum(1 for a in audit if a["action"] == "escalate"), 0)  # 1 alerta, não 3

    def test_10_idempotency(self):
        # (a) mesma janela processada duas vezes → nada é refeito
        self.sb.failed_run(RUN, "HTTP Error 503")
        orch = self.orch()
        first = orch.run()
        second = orch.run()
        self.assertEqual(len(first["incidents"]), 1)
        self.assertEqual(second["incidents"], [])
        self.assertEqual(second["skipped_idempotent"], [first["incidents"][0]["incident_id"]])
        # (b) já corrigido antes do reparo → ALREADY_OK, executor não chamado
        sb2 = Sandbox("fixed")
        sb2.root = self.sb.root
        sb2.failed_run(RUN, "HTTP Error 503")
        automation = sb2.automation()
        executor = FakeExecutor()
        orch2 = make_orchestrator(self.state, [automation], self.clock, executor=executor, live=True)
        check = orch2.guardian.evaluate(automation, now=self.clock())
        sb2.paths(RUN)["log"].unlink()
        sb2.good_run(RUN.replace(minute=5))  # o próprio retry nativo da automação resolveu
        incident = orch2.store.create_incident("fixed|x", "fixed", check.slot, check.incident_type, "{}")
        diagnosis = orch2.diagnostician.diagnose(automation, check, incident["id"])
        outcome, _, _ = orch2._recover(automation, check, incident, diagnosis, 1)
        self.assertEqual(outcome, Outcome.ALREADY_OK.value)
        self.assertEqual(executor.calls, [])

    def test_11_circuit_breaker(self):
        self.sb.failed_run(RUN, "HTTP Error 503")
        executor = FakeExecutor()
        orch = self.orch(executor=executor, live=True)
        for n in range(5):
            orch.store.create_incident(f"job|old{n}", "job", None, "API_FAILURE", "{}")
        summary = orch.run()
        inc = summary["incidents"][0]
        self.assertEqual(inc["outcome"], Outcome.CIRCUIT_BREAKER_OPEN.value)
        self.assertEqual(inc["type"], IncidentType.RECURRING_FAILURE.value)
        self.assertEqual(executor.calls, [])
        self.assertEqual(orch.store.get_circuit("job")["state"], "OPEN")

    def test_12_credential_missing_action_required(self):
        self.sb.failed_run(RUN, "variável CANARY_API_TOKEN não definida — abortando")
        executor = FakeExecutor()
        orch = self.orch(executor=executor, live=True, overrides={"notification": {"channels": ["outbox"]}})
        summary = orch.run()
        inc = summary["incidents"][0]
        self.assertEqual(inc["outcome"], Outcome.ESCALATED_WITH_ACTION_REQUIRED.value)
        self.assertEqual(executor.calls, [])
        stored = orch.store.get_incident(inc["incident_id"])
        self.assertIn("credencial", stored["human_action"].lower())
        body = next((self.state / "outbox").glob("*.md")).read_text(encoding="utf-8")
        self.assertIn("AÇÃO NECESSÁRIA", body)
        self.assertNotIn("CANARY_API_TOKEN=", body)


class TestSafetyRails(ScenarioBase):
    def test_dry_run_never_executes(self):
        self.sb.failed_run(RUN, "<urlopen error [WinError 10060] timed out>")
        executor = FakeExecutor()
        summary = self.orch(executor=executor).run()
        self.assertEqual(summary["incidents"][0]["outcome"], Outcome.DRY_RUN_PLANNED.value)
        self.assertEqual(executor.calls, [])

    def test_delivery_guard_blocks_duplicate_send(self):
        automation = self.sb.automation(rerun_guard="no_delivery")
        self.sb.good_run(RUN, data=False)  # e-mail já saiu, banco não atualizou
        executor = FakeExecutor()
        orch = self.orch([automation], executor=executor, live=True)
        check = orch.guardian.evaluate(automation, now=self.clock())
        check.cause_hint = "NETWORK_TIMEOUT"
        diagnosis = orch.diagnostician.diagnose(automation, check)
        decision = orch.repair.plan(automation, diagnosis, check)
        self.assertFalse(decision.allowed)
        self.assertIn("duplicaria", decision.reason)

    def test_unverified_idempotency_blocks_rerun(self):
        automation = self.sb.automation(idempotent="unverified")
        self.sb.failed_run(RUN, "HTTP Error 503")
        executor = FakeExecutor()
        summary = self.orch([automation], executor=executor, live=True).run()
        self.assertEqual(summary["incidents"][0]["outcome"], Outcome.ESCALATED.value)
        self.assertEqual(executor.calls, [])

    def test_action_not_in_registry_blocks(self):
        automation = self.sb.automation(allowed_recovery_actions=[])
        self.sb.failed_run(RUN, "HTTP Error 503")
        executor = FakeExecutor()
        summary = self.orch([automation], executor=executor, live=True).run()
        self.assertIn("não autorizada", summary["incidents"][0]["reason"])
        self.assertEqual(executor.calls, [])

    def test_rate_limit_repairs(self):
        self.sb.failed_run(RUN, "HTTP Error 503")
        executor = FakeExecutor()
        orch = self.orch(executor=executor, live=True, overrides={"rate_limits": {"repairs_per_hour": 0}})
        summary = orch.run()
        self.assertEqual(summary["incidents"][0]["outcome"], Outcome.RATE_LIMITED.value)
        self.assertEqual(executor.calls, [])

    def test_audit_log_has_required_fields(self):
        self.sb.failed_run(RUN, "<urlopen error [WinError 10060] timed out>")
        executor = FakeExecutor(effect=lambda now: self.sb.good_run(now) or True, clock=self.clock)
        orch = self.orch(executor=executor, live=True)
        orch.run()
        entry = next(a for a in orch.store.audit_entries() if a["agent"] == "hermes-repair-agent")
        for field in ("ts", "agent", "automation", "incident", "action", "reason", "tool", "result", "validation",
                      "risk_level"):
            self.assertIsNotNone(entry[field], field)

    def test_delayed_with_valid_outputs_is_recorded_not_repaired(self):
        automation = self.sb.automation(source="windows_task", task_name="\\Job", delay_tolerance_minutes=10)
        late = RUN + timedelta(minutes=90)
        tasks = FakeTasks({"\\Job": TaskInfo(name="\\Job", state="Ready", last_run=late, last_result=0)})
        self.sb.good_run(late)
        executor = FakeExecutor()
        summary = self.orch([automation], tasks=tasks, executor=executor, live=True).run()
        self.assertEqual(summary["incidents"][0]["type"], IncidentType.DELAYED_EXECUTION.value)
        self.assertEqual(summary["incidents"][0]["outcome"], Outcome.DELAY_RECORDED.value)
        self.assertEqual(executor.calls, [])

    def test_expired_repair_window_blocks_rerun(self):
        yesterday = RUN - timedelta(days=1)
        automation = self.sb.automation()
        self.sb.failed_run(yesterday, "HTTP Error 503")
        executor = FakeExecutor()
        clock_orch = self.orch([automation], executor=executor, live=True)
        self.clock.now = NOW  # janela de ontem 07:00 → 27h atrás
        automation["schedule"] = {"type": "daily", "times": ["07:00"], "weekdays": [yesterday.weekday()]}
        summary = clock_orch.run()
        self.assertIn("Janela de reparo expirada", summary["incidents"][0]["reason"])
        self.assertEqual(executor.calls, [])

    def test_windows_task_hung_and_access_denied(self):
        hung = self.sb.automation(source="windows_task", task_name="\\Hung", checks=[], max_duration_minutes=30)
        denied = self.sb.automation(id="denied", source="windows_task", task_name="\\Denied", checks=[])
        tasks = FakeTasks({
            "\\Hung": TaskInfo(name="\\Hung", state="Running", last_run=NOW - timedelta(minutes=90), last_result=0x41301),
            "\\Denied": TaskInfo(name="\\Denied", state="Ready", last_run=RUN, last_result=0x80070005),
        })
        hung["schedule"] = {"type": "daily", "times": ["08:30"]}
        orch = self.orch([hung, denied], tasks=tasks)
        r1 = orch.guardian.evaluate(hung, now=NOW)
        r2 = orch.guardian.evaluate(denied, now=NOW)
        self.assertEqual((r1.incident_type, r1.cause_hint), ("FAILED_EXECUTION", "TASK_HUNG"))
        self.assertEqual((r2.incident_type, r2.cause_hint), ("FAILED_EXECUTION", "TASK_ACCESS_DENIED"))
        diagnosis = orch.diagnostician.diagnose(denied, r2)
        self.assertIsNotNone(diagnosis.human_action_required)
        self.assertIsNone(diagnosis.auto_action)

    def test_running_within_limit_is_pending(self):
        automation = self.sb.automation(source="windows_task", task_name="\\Job")
        tasks = FakeTasks({"\\Job": TaskInfo(name="\\Job", state="Running", last_run=NOW - timedelta(minutes=2))})
        automation["schedule"] = {"type": "daily", "times": ["09:58"]}
        self.assertEqual(self.evaluate(automation, tasks).status, CheckStatus.PENDING.value)

    def test_no_evidence_never_declares_success(self):
        automation = self.sb.automation(source="github_actions", github="o/r:w.yml", checks=[])
        orch = self.orch([automation])
        orch.guardian.providers["github_actions"] = FakeTasks(
            {"o/r:w.yml": TaskInfo(name="x", extra={"unverifiable": "GITHUB_TOKEN ausente"})})
        result = orch.guardian.evaluate(automation, now=NOW)
        self.assertEqual(result.status, CheckStatus.INSUFFICIENT_EVIDENCE.value)


if __name__ == "__main__":
    unittest.main()
