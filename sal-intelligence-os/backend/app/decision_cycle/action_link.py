"""Vínculo Decisão aprovada → ActionExecution EXISTENTE + acompanhamento (follow-up).

Não existe executor novo: esta camada só produz o ActionExecutionCreate (schema atual) a partir de uma
decisão aprovada. Nesta fase nada é executado — `link_action` nunca inicia nem conclui a ação.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.decision_cycle.approval import ApprovedDecision
from app.decision_cycle.events import CycleEvent, CycleEventRecorder
from app.decision_cycle.governance import Actor, GovernanceViolation
from app.decision_cycle.proposal import DecisionProposal
from app.decision_cycle.states import CaseState, state_from_action
from app.schemas.action_execution import ActionExecutionBase, ActionExecutionCreate
from app.schemas.enums import DecisionOutcome

FollowUpStatus = Literal["PENDING", "EXECUTING", "COMPLETED", "OVERDUE", "CANCELLED"]


class FollowUp(BaseModel):
    """Acompanhamento da ação: dono, prazo, resultado esperado × real, evidência, atraso e escalonamento.

    Sem scheduler novo: `refresh_overdue` é uma função pura que qualquer agendador existente
    (refresh_alertas / pg_cron) pode chamar quando isso for habilitado — nesta fase, ninguém chama sozinho.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    decision_id: str
    action_id: str
    owner: str = Field(min_length=1)
    due_at: datetime
    status: FollowUpStatus = "PENDING"
    expected_result: str = Field(min_length=1)
    expected_kpi: str
    expected_target: str
    actual_result: str | None = None
    evidence: tuple[str, ...] = ()
    overdue: bool = False
    escalated: bool = False

    def refresh_overdue(self, now: datetime) -> "FollowUp":
        late = self.status not in {"COMPLETED", "CANCELLED"} and now > self.due_at
        return self.model_copy(update={"overdue": late, "status": "OVERDUE" if late else self.status})


@dataclass
class ActionLinker:
    events: CycleEventRecorder

    def link_action(self, decision: ApprovedDecision, proposal: DecisionProposal, actor: Actor,
                    owner: str, due_at: datetime) -> tuple[ActionExecutionCreate, FollowUp]:
        """Só uma decisão APROVADA gera ActionExecution — e apenas o vínculo, sem execução."""
        if decision.outcome is not DecisionOutcome.APPROVED:
            raise GovernanceViolation(
                f"somente decisão aprovada gera ação; decisão {decision.decision_id} está {decision.outcome.value}")
        if decision.state is not CaseState.APPROVED:
            raise GovernanceViolation("decisão sem estado APPROVED não gera ação")
        if decision.proposal_id != proposal.proposal_id:
            raise GovernanceViolation("decisão e proposta não pertencem ao mesmo caso")
        if not owner.strip():
            raise GovernanceViolation("ação exige dono humano responsável")
        action = ActionExecutionCreate(
            decision_id=decision.decision_id, owner=owner, due_at=due_at,
            started_at=None, completed_at=None, evidence=[], actual_impact=None,
            outcome=None, recurrence=None,  # resultado só existe após verificação
        )
        follow_up = FollowUp(
            case_id=decision.case_id, decision_id=decision.decision_id, action_id=f"pending:{decision.decision_id}",
            owner=owner, due_at=due_at, expected_result=proposal.expected_impact,
            expected_kpi=proposal.success_kpi, expected_target=proposal.success_target,
        )
        self.events.record(CycleEvent.ACTION_LINKED, actor, decision.case_id,
                           summary=f"ação vinculada (não executada): {proposal.suggested_action}",
                           payload={"decision_id": decision.decision_id, "owner": owner,
                                    "due_at": due_at.isoformat(), "executed": False},
                           case_version=decision.case_version)
        return action, follow_up

    @staticmethod
    def state_of(action: ActionExecutionBase, now: datetime) -> CaseState:
        return state_from_action(action, now)
