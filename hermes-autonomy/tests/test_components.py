"""Testes de componentes: agenda, segmentação de log, redação, registry, prioridade, relatório, notificação."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from hermes_autonomy.config import PACKAGE_ROOT, load_settings
from hermes_autonomy.guardian import last_block_segment, since_run_segment
from hermes_autonomy.knowledge import match_causes
from hermes_autonomy.notify import Notification, NotificationService
from hermes_autonomy.priority import compute_priority
from hermes_autonomy.redact import looks_like_secret, redact
from hermes_autonomy.registry import RegistryError, load_registry
from hermes_autonomy.report import daily_report
from hermes_autonomy.store import Store
from hermes_autonomy.timeutil import last_slot

from support import LOCAL_TZ, NOW


def at(h: int, m: int, day: int = 18) -> datetime:
    return datetime(2026, 9, day, h, m, tzinfo=LOCAL_TZ)


class TestSchedule(unittest.TestCase):
    def test_daily_weekdays(self):
        sched = {"type": "daily", "times": ["06:00", "14:30"], "weekdays": "mon-fri"}
        self.assertEqual(last_slot(sched, at(10, 0)), at(6, 0))
        self.assertEqual(last_slot(sched, at(15, 0)), at(14, 30))
        # 20/09/2026 é domingo → última janela é sexta 18/09 14:30
        self.assertEqual(last_slot(sched, at(9, 0, day=20)), at(14, 30))

    def test_interval_window(self):
        sched = {"type": "interval", "every_minutes": 30, "anchor": "00:30", "window": ["00:30", "06:00"]}
        self.assertEqual(last_slot(sched, at(10, 0)), at(6, 0))
        self.assertEqual(last_slot(sched, at(3, 10)), at(3, 0))
        anchored = {"type": "interval", "every_minutes": 30, "anchor": "00:26"}
        self.assertEqual(last_slot(anchored, at(10, 50)), at(10, 26))

    def test_monthly_and_cron_utc(self):
        self.assertEqual(last_slot({"type": "monthly", "day": 1, "time": "07:00"}, at(10, 0)), at(7, 0, day=1))
        from datetime import timezone
        slot = last_slot({"type": "cron", "expr": "12 11,15 * * 1-5", "utc": True}, at(13, 0))
        candidates = [datetime(2026, 9, 18, h, 12, tzinfo=timezone.utc) for h in (11, 15)]
        self.assertEqual(slot, max(c for c in candidates if c <= at(13, 0)))

    def test_event_has_no_slot(self):
        self.assertIsNone(last_slot({"type": "event"}, at(10, 0)))


class TestLogSegments(unittest.TestCase):
    def test_since_run_start_stamped(self):
        text = ("2026-09-18 06:30:00  === inicio ===\n2026-09-18 06:30:05  ERRO antigo\nTraceback continua\n"
                "2026-09-18 14:00:00  === inicio ===\n2026-09-18 14:00:09  === fim ===\n")
        seg = since_run_segment(text, at(14, 0))
        self.assertNotIn("ERRO antigo", seg)
        self.assertNotIn("Traceback continua", seg)
        self.assertIn("=== fim ===", seg)

    def test_since_run_end_stamped(self):
        text = ("====\nlinha run 1\nFim 18/09/2026  9:56:03,10\n====\nlinha run 2\nTraceback x\n"
                "Fim 18/09/2026 10:26:02,37\n")
        seg = since_run_segment(text, at(10, 26))
        self.assertIn("linha run 2", seg)
        self.assertIn("Fim 18/09/2026 10:26", seg)
        self.assertNotIn("linha run 1", seg)

    def test_since_run_end_stamped_run_in_progress(self):
        text = "linha run 1\nFim 18/09/2026  9:56:03,10\nlinha run 2 sem fim\n"
        self.assertIn("linha run 2 sem fim", since_run_segment(text, at(10, 26)))

    def test_last_block(self):
        end = r"^\[REPORT\] \S+: (True|False).*$"
        text = "a\n[REPORT] x@y: False\nb\n[REPORT] x@y: True\n"
        self.assertNotIn("False", last_block_segment(text, end))
        self.assertIn("c crash", last_block_segment(text + "c crash\n", end))


class TestKnowledgeAndRedaction(unittest.TestCase):
    def test_cause_priority(self):
        hits = match_causes("ERROR x\n<urlopen error [WinError 10060] ...>\nNenhum registro lido.")
        self.assertEqual(hits[0][0].code, "NETWORK_TIMEOUT")
        self.assertEqual(match_causes("invalid_grant: Token has been expired or revoked")[0][0].code, "AUTH_EXPIRED")
        self.assertEqual(match_causes("ModuleNotFoundError: No module named 'x'")[0][0].code, "MODULE_MISSING")

    def test_redaction(self):
        raw = ("api_key=abcd1234efgh token: sk-abcdefghijklmnop Authorization: Bearer abc.def.ghijk "
               "ghp_ABCDEFGHIJKLMNOPQRSTUV postgres://user:pwd123@host/db")
        out = redact(raw)
        for secret in ("abcd1234efgh", "sk-abcdefghijklmnop", "ghp_ABCDEFGHIJKLMNOPQRSTUV", "pwd123"):
            self.assertNotIn(secret, out)
        self.assertIn("token expired", redact("token expired"))  # não destrói evidência textual

    def test_registry_secret_detection(self):
        self.assertTrue(looks_like_secret('{"api_key": "abcdefghijklmnop1234"}'))
        self.assertFalse(looks_like_secret('{"headers": {"apikey": "{env:SUPABASE_KEY}"}}'))


class TestRegistry(unittest.TestCase):
    def test_real_registries_are_valid(self):
        real = load_registry(PACKAGE_ROOT / "registry" / "automations.json")
        self.assertGreaterEqual(len([a for a in real if a["enabled"]]), 20)
        self.assertTrue(all(a.get("schedule") for a in real))
        self.assertEqual(len({a["id"] for a in real}), len(real))
        self.assertEqual(load_registry(PACKAGE_ROOT / "registry" / "sandbox.json")[0]["id"], "hermes-canary")

    def test_instances_expand(self):
        real = {a["id"]: a for a in load_registry(PACKAGE_ROOT / "registry" / "automations.json")}
        self.assertEqual(real["torre-importar-ssw-1630"]["task_name"], "\\Torre - Importar SSW 16h30")
        self.assertIn("_16-30.log", real["torre-importar-ssw-1630"]["checks"][0]["path"])

    def test_rejects_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.json"
            path.write_text(json.dumps({"automations": [
                {"id": "x", "name": "x", "source": "windows_task", "schedule": {"type": "event"}, "enabled": True,
                 "allowed_recovery_actions": ["drop_database"], "password": "supersecret12345"}]}))
            with self.assertRaises(RegistryError) as ctx:
                load_registry(path)
            message = str(ctx.exception)
            self.assertIn("task_name", message)
            self.assertIn("drop_database", message)
            self.assertIn("segredo", message)


class TestPriorityReportNotify(unittest.TestCase):
    def test_priority(self):
        self.assertEqual(compute_priority({"criticality": "critical"}, "FAILED_EXECUTION", recurrence=3), "P0")
        self.assertEqual(compute_priority({"criticality": "high"}, "API_FAILURE"), "P1")
        self.assertEqual(compute_priority({"criticality": "low"}, "DELAYED_EXECUTION"), "P3")

    def test_report_and_dedupe(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = load_settings(config_path=str(Path(tmp) / "none.json"), state_dir=tmp,
                                     overrides={"notification": {"channels": ["outbox"]}})
            store = Store(Path(tmp) / "autonomy.db")
            report = daily_report(store, [{"id": "a", "name": "A", "enabled": True}], settings)
            self.assertIn("HERMES AUTOMATION HEALTH", report["text"])
            self.assertEqual(report["counts"]["monitored"], 1)
            service = NotificationService(settings, store)
            note = Notification(kind="immediate", subject="s", body="token=abc123456789", dedupe_key="k1")
            first = service.notify(note)
            self.assertIn("outbox", first)
            self.assertNotIn("hermes_send", first)  # canal externo só existe se configurado
            self.assertEqual(service.notify(Notification(kind="immediate", subject="s", body="b", dedupe_key="k1")),
                             {"status": "DEDUPED"})
            body = next((Path(tmp) / "outbox").glob("*.md")).read_text(encoding="utf-8")
            self.assertNotIn("abc123456789", body)
            store.close()

    def test_external_channels_disabled_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = load_settings(config_path=str(Path(tmp) / "none.json"), state_dir=tmp,
                                     overrides={"notification": {"channels": ["outbox", "hermes_send"],
                                                                 "hermes_send_target": "whatsapp"}})
            store = Store(Path(tmp) / "autonomy.db")
            result = NotificationService(settings, store).notify(Notification(kind="immediate", subject="s", body="b"))
            self.assertTrue(result["hermes_send"].startswith("SKIPPED"))
            store.close()


if __name__ == "__main__":
    unittest.main()
