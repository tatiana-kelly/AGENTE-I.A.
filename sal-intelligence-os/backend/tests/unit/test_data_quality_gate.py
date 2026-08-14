from datetime import UTC, datetime, timedelta

from app.services.data_quality_gate import DataQualityGate


def test_freshness_check_fails_when_stale():
    gate = DataQualityGate()
    ok, reason = gate.check_freshness(datetime.now(UTC) - timedelta(days=10), timedelta(days=1))
    assert not ok
    assert "desatualizado" in reason


def test_completeness_check_lists_missing_fields():
    gate = DataQualityGate()
    ok, reason = gate.check_completeness({"a": 1, "b": None}, ["a", "b", "c"])
    assert not ok
    assert "b" in reason and "c" in reason


def test_evaluate_blocks_when_below_minimum_score():
    gate = DataQualityGate(minimum_score=80)
    result = gate.evaluate([(True, "ok"), (False, "duplicado")])
    assert result.passed is False
    assert result.score == 50
    assert "duplicado" in result.reasons


def test_evaluate_passes_when_all_checks_ok():
    gate = DataQualityGate()
    result = gate.evaluate([(True, "ok"), (True, "ok")])
    assert result.passed is True
    assert result.score == 100
