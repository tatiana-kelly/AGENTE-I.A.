"""Verificação de resultado. Nunca assume sucesso.

verify(action, expected_result, evidence) → VERIFIED_OK | VERIFIED_FAIL | INSUFFICIENT_EVIDENCE

- MetricRegistryVerifier usa o MetricRegistry existente: só decide quando a métrica é real e há medição.
- NoSourceVerifier é o padrão quando não há fonte: INSUFFICIENT_EVIDENCE, nunca OK.
Nenhuma métrica é inventada e nenhum limiar é assumido: sem alvo numérico registrado, não há veredito.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.decision_cycle.action_link import FollowUp
from app.decision_cycle.events import CycleEvent, CycleEventRecorder
from app.decision_cycle.governance import Actor
from app.decision_cycle.states import CaseState
from app.schemas.action_execution import ActionExecutionBase


class VerificationVerdict(StrEnum):
    VERIFIED_OK = "VERIFIED_OK"
    VERIFIED_FAIL = "VERIFIED_FAIL"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    verdict: VerificationVerdict
    reason: str = Field(min_length=1)
    metric_name: str | None = None
    measured_value: float | None = None
    target_value: float | None = None
    evidence: tuple[str, ...] = ()
    verified_at: datetime
    verifier: str

    @property
    def state(self) -> CaseState:
        if self.verdict is VerificationVerdict.VERIFIED_OK:
            return CaseState.VERIFIED_OK
        if self.verdict is VerificationVerdict.VERIFIED_FAIL:
            return CaseState.VERIFIED_FAIL
        return CaseState.VERIFYING  # sem evidência o caso não sai da verificação


class Verifier(Protocol):
    name: str

    def verify(self, action: ActionExecutionBase, expected_result: str,
               evidence: tuple[str, ...]) -> VerificationResult: ...


def _insufficient(reason: str, verifier: str, now: datetime, evidence: tuple[str, ...] = ()) -> VerificationResult:
    return VerificationResult(verdict=VerificationVerdict.INSUFFICIENT_EVIDENCE, reason=reason,
                              verified_at=now, verifier=verifier, evidence=evidence)


@dataclass
class NoSourceVerifier:
    """Sem conector real para a métrica do caso: o veredito é sempre falta de evidência."""

    clock: object = None
    name: str = "no-source"

    def verify(self, action: ActionExecutionBase, expected_result: str,
               evidence: tuple[str, ...]) -> VerificationResult:
        now = self.clock() if callable(self.clock) else datetime.now(UTC)
        return _insufficient("não há fonte de medição conectada para este resultado", self.name, now, evidence)


@dataclass
class MetricRegistryVerifier:
    """Usa uma medição real da métrica registrada. `measure` é o conector já existente do projeto."""

    registry: object  # MetricRegistry existente
    measure: object   # callable(metric_name, action) -> float | None
    clock: object = None
    name: str = "metric-registry"

    def verify(self, action: ActionExecutionBase, expected_result: str,
               evidence: tuple[str, ...]) -> VerificationResult:
        now = self.clock() if callable(self.clock) else datetime.now(UTC)
        metric = self.registry.get_by_name(expected_result)
        if metric is None:
            return _insufficient(f"métrica '{expected_result}' não está no MetricRegistry", self.name, now, evidence)
        target = getattr(metric, "target", None)
        if target is None:
            return _insufficient(f"métrica '{metric.name}' não tem alvo registrado", self.name, now, evidence)
        if not evidence:
            return _insufficient("ação sem evidência anexada", self.name, now, evidence)
        measured = self.measure(metric.name, action)
        if measured is None:
            return _insufficient(f"sem medição disponível para '{metric.name}'", self.name, now, evidence)
        ok = measured >= float(target)
        return VerificationResult(
            verdict=VerificationVerdict.VERIFIED_OK if ok else VerificationVerdict.VERIFIED_FAIL,
            reason=f"{metric.name}: medido {measured} contra alvo {target}",
            metric_name=metric.name, measured_value=float(measured), target_value=float(target),
            evidence=evidence, verified_at=now, verifier=self.name,
        )


@dataclass
class VerificationService:
    verifier: Verifier
    events: CycleEventRecorder

    def verify(self, follow_up: FollowUp, action: ActionExecutionBase, actor: Actor,
               case_version: int) -> VerificationResult:
        self.events.record(CycleEvent.VERIFICATION_STARTED, actor, follow_up.case_id,
                           summary=f"verificação de {follow_up.expected_kpi}",
                           payload={"action_id": follow_up.action_id}, case_version=case_version)
        evidence = tuple(action.evidence or ()) or follow_up.evidence
        if action.completed_at is None:
            result = _insufficient("ação não concluída: nada a verificar", self.verifier.name,
                                   datetime.now(UTC), evidence)
        else:
            result = self.verifier.verify(action, follow_up.expected_kpi, evidence)
        self.events.record(CycleEvent.VERIFICATION_COMPLETED, actor, follow_up.case_id,
                           summary=f"{result.verdict.value}: {result.reason}",
                           payload=result.model_dump(mode="json"), case_version=case_version)
        return result
