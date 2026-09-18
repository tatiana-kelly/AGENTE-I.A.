"""As 8 portas do Knowledge Gate como funções puras.

Nenhuma porta chama IA, lê rede ou grava estado: recebem dados já carregados e devolvem um resultado
com trace estruturado. A ordem e a parada ficam em router.py.
"""

from dataclasses import dataclass
from datetime import timedelta

from app.decision_router.bands import BandResult
from app.decision_router.contract import (
    DeterministicResolution,
    GateTraceEntry,
    NextStep,
    QualityStatus,
    Route,
    SelectedAgent,
    SimilarityReference,
)
from app.decision_router.fingerprint import direction_of, dominant_dimension, source_quality_class
from app.decision_router.inputs import AlertEnvelope, MemoryEntry, PatternStats, Playbook, ReferenceCase
from app.decision_router.policy import CHALLENGER, INVESTIGATOR, MetricPolicy, ReusePolicy
from app.schemas.enums import DecisionOutcome, DecisionStatus, HypothesisStatus
from app.services.data_quality_gate import DataQualityGate

ACCEPTED_SOURCE_CLASSES = {"real", "partial"}


def _trace(gate: str, result: str, reason: str, rule_ref: str | None = None) -> GateTraceEntry:
    return GateTraceEntry(gate=gate, result=result, reason=reason[:500], rule_ref=rule_ref)


# 1 ─ qualidade ──────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class QualityOutcome:
    trace: GateTraceEntry
    status: QualityStatus
    blocked: bool


def quality_gate(envelope: AlertEnvelope, gate: DataQualityGate, minimum: int) -> QualityOutcome:
    alert = envelope.alert
    record = {
        "metric_id": alert.metric_id,
        "title": alert.title,
        "period": alert.period,
        "source_quality": alert.source_quality,
        "concentration": alert.concentration,  # .claude/rules/alert-contract.md: todo alerta aponta concentração
    }
    checks = [gate.check_completeness(record, list(record))]
    source_class = source_quality_class(envelope)
    checks.append(
        (True, "fonte aceita")
        if source_class in ACCEPTED_SOURCE_CLASSES
        else (False, f"source_quality={source_class} não é aceita em produção")
    )
    inputs = envelope.quality_inputs
    if inputs and inputs.last_updated_at and inputs.max_age_hours:
        # mesma regra de DataQualityGate.check_freshness, com o relógio da avaliação (determinístico)
        age = envelope.evaluated_at - inputs.last_updated_at
        limit = timedelta(hours=inputs.max_age_hours)
        checks.append(
            (False, f"dado desatualizado: última atualização há {age}, limite é {limit}")
            if age > limit
            else (True, "atualização dentro do limite")
        )
    if inputs and inputs.current_grain and inputs.reference_grain:
        checks.append(gate.check_comparability(inputs.current_grain, inputs.reference_grain))
    result = gate.evaluate(checks)
    status = QualityStatus(passed=result.passed, score=result.score, reasons=tuple(result.reasons))
    rule_ref = f"priority-scoring.gates.minimum_data_quality={minimum}"
    if result.passed:
        return QualityOutcome(_trace("quality", "pass", f"score={result.score}", rule_ref), status, False)
    reason = "; ".join(result.reasons) or f"score={result.score} abaixo do mínimo"
    return QualityOutcome(_trace("quality", "blocked", reason, rule_ref), status, True)


# 2 ─ regras determinísticas ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class InvestigationNeed:
    missing_evidence: tuple[str, ...]
    evidence_sources: tuple[str, ...]
    rule_ref: str


@dataclass(frozen=True)
class RuleOutcome:
    trace: GateTraceEntry
    resolution: DeterministicResolution | None
    investigation: InvestigationNeed | None


