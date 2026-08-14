import pytest

from app.services.priority_engine import PriorityEngine

FULL_DIMENSIONS = {
    "financial_impact": 90,
    "operational_impact": 50,
    "risk_impact": 40,
    "urgency": 60,
    "causal_confidence": 87,
    "reversibility": 80,
    "ease": 70,
    "time_to_value": 60,
}


def test_score_matches_weighted_sum():
    engine = PriorityEngine()
    score = engine.score(FULL_DIMENSIONS)
    expected = sum(FULL_DIMENSIONS[name] * spec["weight"] for name, spec in engine.dimensions.items())
    assert score == round(expected, 2)


def test_score_raises_when_dimension_missing():
    engine = PriorityEngine()
    with pytest.raises(ValueError):
        engine.score({"financial_impact": 90})


def test_label_matches_configured_ranges():
    engine = PriorityEngine()
    assert engine.label_for(90) == "EXECUTAR/DECIDIR AGORA"
    assert engine.label_for(75) == "ALTA PRIORIDADE"
    assert engine.label_for(55) == "INVESTIGAR OU DELEGAR"
    assert engine.label_for(10) == "BAIXA PRIORIDADE"


def test_human_approval_required_for_disciplinary_action():
    engine = PriorityEngine()
    needs_approval, triggered = engine.requires_human_approval(["disciplinary_people_action"])
    assert needs_approval is True
    assert triggered == ["disciplinary_people_action"]


def test_human_approval_not_required_for_unrelated_flags():
    engine = PriorityEngine()
    needs_approval, triggered = engine.requires_human_approval(["routine_flag"])
    assert needs_approval is False
    assert triggered == []
