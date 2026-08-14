"""Mapeia docs/ACCEPTANCE_TESTS.md Teste 1, 3 e 5 — a parte que dá para provar em código,
sem depender de uma chamada real ao LLM: o contrato DiagnosisBase é estrutural, não uma sugestão
de prompt. Se um agente tentar devolver "só o KPI" ou uma solução abstrata sem dono/prazo/KPI,
a validação falha antes de virar um registro."""

import pytest
from pydantic import ValidationError

from app.schemas.diagnosis import DiagnosisBase

VALID_RECOMMENDATIONS = [
    {
        "type": "containment",
        "action": "Reduzir alçada de desconto para clientes Linha Premium",
        "expected_impact": "R$ 60 mil/mês",
        "effort": "low",
        "risk": "low",
        "time_to_value": "7 dias",
        "reversibility": "reversible",
        "owner_role": "gerente comercial",
        "deadline": "2026-08-20",
        "success_kpi": "margem bruta",
        "success_target": "33%",
    },
    {
        "type": "structural",
        "action": "Renegociar contrato dos 2 fornecedores responsáveis por 71% do aumento de aquisição",
        "expected_impact": "R$ 120 mil/mês",
        "effort": "medium",
        "risk": "medium",
        "time_to_value": "45 dias",
        "reversibility": "partially_reversible",
        "owner_role": "diretoria de compras",
        "deadline": "2026-09-30",
        "success_kpi": "custo de aquisição",
        "success_target": "-5%",
    },
    {
        "type": "optimization",
        "action": "Consolidar pedidos fracionados nas 3 rotas com maior aumento de frete",
        "expected_impact": "R$ 40 mil/mês",
        "effort": "low",
        "risk": "low",
        "time_to_value": "15 dias",
        "reversibility": "reversible",
        "owner_role": "operação da filial",
        "deadline": "2026-08-28",
        "success_kpi": "frete extraordinário",
        "success_target": "-30%",
    },
]

VALID_HYPOTHESES = [
    {
        "statement": "Descontos adicionais não autorizados reduziram a margem",
        "favorable_evidence": ["57% dos descontos concentrados em 4 vendedores"],
        "contrary_evidence": ["descontos explicam só 50% do desvio total"],
        "missing_evidence": ["política de alçada vigente no período"],
        "confidence": 70,
        "status": "untested",
    },
    {
        "statement": "Custo de aquisição não renegociado also pressionou a margem",
        "favorable_evidence": ["71% do aumento de aquisição em 2 fornecedores"],
        "contrary_evidence": [],
        "missing_evidence": ["contrato vigente com os 2 fornecedores"],
        "confidence": 65,
        "status": "untested",
    },
]


def _base_payload(**overrides) -> dict:
    payload = {
        "facts": [{"fato": "margem bruta caiu 6 p.p. no período"}],
        "concentration": [{"dimensao": "linha_produto", "chave": "Linha Premium", "participacao_pct": 62}],
        "hypotheses": VALID_HYPOTHESES,
        "probable_cause": "combinação de descontos não autorizados e custo de aquisição não renegociado",
        "confidence": 75,
        "recommendations": VALID_RECOMMENDATIONS,
        "owner": "diretoria comercial",
        "success_kpi": "margem bruta",
        "decision_status": "READY_FOR_DECISION",
    }
    payload.update(overrides)
    return payload


def test_diagnosis_with_only_kpi_value_is_rejected():
    """Teste 1 — um alerta que só repete o KPI não pode virar Diagnosis válido: faltam hipóteses e recomendações."""
    with pytest.raises(ValidationError):
        DiagnosisBase.model_validate({"probable_cause": "margem caiu", "confidence": 50, "owner": "x"})


def test_diagnosis_requires_at_least_one_hypothesis():
    with pytest.raises(ValidationError):
        DiagnosisBase.model_validate(_base_payload(hypotheses=[]))


def test_diagnosis_rejects_single_cause_without_alternative_hypothesis_data():
    """Teste 2 (parcial, estrutural) — não é o schema que decide se a causa é única, mas ele obriga a
    registrar >= 1 hipótese com evidência a favor/contra; um diagnóstico de causa única "porque sim"
    não preenche favorable_evidence/contrary_evidence e falha aqui."""
    bad_hypotheses = [{"statement": "desconto é a causa", "confidence": 90, "status": "confirmed"}]
    with pytest.raises(ValidationError):
        DiagnosisBase.model_validate(_base_payload(hypotheses=bad_hypotheses))


def test_diagnosis_rejects_irreversible_action_pretending_high_confidence_without_data():
    """Teste 3 — confiança baixa + ação irreversível é uma combinação que o Solutions agent não deve propor;
    aqui garantimos ao menos que reversibility é um campo obrigatório e tipado, não texto livre ignorável."""
    recs = [dict(r) for r in VALID_RECOMMENDATIONS]
    del recs[0]["reversibility"]
    with pytest.raises(ValidationError):
        DiagnosisBase.model_validate(_base_payload(recommendations=recs))


def test_diagnosis_rejects_fewer_than_three_recommendations():
    with pytest.raises(ValidationError):
        DiagnosisBase.model_validate(_base_payload(recommendations=VALID_RECOMMENDATIONS[:2]))


def test_diagnosis_rejects_recommendations_missing_a_horizon():
    """Teste 5 — 3 recomendações que não cobrem contenção+estrutural+otimização (ex.: 2 estruturais e 1
    contenção) não são um conjunto válido — a regra .claude/rules/action-design.md exige os 3 horizontes."""
    recs = [dict(r) for r in VALID_RECOMMENDATIONS]
    recs[2]["type"] = "structural"  # agora tem containment, structural, structural — falta optimization
    with pytest.raises(ValidationError):
        DiagnosisBase.model_validate(_base_payload(recommendations=recs))


def test_diagnosis_rejects_abstract_recommendation_without_owner_or_deadline():
    """Teste 5 — "melhorar margem" sem dono/prazo/KPI não é uma recomendação válida."""
    recs = [dict(r) for r in VALID_RECOMMENDATIONS]
    del recs[0]["owner_role"]
    del recs[0]["deadline"]
    with pytest.raises(ValidationError):
        DiagnosisBase.model_validate(_base_payload(recommendations=recs))


def test_ready_for_decision_requires_minimum_confidence():
    """config/priority-scoring.yaml: minimum_confidence_ready_for_decision = 70."""
    with pytest.raises(ValidationError):
        DiagnosisBase.model_validate(_base_payload(confidence=50, decision_status="READY_FOR_DECISION"))


def test_valid_diagnosis_is_accepted():
    diagnosis = DiagnosisBase.model_validate(_base_payload())
    assert len(diagnosis.recommendations) == 3
    assert {r.type for r in diagnosis.recommendations} == {"containment", "structural", "optimization"}
