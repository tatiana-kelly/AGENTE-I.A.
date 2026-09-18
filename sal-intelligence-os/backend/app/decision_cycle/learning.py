"""Aprendizado organizacional do ciclo — só depois de decisão + ação + verificação.

Aprendizado NÃO é decisão e nunca cria aprovação: o registro produzido é um OrganizationalLearningCreate
(schema existente) mais os campos de desempenho do caso. Sem verificação explícita, não há aprendizado de
sucesso — INSUFFICIENT_EVIDENCE gera aprendizado de "não verificado", jamais de "funcionou".
"""

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.decision_cycle.approval import ApprovedDecision
from app.decision_cycle.events import CycleEvent, CycleEventRecorder
from app.decision_cycle.governance import Actor, GovernanceViolation
from app.decision_cycle.proposal import DecisionProposal
from app.decision_cycle.states import CaseState
from app.decision_cycle.verification import VerificationResult, VerificationVerdict
from app.schemas.action_execution import ActionExecutionBase
from app.schemas.enums import DecisionOutcome
from app.schemas.organizational_learning import OrganizationalLearningCreate


class LearningRecord(BaseModel):
    """O que o caso ensinou. `verified_result` é o único campo que afirma resultado."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    decision_id: str
    pattern_key: str
    decision_outcome: DecisionOutcome
    predicted_impact: float | None
    actual_impact: float | None
    verified_result: VerificationVerdict
    recurrence: bool | None
    agent_usefulness: float | None = Field(default=None, ge=0, le=100)
    human_feedback: str | None = None
    lesson: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=100)
    created_at: datetime
    state: CaseState = CaseState.LEARNED

    def to_learning_create(self, pattern: str, intervention: str, conditions: str | None = None
                           ) -> OrganizationalLearningCreate:
        """Converte para o schema organizacional existente, sem duplicar o modelo."""
        return OrganizationalLearningCreate(
            pattern=pattern, intervention=intervention, predicted_impact=self.predicted_impact,
            actual_impact=self.actual_impact, conditions=conditions, lesson=self.lesson,
            confidence=self.confidence,
        )

    def enables_reuse(self) -> bool:
        """Condição futura de reuso — informativa. Nesta fase nada é ativado automaticamente."""
        return (self.decision_outcome is DecisionOutcome.APPROVED
                and self.verified_result is VerificationVerdict.VERIFIED_OK
                and self.recurrence is False)


@dataclass
class LearningService:
    events: CycleEventRecorder

    def record(self, *, proposal: DecisionProposal, decision: ApprovedDecision, action: ActionExecutionBase,
               verification: VerificationResult, pattern_key: str, actor: Actor, now: datetime,
               agent_usefulness: float | None = None, human_feedback: str | None = None,
               confidence: float = 50.0) -> LearningRecord:
        if action.completed_at is None:
            raise GovernanceViolation("aprendizado exige ação concluída")
        if verification.verdict is VerificationVerdict.VERIFIED_OK and not verification.evidence:
            raise GovernanceViolation("não se registra sucesso sem evidência de verificação")
        lesson = {
            VerificationVerdict.VERIFIED_OK: f"{proposal.suggested_action}: resultado verificado ok",
            VerificationVerdict.VERIFIED_FAIL: f"{proposal.suggested_action}: resultado verificado como falha",
            VerificationVerdict.INSUFFICIENT_EVIDENCE:
                f"{proposal.suggested_action}: sem evidência suficiente — resultado NÃO comprovado",
        }[verification.verdict]
        record = LearningRecord(
            case_id=proposal.case_id, decision_id=decision.decision_id, pattern_key=pattern_key,
            decision_outcome=decision.outcome, predicted_impact=proposal.expected_impact_value,
            actual_impact=action.actual_impact, verified_result=verification.verdict,
            recurrence=action.recurrence, agent_usefulness=agent_usefulness, human_feedback=human_feedback,
            lesson=f"{lesson} ({verification.reason})", confidence=confidence, created_at=now,
        )
        self.events.record(CycleEvent.LEARNING_RECORDED, actor, proposal.case_id, summary=record.lesson,
                           payload={"verified_result": verification.verdict.value,
                                    "enables_future_reuse": record.enables_reuse(),
                                    "creates_approval": False},
                           case_version=decision.case_version)
        return record
