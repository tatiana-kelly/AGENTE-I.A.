"""Ciclo de decisão governado (Fase 4): alerta → rota → diagnóstico → recomendação → proposta →
aprovação humana → decisão → ação → verificação → aprendizado → memória.

Reutiliza os modelos existentes do SAL OS (Diagnosis, Recommendation, Hypothesis, Decision,
ActionExecution, OrganizationalLearning, AuditTrail, RBAC, PriorityEngine, DataQualityGate,
MetricRegistry) e a memória do Decision Router (Fase 3). Nesta fase nada é executado.
"""

from app.decision_cycle.approval import ApprovalService, ApprovedDecision
from app.decision_cycle.governance import Actor, ActorKind, GovernanceViolation, human, machine
from app.decision_cycle.proposal import DecisionProposal, build_proposal
from app.decision_cycle.states import CaseState, IllegalTransition, assert_transition, can_transition

__all__ = [
    "Actor",
    "ActorKind",
    "ApprovalService",
    "ApprovedDecision",
    "CaseState",
    "DecisionProposal",
    "GovernanceViolation",
    "IllegalTransition",
    "assert_transition",
    "build_proposal",
    "can_transition",
    "human",
    "machine",
]
