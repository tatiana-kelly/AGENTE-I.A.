"""Gravação idempotente de rotas na memória do Router, controlada por modo explícito.

Modos:
- SHADOW_READ_ONLY (padrão): lê memória; nenhuma gravação, nenhuma estatística alterada.
- SHADOW_SIMULATED_PERSISTENCE: grava somente em repositório em memória do processo (testes/simulação).
- PERSIST: grava no repositório persistente; exige habilitação explícita. Nesta fase não há banco aprovado (D4).

O gravador nunca preenche decisão, aprovação, ação, verificação ou aprendizado: esses campos ficam
"none" até que o fluxo humano existente os registre. Nunca cria nem ativa playbook.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from app.decision_router.adapters.base import AdaptedAlert
from app.decision_router.bands import classify_band
from app.decision_router.contract import DecisionRoute
from app.decision_router.fingerprint import direction_of, dominant_dimension
from app.decision_router.memory.records import CaseRecord, PatternStatsRecord
from app.decision_router.memory.repository import (
    CaseMemoryRepository,
    InMemoryCaseMemoryRepository,
    MemoryWriteBlocked,
)
from app.decision_router.policy import RouterPolicy


class MemoryMode(StrEnum):
    SHADOW_READ_ONLY = "SHADOW_READ_ONLY"
    SHADOW_SIMULATED_PERSISTENCE = "SHADOW_SIMULATED_PERSISTENCE"
    PERSIST = "PERSIST"


_AI_ROUTES = {"ONE_AGENT", "MULTI_AGENT"}


def case_record_from_route(policy: RouterPolicy, adapted: AdaptedAlert, route: DecisionRoute,
                           now: datetime) -> CaseRecord:
    envelope = adapted.envelope
    metric = policy.metric(envelope.alert.metric_id)
    band = classify_band(metric, envelope)
    resolution = route.deterministic_resolution
    return CaseRecord(
        id=uuid.uuid5(uuid.NAMESPACE_URL, route.fingerprints.exact).hex,
        alert_id=adapted.alert_id,
        source=adapted.source,
        metric_id=route.metric_id,
        case_type=route.case_type,
        exact_fingerprint=route.fingerprints.exact,
        pattern_key=route.fingerprints.pattern_key,
        lineage_key=route.fingerprints.lineage_key,
        status=route.status,
        route=route.route,
        route_reason=route.reason,
        observed_at=envelope.evaluated_at,
        created_at=now,
        updated_at=now,
        period=envelope.alert.period,
        engine_source=envelope.engine_source,
        entity_type=envelope.entity_type,
        entity_id=envelope.entity_id,
        direction=direction_of(envelope),
        dominant_dimension=dominant_dimension(envelope),
        magnitude_band=band.label,
        rules_version=envelope.rules_version,
        approval_flags=tuple(sorted(set(metric.approval_flags) | set(envelope.approval_flags))),
        priority_score=route.priority.score,
        priority_label=route.priority.label,
        quality_passed=route.quality.passed,
        quality_score=route.quality.score,
        source_quality=envelope.alert.source_quality,
        selected_agents=tuple(agent.agent_name for agent in route.selected_agents),
        estimated_ai_calls=route.estimated_ai_calls,
        deterministic_outcome=resolution.outcome if resolution else None,
        reopen_count=route.loop_guard.reopen_count,
        evidence=tuple({"kind": item.kind, "ref": item.ref, "sha256": item.sha256} for item in route.evidence),
        route_payload=route.model_dump(mode="json"),
    )


def updated_stats(current: PatternStatsRecord | None, case: CaseRecord, now: datetime) -> PatternStatsRecord:
    base = current or PatternStatsRecord(pattern_key=case.pattern_key)
    return base.model_copy(update={
        "occurrences": base.occurrences + 1,
        "false_positives": base.false_positives + (1 if case.deterministic_outcome == "false_positive" else 0),
        "approved_decisions": base.approved_decisions + (1 if case.decision_status == "approved" else 0),
        "reuse_count": base.reuse_count + (1 if case.route == "REUSE_DECISION" else 0),
        "verified_ok": base.verified_ok + (1 if case.verification_status == "ok" else 0),
        "verified_fail": base.verified_fail + (1 if case.verification_status == "fail" else 0),
        "reopened": base.reopened + (1 if case.reopen_count > 0 else 0),
        "agent_calls": base.agent_calls + case.estimated_ai_calls,
        "ai_routed_cases": base.ai_routed_cases + (1 if case.route in _AI_ROUTES else 0),
        "last_seen_at": case.observed_at if base.last_seen_at is None else max(base.last_seen_at, case.observed_at),
        "rules_version": case.rules_version,
        "current_magnitude_band": case.magnitude_band,
        "updated_at": now,
    })


class MemoryRecorder:
    def __init__(self, policy: RouterPolicy, repository: CaseMemoryRepository,
                 mode: MemoryMode = MemoryMode.SHADOW_READ_ONLY, *, persist_enabled: bool = False,
                 clock=None) -> None:
        if mode is MemoryMode.SHADOW_SIMULATED_PERSISTENCE and not isinstance(repository, InMemoryCaseMemoryRepository):
            raise MemoryWriteBlocked("SHADOW_SIMULATED_PERSISTENCE só aceita repositório em memória do processo")
        if mode is MemoryMode.PERSIST and not persist_enabled:
            raise MemoryWriteBlocked("PERSIST exige habilitação explícita (persist_enabled=True)")
        self.policy = policy
        self.repository = repository
        self.mode = mode
        self._clock = clock
        self.inserted = 0
        self.duplicates = 0
        self.skipped_read_only = 0

    def record(self, adapted: AdaptedAlert, route: DecisionRoute) -> CaseRecord | None:
        now = self._clock() if self._clock else route.evaluated_at
        if self.mode is MemoryMode.SHADOW_READ_ONLY:
            self.skipped_read_only += 1
            return self.repository.get_by_exact(route.fingerprints.exact)
        case = case_record_from_route(self.policy, adapted, route, now)
        stored, created = self.repository.record_case(case)
        if not created:
            self.duplicates += 1
            return stored
        self.inserted += 1
        self.repository.save_pattern_stats(
            updated_stats(self.repository.get_pattern_stats(case.pattern_key), case, now)
        )
        return stored


class RepositoryRouteStore:
    """RouteStore sobre a memória: um alerta idêntico já gravado devolve a mesma rota (sem duplicar)."""

    def __init__(self, repository: CaseMemoryRepository) -> None:
        self._repository = repository

    def get_open(self, fingerprint_exact: str) -> DecisionRoute | None:
        case = self._repository.get_by_exact(fingerprint_exact)
        if case is None or case.route_payload is None:
            return None
        return DecisionRoute.model_validate(case.route_payload)

    def remember(self, route: DecisionRoute) -> None:
        """Gravação é responsabilidade do MemoryRecorder (que conhece o modo); aqui não há escrita."""
