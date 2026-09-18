"""Decision Router — cérebro determinístico: AlertEnvelope → DecisionRoute.

Ordem: idempotência → proteção contra loop → qualidade → regra → memória → semelhante →
decisão validada → aprendizado → playbook → roteamento de IA. Para na porta que resolve.
Exceção deliberada: a decisão validada gera só um CANDIDATO a reuso; a porta de aprendizado roda
sempre antes de confirmar, porque aprendizado negativo tem poder de veto.

Nesta fase o Router não chama IA, não grava Decision, não cria ação e não persiste nada.
"""

from app.decision_router.bands import BandResult, classify_band
from app.decision_router.contract import (
    CONTRACT_VERSION,
    DecisionRoute,
    DeterministicResolution,
    EvidenceItem,
    GateTraceEntry,
    LoopGuard,
    NextStep,
    PlaybookRef,
    PriorityStatus,
    QualityStatus,
)
from app.decision_router.fingerprint import compute_fingerprints, sha256_tagged
from app.decision_router.gates import (
    ai_routing_gate,
    deterministic_rule_gate,
    learning_gate,
    memory_gate,
    playbook_gate,
    quality_gate,
    similarity_gate,
    validated_decision_gate,
)
from app.decision_router.inputs import AlertEnvelope, PatternStats
from app.decision_router.policy import MetricPolicy, RouterPolicy
from app.decision_router.providers import (
    MemoryLedgerProvider,
    PatternStatsProvider,
    PlaybookProvider,
    RouteStore,
    SimilarityCaseProvider,
)
from app.services.data_quality_gate import DataQualityGate
from app.services.priority_engine import PriorityEngine

MAX_HOPS = 3
MAX_REOPEN = 2

_CLOSE_OUTCOMES = {"dismissed", "known_no_change", "false_positive"}


