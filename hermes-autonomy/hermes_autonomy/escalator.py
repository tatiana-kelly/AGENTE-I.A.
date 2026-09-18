"""hermes-escalator — chama a Tatiana só quando necessário, com mensagem acionável (nunca "falhou")."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .models import CheckResult, Diagnosis, Outcome
from .notify import Notification, NotificationService
from .priority import at_least

AGENT = "hermes-escalator"

TYPE_LABEL = {
    "MISSED_EXECUTION": "Não executou no horário esperado",
    "DELAYED_EXECUTION": "Executou com atraso",
    "FAILED_EXECUTION": "Execução falhou",
    "PARTIAL_EXECUTION": "Execução parcial (não concluiu todas as etapas)",
    "MISSING_OUTPUT": "Arquivo/saída esperada não foi gerada",
    "INVALID_OUTPUT": "Saída gerada é inválida",
    "DATA_NOT_UPDATED": "Banco/dado não foi atualizado",
    "DELIVERY_FAILURE": "Entrega (e-mail/publicação) não concluída",
    "AUTHENTICATION_FAILURE": "Falha de autenticação/credencial",
    "API_FAILURE": "API/serviço externo falhou",
    "DEPENDENCY_FAILURE": "Dependência ausente/quebrada",
    "RESOURCE_FAILURE": "Recurso da máquina esgotado/bloqueado",
    "UNKNOWN_FAILURE": "Falha sem causa identificada",
    "RECURRING_FAILURE": "Falha recorrente",
    "ROOT_CAUSE_INCIDENT": "Causa raiz comum a várias automações",
}


def _slot_label(slot: str | None) -> str:
    if not slot:
        return "sob demanda"
    dt = datetime.fromisoformat(slot)
    return f"{dt:%H:%M} ({dt:%d/%m/%Y})"


def format_escalation(automation: dict[str, Any], incident: dict[str, Any], check: CheckResult,
                      diagnosis: Diagnosis, actions: list[str], outcome: str, reason: str) -> str:
    status = {"ESCALATED_WITH_ACTION_REQUIRED": "🔴 NÃO RESOLVIDO — AÇÃO NECESSÁRIA",
              "CIRCUIT_BREAKER_OPEN": "🔴 NÃO RESOLVIDO — FALHA REPETIDA (circuit breaker aberto)",
              "DRY_RUN_PLANNED": "🟡 DETECTADO — modo DRY_RUN (nada foi alterado)"}.get(outcome, "🔴 NÃO RESOLVIDO")
    problem = TYPE_LABEL.get(check.incident_type or "", check.incident_type or "?")
    first = next((f for f in check.findings if f), "")
    lines = [
        f"AUTOMAÇÃO:\n{automation['name']}",
        f"STATUS:\n{status}",
        f"PRIORIDADE:\n{incident.get('priority') or '?'}",
        f"HORÁRIO ESPERADO:\n{_slot_label(check.slot)}",
        f"PROBLEMA:\n{problem}. {first}".strip(),
        f"DIAGNÓSTICO:\n{diagnosis.probable_cause} (confiança {diagnosis.confidence_label}; código {diagnosis.cause_code})",
        "EVIDÊNCIAS:\n" + ("\n".join(f"- {e}" for e in diagnosis.evidence[:5]) or "- (nenhuma)"),
        "AÇÕES EXECUTADAS:\n" + ("\n".join(f"{i}. {a}" for i, a in enumerate(actions, 1)) or "nenhuma"),
        f"RESULTADO:\n{reason}",
        f"IMPACTO:\n{diagnosis.impact}",
        f"AÇÃO NECESSÁRIA:\n{diagnosis.human_action_required or diagnosis.recommended_action}",
        f"LINK/REFERÊNCIA:\nIncidente {incident['id']} — detalhes: python -m hermes_autonomy incident {incident['id']}"
        + (f"\nScript: {automation['script']}" if automation.get("script") else ""),
        f"TENTATIVAS:\n{incident.get('attempts') or 0}",
    ]
    if diagnosis.recurrence:
        lines.append(f"HISTÓRICO:\n{diagnosis.recurrence} ocorrência(s) anterior(es) desta causa"
                     + (f"; última solução: {diagnosis.last_resolution}" if diagnosis.last_resolution else ""))
    return "\n\n".join(lines)


class Escalator:
    def __init__(self, settings, store, notifier: NotificationService):
        self.settings = settings
        self.store = store
        self.notifier = notifier

    def should_alert_now(self, priority: str, outcome: str) -> bool:
        if outcome == Outcome.DRY_RUN_PLANNED.value:
            return at_least(priority, "P0")  # em DRY_RUN só P0 vira alerta imediato; o resto vai ao relatório
        if outcome in (Outcome.ESCALATED_WITH_ACTION_REQUIRED.value, Outcome.CIRCUIT_BREAKER_OPEN.value):
            return True
        return at_least(priority, self.settings["notification"]["immediate_min_priority"])

    def escalate(self, automation, incident, check, diagnosis, actions, outcome, reason) -> dict[str, Any]:
        body = format_escalation(automation, incident, check, diagnosis, actions, outcome, reason)
        immediate = self.should_alert_now(incident.get("priority") or "P2", outcome)
        tag = "URGENTE" if incident.get("priority") == "P0" else (
            "AÇÃO NECESSÁRIA" if outcome == Outcome.ESCALATED_WITH_ACTION_REQUIRED.value else "ALERTA")
        note = Notification(kind="immediate" if immediate else "digest",
                            subject=f"[{incident.get('priority')}] {automation['name']}: "
                                    f"{TYPE_LABEL.get(check.incident_type or '', check.incident_type)}",
                            body=body, priority=incident.get("priority") or "P2", incident_id=incident["id"],
                            dedupe_key=f"esc:{incident['id']}", tag=tag)
        delivery = self.notifier.notify(note) if immediate else {"status": "QUEUED_FOR_DAILY_REPORT"}
        self.store.audit(AGENT, "escalate", reason, outcome, automation=automation["id"], incident=incident["id"],
                         tool="notification", validation=str(delivery), risk_level="low",
                         dry_run=self.settings.dry_run)
        return {"body": body, "immediate": immediate, "delivery": delivery}

    def escalate_root(self, root: dict[str, Any], members: list[dict[str, Any]], diagnosis: Diagnosis,
                      priority: str) -> dict[str, Any]:
        impacted = "\n".join(f"- {m['automation_name']} ({m['type']}) — {m['incident_id']}" for m in members)
        body = "\n\n".join([
            f"INCIDENTE RAIZ:\n{root['id']} — {diagnosis.cause_code}",
            f"STATUS:\n🔴 {len(members)} automações afetadas pela MESMA causa",
            f"PRIORIDADE:\n{priority}",
            f"DIAGNÓSTICO:\n{diagnosis.probable_cause} (confiança {diagnosis.confidence_label})",
            "EVIDÊNCIAS:\n" + "\n".join(f"- {e}" for e in diagnosis.evidence[:4]),
            f"IMPACTOS RELACIONADOS:\n{impacted}",
            f"AÇÃO NECESSÁRIA:\n{diagnosis.human_action_required or diagnosis.recommended_action}",
        ])
        note = Notification(kind="immediate", subject=f"[{priority}] Causa raiz comum: {diagnosis.probable_cause}",
                            body=body, priority=priority, incident_id=root["id"], dedupe_key=f"root:{root['id']}",
                            tag="URGENTE" if priority == "P0" else "ALERTA")
        immediate = self.settings.dry_run is False or at_least(priority, "P0")
        delivery = self.notifier.notify(note) if immediate else {"status": "QUEUED_FOR_DAILY_REPORT"}
        self.store.audit(AGENT, "escalate_root", f"{len(members)} impactos", "ESCALATED", incident=root["id"],
                         tool="notification", validation=str(delivery), dry_run=self.settings.dry_run)
        return {"body": body, "delivery": delivery}