def deterministic_rule_gate(envelope: AlertEnvelope, policy: MetricPolicy, band: BandResult) -> RuleOutcome:
    alert = envelope.alert
    delta = alert.current_value - alert.reference_value
    threshold = policy.alert_threshold
    if threshold is not None:
        below: list[str] = []
        if threshold.min_abs_delta is not None and abs(delta) < threshold.min_abs_delta:
            below.append(f"|delta| {abs(delta):.2f} < {threshold.min_abs_delta}")
        if threshold.min_abs_pct is not None:
            pct = abs(delta) / abs(alert.reference_value) * 100 if alert.reference_value else 0.0
            if pct < threshold.min_abs_pct:
                below.append(f"|pct| {pct:.2f} < {threshold.min_abs_pct}")
        if threshold.min_current_value is not None and alert.current_value < threshold.min_current_value:
            below.append(f"valor {alert.current_value} < {threshold.min_current_value}")
        if threshold.min_materiality is not None and alert.materiality < threshold.min_materiality:
            below.append(f"materialidade {alert.materiality} < {threshold.min_materiality}")
        if threshold.above_entity_reference and band.label != "ACIMA_REFERENCIA":
            below.append("valor não ultrapassa a referência da entidade")
        if below:
            resolution = DeterministicResolution(resolved_by="rule", outcome="dismissed", rule_ref=threshold.rule_ref)
            return RuleOutcome(_trace("rule", "resolved", "; ".join(below), threshold.rule_ref), resolution, None)

    thresholds = policy.thresholds
    if (
        thresholds is not None
        and thresholds.source != "mock"
        and thresholds.materiality_min is not None
        and alert.materiality < thresholds.materiality_min
    ):
        resolution = DeterministicResolution(resolved_by="rule", outcome="dismissed", rule_ref=thresholds.rule_ref)
        reason = f"materialidade {alert.materiality} < {thresholds.materiality_min}"
        return RuleOutcome(_trace("rule", "resolved", reason, thresholds.rule_ref), resolution, None)

    coverage = policy.coverage_rule
    signals = envelope.signals
    if (
        coverage is not None
        and signals.coverage_scope == coverage.scope
        and signals.coverage_pct is not None
        and signals.coverage_pct < coverage.min_pct
    ):
        need = InvestigationNeed(
            missing_evidence=(coverage.missing_evidence_template.format(entity_id=envelope.entity_id),),
            evidence_sources=coverage.evidence_sources,
            rule_ref=coverage.rule_ref,
        )
        reason = f"cobertura {signals.coverage_pct}% < {coverage.min_pct}%: {coverage.scope} parcial"
        return RuleOutcome(_trace("rule", "blocked", reason, coverage.rule_ref), None, need)

    if (
        policy.window_rule_ref
        and signals.single_day
        and signals.window_class
        and not band.missing
        and signals.window_class != band.label
    ):
        resolution = DeterministicResolution(resolved_by="rule", outcome="monitor", rule_ref=policy.window_rule_ref)
        reason = f"o dia detecta ({band.label}), a janela decide ({signals.window_class})"
        return RuleOutcome(_trace("rule", "resolved", reason, policy.window_rule_ref), resolution, None)

    return RuleOutcome(_trace("rule", "pass", "limites e janelas atendidos"), None, None)


# 3 ─ memória de conhecido / falso positivo ──────────────────────────────────────────────────


@dataclass(frozen=True)
class MemoryOutcome:
    trace: GateTraceEntry
    resolution: DeterministicResolution | None
    entry: MemoryEntry | None


def memory_gate(
    envelope: AlertEnvelope, policy: MetricPolicy, band: BandResult, entry: MemoryEntry | None
) -> MemoryOutcome:
    if entry is None:
        return MemoryOutcome(_trace("memory", "skipped", "sem memória para a entidade"), None, None)
    if entry.engine_source != envelope.engine_source:
        return MemoryOutcome(_trace("memory", "pass", "memória de outro motor: não equivalente"), None, entry)
    if entry.direction != direction_of(envelope):
        return MemoryOutcome(_trace("memory", "pass", "direção mudou: mudança material"), None, entry)

    delta = envelope.alert.current_value - envelope.alert.reference_value
    if policy.memory_tolerance_pct is not None and entry.delta is not None:
        variation = abs(delta - entry.delta) / (abs(entry.delta) or 1) * 100
        if variation > policy.memory_tolerance_pct:
            reason = f"variação {variation:.1f}% > {policy.memory_tolerance_pct}%: mudança material"
            return MemoryOutcome(_trace("memory", "pass", reason, policy.memory_tolerance_ref), None, entry)
        no_change_reason = f"variação {variation:.1f}% <= {policy.memory_tolerance_pct}%"
        rule_ref = policy.memory_tolerance_ref
    elif not band.missing and entry.magnitude_band == band.label:
        no_change_reason = f"mesma faixa {band.label}"
        rule_ref = band.rule_ref
    else:
        return MemoryOutcome(_trace("memory", "pass", "sem critério para provar ausência de mudança"), None, entry)

    if entry.false_positive_active:
        resolution = DeterministicResolution(
            resolved_by="memory", outcome="false_positive", rule_ref="pattern_stats.false_positive_active"
        )
        reason = f"falso positivo ativo ({entry.false_positive_reason or 'sem motivo'}); {no_change_reason}"
        return MemoryOutcome(_trace("memory", "resolved", reason, resolution.rule_ref), resolution, entry)
    if entry.status == "ABERTA" and entry.causa:
        resolution = DeterministicResolution(
            resolved_by="memory", outcome="known_no_change", rule_ref=rule_ref or entry.source_ref
        )
        reason = f"conhecido, causa registrada; {no_change_reason}"
        return MemoryOutcome(_trace("memory", "resolved", reason, resolution.rule_ref), resolution, entry)
    return MemoryOutcome(_trace("memory", "pass", "conhecido sem causa registrada"), None, entry)


