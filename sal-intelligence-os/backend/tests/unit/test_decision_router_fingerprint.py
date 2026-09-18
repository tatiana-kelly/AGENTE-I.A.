"""fp/1: canonicalização determinística e o que torna casos iguais, semelhantes ou diferentes."""

from app.decision_router.bands import classify_band
from app.decision_router.fingerprint import canonical_json, compute_fingerprints, sha256_tagged
from tests.fixtures.decision_router_loader import build_router, fixture_policy, load_cases

CASES = load_cases()
POLICY = fixture_policy()


def _envelope(case_id: str, **alert_updates):
    _, envelope = build_router(CASES[case_id], POLICY)
    if alert_updates:
        envelope = envelope.model_copy(update={"alert": envelope.alert.model_copy(update=alert_updates)})
    return envelope


def _fingerprints(envelope):
    metric = POLICY.metric(envelope.alert.metric_id)
    band = classify_band(metric, envelope)
    flags = tuple(sorted(set(metric.approval_flags) | set(envelope.approval_flags)))
    return compute_fingerprints(envelope, metric, band, flags)


def test_canonical_json_ignores_key_order():
    assert canonical_json({"b": 1, "a": [2, {"d": 3, "c": 4}]}) == canonical_json({"a": [2, {"c": 4, "d": 3}], "b": 1})
    assert sha256_tagged({"x": 1}).startswith("sha256:") and len(sha256_tagged({"x": 1})) == 71


def test_same_alert_same_fingerprints():
    assert _fingerprints(_envelope("F05")) == _fingerprints(_envelope("F05"))


def test_period_change_changes_exact_but_keeps_similarity():
    base = _fingerprints(_envelope("F05"))
    other = _fingerprints(_envelope("F05", period="2026-08", current_value=29.6))
    assert base.exact != other.exact
    assert base.pattern_key == other.pattern_key
    assert base.lineage_key == other.lineage_key


def test_direction_change_changes_similarity():
    base = _fingerprints(_envelope("F05"))
    other = _fingerprints(_envelope("F05", current_value=40.0, reference_value=36.0))
    assert base.pattern_key != other.pattern_key


def test_band_change_changes_similarity():
    base = _fingerprints(_envelope("F05"))  # 30.0 → CRITICO
    other = _fingerprints(_envelope("F05", current_value=31.5))  # AVISO
    assert base.pattern_key != other.pattern_key
    assert base.lineage_key == other.lineage_key


def test_dominant_dimension_change_changes_similarity():
    base = _fingerprints(_envelope("F05"))
    other = _fingerprints(
        _envelope("F05", concentration=[{"dimension": "regiao", "value": "Sul", "share_pct": 70}])
    )
    assert base.pattern_key != other.pattern_key


def test_engine_source_change_changes_similarity():
    envelope = _envelope("F09")
    other = envelope.model_copy(update={"engine_source": "torre.motor_snapshot_painel"})
    assert _fingerprints(envelope).pattern_key != _fingerprints(other).pattern_key


def test_missing_band_still_produces_fingerprint():
    envelope = _envelope("F01")
    metric = POLICY.metric(envelope.alert.metric_id)
    assert classify_band(metric, envelope).missing
    prints = _fingerprints(envelope)
    assert prints.exact.startswith("sha256:") and prints.pattern_key.startswith("sha256:")


def test_occupancy_labels_are_engine_specific():
    envelope = _envelope("F09", current_value=55.0)
    metric = POLICY.metric("ocupacao-transferencia")
    painel = envelope.model_copy(update={"engine_source": "torre.motor_snapshot_painel"})
    assert classify_band(metric, envelope).label == "MODERADA"  # config_investigador [50,70)
    assert classify_band(metric, painel).label == "ALTA"  # config_operacional <60 = ociosidade
