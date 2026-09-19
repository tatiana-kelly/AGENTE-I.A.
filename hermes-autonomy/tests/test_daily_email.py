"""E-mail diário (decisão da Tatiana, 2026-09-19): um e-mail só com o que não rodou e não foi corrigido."""
import tempfile
import unittest
from pathlib import Path

from hermes_autonomy.config import load_settings
from hermes_autonomy.report import daily_report


class FakeStore:
    def __init__(self, checks, incidents=()):
        self._checks, self._incidents = checks, list(incidents)

    def latest_checks(self, _start):
        return self._checks

    def incidents(self, since=None, limit=100):
        return self._incidents

    def audit_entries(self, since=None, limit=100):
        return []


AUTOMATIONS = [{"id": "ok", "name": "Rodou bem", "enabled": True}, {"id": "falhou", "name": "Torre — Fechar Dia", "enabled": True},
               {"id": "corrigida", "name": "Importar SSW", "enabled": True}, {"id": "atrasada", "name": "Snapshot", "enabled": True}]


class TestDailyEmail(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = load_settings(config_path=str(Path(self.tmp.name) / "none.json"), state_dir=self.tmp.name,
                                      overrides={"notification": {"channels": ["outbox"]}})

    def tearDown(self):
        self.tmp.cleanup()

    def test_email_lista_so_o_que_nao_rodou_e_nao_foi_corrigido(self):
        checks = [{"automation_id": "ok", "status": "SUCCESS"},
                  {"automation_id": "falhou", "status": "INCIDENT", "incident_type": "TASK_FAILED", "priority": "P1"},
                  {"automation_id": "corrigida", "status": "SUCCESS"},
                  {"automation_id": "atrasada", "status": "INCIDENT", "incident_type": "DELAYED_EXECUTION"}]
        incidents = [{"is_root": False, "automation_id": "corrigida", "outcome": "AUTO_RECOVERED", "type": "TASK_FAILED",
                      "state": "RESOLVED", "cause_code": "x", "human_action": None, "priority": "P2", "probable_cause": None,
                      "id": "inc-1"}]
        report = daily_report(FakeStore(checks, incidents), AUTOMATIONS, self.settings)
        self.assertEqual(report["unresolved"], ["falhou"])
        body = report["email_text"]
        self.assertIn("Torre — Fechar Dia — TASK_FAILED", body)
        self.assertIn("corrigidas sozinhas: 1", body)
        for name in ("Rodou bem", "Importar SSW", "Snapshot"):
            self.assertNotIn(name, body)  # o que rodou, foi corrigido ou só atrasou não entra no e-mail

    def test_sem_pendencia_manda_uma_linha_de_confirmacao(self):
        report = daily_report(FakeStore([{"automation_id": "ok", "status": "SUCCESS"}]), AUTOMATIONS[:1], self.settings)
        self.assertEqual(report["unresolved"], [])
        self.assertIn("Nenhuma pendência", report["email_text"])

    def test_configuracao_envia_para_tatiana_as_10h(self):
        from hermes_autonomy.install import JOBS as CRON_JOBS
        repo_settings = load_settings()
        self.assertEqual(repo_settings["notification"]["email_agent"]["recipient"], "tatiana@salexpress.com.br")
        self.assertFalse(repo_settings["notification"]["external_enabled"])  # envio real só na ativação aprovada
        self.assertEqual(CRON_JOBS["hermes-autonomy-daily-report"][0], "0 10 * * *")


if __name__ == "__main__":
    unittest.main()