# 4 ─ caso semelhante ────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SimilarityOutcome:
    trace: GateTraceEntry
    reference: ReferenceCase | None
    similarity: SimilarityReference | None


def material_change_reasons(envelope: AlertEnvelope, band: BandResult, reference: ReferenceCase) -> tuple[str, ...]:
    reasons: list[str] = []
    if reference.direction != direction_of(envelope):
        reasons.append("direction")
    if reference.magnitude_band != band.label:
        reasons.append("magnitude_band")
    if reference.dominant_dimension != dominant_dimension(envelope):
        reasons.append("dominant_dimension")
    if reference.engine_source != envelope.engine_source:
        reasons.append("engine_source")
    if reference.rules_version != envelope.rules_version:
        reasons.append("rules_version")
    return tuple(reasons)


def similarity_gate(envelope: AlertEnvelope, band: BandResult, reference: ReferenceCase | None) -> SimilarityOutcome:
    if reference is None:
        return SimilarityOutcome(_trace("similar", "pass", "sem caso anterior"), None, None)
    if reference.engine_source != envelope.engine_source:
        reason = "caso anterior de outro motor: não semelhante"
        return SimilarityOutcome(_trace("similar", "pass", reason), None, None)
    reasons = material_change_reasons(envelope, band, reference)
    similarity = SimilarityReference(
        case_id=reference.case_id,
        match_level="exact" if reference.period == envelope.alert.period else "similar",
        material_change=bool(reasons),
        material_change_reasons=reasons,
    )
    note = f"referência {reference.case_id}; mudança material: {', '.join(reasons) or 'nenhuma'}"
    return SimilarityOutcome(_trace("similar", "pass", note), reference, similarity)


# 5 ─ decisão validada ───────────────────────────────────────────────────────────────────────


def _previous_month(period: str) -> str | None:
    try:
        year, month = (int(part) for part in period.split("-"))
    except ValueError:
        return None
    if not 1 <= month <= 12:
        return None
    return f"{year - 1}-12" if month == 1 else f"{year}-{month - 1:02d}"


def reuse_failures(
    envelope: AlertEnvelope,
    policy: MetricPolicy,
    band: BandResult,
    approval_flags: tuple[str, ...],
    similarity: SimilarityReference | None,
    reference: ReferenceCase | None,
    stats: PatternStats | None,
    reuse: ReusePolicy,
) -> tuple[str, ...]:
    """Todas as condições de REUSE_DECISION. Lista vazia = reuso permitido. Qualquer dúvida falha."""
    if reference is None or similarity is None:
        return ("sem caso de referência comparável",)
    failures: list[str] = []
    if similarity.material_change:
        failures.append(f"material_change ({', '.join(similarity.material_change_reasons)})")
    if band.missing:
        failures.append("magnitude_band MISSING")
    decision = reference.decision
    if decision is None or decision.outcome != DecisionOutcome.APPROVED:
        failures.append("decisão anterior não aprovada")
    diagnosis = reference.diagnosis
    if diagnosis is None:
        failures.append("sem diagnóstico de referência")
    else:
        if diagnosis.confidence < reuse.min_diagnosis_confidence:
            failures.append(f"confiança {diagnosis.confidence} < {reuse.min_diagnosis_confidence}")
        if diagnosis.decision_status != DecisionStatus.READY_FOR_DECISION:
            failures.append("diagnóstico não estava READY_FOR_DECISION")
        statuses = diagnosis.hypothesis_statuses
        if not statuses or any(status != HypothesisStatus.CONFIRMED for status in statuses):
            failures.append("hipóteses de referência não confirmadas")
        if sorted(diagnosis.missing_data) != sorted(envelope.missing_data):
            failures.append("evidência faltante mudou")
    action = reference.action
    if action is None or action.outcome != "ok":
        failures.append(f"ação anterior sem outcome ok ({action.outcome if action else 'ausente'})")
    if action is None or action.recurrence is not False:
        failures.append(f"recorrência não descartada ({action.recurrence if action else 'ausente'})")
    learning = reference.learning
    if (
        learning is None
        or learning.predicted_impact is None
        or learning.actual_impact is None
        or learning.actual_impact < learning.predicted_impact * reuse.learning_min_ratio
    ):
        failures.append("aprendizado incompatível ou ausente")
    if reference.rules_version != envelope.rules_version:
        failures.append("rules_version diferente")
    new_flags = set(approval_flags) - set(reference.approval_flags)
    if new_flags:
        failures.append(f"novas marcas de aprovação: {sorted(new_flags)}")
    if reference.reopen_count != 0 or envelope.loop.reopen_count != 0 or envelope.loop.is_reopen:
        failures.append("caso reaberto")
    if policy.granularity == "monthly":
        if reference.period != _previous_month(envelope.alert.period):
            failures.append("validade: referência não é a competência imediatamente anterior")
    elif policy.granularity in {"daily", "window_5du"}:
        if envelope.evaluated_at - reference.evaluated_at > timedelta(days=reuse.daily_validity_days):
            failures.append(f"validade: referência com mais de {reuse.daily_validity_days} dias")
    else:
        failures.append("validade temporal MISSING para a granularidade")
    approved_reference = 1 if decision is not None and decision.outcome == DecisionOutcome.APPROVED else 0
    approved = max(stats.decisions_approved if stats else 0, approved_reference)
    verified = max(stats.verified_ok if stats else 0, 1 if action and action.outcome == "ok" else 0)
    if approved < reuse.first_reuse_min_approved_decisions:
        failures.append(f"decisões aprovadas {approved} < {reuse.first_reuse_min_approved_decisions}")
    if verified < reuse.first_reuse_min_verified_ok:
        failures.append(f"verificações ok {verified} < {reuse.first_reuse_min_verified_ok}")
    return tuple(failures)


