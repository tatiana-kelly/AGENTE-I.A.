"""Reabertura e escalonamento — apenas mecanismo lógico. Nada é enviado a ninguém nesta fase."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.decision_cycle.action_link import FollowUp
from app.decision_cycle.events import CycleEvent, CycleEventRecorder
from app.decision_cycle.governance import Actor
from app.decision_cycle.states import CaseState, assert_transition
from app.decision_cycle.verification import VerificationResult, VerificationVerdict
from app.schemas.enums import Severity

MAX_REOPEN = 2  # mesmo limite do loop_guard do Router (contract.LoopGuard)


class ReopenEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    reopen_count: int = Field(ge=1)
    reason: str = Field(min_length=1)
    evidence: tuple[str, ...] = ()
    created_at: datetime
    target_state: Literal[CaseState.INVESTIGATING, CaseState.PROPOSED]


class EscalationReason(StrEnum):
    OVERDUE = "prazo vencido"
    REPETITION = "repetição do padrão"
    ACTION_FAILURE = "falha de ação verificada"
    MATERIAL_RISK = "risco material"
    PERSISTENT_CONFLICT = "conflito persistente"
    MULTIPLE_REOPENS = "múltiplas reaberturas"


class EscalationEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    escalation_id: str
    case_id: str
    reason: EscalationReason
    detail: str
    severity: Severity
    owner: str
    created_at: datetime
    notified: Literal[False] = False  # nenhum canal é acionado nesta fase


@dataclass
class ReopenService:
    events: CycleEventRecorder

    def evaluate(self, result: VerificationResult, follow_up: FollowUp, actor: Actor, current_state: CaseState,
                 reopen_count: int, requires_follow_up: bool, now: datetime) -> ReopenEvent | None:
        """Reabre quando a verificação falhou ou faltou evidência E a regra do caso exige acompanhamento."""
        if result.verdict is VerificationVerdict.VERIFIED_OK or not requires_follow_up:
            return None
        target = (CaseState.PROPOSED if result.verdict is VerificationVerdict.VERIFIED_FAIL
                  else CaseState.INVESTIGATING)
        assert_transition(current_state, CaseState.REOPENED)
        event = ReopenEvent(
            case_id=follow_up.case_id, reopen_count=reopen_count + 1, reason=result.reason,
            evidence=result.evidence, created_at=now, target_state=target,
        )
        self.events.record(CycleEvent.CASE_REOPENED, actor, follow_up.case_id,
                           summary=f"reaberto ({result.verdict.value}): {result.reason}",
                           payload=event.model_dump(mode="json"))
        return event


@dataclass
class EscalationService:
    events: CycleEventRecorder

    def _emit(self, case_id: str, reason: EscalationReason, detail: str, severity: Severity, owner: str,
              actor: Actor, now: datetime) -> EscalationEvent:
        event = EscalationEvent(escalation_id=str(uuid.uuid4()), case_id=case_id, reason=reason, detail=detail,
                                severity=severity, owner=owner, created_at=now)
        self.events.record(CycleEvent.CASE_ESCALATED, actor, case_id,
                           summary=f"escalonado: {reason.value}", payload=event.model_dump(mode="json"))
        return event

    def evaluate(self, *, case_id: str, actor: Actor, now: datetime, owner: str,
                 follow_up: FollowUp | None = None, verification: VerificationResult | None = None,
                 reopen_count: int = 0, pattern_occurrences: int = 0, material_risk: bool = False,
                 persistent_conflict: bool = False) -> list[EscalationEvent]:
        events: list[EscalationEvent] = []
        if follow_up is not None and follow_up.refresh_overdue(now).overdue:
            events.append(self._emit(case_id, EscalationReason.OVERDUE,
                                     f"prazo {follow_up.due_at.isoformat()} vencido", Severity.HIGH, owner, actor, now))
        if verification is not None and verification.verdict is VerificationVerdict.VERIFIED_FAIL:
            events.append(self._emit(case_id, EscalationReason.ACTION_FAILURE, verification.reason,
                                     Severity.HIGH, owner, actor, now))
        if reopen_count > MAX_REOPEN:
            events.append(self._emit(case_id, EscalationReason.MULTIPLE_REOPENS,
                                     f"{reopen_count} reaberturas (limite {MAX_REOPEN})",
                                     Severity.CRITICAL, owner, actor, now))
        if pattern_occurrences >= 3:
            events.append(self._emit(case_id, EscalationReason.REPETITION,
                                     f"{pattern_occurrences} ocorrências do mesmo padrão",
                                     Severity.MEDIUM, owner, actor, now))
        if material_risk:
            events.append(self._emit(case_id, EscalationReason.MATERIAL_RISK, "risco material declarado",
                                     Severity.CRITICAL, owner, actor, now))
        if persistent_conflict:
            events.append(self._emit(case_id, EscalationReason.PERSISTENT_CONFLICT,
                                     "divergência não resolvida entre áreas", Severity.MEDIUM, owner, actor, now))
        return events
