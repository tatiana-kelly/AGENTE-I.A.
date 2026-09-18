"""Fase 4 — ciclo governado: proposta, aprovação humana, ação, verificação, reabertura, escalonamento,
aprendizado, playbook, auditoria, RBAC, idempotência e ausência de escrita em shadow.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.rbac import Role
from app.decision_cycle.action_link import ActionLinker, FollowUp
from app.decision_cycle.approval import ApprovalService
from app.decision_cycle.events import CycleEvent, CycleEventRecorder
from app.decision_cycle.governance import GovernanceViolation, human, machine
from app.decision_cycle.learning import LearningService
from app.decision_cycle.playbooks import approve_playbook, candidate_playbook, eligibility
from app.decision_cycle.proposal import DecisionProposal, build_proposal
from app.decision_cycle.reopen import EscalationReason, EscalationService, ReopenService
from app.decision_cycle.shadow_cycle import cycle_report, run_cycle_shadow, write_cycle_report
from app.decision_cycle.states import (
    CaseState,
    IllegalTransition,
    assert_transition,
    state_from_action,
    state_from_decision_outcome,
    state_from_diagnosis_status,
    state_from_route,
)
from app.decision_cycle.stats_service import PatternStatsService
from app.decision_cycle.verification import (
    MetricRegistryVerifier,
    NoSourceVerifier,
    VerificationService,
    VerificationVerdict,
)
from app.decision_router.adapters import TorreDataReader, default_torre_adapters
from app.decision_router.memory.recorder import MemoryMode
from app.decision_router.memory.records import PatternStatsRecord
from app.decision_router.memory.repository import InMemoryCaseMemoryRepository, MemoryWriteBlocked
from app.decision_router.policy import build_default_policy
from app.decision_router.providers import (
    InMemoryMemoryLedgerProvider,
    InMemoryPatternStatsProvider,
    InMemoryPlaybookProvider,
    InMemoryRouteStore,
    InMemorySimilarityCaseProvider,
)
from app.decision_router.router import DecisionRouter
from app.decision_router.shadow_runner import compute_rules_version
from app.schemas.action_execution import ActionExecutionBase
from app.schemas.diagnosis import DiagnosisBase
from app.schemas.enums import (
    DecisionOutcome,
    DecisionStatus,
    Effort,
    HypothesisStatus,
    RecommendationType,
    Reversibility,
    Risk,
)
from app.schemas.hypothesis import HypothesisBase
from app.schemas.recommendation import RecommendationBase
from app.services.audit_trail import AuditTrail

FIXTURE_TORRE = Path(__file__).resolve().parents[1] / "fixtures" / "decision_router_shadow" / "torre_data"
NOW = datetime(2026, 9, 17, 12, tzinfo=UTC)
PATTERN = "sha256:" + "a" * 64
GESTOR = human("tatiana", Role.DIRETORIA)
ANALISTA = human("analista.junior", Role.ANALISTA)
ROUTER_AGENT = machine("decision-router")


def _recommendation(kind: RecommendationType) -> RecommendationBase:
    return RecommendationBase(
        type=kind, action=f"{kind.value}: renegociar rota", expected_impact="R$ 12.000/mês",
        effort=Effort.MEDIUM, risk=Risk.LOW, time_to_value="30 dias", reversibility=Reversibility.REVERSIBLE,
        owner_role="gestor de transferência", deadline="2026-10-15", success_kpi="ocupacao-transferencia",
        success_target="85",
    )


def _diagnosis(status: DecisionStatus = DecisionStatus.READY_FOR_DECISION) -> DiagnosisBase:
    return DiagnosisBase(
        hypotheses=[HypothesisBase(statement="malha desbalanceada", confidence=80,
                                   status=HypothesisStatus.CONFIRMED,
                                   favorable_evidence=["ocupação 17,6%"], contrary_evidence=["frete estável"])],
        probable_cause="rota operando abaixo da ocupação alvo", confidence=80,
        recommendations=[_recommendation(RecommendationType.CONTAINMENT),
                         _recommendation(RecommendationType.STRUCTURAL),
                         _recommendation(RecommendationType.OPTIMIZATION)],
        owner="gestor de transferência", success_kpi="ocupacao-transferencia", decision_status=status,
    )


@pytest.fixture()
def cycle(tmp_path):
    audit = AuditTrail(tmp_path / "audit_trail.jsonl")
    events = CycleEventRecorder(audit)
    return {
        "audit": audit, "events": events,
        "approval": ApprovalService(events, clock=lambda: NOW),
        "linker": ActionLinker(events),
        "reopen": ReopenService(events),
        "escalation": EscalationService(events),
        "learning": LearningService(events),
    }


@pytest.fixture()
def proposal(shadow_route) -> DecisionProposal:
    diagnosis = _diagnosis()
    return build_proposal(
        case_id="caso-1", exact_fingerprint=shadow_route.fingerprints.exact, route=shadow_route,
        diagnosis=diagnosis, recommendation=diagnosis.recommendations[1], proposed_by=ROUTER_AGENT,
        created_at=NOW, proposal_id="prop-1",
    )


@pytest.fixture(scope="module")
def shadow_route():
    """Rota real produzida pelo recorte de transferências da Torre (mesmo fixture das fases 2 e 3)."""
    reader = TorreDataReader(FIXTURE_TORRE)
    rules = compute_rules_version(reader)
    router = DecisionRouter(build_default_policy(), memory=InMemoryMemoryLedgerProvider(),
                            similarity=InMemorySimilarityCaseProvider(),
                            pattern_stats=InMemoryPatternStatsProvider(), playbooks=InMemoryPlaybookProvider(),
                            route_store=InMemoryRouteStore())
    for adapter in default_torre_adapters():
        for adapted in adapter.adapt(reader, rules).alerts:
            route = router.route(adapted.envelope)
            if route.route == "MULTI_AGENT":
                return route
    raise AssertionError("nenhuma rota MULTI_AGENT no fixture")


def _action(**fields) -> ActionExecutionBase:
    base = {"owner": "gestor", "due_at": NOW + timedelta(days=7), "evidence": []}
    return ActionExecutionBase(**{**base, **fields})


def _approve(cycle, proposal):
    return cycle["approval"].approve_proposal(proposal, GESTOR, "impacto confirmado", "rec-1", case_version=1)


# 1–4 ─ proposta e decisão humana ────────────────────────────────────────────────────────────

def test_01_alert_becomes_proposal(proposal, shadow_route):
    assert proposal.case_id == "caso-1"
    assert proposal.state is CaseState.WAITING_HUMAN_APPROVAL
    assert proposal.requires_human_approval is True
    assert proposal.is_approved() is False
    assert proposal.suggested_action.startswith("structural")
    assert proposal.evidence and proposal.hypotheses
    assert proposal.metric_id == shadow_route.metric_id


def test_02_proposal_to_approval(cycle, proposal):
    decision = _approve(cycle, proposal)
    assert decision.outcome is DecisionOutcome.APPROVED
    assert decision.state is CaseState.APPROVED
    assert decision.human_owner == "tatiana" and decision.human_role == Role.DIRETORIA.value
    assert decision.rationale and decision.decided_at == NOW and decision.case_version == 1
    assert decision.to_decision_create().decision is DecisionOutcome.APPROVED


def test_03_proposal_to_rejection(cycle, proposal):
    decision = cycle["approval"].reject_proposal(proposal, GESTOR, "custo maior que o ganho", "rec-1", 1)
    assert decision.outcome is DecisionOutcome.REJECTED and decision.state is CaseState.REJECTED


def test_04_proposal_to_more_evidence(cycle, proposal):
    decision = cycle["approval"].request_more_evidence(proposal, GESTOR, "faltou custo real", "rec-1", 1)
    assert decision.outcome is DecisionOutcome.REQUEST_MORE_EVIDENCE
    assert decision.state is CaseState.MORE_EVIDENCE_REQUIRED
    assert state_from_decision_outcome(DecisionOutcome.REQUEST_MORE_EVIDENCE) is CaseState.MORE_EVIDENCE_REQUIRED


# 5–7 ─ ação só depois da decisão; máquina não aprova ────────────────────────────────────────

def test_05_approved_decision_links_action(cycle, proposal):
    decision = _approve(cycle, proposal)
    action, follow_up = cycle["linker"].link_action(decision, proposal, GESTOR, "gestor.transferencia",
                                                    NOW + timedelta(days=7))
    assert action.decision_id == decision.decision_id
    assert action.started_at is None and action.completed_at is None  # vínculo, não execução
    assert action.outcome is None and action.recurrence is None
    assert follow_up.status == "PENDING" and follow_up.expected_kpi == "ocupacao-transferencia"
    assert state_from_action(_action(), NOW) is CaseState.ACTION_PENDING


def test_06_proposal_alone_cannot_generate_action(cycle, proposal):
    rejected = cycle["approval"].reject_proposal(proposal, GESTOR, "não aprovado", "rec-1", 1)
    with pytest.raises(GovernanceViolation):
        cycle["linker"].link_action(rejected, proposal, GESTOR, "gestor", NOW + timedelta(days=7))
    with pytest.raises(IllegalTransition):
        assert_transition(CaseState.PROPOSED, CaseState.ACTION_PENDING)
    with pytest.raises(IllegalTransition):
        assert_transition(CaseState.WAITING_HUMAN_APPROVAL, CaseState.ACTION_EXECUTING)


def test_07_agent_cannot_approve(cycle, proposal):
    with pytest.raises(GovernanceViolation):
        cycle["approval"].approve_proposal(proposal, ROUTER_AGENT, "auto", "rec-1", 1)
    with pytest.raises(GovernanceViolation):
        cycle["approval"].approve_proposal(proposal, machine("coordenador-central"), "auto", "rec-1", 1)
    assert not any(event.event_type == "human_decision" for event in cycle["audit"].read_all())


# 8–11 ─ verificação ─────────────────────────────────────────────────────────────────────────

def _follow_up(decision_id="dec-1", **fields) -> FollowUp:
    base = {"case_id": "caso-1", "decision_id": decision_id, "action_id": "act-1", "owner": "gestor",
            "due_at": NOW + timedelta(days=7), "expected_result": "ocupação 85%",
            "expected_kpi": "ocupacao-transferencia", "expected_target": "85"}
    return FollowUp(**{**base, **fields})


class _Registry:
    def __init__(self, target=None):
        self._target = target

    def get_by_name(self, name):
        if self._target is None:
            return None
        return type("Metric", (), {"name": name, "target": self._target})()


def test_08_action_goes_to_verification(cycle):
    service = VerificationService(NoSourceVerifier(clock=lambda: NOW), cycle["events"])
    action = _action(completed_at=NOW, evidence=["relatorio.pdf"])
    result = service.verify(_follow_up(), action, GESTOR, 1)
    assert result.verdict is VerificationVerdict.INSUFFICIENT_EVIDENCE
    kinds = [event.payload["cycle_event"] for event in cycle["audit"].read_all()]
    assert CycleEvent.VERIFICATION_STARTED.value in kinds and CycleEvent.VERIFICATION_COMPLETED.value in kinds


def test_09_verification_ok(cycle):
    verifier = MetricRegistryVerifier(_Registry(target=85), lambda name, action: 90.0, clock=lambda: NOW)
    result = VerificationService(verifier, cycle["events"]).verify(
        _follow_up(), _action(completed_at=NOW, evidence=["medicao.csv"]), GESTOR, 1)
    assert result.verdict is VerificationVerdict.VERIFIED_OK and result.state is CaseState.VERIFIED_OK
    assert result.measured_value == 90.0 and result.target_value == 85.0


def test_10_verification_fail(cycle):
    verifier = MetricRegistryVerifier(_Registry(target=85), lambda name, action: 40.0, clock=lambda: NOW)
    result = VerificationService(verifier, cycle["events"]).verify(
        _follow_up(), _action(completed_at=NOW, evidence=["medicao.csv"]), GESTOR, 1)
    assert result.verdict is VerificationVerdict.VERIFIED_FAIL and result.state is CaseState.VERIFIED_FAIL


def test_11_insufficient_evidence_never_becomes_success(cycle):
    verifier = MetricRegistryVerifier(_Registry(target=85), lambda name, action: None, clock=lambda: NOW)
    service = VerificationService(verifier, cycle["events"])
    sem_medicao = service.verify(_follow_up(), _action(completed_at=NOW, evidence=["nota.txt"]), GESTOR, 1)
    sem_evidencia = service.verify(_follow_up(), _action(completed_at=NOW), GESTOR, 1)
    sem_metrica = VerificationService(
        MetricRegistryVerifier(_Registry(), lambda name, action: 99.0, clock=lambda: NOW), cycle["events"]
    ).verify(_follow_up(), _action(completed_at=NOW, evidence=["x"]), GESTOR, 1)
    for result in (sem_medicao, sem_evidencia, sem_metrica):
        assert result.verdict is VerificationVerdict.INSUFFICIENT_EVIDENCE
        assert result.state is CaseState.VERIFYING


# 12–13 ─ reabertura e escalonamento ─────────────────────────────────────────────────────────

def test_12_reopen_on_failure_and_on_missing_evidence(cycle):
    verifier = MetricRegistryVerifier(_Registry(target=85), lambda name, action: 40.0, clock=lambda: NOW)
    fail = VerificationService(verifier, cycle["events"]).verify(
        _follow_up(), _action(completed_at=NOW, evidence=["m.csv"]), GESTOR, 1)
    event = cycle["reopen"].evaluate(fail, _follow_up(), GESTOR, CaseState.VERIFYING, 0, True, NOW)
    assert event.reopen_count == 1 and event.target_state is CaseState.PROPOSED and event.evidence
    insufficient = VerificationService(NoSourceVerifier(clock=lambda: NOW), cycle["events"]).verify(
        _follow_up(), _action(completed_at=NOW), GESTOR, 1)
    again = cycle["reopen"].evaluate(insufficient, _follow_up(), GESTOR, CaseState.VERIFYING, 1, True, NOW)
    assert again.reopen_count == 2 and again.target_state is CaseState.INVESTIGATING
    ok_result = VerificationService(
        MetricRegistryVerifier(_Registry(target=85), lambda n, a: 99.0, clock=lambda: NOW), cycle["events"]
    ).verify(_follow_up(), _action(completed_at=NOW, evidence=["m.csv"]), GESTOR, 1)
    assert cycle["reopen"].evaluate(ok_result, _follow_up(), GESTOR, CaseState.VERIFYING, 0, True, NOW) is None


def test_13_escalation_emits_event_without_notifying(cycle):
    late = _follow_up(due_at=NOW - timedelta(days=1))
    events = cycle["escalation"].evaluate(case_id="caso-1", actor=GESTOR, now=NOW, owner="diretoria",
                                          follow_up=late, reopen_count=3, pattern_occurrences=4,
                                          material_risk=True, persistent_conflict=True)
    reasons = {event.reason for event in events}
    assert EscalationReason.OVERDUE in reasons and EscalationReason.MULTIPLE_REOPENS in reasons
    assert EscalationReason.REPETITION in reasons and EscalationReason.MATERIAL_RISK in reasons
    assert all(event.notified is False for event in events)
    assert cycle["escalation"].evaluate(case_id="caso-1", actor=GESTOR, now=NOW, owner="diretoria") == []


# 14–17 ─ aprendizado e integridade do resultado ─────────────────────────────────────────────

def _learn(cycle, proposal, verdict_source, action=None):
    decision = _approve(cycle, proposal)
    action = action or _action(completed_at=NOW, evidence=["m.csv"], actual_impact=9000.0, recurrence=False)
    result = VerificationService(verdict_source, cycle["events"]).verify(_follow_up(), action, GESTOR, 1)
    return cycle["learning"].record(proposal=proposal, decision=decision, action=action, verification=result,
                                    pattern_key=PATTERN, actor=GESTOR, now=NOW), result


def test_14_learning_is_recorded_after_decision_action_and_verification(cycle, proposal):
    ok = MetricRegistryVerifier(_Registry(target=85), lambda n, a: 90.0, clock=lambda: NOW)
    learning, result = _learn(cycle, proposal, ok)
    assert learning.verified_result is VerificationVerdict.VERIFIED_OK
    assert learning.decision_outcome is DecisionOutcome.APPROVED
    assert learning.actual_impact == 9000.0 and learning.recurrence is False
    assert learning.enables_reuse() is True  # habilitaria reuso no futuro — não ativa nada agora
    assert learning.to_learning_create(pattern="ocupação baixa", intervention="renegociar").confidence == 50.0
    assert result.state is CaseState.VERIFIED_OK


def test_15_learning_is_not_a_decision(cycle, proposal):
    learning, _ = _learn(cycle, proposal, MetricRegistryVerifier(_Registry(85), lambda n, a: 90.0, clock=lambda: NOW))
    assert not hasattr(learning, "approve")
    assert learning.state is CaseState.LEARNED
    payload = next(event.payload for event in cycle["audit"].read_all()
                   if event.payload.get("cycle_event") == CycleEvent.LEARNING_RECORDED.value)
    assert payload["creates_approval"] is False


def test_16_unapproved_decision_generates_no_action(cycle, proposal):
    for method in ("reject_proposal", "request_more_evidence"):
        decision = getattr(cycle["approval"], method)(proposal, GESTOR, "motivo", "rec-1", 1)
        with pytest.raises(GovernanceViolation):
            cycle["linker"].link_action(decision, proposal, GESTOR, "gestor", NOW + timedelta(days=7))


def test_17_action_without_verification_never_becomes_verified_ok(cycle, proposal):
    incomplete = _action(started_at=NOW)
    result = VerificationService(NoSourceVerifier(clock=lambda: NOW), cycle["events"]).verify(
        _follow_up(), incomplete, GESTOR, 1)
    assert result.verdict is VerificationVerdict.INSUFFICIENT_EVIDENCE
    assert state_from_action(incomplete, NOW) is CaseState.ACTION_EXECUTING
    with pytest.raises(GovernanceViolation):
        cycle["learning"].record(proposal=proposal, decision=_approve(cycle, proposal), action=incomplete,
                                 verification=result, pattern_key=PATTERN, actor=GESTOR, now=NOW)
    with pytest.raises(IllegalTransition):
        assert_transition(CaseState.ACTION_COMPLETED, CaseState.VERIFIED_OK)


# 18–20 ─ playbook, auditoria, RBAC ──────────────────────────────────────────────────────────

def test_18_unapproved_playbook_never_active():
    stats = PatternStatsRecord(pattern_key=PATTERN, occurrences=9, approved_decisions=1, verified_ok=1)
    candidate = candidate_playbook(pattern_key=PATTERN, case_type="transfer", name="rota ociosa",
                                   conditions={}, recommended_action={}, rules_version="rules:1",
                                   magnitude_band="BAIXA", stats=stats, now=NOW)
    assert candidate.status == "pending_approval"  # recorrência nunca ativa sozinha
    with pytest.raises(GovernanceViolation):
        approve_playbook(candidate, ROUTER_AGENT, stats=stats, evidence=("caso-1",),
                         current_rules_version="rules:1", now=NOW)
    with pytest.raises(GovernanceViolation):
        approve_playbook(candidate, ANALISTA, stats=stats, evidence=("caso-1",),
                         current_rules_version="rules:1", now=NOW)
    sem_historico = PatternStatsRecord(pattern_key=PATTERN, occurrences=1)
    assert eligibility(candidate, sem_historico, (), "rules:1").eligible is False
    with pytest.raises(GovernanceViolation):
        approve_playbook(candidate, GESTOR, stats=sem_historico, evidence=(), current_rules_version="rules:1",
                         now=NOW)
    approved = approve_playbook(candidate, GESTOR, stats=stats, evidence=("caso-1",),
                                current_rules_version="rules:1", now=NOW)
    assert approved.status == "active" and approved.approved_by == "tatiana" and approved.approved_at == NOW


def test_19_audit_trail_records_every_step(cycle, proposal, tmp_path):
    decision = _approve(cycle, proposal)
    cycle["linker"].link_action(decision, proposal, GESTOR, "gestor", NOW + timedelta(days=7))
    events = cycle["audit"].read_all()
    kinds = [event.payload["cycle_event"] for event in events]
    assert CycleEvent.DECISION_APPROVED.value in kinds and CycleEvent.ACTION_LINKED.value in kinds
    approval = next(event for event in events if event.payload["cycle_event"] == CycleEvent.DECISION_APPROVED.value)
    assert approval.event_type == "human_decision" and approval.actor == "tatiana"
    assert approval.payload["actor_kind"] == "human" and approval.payload["case_version"] == 1
    assert approval.payload["rationale"] and approval.timestamp
    # append-only: o arquivo do audit trail existente é o único sink
    assert (tmp_path / "audit_trail.jsonl").exists()
    linked = next(event for event in events if event.payload["cycle_event"] == CycleEvent.ACTION_LINKED.value)
    assert linked.payload["executed"] is False


def test_20_rbac_is_enforced_for_every_human_operation(cycle, proposal):
    for method in ("approve_proposal", "reject_proposal", "request_more_evidence"):
        with pytest.raises(GovernanceViolation):
            getattr(cycle["approval"], method)(proposal, ANALISTA, "motivo", "rec-1", 1)
    with pytest.raises(GovernanceViolation):
        cycle["approval"].approve_proposal(proposal, GESTOR, "   ", "rec-1", 1)  # sem motivo
    assert cycle["approval"].approve_proposal(proposal, human("gestor.malha", Role.GESTOR), "ok", "rec-1", 1)


# 21–22 ─ idempotência e shadow sem escrita ──────────────────────────────────────────────────

def test_21_idempotency_of_states_and_proposals(shadow_route):
    diagnosis = _diagnosis()
    first = build_proposal(case_id="caso-1", exact_fingerprint=shadow_route.fingerprints.exact,
                           route=shadow_route, diagnosis=diagnosis, recommendation=diagnosis.recommendations[0],
                           proposed_by=ROUTER_AGENT, created_at=NOW, proposal_id="prop-x")
    second = first.model_copy()
    assert first == second and first.proposal_id == second.proposal_id
    assert state_from_diagnosis_status(DecisionStatus.READY_FOR_DECISION) is CaseState.DIAGNOSED
    assert state_from_route(shadow_route) is CaseState.INVESTIGATING  # rota real → estado do ciclo
    assert state_from_action(_action(completed_at=NOW), NOW) is CaseState.ACTION_COMPLETED
    with pytest.raises(ValidationError):
        first.status = "APPROVED"  # contrato congelado: proposta não vira decisão por mutação


def test_22_cycle_shadow_writes_nothing_but_the_report(tmp_path):
    repository = InMemoryCaseMemoryRepository()
    stats_service = PatternStatsService(repository, MemoryMode.SHADOW_READ_ONLY)
    assert stats_service.writes is False
    learning = type("L", (), {"pattern_key": PATTERN, "decision_outcome": DecisionOutcome.APPROVED,
                              "verified_result": VerificationVerdict.VERIFIED_OK})()
    projected = stats_service.project(learning, NOW)
    assert projected.approved_decisions == 1 and repository.get_pattern_stats(PATTERN) is None
    with pytest.raises(MemoryWriteBlocked):
        stats_service.apply(learning, NOW)
    with pytest.raises(MemoryWriteBlocked):
        PatternStatsService(repository, MemoryMode.PERSIST)

    before = {path: path.read_bytes() for path in FIXTURE_TORRE.rglob("*") if path.is_file()}
    run = run_cycle_shadow(FIXTURE_TORRE, run_id="ciclo-teste")
    target = write_cycle_report(run, tmp_path)
    report = cycle_report(run)
    assert report["cases_received"] > 0
    assert report["effects"] == {"ai_calls": 0, "proposals_created": 0, "approvals": 0, "actions_linked": 0,
                                 "actions_executed": 0, "verifications": 0, "learnings": 0, "notifications": 0}
    assert json.loads((target / "summary.json").read_text(encoding="utf-8"))["cases_received"] > 0
    assert {path: path.read_bytes() for path in FIXTURE_TORRE.rglob("*") if path.is_file()} == before
