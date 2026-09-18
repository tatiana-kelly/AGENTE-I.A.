"""Estados formais do caso e o mapeamento com os enums que JÁ existem no SAL OS.

Nada aqui substitui DecisionStatus, DecisionOutcome ou os campos de ActionExecution: CaseState é a visão
do ciclo, derivada desses estados existentes. As funções de mapeamento provam essa correspondência.
"""

from datetime import datetime
from enum import StrEnum

from app.decision_router.contract import DecisionRoute
from app.schemas.action_execution import ActionExecutionBase
from app.schemas.enums import DecisionOutcome, DecisionStatus


class CaseState(StrEnum):
    RECEIVED = "RECEIVED"
    GATED = "GATED"
    INVESTIGATING = "INVESTIGATING"
    DIAGNOSED = "DIAGNOSED"
    PROPOSED = "PROPOSED"
    WAITING_HUMAN_APPROVAL = "WAITING_HUMAN_APPROVAL"
    APPROVED = "APPROVED"
    ACTION_PENDING = "ACTION_PENDING"
    ACTION_EXECUTING = "ACTION_EXECUTING"
    ACTION_COMPLETED = "ACTION_COMPLETED"
    VERIFYING = "VERIFYING"
    VERIFIED_OK = "VERIFIED_OK"
    VERIFIED_FAIL = "VERIFIED_FAIL"
    LEARNED = "LEARNED"
    CLOSED = "CLOSED"
    REJECTED = "REJECTED"
    MORE_EVIDENCE_REQUIRED = "MORE_EVIDENCE_REQUIRED"
    OVERDUE = "OVERDUE"
    ESCALATED = "ESCALATED"
    REOPENED = "REOPENED"


#: Transições permitidas. Tudo que não está aqui é proibido — inclusive PROPOSED → ACTION_*.
TRANSITIONS: dict[CaseState, frozenset[CaseState]] = {
    CaseState.RECEIVED: frozenset({CaseState.GATED, CaseState.ESCALATED}),
    CaseState.GATED: frozenset({CaseState.INVESTIGATING, CaseState.CLOSED, CaseState.ESCALATED}),
    CaseState.INVESTIGATING: frozenset({CaseState.DIAGNOSED, CaseState.CLOSED, CaseState.ESCALATED,
                                        CaseState.OVERDUE}),
    CaseState.DIAGNOSED: frozenset({CaseState.PROPOSED, CaseState.CLOSED, CaseState.ESCALATED}),
    CaseState.PROPOSED: frozenset({CaseState.WAITING_HUMAN_APPROVAL, CaseState.ESCALATED}),
    CaseState.WAITING_HUMAN_APPROVAL: frozenset({CaseState.APPROVED, CaseState.REJECTED,
                                                 CaseState.MORE_EVIDENCE_REQUIRED, CaseState.OVERDUE,
                                                 CaseState.ESCALATED}),
    CaseState.APPROVED: frozenset({CaseState.ACTION_PENDING, CaseState.ESCALATED}),
    CaseState.ACTION_PENDING: frozenset({CaseState.ACTION_EXECUTING, CaseState.OVERDUE, CaseState.ESCALATED}),
    CaseState.ACTION_EXECUTING: frozenset({CaseState.ACTION_COMPLETED, CaseState.OVERDUE, CaseState.ESCALATED}),
    CaseState.ACTION_COMPLETED: frozenset({CaseState.VERIFYING, CaseState.ESCALATED}),
    CaseState.VERIFYING: frozenset({CaseState.VERIFIED_OK, CaseState.VERIFIED_FAIL, CaseState.REOPENED,
                                    CaseState.ESCALATED}),
    CaseState.VERIFIED_OK: frozenset({CaseState.LEARNED, CaseState.ESCALATED}),
    CaseState.VERIFIED_FAIL: frozenset({CaseState.LEARNED, CaseState.REOPENED, CaseState.ESCALATED}),
    CaseState.LEARNED: frozenset({CaseState.CLOSED, CaseState.REOPENED}),
    CaseState.CLOSED: frozenset({CaseState.REOPENED}),
    CaseState.REJECTED: frozenset({CaseState.CLOSED, CaseState.REOPENED, CaseState.ESCALATED}),
    CaseState.MORE_EVIDENCE_REQUIRED: frozenset({CaseState.INVESTIGATING, CaseState.CLOSED, CaseState.ESCALATED}),
    CaseState.OVERDUE: frozenset({CaseState.ESCALATED, CaseState.ACTION_EXECUTING, CaseState.ACTION_COMPLETED,
                                  CaseState.WAITING_HUMAN_APPROVAL, CaseState.INVESTIGATING, CaseState.CLOSED}),
    CaseState.ESCALATED: frozenset({CaseState.INVESTIGATING, CaseState.WAITING_HUMAN_APPROVAL, CaseState.CLOSED,
                                    CaseState.REOPENED}),
    CaseState.REOPENED: frozenset({CaseState.INVESTIGATING, CaseState.PROPOSED, CaseState.ESCALATED}),
}

