"""Fase 5G — trava de teste sintético: nenhuma requisição sai sem ser comprovadamente sintética e dentro dos limites."""

from datetime import UTC, datetime

import pytest

from app.agent_bridge import AgentRunClientConfig, Evidence, EvidenceQuality, build_investigation_request
from app.agent_bridge.contract import ExecutionLimits, ReviewPolicy
from app.agent_bridge.synthetic_guard import (
    GuardedClient,
    SyntheticGuardPolicy,
    SyntheticGuardViolation,
    validate_synthetic_request,
)

CFG = AgentRunClientConfig(base_url="http://127.0.0.1:3100", principal="service:sal-intelligence-os",
                           project="sal-intelligence-os", secret="s" * 40)
POLICY = SyntheticGuardPolicy(real_markers=frozenset({"CIDADE-REAL-X", "ROTA-REAL→Y"}),
                              authorized_context=frozenset({"ARCHITECTURE.md", "DATA_MODEL.md", "AGENT_WORKFLOW.md"}),
                              max_cost_usd_per_call=1.0, max_cost_usd_per_job=3.0)


def _evidence(filters=None, data=None):
    return (Evidence(id="ev-sint", source="caso sintético", period="P1", timestamp=datetime(2026, 9, 18, tzinfo=UTC),
                     filters=filters if filters is not None else {"synthetic_test": True},
                     quality=EvidenceQuality(source_quality="sintetica"), data=data or {"ocupacao_pct": 30}),)


def _request(**overrides):
    base = {"config": CFG, "case_id": "sint", "fingerprint": "sha256:sint", "agent": "investigador", "agent_version": "1.0.0",
            "task": "Investigue o caso sintético.", "context_files": ("ARCHITECTURE.md",), "evidence": _evidence(),
            "business_data": {"synthetic_test": True},
            "limits": ExecutionLimits(timeout_seconds=120, max_attempts=2, max_cost_usd_per_call=1, max_cost_usd_per_job=3),
            "review": ReviewPolicy(required=False, max_correction_attempts=0)}
    base.update(overrides)
    return build_investigation_request(**base)


def test_requisicao_sintetica_valida_passa():
    validate_synthetic_request(_request(), POLICY)


@pytest.mark.parametrize(("overrides", "motivo"), [
    ({"business_data": {}}, "synthetic_test"),
    ({"evidence": _evidence(filters={})}, "evidência sem marcação"),
    ({"evidence": _evidence(data={"rota": "CIDADE-REAL-X"})}, "marcadores de dado real"),
    ({"task": "Investigue a ROTA-REAL→Y"}, "marcadores de dado real"),
    ({"context_files": ("ARCHITECTURE.md", "MASTER_SPEC.md")}, "contexto fora do autorizado"),
    ({"limits": ExecutionLimits(timeout_seconds=120, max_attempts=2, max_cost_usd_per_call=5, max_cost_usd_per_job=3)}, "orçamento"),
    ({"limits": ExecutionLimits(timeout_seconds=120, max_attempts=2, max_cost_usd_per_call=1, max_cost_usd_per_job=50)}, "orçamento"),
])
def test_qualquer_falha_bloqueia(overrides, motivo):
    with pytest.raises(SyntheticGuardViolation, match=motivo):
        validate_synthetic_request(_request(**overrides), POLICY)


def test_corpo_acima_do_limite_bloqueia():
    with pytest.raises(SyntheticGuardViolation, match="bytes"):
        validate_synthetic_request(_request(), SyntheticGuardPolicy(**{**POLICY.__dict__, "max_body_bytes": 100}))


def test_cliente_protegido_nao_chama_o_provider_quando_a_trava_falha():
    class Espiao:
        chamadas = 0

        def run(self, request, **_kwargs):
            Espiao.chamadas += 1

    guarded = GuardedClient(Espiao(), POLICY)
    with pytest.raises(SyntheticGuardViolation):
        guarded.run(_request(business_data={}))
    assert Espiao.chamadas == 0 and guarded.validated == []
    guarded.run(_request())
    assert Espiao.chamadas == 1 and len(guarded.validated) == 1
