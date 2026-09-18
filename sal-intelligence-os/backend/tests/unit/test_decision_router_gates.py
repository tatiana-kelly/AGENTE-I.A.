"""Portas isoladas: qualidade, regra, memória, material_change, reuso, aprendizado, playbook, UNKNOWN."""

from datetime import datetime

from app.decision_router.bands import classify_band
from app.decision_router.gates import (
    deterministic_rule_gate,
    learning_gate,
    material_change_reasons,
    memory_gate,
    playbook_gate,
    quality_gate,
    reuse_failures,
    similarity_gate,
)
from app.decision_router.inputs import MemoryEntry, PatternStats, Playbook, QualityInputs, ReferenceCase
from app.decision_router.policy import b7_recommended_reuse
from app.services.data_quality_gate import DataQualityGate
from tests.fixtures.decision_router_loader import build_router, fixture_policy, load_cases

CASES = load_cases()
POLICY = fixture_policy()
GATE = DataQualityGate(minimum_score=POLICY.minimum_data_quality)


def _envelope(case_id: str):
    return build_router(CASES[case_id], POLICY)[1]


def _band(envelope):
    return classify_band(POLICY.metric(envelope.alert.metric_id), envelope)


def test_quality_blocks_missing_concentration():
    envelope = _envelope("F05")
    envelope = envelope.model_copy(update={"alert": envelope.alert.model_copy(update={"concentration": []})})
    outcome = quality_gate(envelope, GATE, POLICY.minimum_data_quality)
    assert outcome.blocked and outcome.status.score < 100


def test_quality_blocks_stale_data_with_injected_clock():
    envelope = _envelope("F05").model_copy(
        update={"quality_inputs": QualityInputs(last_updated_at=datetime.fromisoformat("2026-07-01T00:00:00+00:00"),
                                                max_age_hours=48)}
    )
    assert quality_gate(envelope, GATE, POLICY.minimum_data_quality).blocked


def test_rule_dismisses_divergence_below_existing_threshold():
    envelope = _envelope("F01")
    envelope = envelope.model_copy(update={"alert": envelope.alert.model_copy(update={"current_value": 17500})})
    outcome = deterministic_rule_gate(envelope, POLICY.metric(envelope.alert.metric_id), _band(envelope))
    assert outcome.resolution is not None and outcome.resolution.outcome == "dismissed"


def test_rule_dismisses_margin_below_materiality():
    envelope = _envelope("F05")
    envelope = envelope.model_copy(update={"alert": envelope.alert.model_copy(update={"materiality": 150000})})
    outcome = deterministic_rule_gate(envelope, POLICY.metric("margem-bruta"), _band(envelope))
    assert outcome.resolution is not None and outcome.resolution.outcome == "dismissed"


def test_memory_material_change_does_not_resolve():
    envelope = _envelope("F01")
    entry = MemoryEntry(engine_source=envelope.engine_source, direction="up", delta=600.0, magnitude_band="MISSING",
                        status="ABERTA", causa="rateio", source_ref="ledger")
    outcome = memory_gate(envelope, POLICY.metric(envelope.alert.metric_id), _band(envelope), entry)
    assert outcome.resolution is None  # 1200 vs 600 = 100% > 15%


def test_memory_from_other_engine_is_not_equivalent():
    envelope = _envelope("F01")
    entry = MemoryEntry(engine_source="torre.outro_motor", direction="up", delta=1150.0, magnitude_band="MISSING",
                        status="ABERTA", causa="rateio", false_positive_active=True, source_ref="ledger")
    assert memory_gate(envelope, POLICY.metric(envelope.alert.metric_id), _band(envelope), entry).resolution is None


def test_material_change_detects_direction_band_dimension_and_rules():
    envelope = _envelope("F06")
    reference = ReferenceCase.model_validate(CASES["F06"]["state"]["reference"]).model_copy(
        update={"direction": "up", "magnitude_band": "AVISO", "dominant_dimension": "regiao", "rules_version": "rv-old"}
    )
    reasons = material_change_reasons(envelope, _band(envelope), reference)
    assert set(reasons) == {"direction", "magnitude_band", "dominant_dimension", "rules_version"}


def test_reference_from_other_engine_is_not_similar():
    envelope = _envelope("F06")
    reference = ReferenceCase.model_validate(CASES["F06"]["state"]["reference"]).model_copy(
        update={"engine_source": "torre.outro_motor"}
    )
    outcome = similarity_gate(envelope, _band(envelope), reference)
    assert outcome.reference is None and outcome.similarity is None


