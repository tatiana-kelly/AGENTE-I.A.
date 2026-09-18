"""DecisionProposal — proposta de decisão. NÃO é decisão aprovada.

Três objetos distintos, com nomes distintos e transições distintas:
  RecommendationBase  → o que a análise sugere (já existe em app/schemas/recommendation.py)
  DecisionProposal    → o que é levado a um humano (este módulo)
  Decision            → o que o humano aprovou (já existe em app/models/decision.py)

A proposta carrega `requires_human_approval=True` por construção e não possui nenhum campo de aprovação:
quem aprova é o ApprovalService, com ator humano. Uma proposta nunca vira decisão por mutação.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.decision_cycle.governance import Actor, ActorKind, GovernanceViolation
from app.decision_cycle.states import CaseState
from app.decision_router.contract import DecisionRoute
from app.schemas.diagnosis import DiagnosisBase
from app.schemas.enums import DecisionStatus, Effort, RecommendationType, Reversibility, Risk
from app.schemas.hypothesis import HypothesisBase
from app.schemas.recommendation import RecommendationBase

ProposalStatus = Literal["DRAFT", "WAITING_HUMAN_APPROVAL", "APPROVED", "REJECTED", "MORE_EVIDENCE_REQUIRED"]


class ProposalEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str
    ref: str
    sha256: str | None = None


class DecisionProposal(BaseModel):
    """Proposta rastreável: caso, diagnóstico, evidências, hipóteses, recomendação, prioridade, risco, prazo."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["sal.decision-proposal/1.0"] = "sal.decision-proposal/1.0"
    proposal_id: str
    case_id: str
    exact_fingerprint: str
    metric_id: str
    case_type: str
    created_at: datetime
    created_by: str  # ator máquina: quem propôs (nunca quem aprova)
    status: ProposalStatus = "WAITING_HUMAN_APPROVAL"
    state: CaseState = CaseState.WAITING_HUMAN_APPROVAL
    requires_human_approval: Literal[True] = True

    # diagnóstico e base analítica (estruturas existentes, não recriadas)
    diagnosis_id: str | None = None
    probable_cause: str
    confidence: float = Field(ge=0, le=100)
    diagnosis_status: DecisionStatus
    hypotheses: tuple[HypothesisBase, ...] = Field(min_length=1)
    evidence: tuple[ProposalEvidence, ...] = Field(min_length=1)
    missing_data: tuple[str, ...] = ()

    # o que se propõe fazer
    recommendation: RecommendationBase
    recommendation_type: RecommendationType
    suggested_action: str
    suggested_owner_role: str
    suggested_deadline: str
    expected_impact: str
    expected_impact_value: float | None = None
    effort: Effort
    risk: Risk
    reversibility: Reversibility
    success_kpi: str
    success_target: str

    # priorização (PriorityEngine existente)
    priority_score: float | None = None
    priority_label: str | None = None
    approval_flags: tuple[str, ...] = ()

    reason: str = Field(min_length=1, max_length=1000)
    source_route: Literal["REUSE_DECISION", "PLAYBOOK", "DIAGNOSIS"]
    reused_decision_id: str | None = None
    playbook_id: str | None = None

    @model_validator(mode="after")
    def proposal_is_never_an_approved_decision(self) -> "DecisionProposal":
        if self.status == "APPROVED" and self.state is not CaseState.APPROVED:
            raise GovernanceViolation("proposta aprovada exige estado APPROVED emitido pelo ApprovalService")
        if self.source_route == "REUSE_DECISION" and not self.reused_decision_id:
            raise GovernanceViolation("reuso exige a decisão aprovada de referência")
        if self.source_route == "PLAYBOOK" and not self.playbook_id:
            raise GovernanceViolation("proposta de playbook exige playbook_id")
        return self

    def is_approved(self) -> bool:
        """Sempre False: aprovação vive em ApprovedDecision, não na proposta."""
        return False


def build_proposal(
    *,
    case_id: str,
    exact_fingerprint: str,
    route: DecisionRoute,
    diagnosis: DiagnosisBase,
    recommendation: RecommendationBase,
    proposed_by: Actor,
    created_at: datetime,
    source_route: Literal["REUSE_DECISION", "PLAYBOOK", "DIAGNOSIS"] = "DIAGNOSIS",
    diagnosis_id: str | None = None,
    expected_impact_value: float | None = None,
    proposal_id: str | None = None,
) -> DecisionProposal:
    """Monta a proposta a partir do diagnóstico e da rota. A máquina PODE propor — e só isso."""
    if proposed_by.kind is not ActorKind.MACHINE and proposed_by.role is None:
        raise GovernanceViolation("propositor sem identidade válida")
    if recommendation not in diagnosis.recommendations:
        raise GovernanceViolation("a recomendação proposta precisa ser uma das 3 do diagnóstico")
    if diagnosis.decision_status is DecisionStatus.NEEDS_INVESTIGATION:
        raise GovernanceViolation("diagnóstico ainda em investigação não gera proposta")
    return DecisionProposal(
        proposal_id=proposal_id or str(uuid.uuid4()),
        case_id=case_id,
        exact_fingerprint=exact_fingerprint,
        metric_id=route.metric_id,
        case_type=route.case_type,
        created_at=created_at,
        created_by=proposed_by.id,
        diagnosis_id=diagnosis_id,
        probable_cause=diagnosis.probable_cause,
        confidence=diagnosis.confidence,
        diagnosis_status=diagnosis.decision_status,
        hypotheses=tuple(diagnosis.hypotheses),
        evidence=tuple(ProposalEvidence(kind=item.kind, ref=item.ref, sha256=item.sha256)
                       for item in route.evidence),
        missing_data=tuple(diagnosis.missing_data),
        recommendation=recommendation,
        recommendation_type=recommendation.type,
        suggested_action=recommendation.action,
        suggested_owner_role=recommendation.owner_role,
        suggested_deadline=recommendation.deadline,
        expected_impact=recommendation.expected_impact,
        expected_impact_value=expected_impact_value,
        effort=recommendation.effort,
        risk=recommendation.risk,
        reversibility=recommendation.reversibility,
        success_kpi=recommendation.success_kpi,
        success_target=recommendation.success_target,
        priority_score=route.priority.score,
        priority_label=route.priority.label,
        approval_flags=tuple(route.priority.triggered_gates),
        reason=route.reason,
        source_route=source_route,
        reused_decision_id=route.reused_decision_id,
        playbook_id=route.playbook.playbook_id if route.playbook else None,
    )
