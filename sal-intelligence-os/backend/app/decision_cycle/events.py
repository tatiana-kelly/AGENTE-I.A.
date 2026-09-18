"""Eventos do ciclo gravados no AuditTrail EXISTENTE (app/services/audit_trail.py).

Nenhum mecanismo novo de auditoria: este módulo só nomeia os eventos e padroniza o payload
(case_id, versão do caso, ator, motivo) sobre o sink append-only que já existe.
"""

from dataclasses import dataclass
from enum import StrEnum

from app.decision_cycle.governance import Actor
from app.services.audit_trail import AuditEvent, AuditTrail


class CycleEvent(StrEnum):
    CASE_RECEIVED = "CaseReceived"
    ROUTE_SELECTED = "RouteSelected"
    DIAGNOSIS_CREATED = "DiagnosisCreated"
    RECOMMENDATION_CREATED = "RecommendationCreated"
    DECISION_PROPOSED = "DecisionProposed"
    DECISION_APPROVED = "DecisionApproved"
    DECISION_REJECTED = "DecisionRejected"
    MORE_EVIDENCE_REQUESTED = "MoreEvidenceRequested"
    ACTION_LINKED = "ActionLinked"
    ACTION_COMPLETED = "ActionCompleted"
    VERIFICATION_STARTED = "VerificationStarted"
    VERIFICATION_COMPLETED = "VerificationCompleted"
    CASE_REOPENED = "CaseReopened"
    CASE_ESCALATED = "CaseEscalated"
    LEARNING_RECORDED = "LearningRecorded"


#: Eventos que só podem ter ator humano.
HUMAN_EVENTS = frozenset({CycleEvent.DECISION_APPROVED, CycleEvent.DECISION_REJECTED,
                          CycleEvent.MORE_EVIDENCE_REQUESTED})


@dataclass
class CycleEventRecorder:
    """Grava eventos do ciclo no audit trail existente; `human_decision` mantém a taxonomia atual."""

    audit: AuditTrail

    def record(self, event: CycleEvent, actor: Actor, case_id: str, summary: str,
               payload: dict | None = None, case_version: int | None = None) -> AuditEvent:
        event_type = "human_decision" if event in HUMAN_EVENTS else "agent_call"
        body = {
            "cycle_event": event.value,
            "case_id": case_id,
            "actor_kind": actor.kind.value,
            "actor_role": actor.role.value if actor.role else None,
            "case_version": case_version,
            **(payload or {}),
        }
        return self.audit.record(event_type=event_type, actor=actor.id, summary=summary, payload=body)