class DecisionRouter:
    def __init__(
        self,
        policy: RouterPolicy,
        *,
        memory: MemoryLedgerProvider,
        similarity: SimilarityCaseProvider,
        pattern_stats: PatternStatsProvider,
        playbooks: PlaybookProvider,
        route_store: RouteStore,
        priority_engine: PriorityEngine | None = None,
    ) -> None:
        self._policy = policy
        self._memory = memory
        self._similarity = similarity
        self._stats = pattern_stats
        self._playbooks = playbooks
        self._store = route_store
        self._priority = priority_engine or PriorityEngine()
        self._quality = DataQualityGate(minimum_score=policy.minimum_data_quality)
        self.evaluations = 0
        self.replays = 0
        self.ai_calls_made = 0  # o Router não possui cliente de IA; permanece 0 por construção

    # ── API pública ────────────────────────────────────────────────────────────────────────

    def keys_for(self, envelope: AlertEnvelope):
        metric, band, flags = self._prepare(envelope)
        return compute_fingerprints(envelope, metric, band, flags)

    def route(self, envelope: AlertEnvelope) -> DecisionRoute:
        metric, band, flags = self._prepare(envelope)
        fingerprints = compute_fingerprints(envelope, metric, band, flags)
        existing = self._store.get_open(fingerprints.exact)
        if existing is not None:
            self.replays += 1
            return existing
        self.evaluations += 1
        route = self._evaluate(envelope, metric, band, flags, fingerprints)
        self._store.remember(route)
        return route

    # ── avaliação ─────────────────────────────────────────────────────────────────────────

    def _prepare(self, envelope: AlertEnvelope) -> tuple[MetricPolicy, BandResult, tuple[str, ...]]:
        metric = self._policy.metric(envelope.alert.metric_id)
        band = classify_band(metric, envelope)
        flags = tuple(sorted(set(metric.approval_flags) | set(envelope.approval_flags)))
        return metric, band, flags

    def _priority_status(self, envelope: AlertEnvelope, flags: tuple[str, ...]) -> PriorityStatus:
        needs_approval, triggered = self._priority.requires_human_approval(list(flags))
        score = label = None
        if envelope.priority_dimensions is not None:
            result = self._priority.evaluate(envelope.priority_dimensions, list(flags))
            score, label = result.score, result.label
        return PriorityStatus(
            score=score, label=label, human_approval_required=needs_approval, triggered_gates=tuple(triggered)
        )

    def _evaluate(self, envelope, metric, band, flags, fingerprints) -> DecisionRoute:
        priority = self._priority_status(envelope, flags)
        quality = quality_gate(envelope, self._quality, self._policy.minimum_data_quality)
        evidence = [self._evidence("alert", f"alert:{envelope.alert.metric_id}:{envelope.alert.period}",
                                   {"alert": envelope.alert.model_dump(mode="json"),
                                    "engine_source": envelope.engine_source,
                                    "entity": [envelope.entity_type, envelope.entity_id]}),
                    self._evidence("data_quality", "DataQualityGate", quality.status.model_dump(mode="json"))]
        base = {
            "metric": metric, "envelope": envelope, "fingerprints": fingerprints, "priority": priority,
            "quality": quality.status, "evidence": evidence,
        }

        next_reopen = envelope.loop.reopen_count + (1 if envelope.loop.is_reopen else 0)
        if envelope.loop.hop > MAX_HOPS or next_reopen > MAX_REOPEN:
            trace = [GateTraceEntry(
                gate="loop_guard", result="blocked",
                reason=f"hop={envelope.loop.hop}/{MAX_HOPS}, reopen={next_reopen}/{MAX_REOPEN}: escalonar",
            )]
            return self._build(
                **base, trace=trace, route="INVESTIGATE_FIRST", status="ESCALATED",
                reason="limite de investigação ou reabertura excedido; decisão humana obrigatória",
                next_step=NextStep(action="await_human", owner_system="human",
                                   missing_evidence=("decisão humana após exceder limite de loop",)),
                requires_approval=True, reopen_count=next_reopen,
            )

        trace = [quality.trace]
        if quality.blocked:
            resolution = DeterministicResolution(
                resolved_by="quality_gate", outcome="data_insufficient", rule_ref=quality.trace.rule_ref or "quality"
            )
            missing = metric.missing_evidence_on_quality or quality.status.reasons or ("dados de qualidade suficiente",)
            return self._build(
                **base, trace=trace, route="NO_AGENT", status="BLOCKED_DATA", resolution=resolution,
                reason="dados insuficientes: IA bloqueada",
                next_step=NextStep(action="collect_evidence", owner_system="human", missing_evidence=tuple(missing)),
                requires_approval=priority.human_approval_required,
            )

        rule = deterministic_rule_gate(envelope, metric, band)
        trace.append(rule.trace)
        if rule.resolution is not None:
            evidence.append(self._evidence("rule", rule.resolution.rule_ref, rule.trace.model_dump(mode="json")))
            return self._resolved(base, trace, rule.resolution, band)

        stats = self._stats.get(fingerprints.pattern_key)
        similarity = None
        learning = None
        playbook = None
        if rule.investigation is None:
            memory = memory_gate(envelope, metric, band, self._memory.get(fingerprints.lineage_key))
            trace.append(memory.trace)
            if memory.entry is not None:
                evidence.append(self._evidence("memory_ledger", memory.entry.source_ref,
                                               memory.entry.model_dump(mode="json")))
            if memory.resolution is not None:
                return self._resolved(base, trace, memory.resolution, band, stats=stats)

            similarity = similarity_gate(
                envelope, band, self._similarity.find_reference(fingerprints.lineage_key, envelope.evaluated_at)
            )
            trace.append(similarity.trace)
            if similarity.reference is not None:
                evidence.append(self._evidence("similar_case", f"case:{similarity.reference.case_id}",
                                               similarity.reference.model_dump(mode="json")))

            decision = validated_decision_gate(
                envelope, metric, band, flags, similarity, stats, self._policy.reuse
            )
            trace.append(decision.trace)
            learning = learning_gate(stats)
            trace.append(learning.trace)
            if decision.reusable and not learning.veto:
                reference = similarity.reference
                evidence.append(self._evidence("decision", f"decision:{reference.decision.decision_id}",
                                               reference.decision.model_dump(mode="json")))
                evidence.append(self._evidence("learning", f"learning:{reference.learning.learning_id}",
                                               reference.learning.model_dump(mode="json")))
                return self._build(
                    **base, trace=trace, route="REUSE_DECISION", status="ROUTED",
                    reason=f"decisão aprovada {reference.decision.decision_id} reutilizável; aprovação humana exigida",
                    next_step=NextStep(action="propose_decision", owner_system="human"),
                    requires_approval=True, similarity=similarity.similarity,
                    reused_decision_id=reference.decision.decision_id,
                    reused_learning_id=reference.learning.learning_id,
                    stats=stats, confidence_cap=reference.diagnosis.confidence,
                )

            playbook = playbook_gate(envelope, band, self._playbooks.get_current(fingerprints.pattern_key),
                                     stats, learning.veto)
            trace.append(playbook.trace)
            if playbook.applies:
                pb = playbook.playbook
                evidence.append(self._evidence("playbook", f"playbook:{pb.playbook_id}@v{pb.version}",
                                               pb.model_dump(mode="json")))
                resolution = DeterministicResolution(
                    resolved_by="playbook", outcome="playbook_applied", rule_ref=playbook.trace.rule_ref or "playbook"
                )
                return self._build(
                    **base, trace=trace, route="NO_AGENT", status="ROUTED", resolution=resolution,
                    reason=f"playbook ativo {pb.playbook_id}@v{pb.version}; aprovação humana exigida",
                    next_step=NextStep(action="propose_decision", owner_system="human"),
                    requires_approval=True, similarity=similarity.similarity,
                    playbook=PlaybookRef(playbook_id=pb.playbook_id, version=pb.version), stats=stats,
                )

        if similarity is None:
            similarity = similarity_gate(envelope, band, None)
        ai = ai_routing_gate(
            envelope, metric, band, flags, similarity, bool(learning and learning.veto), rule.investigation
        )
        trace.append(ai.trace)
        if rule.investigation is not None:
            evidence.append(self._evidence("engine_signal", rule.investigation.rule_ref,
                                           envelope.signals.model_dump(mode="json")))
        requires_approval = (
            priority.human_approval_required
            or bool(learning and learning.veto)
            or ai.next_step.action == "await_human"
        )
        calls = len(ai.agents) + 1 if ai.agents else 0
        return self._build(
            **base, trace=trace, route=ai.route, status="ROUTED",
            reason=ai.trace.reason, next_step=ai.next_step, requires_approval=requires_approval,
            similarity=similarity.similarity, agents=ai.agents, calls=calls, stats=stats,
        )

    def _resolved(self, base, trace, resolution: DeterministicResolution, band: BandResult,
                  stats: PatternStats | None = None) -> DecisionRoute:
        if resolution.outcome in _CLOSE_OUTCOMES:
            step = NextStep(action="close_case", owner_system="sal-os")
        else:
            step = NextStep(action="monitor", owner_system="sal-os")
        return self._build(
            **base, trace=trace, route="NO_AGENT", status="ROUTED", resolution=resolution,
            reason=f"resolvido sem IA: {resolution.outcome}", next_step=step,
            requires_approval=base["priority"].human_approval_required, stats=stats,
        )

    # ── montagem ──────────────────────────────────────────────────────────────────────────

    def _build(
        self, *, metric: MetricPolicy, envelope: AlertEnvelope, fingerprints, priority: PriorityStatus,
        quality: QualityStatus, evidence: list[EvidenceItem], trace: list[GateTraceEntry], route: str,
        status: str, reason: str, next_step: NextStep, requires_approval: bool,
        resolution: DeterministicResolution | None = None, similarity=None, agents=(), calls: int = 0,
        reused_decision_id: str | None = None, reused_learning_id: str | None = None,
        playbook: PlaybookRef | None = None, stats: PatternStats | None = None,
        confidence_cap: float | None = None, reopen_count: int | None = None,
    ) -> DecisionRoute:
        avoided, basis = self._cost_avoided(route, metric, stats)
        confidence = float(quality.score)
        if confidence_cap is not None:
            confidence = min(confidence, confidence_cap)
        return DecisionRoute(
            contract_version=CONTRACT_VERSION,
            status=status,
            route=route,
            reason=reason[:1000],
            metric_id=envelope.alert.metric_id,
            case_type=metric.case_type,
            mapping_confidence=metric.mapping_confidence,
            evaluated_at=envelope.evaluated_at,
            evidence=tuple(evidence),
            quality=quality,
            priority=priority,
            selected_agents=tuple(agents),
            deterministic_resolution=resolution,
            reused_decision_id=reused_decision_id,
            reused_learning_id=reused_learning_id,
            playbook=playbook,
            fingerprints=fingerprints,
            similarity_reference=similarity,
            estimated_ai_calls=calls,
            estimated_ai_cost_avoided_usd=avoided,
            cost_basis=basis,
            confidence=confidence,
            requires_human_approval=requires_approval or priority.human_approval_required,
            next_step=next_step,
            gate_trace=tuple(trace),
            loop_guard=LoopGuard(
                hop=envelope.loop.hop,
                reopen_count=envelope.loop.reopen_count if reopen_count is None else reopen_count,
            ),
        )

    def _cost_avoided(self, route: str, metric: MetricPolicy, stats: PatternStats | None):
        """Nunca inventa custo: histórico do padrão, teto reservado configurado, ou desconhecido."""
        if route not in {"NO_AGENT", "REUSE_DECISION"}:
            return None, "unknown"
        if stats is not None and stats.ai_cases > 0:
            return round(stats.ai_cost_usd_total / stats.ai_cases, 4), "pattern_history"
        ceiling = self._policy.reserved_ceiling_usd_per_call
        if ceiling is not None and metric.routable:
            return round(ceiling * (len(self._policy.routing[metric.case_type]) + 1), 4), "reserved_ceiling"
        return None, "unknown"

    @staticmethod
    def _evidence(kind: str, ref: str, payload: object) -> EvidenceItem:
        return EvidenceItem(kind=kind, ref=ref[:500], sha256=sha256_tagged(payload))
