"""Teste 7 de docs/ACCEPTANCE_TESTS.md — decisão trabalhista/jurídica/fiscal/contrato relevante
exige HUMAN_APPROVAL_REQUIRED, tanto no gate de prioridade quanto na API de decisões."""

import pytest
from fastapi import HTTPException

from app.core.rbac import Role, require_approval_role
from app.services.priority_engine import PriorityEngine

SENSITIVE_FLAGS = [
    "disciplinary_people_action",
    "legal_final_interpretation",
    "material_tax_or_accounting_change",
    "fraud_allegation",
    "material_contract_or_payment",
    "irreversible_high_impact_action",
]


@pytest.mark.parametrize("flag", SENSITIVE_FLAGS)
def test_each_sensitive_flag_triggers_human_approval(flag):
    engine = PriorityEngine()
    needs_approval, triggered = engine.requires_human_approval([flag])
    assert needs_approval is True
    assert triggered == [flag]


def test_analista_cannot_approve_decision():
    with pytest.raises(HTTPException) as exc_info:
        require_approval_role(Role.ANALISTA)
    assert exc_info.value.status_code == 403


def test_gestor_can_approve_decision():
    require_approval_role(Role.GESTOR)  # não deve levantar


def test_decision_endpoint_blocks_analista(client):
    response = client.post(
        "/decisions",
        json={"recommendation_id": "rec-1", "decision": "approved", "human_owner": "Tatiana"},
        headers={"X-Sal-Role": "analista"},
    )
    assert response.status_code == 403


def test_decision_endpoint_allows_gestor(client):
    response = client.post(
        "/decisions",
        json={"recommendation_id": "rec-1", "decision": "approved", "human_owner": "Tatiana"},
        headers={"X-Sal-Role": "gestor"},
    )
    assert response.status_code == 201
