"""Aprovação humana de propostas. Serviço/contrato de backend — sem UI.

approve_proposal / reject_proposal / request_more_evidence exigem, cada uma:
identidade humana, papel com poder de decisão (RBAC existente), motivo, timestamp, versão do caso e auditoria.
Nenhuma delas aceita ator máquina, e não existe caminho de aprovação automática.
A decisão aprovada sai como DecisionCreate (schema existente) — persistir é responsabilidade de quem chama,
em modo explicitamente habilitado.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.decision_cycle.events import CycleEvent, CycleEventRecorder
from app.decision_cycle.governance import Actor, GovernanceViolation, require_approval_role
from app.decision_cycle.proposal import DecisionProposal
from app.decision_cycle.states import CaseState, assert_transition
from app.schemas.decision import DecisionCreate
from app.schemas.enums import DecisionOutcome


class ApprovedDecision(BaseModel):
    """Resultado de uma aprovação humana — o único objeto que autoriza uma ação."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision_id: str
    proposal_id: str
    case_id: str
    recommendation_id: str
    outcome: DecisionOutcome
    human_owner: str
    human_role: str
    rationale: str = Field(min_length=1)
    decided_at: datetime
    case_version: int
    state: CaseState

    def to_decision_create(self) -> DecisionCreate:
        """Converte para o schema existente (app/schemas/decision.py), sem duplicar o modelo."""
        return DecisionCreate(
            recommendation_id=self.recommendation_id,
            decision=self.outcome,
            human_owner=self.human_owner,
            rationale=self.rationale,
        )


@dataclass
class ApprovalService:
    events: CycleEventRecorder
    clock: object = None  # callable() -> datetime; injetado nos testes

    def _now(self) -> datetime:
        return self.clock() if callable(self.clock) else datetime.now(UTC)

    def _decide(self, proposal: DecisionProposal, actor: Actor, rationale: str, outcome: DecisionOutcome,
                recommendation_id: str, case_version: int, event: CycleEvent,
                target: CaseState) -> ApprovedDecision:
        operation = f"{outcome.value} da proposta {proposal.proposal_id}"
        require_approval_role(actor, operation)
        if not rationale or not rationale.strip():
            raise GovernanceViolation(f"{operation} exige motivo registrado")
        if proposal.status != "WAITING_HUMAN_APPROVAL":
            raise GovernanceViolation(f"proposta em {proposal.status} não está aguardando aprovação")
        assert_transition(proposal.state, target)
        decided_at = self._now()
        decision = ApprovedDecision(
            decision_id=str(uuid.uuid4()), proposal_id=proposal.proposal_id, case_id=proposal.case_id,
            recommendation_id=recommendation_id, outcome=outcome, human_owner=actor.id,
            human_role=actor.role.value, rationale=rationale.strip(), decided_at=decided_at,
            case_version=case_version, state=target,
        )
        self.events.record(
            event, actor, proposal.case_id,
            summary=f"{outcome.value}: {proposal.suggested_action}",
            payload={"proposal_id": proposal.proposal_id, "decision_id": decision.decision_id,
                     "rationale": decision.rationale, "decided_at": decided_at.isoformat(),
                     "recommendation_id": recommendation_id, "outcome": outcome.value},
            case_version=case_version,
        )
        return decision

    def approve_proposal(self, proposal: DecisionProposal, actor: Actor, rationale: str,
                         recommendation_id: str, case_version: int) -> ApprovedDecision:
        return self._decide(proposal, actor, rationale, DecisionOutcome.APPROVED, recommendation_id,
                            case_version, CycleEvent.DECISION_APPROVED, CaseState.APPROVED)

    def reject_proposal(self, proposal: DecisionProposal, actor: Actor, rationale: str,
                        recommendation_id: str, case_version: int) -> ApprovedDecision:
        return self._decide(proposal, actor, rationale, DecisionOutcome.REJECTED, recommendation_id,
                            case_version, CycleEvent.DECISION_REJECTED, CaseState.REJECTED)

    def request_more_evidence(self, proposal: DecisionProposal, actor: Actor, rationale: str,
                              recommendation_id: str, case_version: int) -> ApprovedDecision:
        return self._decide(proposal, actor, rationale, DecisionOutcome.REQUEST_MORE_EVIDENCE, recommendation_id,
                            case_version, CycleEvent.MORE_EVIDENCE_REQUESTED, CaseState.MORE_EVIDENCE_REQUIRED)
