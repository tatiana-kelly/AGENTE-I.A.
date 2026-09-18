"""Provedores do Router lidos da memória persistente (implementam os Protocols da Fase 1).

Mapeamentos conservadores:
- só decision_status='approved' vira decisão aprovada; 'proposed' não é decisão;
- só verification_status vira resultado; action_status='completed' sem verificação NÃO é resultado ok;
- playbook 'active' sem approved_by/approved_at é tratado como 'pending_approval' (V1 exige aprovação humana).
"""

from datetime import datetime

from app.decision_router.inputs import (
    PatternStats,
    Playbook,
    ReferenceAction,
    ReferenceCase,
    ReferenceDecision,
    ReferenceDiagnosis,
    ReferenceLearning,
)
from app.decision_router.memory.records import CaseRecord, PatternStatsRecord, PlaybookRecord
from app.decision_router.memory.repository import CaseMemoryRepository
from app.schemas.enums import DecisionOutcome, DecisionStatus, HypothesisStatus

_DECISION_OUTCOME = {
    "approved": DecisionOutcome.APPROVED,
    "rejected": DecisionOutcome.REJECTED,
    "request_more_evidence": DecisionOutcome.REQUEST_MORE_EVIDENCE,
}
_VERIFICATION_OUTCOME = {"ok": "ok", "partial": "partial", "fail": "fail"}


def reference_from_case(case: CaseRecord) -> ReferenceCase:
    decision = None
    if case.decision_id and case.decision_status in _DECISION_OUTCOME:
        decision = ReferenceDecision(decision_id=case.decision_id, outcome=_DECISION_OUTCOME[case.decision_status])
    diagnosis = None
    if case.diagnosis_confidence is not None and case.diagnosis_status in {status.value for status in DecisionStatus}:
        statuses = tuple(
            HypothesisStatus(item["status"]) for item in case.hypotheses
            if item.get("status") in {status.value for status in HypothesisStatus}
        )
        diagnosis = ReferenceDiagnosis(
            confidence=case.diagnosis_confidence,
            decision_status=DecisionStatus(case.diagnosis_status),
            hypothesis_statuses=statuses,
        )
    action = None
    if case.action_id:
        action = ReferenceAction(
            action_execution_id=case.action_id,
            outcome=_VERIFICATION_OUTCOME.get(case.verification_status),
            recurrence=case.recurrence,
        )
    learning = None
    if case.learning_id:
        learning = ReferenceLearning(
            learning_id=case.learning_id,
            predicted_impact=case.learning_predicted_impact,
            actual_impact=case.learning_actual_impact,
        )
    return ReferenceCase(
        case_id=case.id,
        period=case.period,
        evaluated_at=case.observed_at,
        engine_source=case.engine_source,
        direction=case.direction,
        magnitude_band=case.magnitude_band,
        dominant_dimension=case.dominant_dimension,
        rules_version=case.rules_version,
        approval_flags=case.approval_flags,
        reopen_count=case.reopen_count,
        diagnosis=diagnosis,
        decision=decision,
        action=action,
        learning=learning,
    )


def pattern_stats_for_router(record: PatternStatsRecord) -> PatternStats:
    return PatternStats(
        decisions_approved=record.approved_decisions,
        verified_ok=record.verified_ok,
        verified_fail=record.verified_fail,
        reopen_total=record.reopened,
        reuse_verified_fail=record.reuse_verified_fail,
        reuse_blocked=record.reuse_blocked,
        reuse_blocked_reason=record.reuse_blocked_reason,
    )


def playbook_for_router(record: PlaybookRecord) -> Playbook:
    status = record.status
    if status == "active" and (not record.approved_by or record.approved_at is None):
        status = "pending_approval"
    return Playbook(
        playbook_id=record.id,
        version=record.version,
        status=status,
        rules_version=record.rules_version,
        valid_from=record.valid_from,
        valid_until=record.valid_until,
    )


class MemorySimilarityCaseProvider:
    def __init__(self, repository: CaseMemoryRepository) -> None:
        self._repository = repository

    def find_reference(self, lineage_key: str, before: datetime) -> ReferenceCase | None:
        case = self._repository.latest_by_lineage(lineage_key, before)
        return reference_from_case(case) if case is not None else None


class MemoryPatternStatsProvider:
    def __init__(self, repository: CaseMemoryRepository) -> None:
        self._repository = repository

    def get(self, pattern_key: str) -> PatternStats | None:
        record = self._repository.get_pattern_stats(pattern_key)
        return pattern_stats_for_router(record) if record is not None else None


class MemoryPlaybookProvider:
    def __init__(self, repository: CaseMemoryRepository) -> None:
        self._repository = repository

    def get_current(self, pattern_key: str) -> Playbook | None:
        record = self._repository.get_current_playbook(pattern_key)
        return playbook_for_router(record) if record is not None else None