@dataclass(frozen=True)
class DecisionOutcomeGate:
    trace: GateTraceEntry
    reusable: bool
    failures: tuple[str, ...]


def validated_decision_gate(
    envelope: AlertEnvelope,
    policy: MetricPolicy,
    band: BandResult,
    approval_flags: tuple[str, ...],
    similarity: SimilarityOutcome,
    stats: PatternStats | None,
    reuse: ReusePolicy,
) -> DecisionOutcomeGate:
    if similarity.reference is None:
        return DecisionOutcomeGate(_trace("decision", "skipped", "sem caso de referência"), False, ())
    failures = reuse_failures(
        envelope, policy, band, approval_flags, similarity.similarity, similarity.reference, stats, reuse
    )
    if failures:
        return DecisionOutcomeGate(_trace("decision", "blocked", "; ".join(failures)), False, failures)
    decision_id = similarity.reference.decision.decision_id  # type: ignore[union-attr]
    return DecisionOutcomeGate(_trace("decision", "resolved", f"decisão {decision_id} reutilizável"), True, ())


# 6 ─ aprendizado ────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LearningOutcome:
    trace: GateTraceEntry
    veto: bool


def learning_gate(stats: PatternStats | None) -> LearningOutcome:
    if stats is None:
        return LearningOutcome(_trace("learning", "skipped", "sem estatística do padrão"), False)
    if stats.reuse_verified_fail > 0 or stats.reuse_blocked:
        reason = stats.reuse_blocked_reason or f"reuse_verified_fail={stats.reuse_verified_fail}"
        return LearningOutcome(_trace("learning", "blocked", f"aprendizado negativo: {reason}"), True)
    return LearningOutcome(_trace("learning", "pass", "sem aprendizado negativo"), False)


# 7 ─ playbook ───────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PlaybookOutcome:
    trace: GateTraceEntry
    playbook: Playbook | None
    applies: bool


def playbook_gate(
    envelope: AlertEnvelope,
    band: BandResult,
    playbook: Playbook | None,
    stats: PatternStats | None,
    learning_veto: bool,
) -> PlaybookOutcome:
    if playbook is None:
        return PlaybookOutcome(_trace("playbook", "skipped", "sem playbook para o padrão"), None, False)
    failures: list[str] = []
    if playbook.status != "active":
        failures.append(f"status {playbook.status}")
    if playbook.rules_version != envelope.rules_version:
        failures.append("rules_version diferente")
    if playbook.valid_from and envelope.evaluated_at < playbook.valid_from:
        failures.append("ainda não vigente")
    if playbook.valid_until and envelope.evaluated_at >= playbook.valid_until:
        failures.append("expirado")
    if band.missing:
        failures.append("magnitude_band MISSING")
    if learning_veto:
        failures.append("veto de aprendizado")
    if stats is None or stats.verified_fail > 0 or stats.reopen_total > 0:
        failures.append("histórico do padrão ausente, com falha ou reabertura")
    if envelope.loop.reopen_count or envelope.loop.is_reopen:
        failures.append("caso reaberto")
    ref = f"playbook {playbook.playbook_id}@v{playbook.version}"
    if failures:
        return PlaybookOutcome(_trace("playbook", "blocked", "; ".join(failures), ref), playbook, False)
    return PlaybookOutcome(_trace("playbook", "resolved", "playbook ativo e válido", ref), playbook, True)