#: Estados que só um humano pode alcançar (o resto da máquina é bloqueado em approval.py).
HUMAN_ONLY_STATES = frozenset({CaseState.APPROVED, CaseState.REJECTED, CaseState.MORE_EVIDENCE_REQUIRED})


class IllegalTransition(RuntimeError):
    pass


def can_transition(current: CaseState, target: CaseState) -> bool:
    return target in TRANSITIONS.get(current, frozenset())


def assert_transition(current: CaseState, target: CaseState) -> None:
    if not can_transition(current, target):
        raise IllegalTransition(f"transição proibida: {current} → {target}")


# ── mapeamentos com o que já existe ──────────────────────────────────────────────────────────

def state_from_route(route: DecisionRoute) -> CaseState:
    """DecisionRoute (Fase 1) → estado do ciclo. Nenhuma rota leva a APPROVED."""
    if route.status == "ESCALATED":
        return CaseState.ESCALATED
    if route.status == "BLOCKED_DATA":
        return CaseState.GATED
    if route.route in {"REUSE_DECISION", "NO_AGENT"} and route.next_step.action == "propose_decision":
        return CaseState.PROPOSED
    if route.route == "NO_AGENT":
        return CaseState.CLOSED if route.next_step.action == "close_case" else CaseState.GATED
    return CaseState.INVESTIGATING


#: Diagnosis.decision_status (existente) → estado do ciclo.
STATE_BY_DECISION_STATUS = {
    DecisionStatus.NEEDS_INVESTIGATION: CaseState.INVESTIGATING,
    DecisionStatus.READY_FOR_DECISION: CaseState.DIAGNOSED,
    DecisionStatus.CONTAINMENT_ONLY: CaseState.DIAGNOSED,
    DecisionStatus.HUMAN_APPROVAL_REQUIRED: CaseState.WAITING_HUMAN_APPROVAL,
}

#: Decision.decision (existente) → estado do ciclo.
STATE_BY_DECISION_OUTCOME = {
    DecisionOutcome.APPROVED: CaseState.APPROVED,
    DecisionOutcome.REJECTED: CaseState.REJECTED,
    DecisionOutcome.REQUEST_MORE_EVIDENCE: CaseState.MORE_EVIDENCE_REQUIRED,
}


def state_from_diagnosis_status(status: DecisionStatus) -> CaseState:
    return STATE_BY_DECISION_STATUS[status]


def state_from_decision_outcome(outcome: DecisionOutcome) -> CaseState:
    return STATE_BY_DECISION_OUTCOME[outcome]


def state_from_action(action: ActionExecutionBase, now: datetime) -> CaseState:
    """ActionExecution (existente) → estado. `outcome` sozinho NÃO produz VERIFIED_OK: isso é do Verifier."""
    if action.completed_at is not None:
        return CaseState.ACTION_COMPLETED
    if action.due_at is not None and now > action.due_at:
        return CaseState.OVERDUE
    if action.started_at is not None:
        return CaseState.ACTION_EXECUTING
    return CaseState.ACTION_PENDING