def _reuse_failures(envelope, reference, stats=None, reuse=None):
    band = _band(envelope)
    similarity = similarity_gate(envelope, band, reference).similarity
    metric = POLICY.metric(envelope.alert.metric_id)
    return reuse_failures(envelope, metric, band, metric.approval_flags, similarity, reference, stats,
                          reuse or POLICY.reuse)


def test_reuse_allowed_only_when_every_condition_holds():
    envelope = _envelope("F06")
    reference = ReferenceCase.model_validate(CASES["F06"]["state"]["reference"])
    assert _reuse_failures(envelope, reference) == ()


def test_reuse_blocked_by_each_condition():
    envelope = _envelope("F06")
    reference = ReferenceCase.model_validate(CASES["F06"]["state"]["reference"])
    variants = {
        "rejeitada": {"decision": reference.decision.model_copy(update={"outcome": "rejected"})},
        "confiança": {"diagnosis": reference.diagnosis.model_copy(update={"confidence": 69})},
        "status": {"diagnosis": reference.diagnosis.model_copy(update={"decision_status": "NEEDS_INVESTIGATION"})},
        "hipótese": {"diagnosis": reference.diagnosis.model_copy(update={"hypothesis_statuses": ("inconclusive",)})},
        "ação": {"action": reference.action.model_copy(update={"outcome": "partial"})},
        "recorrência": {"action": reference.action.model_copy(update={"recurrence": None})},
        "aprendizado": {"learning": reference.learning.model_copy(update={"actual_impact": 299999})},
        "regras": {"rules_version": "rv-old"},
        "reaberto": {"reopen_count": 1},
        "validade": {"period": "2026-06"},
    }
    for name, update in variants.items():
        assert _reuse_failures(envelope, reference.model_copy(update=update)), name


def test_reuse_blocked_when_band_missing():
    envelope = _envelope("F06")
    reference = ReferenceCase.model_validate(CASES["F06"]["state"]["reference"]).model_copy(
        update={"magnitude_band": "MISSING"}
    )
    policy = POLICY.with_thresholds(
        "margem-bruta", POLICY.metric("margem-bruta").thresholds.__class__(36, 33, 30, source="mock")
    )
    metric = policy.metric("margem-bruta")
    band = classify_band(metric, envelope)
    assert band.missing
    similarity = similarity_gate(envelope, band, reference).similarity
    failures = reuse_failures(envelope, metric, band, (), similarity, reference, None, policy.reuse)
    assert "magnitude_band MISSING" in failures


def test_b7_recommended_preset_blocks_first_reuse_with_single_decision():
    envelope = _envelope("F06")
    reference = ReferenceCase.model_validate(CASES["F06"]["state"]["reference"])
    failures = _reuse_failures(envelope, reference, reuse=b7_recommended_reuse(POLICY.reuse))
    assert any("decisões aprovadas" in failure for failure in failures)


def test_learning_veto():
    assert learning_gate(PatternStats(reuse_verified_fail=1)).veto
    assert learning_gate(PatternStats(reuse_blocked=True)).veto
    assert not learning_gate(PatternStats(verified_ok=3)).veto


def test_playbook_rejected_when_missing_band_or_veto_or_expired():
    envelope = _envelope("F09")
    band = _band(envelope)
    playbook = Playbook.model_validate(CASES["F09"]["state"]["playbook"])
    stats = PatternStats(verified_ok=2)
    assert playbook_gate(envelope, band, playbook, stats, learning_veto=False).applies
    assert not playbook_gate(envelope, band, playbook, stats, learning_veto=True).applies
    expired = playbook.model_copy(update={"valid_until": datetime.fromisoformat("2026-09-10T00:00:00+00:00")})
    assert not playbook_gate(envelope, band, expired, stats, learning_veto=False).applies
    suspended = playbook.model_copy(update={"status": "suspended"})
    assert not playbook_gate(envelope, band, suspended, stats, learning_veto=False).applies


def test_medium_confidence_mapping_is_not_routed_to_agents():
    case = {**CASES["F01"], "state": {}}
    router, envelope = build_router(case, POLICY)
    route = router.route(envelope)
    assert route.route == "INVESTIGATE_FIRST"
    assert route.selected_agents == ()
    assert route.mapping_confidence == "MEDIA"
    assert "confirmação humana" in route.next_step.missing_evidence[0]
