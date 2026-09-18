"""Fluxo central (PRP §30):

SCHEDULER(Hermes cron) → GUARDIAN → incidente? → DIAGNOSTICIAN → reparo possível?
   não → ESCALATOR
   sim → REPAIRER → VALIDATOR → sucesso? sim → CLOSE | não → RETRY até o limite → ESCALATOR
"""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .adapters import CommandRunRecorder, GithubRunsProvider, SystemExecutor, WindowsTaskProvider
from .config import PACKAGE_ROOT, Settings
from .diagnostician import Diagnostician
from .escalator import Escalator
from .guardian import Guardian
from .models import (TERMINAL_STATES, CheckResult, CheckStatus, Diagnosis, IncidentType, Lifecycle, Outcome,
                     now_local)
from .notify import NotificationService
from .priority import compute_priority
from .registry import _render_vars, load_registry
from .repair import RepairAgent
from .store import Store
from .validator import Validator

AGENT = "hermes-orchestrator"


class Orchestrator:
    def __init__(self, settings: Settings, store: Store, automations: list[dict[str, Any]], guardian: Guardian,
                 diagnostician: Diagnostician, repair: RepairAgent, validator: Validator, escalator: Escalator,
                 notifier: NotificationService, clock: Callable[[], datetime] = now_local,
                 sleep: Callable[[float], None] = time.sleep):
        self.settings = settings
        self.store = store
        self.automations = automations
        self.guardian = guardian
        self.diagnostician = diagnostician
        self.repair = repair
        self.validator = validator
        self.escalator = escalator
        self.notifier = notifier
        self.clock = clock
        self.sleep = sleep

    # ------------------------------------------------------------------ build
    @classmethod
    def build(cls, settings: Settings, *, providers: dict[str, Any] | None = None, executor: Any = None,
              http_get: Any = None, clock: Callable[[], datetime] = now_local,
              sleep: Callable[[float], None] = time.sleep, channels: list[Any] | None = None,
              automations: list[dict[str, Any]] | None = None) -> "Orchestrator":
        store = Store(settings.state_dir / "autonomy.db")
        if automations is None:
            tokens = {"python": sys.executable.replace("\\", "/"), "app_root": str(PACKAGE_ROOT).replace("\\", "/"),
                      "state_dir": str(settings.state_dir).replace("\\", "/")}
            automations = [_render_vars(a, tokens) for a in load_registry(settings.registry_path)]
        providers = providers or {"windows_task": WindowsTaskProvider(), "github_actions": GithubRunsProvider(http_get),
                                  "command": CommandRunRecorder()}
        guardian = Guardian(settings, providers, http_get=http_get, clock=clock)
        notifier = NotificationService(settings, store, channels)
        return cls(settings, store, automations, guardian, Diagnostician(store),
                   RepairAgent(settings, store, executor or SystemExecutor(), guardian, clock, sleep),
                   Validator(settings, guardian, clock, sleep), Escalator(settings, store, notifier), notifier,
                   clock, sleep)

    def select(self, only: list[str] | None = None, include_disabled: bool = False) -> list[dict[str, Any]]:
        chosen = []
        for a in self.automations:
            if only and a["id"] not in only and a.get("group") not in only:
                continue
            if not a.get("enabled", True):
                if not (include_disabled and only):
                    continue
                a = {**a, "enabled": True}
            chosen.append(a)
        return chosen

    # -------------------------------------------------------------------- run
    def run(self, only: list[str] | None = None, mode: str = "tick", include_disabled: bool = False) -> dict[str, Any]:
        run_id = self.store.start_run(mode, self.settings.dry_run)
        summary: dict[str, Any] = {"run_id": run_id, "mode": mode, "dry_run": self.settings.dry_run,
                                   "live_repairs": self.settings.live_repairs_enabled, "checked": 0,
                                   "statuses": defaultdict(int), "incidents": [], "skipped_idempotent": []}
        work: list[tuple[dict[str, Any], CheckResult, dict[str, Any]]] = []
        for automation in self.select(only, include_disabled):
            check = self._safe_evaluate(automation)
            summary["checked"] += 1
            summary["statuses"][check.status] += 1
            self.store.record_check(run_id, check)
            if not check.is_incident:
                continue
            fingerprint = f"{automation['id']}|{check.slot}"
            existing = self.store.find_by_fingerprint(fingerprint)
            if existing and existing["state"] in TERMINAL_STATES:
                summary["skipped_idempotent"].append(existing["id"])  # já tratado nesta janela: não repetir
                continue
            incident = existing or self.store.create_incident(fingerprint, automation["id"], check.slot,
                                                              check.incident_type or "UNKNOWN_FAILURE",
                                                              json.dumps(check.to_dict(), default=str))
            self.store.transition(incident["id"], Lifecycle.CLASSIFIED.value, "hermes-guardian",
                                  f"{check.incident_type}: {'; '.join(check.findings[:2])}")
            work.append((automation, check, incident))

        diagnosed = []
        for automation, check, incident in work:
            self.store.transition(incident["id"], Lifecycle.DIAGNOSING.value, "hermes-diagnostician")
            diagnosis = self.diagnostician.diagnose(automation, check, incident["id"])
            self.store.update_incident(incident["id"], cause_code=diagnosis.cause_code, cause_key=diagnosis.cause_key,
                                       probable_cause=diagnosis.probable_cause, confidence=diagnosis.confidence,
                                       human_action=diagnosis.human_action_required,
                                       diagnosis_json=json.dumps(diagnosis.to_dict(), default=str))
            self.store.transition(incident["id"], Lifecycle.DIAGNOSED.value, "hermes-diagnostician",
                                  f"{diagnosis.cause_code} (confiança {diagnosis.confidence_label})")
            self.store.audit("hermes-diagnostician", "diagnose", diagnosis.probable_cause, diagnosis.cause_code,
                             automation=automation["id"], incident=incident["id"], tool="knowledge+memory",
                             validation="; ".join(diagnosis.evidence[:3]), dry_run=self.settings.dry_run)
            diagnosed.append((automation, check, incident, diagnosis))

        groups: dict[str, list] = defaultdict(list)
        for item in diagnosed:
            if not item[3].cause_key.endswith(f"@{item[0]['id']}"):
                groups[item[3].cause_key].append(item)
        roots = {key: members for key, members in groups.items() if len(members) >= 2}
        root_ids: dict[str, dict[str, Any]] = {}
        for key, members in roots.items():
            root_ids[key] = self._root_incident(key, members)

        root_members: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for automation, check, incident, diagnosis in diagnosed:
            affected = len(roots.get(diagnosis.cause_key, [])) or 1
            outcome, actions, reason = self._recover(automation, check, incident, diagnosis, affected)
            current = self.store.get_incident(incident["id"]) or incident
            entry = {"incident_id": incident["id"], "automation": automation["id"],
                     "automation_name": automation["name"], "type": current["type"],
                     "cause": diagnosis.cause_code, "priority": current.get("priority"), "outcome": outcome,
                     "reason": reason}
            summary["incidents"].append(entry)
            if outcome in (Outcome.AUTO_RECOVERED.value, Outcome.ALREADY_OK.value, Outcome.DELAY_RECORDED.value):
                continue
            if diagnosis.cause_key in root_ids:
                root_members[diagnosis.cause_key].append(entry)
                self.escalator.store.audit("hermes-escalator", "escalate_suppressed", "agrupado na causa raiz",
                                           root_ids[diagnosis.cause_key]["id"], automation=automation["id"],
                                           incident=incident["id"], dry_run=self.settings.dry_run)
            else:
                self.escalator.escalate(automation, current, check, diagnosis, actions, outcome, reason)

        for key, members in root_members.items():
            root = root_ids[key]
            diagnosis = roots[key][0][3]
            priority = compute_priority({"criticality": "high"}, IncidentType.ROOT_CAUSE_INCIDENT.value,
                                        affected=len(roots[key]), unresolved=True)
            self.store.update_incident(root["id"], priority=priority, outcome=Outcome.ESCALATED.value)
            self.escalator.escalate_root(root, members, diagnosis, priority)
            self.store.transition(root["id"], Lifecycle.ESCALATED.value, "hermes-escalator",
                                  f"{len(members)} impactos não resolvidos")
        for key, root in root_ids.items():
            if key not in root_members:
                self.store.update_incident(root["id"], outcome=Outcome.AUTO_RECOVERED.value, resolved_at=self._ts())
                self.store.transition(root["id"], Lifecycle.RESOLVED.value, AGENT, "todos os impactos recuperados")
        summary["root_causes"] = [{"id": r["id"], "cause_key": k, "members": len(roots[k])} for k, r in root_ids.items()]
        summary["statuses"] = dict(summary["statuses"])
        if (self.settings.data.get("outbox") or {}).get("enabled"):
            summary["outbox"] = self.emit_to_outbox([i["incident_id"] for i in summary["incidents"]])
        self.store.finish_run(run_id, summary)
        return summary

    # -------------------------------------------------------------- ponte (outbox local)
    def emit_to_outbox(self, incident_ids: list[str]) -> dict[str, int]:
        """Hermes → AUTOMATION_INCIDENT → outbox local validado. Sem consumidor, sem envio, sem IA."""
        from .contract import IncidentOutbox, build_event, registry_version
        outbox = IncidentOutbox(self.settings.state_dir / "events")
        reg = registry_version(self.settings.registry_path) if Path(self.settings.registry_path).exists() \
            else "registry@inline"
        by_id = {a["id"]: a for a in self.automations}
        counts: dict[str, int] = defaultdict(int)
        for incident_id in incident_ids:
            incident = self.store.get_incident(incident_id)
            if not incident or incident["is_root"] or incident["state"] not in TERMINAL_STATES:
                counts["SKIPPED"] += 1
                continue
            automation = by_id.get(incident["automation_id"])
            if automation is None:
                counts["SKIPPED"] += 1
                continue
            status, errors = outbox.emit(build_event(self.store, automation, incident_id, self.settings,
                                                     reg_version=reg, now=self.clock()))
            counts[status] += 1
            self.store.audit(AGENT, "outbox_emit", "AUTOMATION_INCIDENT local", status, automation=automation["id"],
                             incident=incident_id, tool="outbox", validation="; ".join(errors)[:500],
                             dry_run=self.settings.dry_run)
        return dict(counts)

    # -------------------------------------------------------------- helpers
    def _ts(self) -> str:
        return self.clock().isoformat()

    def _safe_evaluate(self, automation: dict[str, Any]) -> CheckResult:
        try:
            return self.guardian.evaluate(automation, now=self.clock())
        except Exception as exc:  # falha de coleta nunca vira "sucesso"
            return CheckResult(automation_id=automation["id"], status=CheckStatus.INSUFFICIENT_EVIDENCE.value,
                               checked_at=self._ts(), findings=[f"Erro ao coletar evidência: {type(exc).__name__}: {exc}"])

    def _root_incident(self, key: str, members: list) -> dict[str, Any]:
        stamp = self.clock()
        fingerprint = f"ROOT|{key}|{stamp:%Y-%m-%dT%H}"
        root = self.store.find_by_fingerprint(fingerprint) or self.store.create_incident(
            fingerprint, "*", members[0][1].slot, IncidentType.ROOT_CAUSE_INCIDENT.value,
            json.dumps({"cause_key": key, "members": [m[2]["id"] for m in members]}), is_root=True)
        diagnosis: Diagnosis = members[0][3]
        self.store.update_incident(root["id"], cause_code=diagnosis.cause_code, cause_key=key,
                                   probable_cause=diagnosis.probable_cause, confidence=diagnosis.confidence,
                                   human_action=diagnosis.human_action_required)
        for m in members:
            self.store.update_incident(m[2]["id"], root_cause_id=root["id"])
        self.store.audit(AGENT, "root_cause", f"{len(members)} incidentes com a mesma causa {key}", root["id"],
                         incident=root["id"], dry_run=self.settings.dry_run)
        return root

    def _close(self, incident: dict[str, Any], state: str, outcome: str, agent: str, note: str,
               resolution: str | None = None) -> None:
        now = self.clock()
        fields: dict[str, Any] = {"outcome": outcome}
        if state == Lifecycle.RESOLVED.value:
            detected = datetime.fromisoformat(incident["detected_at"])
            fields.update(resolved_at=now.isoformat(), resolution=resolution,
                          recovery_seconds=int((now - detected).total_seconds()))
        self.store.update_incident(incident["id"], **fields)
        self.store.transition(incident["id"], state, agent, note)

    def _recover(self, automation, check, incident, diagnosis: Diagnosis, affected: int) -> tuple[str, list[str], str]:
        priority = compute_priority(automation, check.incident_type or "", recurrence=diagnosis.recurrence,
                                    affected=affected, slot=check.slot, now=self.clock())
        self.store.update_incident(incident["id"], priority=priority)
        incident = self.store.get_incident(incident["id"]) or incident
        actions: list[str] = []

        if check.incident_type == IncidentType.DELAYED_EXECUTION.value:
            reason = (f"Executou com atraso, mas as saídas foram validadas ({check.validated_by()}). "
                      "Registrado para o relatório diário; nenhuma correção necessária.")
            self._close(incident, Lifecycle.RESOLVED.value, Outcome.DELAY_RECORDED.value, "hermes-validator", reason,
                        "atraso registrado")
            return Outcome.DELAY_RECORDED.value, actions, reason

        if diagnosis.human_action_required:
            reason = f"Correção automática não aplicável: {diagnosis.probable_cause}."
            self._escalate_state(incident, Outcome.ESCALATED_WITH_ACTION_REQUIRED.value, reason, priority, automation, check)
            return Outcome.ESCALATED_WITH_ACTION_REQUIRED.value, actions, reason

        decision = self.repair.plan(automation, diagnosis, check)
        if not decision.allowed:
            outcome = decision.outcome or Outcome.ESCALATED.value
            if outcome == Outcome.CIRCUIT_BREAKER_OPEN.value:
                self.store.update_incident(incident["id"], type=IncidentType.RECURRING_FAILURE.value)
                check.incident_type = IncidentType.RECURRING_FAILURE.value
            reason = f"Correção automática não executada: {decision.reason}."
            self._escalate_state(incident, outcome, reason, priority, automation, check)
            return outcome, actions, reason

        if not decision.live:
            attempt_id = self.store.begin_attempt(incident["id"], automation["id"], 0, decision.action, dry_run=True)
            if attempt_id:
                self.store.finish_attempt(attempt_id, "SIMULATED", "DRY_RUN")
            self.store.audit("hermes-repair-agent", decision.action, "DRY_RUN: executaria", "SIMULATED",
                             automation=automation["id"], incident=incident["id"], tool=decision.action,
                             risk_level="low", dry_run=True)
            actions.append(f"DRY_RUN: {decision.action} seria executada (autorizada pelo registry)")
            reason = (f"Modo DRY_RUN — nada foi alterado. Ação planejada: {decision.action}. "
                      "Para executar: DRY_RUN=false e AUTONOMOUS_REPAIR=true.")
            self._escalate_state(incident, Outcome.DRY_RUN_PLANNED.value, reason, priority, automation, check)
            return Outcome.DRY_RUN_PLANNED.value, actions, reason

        max_attempts = int(self.settings["max_repair_attempts"])
        backoff = self.settings["retry_backoff_seconds"]
        last_findings = ""
        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                decision = self.repair.plan(automation, diagnosis, check)
                if not decision.allowed:
                    last_findings = decision.reason
                    break
                self.sleep(backoff[min(attempt - 1, len(backoff) - 1)])
            current = self.repair.already_ok(automation)
            if current is not None:
                outcome = Outcome.ALREADY_OK.value if attempt == 1 else Outcome.AUTO_RECOVERED.value
                reason = f"Estado esperado já presente — validado por {current.validated_by()}. Nada reexecutado."
                self.store.audit("hermes-repair-agent", "idempotency_check", "já corrigido", outcome,
                                 automation=automation["id"], incident=incident["id"], tool="guardian",
                                 validation=current.validated_by(), dry_run=False)
                self._close(incident, Lifecycle.RESOLVED.value, outcome, "hermes-validator", reason,
                            "estado normalizado sem reexecução")
                return outcome, actions, reason
            self.store.transition(incident["id"], Lifecycle.REPAIRING.value, "hermes-repair-agent",
                                  f"{decision.action} tentativa {attempt}")
            started = self.clock()
            baseline = self.guardian.snapshot(automation, started)
            ok, detail = self.repair.execute(automation, decision.action, incident["id"], attempt)
            self.store.update_incident(incident["id"], attempts=attempt)
            actions.append(f"{decision.action} (tentativa {attempt}) → {'disparado' if ok else 'retornou erro'}: "
                           f"{detail[:160]}")
            if not ok and decision.action != "rerun_command":
                self.repair.finish("EXEC_FAILED", detail)  # não conseguiu nem disparar: nada a validar
                last_findings = detail
                continue
            self.store.transition(incident["id"], Lifecycle.VALIDATING.value, "hermes-validator", f"tentativa {attempt}")
            result = self.validator.validate(automation, since=started, baseline=baseline)
            if result.status == CheckStatus.SUCCESS.value:
                self.repair.finish("SUCCESS", result.validated_by())
                reason = f"Recuperado na tentativa {attempt}. Validado por {result.validated_by()}."
                self.store.audit("hermes-validator", "validate", "pós-reparo", "SUCCESS", automation=automation["id"],
                                 incident=incident["id"], tool="guardian", validation=result.validated_by(),
                                 dry_run=False)
                self._close(incident, Lifecycle.RESOLVED.value, Outcome.AUTO_RECOVERED.value, "hermes-validator",
                            reason, f"{decision.action} após {diagnosis.cause_code}")
                candidate = self.store.register_skill_candidate(diagnosis.cause_code, decision.action, automation["id"])
                self.store.audit(AGENT, "skill_candidate", "solução validada e reutilizável",
                                 f"{candidate['cause_code']}→{candidate['action']} (x{candidate['success_count']})",
                                 automation=automation["id"], incident=incident["id"], dry_run=False)
                return Outcome.AUTO_RECOVERED.value, actions, reason
            last_findings = "; ".join(result.findings[:3])
            self.repair.finish("FAILED", last_findings)
            actions.append(f"validação da tentativa {attempt}: FALHOU — {last_findings[:160]}")
            self.store.audit("hermes-validator", "validate", "pós-reparo", "FAILED", automation=automation["id"],
                             incident=incident["id"], tool="guardian", validation=last_findings, dry_run=False)
        attempts = (self.store.get_incident(incident["id"]) or {}).get("attempts") or 0
        reason = (f"Falha persiste após {attempts} tentativa(s) autorizada(s). "
                  f"Última evidência: {last_findings[:200]}")
        deps = ", ".join(automation.get("dependencies", [])) or "dependências da automação"
        diagnosis.recommended_action = (
            f"Recuperação automática ({decision.action}) já tentada {attempts}x sem sucesso. "
            f"Verificar {deps}: {diagnosis.probable_cause.lower()}. Após normalizar, reexecutar a automação.")
        self._escalate_state(incident, Outcome.ESCALATED.value, reason, priority, automation, check, unresolved=True)
        return Outcome.ESCALATED.value, actions, reason

    def _escalate_state(self, incident, outcome, reason, priority, automation, check, unresolved=False) -> None:
        if unresolved:
            priority = compute_priority(automation, check.incident_type or "", unresolved=True, slot=check.slot,
                                        now=self.clock())
            self.store.update_incident(incident["id"], priority=priority)
        self._close(self.store.get_incident(incident["id"]) or incident, Lifecycle.ESCALATED.value, outcome,
                    "hermes-escalator", reason)