# 8 ─ roteamento de IA (só decide QUEM seria chamado) ────────────────────────────────────────


@dataclass(frozen=True)
class AiRoutingOutcome:
    trace: GateTraceEntry
    route: Route
    agents: tuple[SelectedAgent, ...]
    next_step: NextStep


def ai_routing_gate(
    envelope: AlertEnvelope,
    policy: MetricPolicy,
    band: BandResult,
    approval_flags: tuple[str, ...],
    similarity: SimilarityOutcome,
    learning_veto: bool,
    investigation: InvestigationNeed | None,
) -> AiRoutingOutcome:
    if investigation is not None:
        step = NextStep(
            action="collect_evidence",
            owner_system="torre-engine",
            missing_evidence=investigation.missing_evidence,
            evidence_sources=investigation.evidence_sources,
        )
        trace = _trace("ai", "resolved", "evidência do motor determinístico antes de qualquer agente",
                       investigation.rule_ref)
        return AiRoutingOutcome(trace, "INVESTIGATE_FIRST", (), step)

    if not policy.routable:
        missing = (
            "classificação do case_type da métrica"
            if policy.case_type == "UNKNOWN"
            else f"confirmação humana da correspondência {policy.metric_id} → {policy.case_type} (MÉDIA)"
        )
        step = NextStep(action="await_human", owner_system="human", missing_evidence=(missing,))
        trace = _trace("ai", "blocked", f"case_type não roteável ({policy.mapping_confidence})", policy.mapping_ref)
        return AiRoutingOutcome(trace, "INVESTIGATE_FIRST", (), step)

    specialists = policy.specialists[:2]
    reference = similarity.reference
    sim = similarity.similarity
    one_agent = (
        reference is not None
        and sim is not None
        and sim.material_change_reasons == ("magnitude_band",)
        and band.adjacent_to(reference.magnitude_band)
        and reference.diagnosis is not None
        and reference.diagnosis.hypothesis_statuses
        and all(status == HypothesisStatus.CONFIRMED for status in reference.diagnosis.hypothesis_statuses)
        and not approval_flags
        and not learning_veto
    )
    run = NextStep(action="run_agents", owner_system="ai-orchestrator")
    if one_agent:
        agent = SelectedAgent(
            agent_name=specialists[0],
            role="specialist",
            why=f"confirmar ou refutar a hipótese herdada de {reference.case_id} após mudança de faixa adjacente",
        )
        return AiRoutingOutcome(_trace("ai", "resolved", "ONE_AGENT: hipótese conhecida, faixa adjacente"),
                                "ONE_AGENT", (agent,), run)

    agents = [SelectedAgent(agent_name=INVESTIGATOR, role="investigate", why="causa não estabelecida")]
    agents += [
        SelectedAgent(agent_name=name, role="specialist", why=f"especialista da rota {policy.case_type}")
        for name in specialists
    ]
    materiality_min = policy.thresholds.materiality_min if policy.thresholds else None
    challenge_reasons = []
    if approval_flags:
        challenge_reasons.append(f"marcas {list(approval_flags)}")
    if learning_veto:
        challenge_reasons.append("aprendizado negativo")
    if materiality_min is not None and envelope.alert.materiality >= materiality_min:
        challenge_reasons.append(f"materialidade >= {materiality_min}")
    if challenge_reasons:
        agents.append(SelectedAgent(agent_name=CHALLENGER, role="challenge", why="; ".join(challenge_reasons)))
    names = ", ".join(agent.agent_name for agent in agents)
    return AiRoutingOutcome(_trace("ai", "resolved", f"MULTI_AGENT: {names}"), "MULTI_AGENT", tuple(agents), run)


__all__ = [
    "AiRoutingOutcome",
    "DecisionOutcomeGate",
    "InvestigationNeed",
    "LearningOutcome",
    "MemoryOutcome",
    "PlaybookOutcome",
    "QualityOutcome",
    "RuleOutcome",
    "SimilarityOutcome",
    "ai_routing_gate",
    "deterministic_rule_gate",
    "learning_gate",
    "material_change_reasons",
    "memory_gate",
    "playbook_gate",
    "quality_gate",
    "reuse_failures",
    "similarity_gate",
    "validated_decision_gate",
]
