"""FASE 5F — MULTI_AGENT e fluxo sintético completo (Tarefas 1 e 6).

RECEIVED → QUALITY_GATE → DECISION_ROUTER → MULTI_AGENT → AGENTE A → AGENTE B → CONSOLIDATION → REVIEW → NEEDS_HUMAN

Tudo sintético: o Decision Router é o real (determinístico, sem IA); o cliente do agent-run é um dublê que
registra cada requisição. Nenhuma chamada paga, nenhuma escrita na Torre, nenhuma decisão/ação/aprendizado.
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.agent_bridge import AgentRunClientConfig, AgentRunProviderFailure
from app.agent_bridge.client import AgentRunOutputRejected
from app.agent_bridge.contract import (
    AgentRunResult,
    Evidence,
    EvidenceQuality,
    ExecutionLimits,
    InvestigationOutput,
)
from app.agent_bridge.multi_agent import (
    CASE_BUDGET_USD,
    CORRECTION_ROUNDS,
    MultiAgentInvestigation,
    RouteNotInvestigable,
    consolidate,
)
from app.decision_cycle.states import CaseState, IllegalTransition, assert_transition
from app.decision_router.adapters.base import PRIORITY_SEVERITY
from app.decision_router.adapters.torre_transferencias import SOURCE as TRANSFER_SOURCE
from app.decision_router.inputs import AlertEnvelope, EngineSignals
from app.decision_router.policy import build_default_policy
from app.decision_router.providers import (
    InMemoryMemoryLedgerProvider,
    InMemoryPatternStatsProvider,
    InMemoryPlaybookProvider,
    InMemoryRouteStore,
    InMemorySimilarityCaseProvider,
)
from app.decision_router.router import DecisionRouter
from app.schemas.alert import AlertBase

SECRET = "segredo-de-teste-multiagente-com-32+chars"
CONFIG = AgentRunClientConfig(base_url="http://127.0.0.1:3100", principal="service:sal-intelligence-os",
                              project="sal-intelligence-os", secret=SECRET)
LIMITS = ExecutionLimits(timeout_seconds=120, max_attempts=2, max_cost_usd_per_call=1, max_cost_usd_per_job=3)
EVIDENCE = (Evidence(id="ev-sint", source="ROTA-SINTÉTICA (inventada)", period="5du:P1", timestamp=datetime(2026, 9, 18, tzinfo=UTC),
                     quality=EvidenceQuality(source_quality="sintetica"), data={"ocupacao_pct": 25.5}),)


def _output(agent: str, confidence: float) -> dict:
    return {"facts": [f"ocupação 25,5% segundo {agent} (ev-sint)"], "calculations": ["85 - 25,5 = 59,5"],
            "inferences": [f"inferência de {agent}"], "hypotheses": [{"statement": f"hipótese de {agent}",
            "favorable_evidence": ["ev-sint"], "contrary_evidence": [], "missing_evidence": ["ida"], "confidence": confidence}],
            "contradictions": [], "missing_data": [f"dado que {agent} precisa"], "evidence": ["ev-sint"], "confidence": confidence}


def _result(request, *, status="succeeded", output=None, review=None, provider="anthropic") -> AgentRunResult:
    return AgentRunResult.model_validate({
        "protocol_version": "sal.agent-run/1.0", "request_id": request.request_id, "run_id": f"run-{request.agent}",
        "status": status, "agent": request.agent, "agent_version": "1.0.0",
        "agent_authority": request.agent_authority.model_dump(), "output": output,
        "output_validation": {"valid": output is not None, "reason": "ok" if output else "sem output"},
        "review": review or {"required": False, "reviewed": False, "status": "NOT_RUN", "corrections": 0},
        "providers": {"primary": provider, "fallback_triggered": False},
        "usage": [{"role": "author", "provider": provider, "outcome": "success", "usage_status": "reported"}],
        "context": {"project": "sal-intelligence-os", "files_sent": [], "missing_context": []},
        "evidence_received": ["ev-sint"], "replayed": False, "created_at": "2026-09-18T12:00:00Z",
        "mode": "consolidated_review" if request.review_target else "investigation",
    })


class FakeClient:
    """Dublê do AgentRunClient: registra cada requisição e responde conforme o roteiro por agente."""

    def __init__(self, *, fail: set[str] = frozenset(), review_status: str = "REJECTED") -> None:
        self.requests = []
        self._fail = fail
        self._review_status = review_status
        self.rejected_usage: dict[str, tuple[dict, ...]] = {}

    def run(self, request, **_kwargs):
        self.requests.append(request)
        if request.review_target is not None:
            return _result(request, status="succeeded" if self._review_status == "APPROVED" else "needs_human",
                           output=request.review_target.output.model_dump(mode="json"), provider="openai",
                           review={"required": True, "reviewed": True, "status": self._review_status, "reviewer": "openai",
                                   "corrections": 0, "summary": "revisão do conjunto"})
        if request.agent in self._fail:
            if request.agent in self.rejected_usage:  # rejeição com uso real reportado (caso da Fase 5G)
                raise AgentRunOutputRejected(422, "rejected_output", "facts.0: Expected string, received object",
                                             run_id=f"run-{request.agent}", usage=self.rejected_usage[request.agent])
            raise AgentRunProviderFailure(502, "failed_provider", f"{request.agent}: provider fora do ar")
        return _result(request, output=_output(request.agent, 40 if request.agent == "investigador" else 30))


def _route(route_class: str = "BAIXA", *, quality: str = "real"):
    alert = AlertBase(metric_id="ocupacao-transferencia", title="Ocupação BAIXA na ROTA-SINTÉTICA", period="5du:P1",
                      current_value=25.5, reference_value=85.0, materiality=1000.0, severity=PRIORITY_SEVERITY["P1"],
                      source_quality=quality, concentration=[{"dimension": "rota", "value": "ROTA-SINTETICA", "share_pct": 100}])
    envelope = AlertEnvelope(alert=alert, engine_source=TRANSFER_SOURCE, entity_type="rota", entity_id="ROTA-SINTETICA",
                             evaluated_at=datetime(2026, 9, 18, 12, tzinfo=UTC), rules_version="rules:sintetico",
                             signals=EngineSignals(single_day=False, window_class=route_class))
    router = DecisionRouter(build_default_policy(), memory=InMemoryMemoryLedgerProvider(), similarity=InMemorySimilarityCaseProvider(),
                            pattern_stats=InMemoryPatternStatsProvider(), playbooks=InMemoryPlaybookProvider(),
                            route_store=InMemoryRouteStore())
    return router.route(envelope)


def _run(client, route=None):
    return MultiAgentInvestigation(client, CONFIG).run(
        route=route or _route(), case_id="caso-sintetico", task_by_agent={"transferencia": "Analise a malha de transferência."},
        default_task="Investigue a baixa ocupação sintética.", context_files=("ARCHITECTURE.md",), evidence=EVIDENCE,
        limits=LIMITS, review_task="Revise a consolidação dos agentes.",
    )


def test_router_pede_multi_agent_e_todos_os_agentes_executam_em_ordem():
    route = _route()
    assert route.route == "MULTI_AGENT"
    agents = [agent.agent_name for agent in route.selected_agents]
    assert agents == ["investigador", "transferencia"]
    client = FakeClient()
    result = _run(client, route)
    executed = [request.agent for request in client.requests if request.review_target is None]
    assert executed == agents
    assert [o.status for o in result.outcomes] == ["succeeded", "succeeded"]


def test_cada_execucao_tem_request_id_e_idempotency_proprios():
    client = FakeClient()
    result = _run(client)
    keys = [o.idempotency_key for o in result.outcomes] + [client.requests[-1].idempotency_key]
    ids = [o.request_id for o in result.outcomes] + [client.requests[-1].request_id]
    assert len(set(keys)) == 3 and len(set(ids)) == 3  # 2 agentes + revisão consolidada
    assert all(uuid.UUID(value) for value in ids)
    assert client.requests[1].task == "Analise a malha de transferência."  # tarefa específica do agente


def test_resultados_consolidados_com_atribuicao_e_dentro_do_contrato():
    result = _run(FakeClient())
    consolidated = InvestigationOutput.model_validate(result.consolidated.model_dump())
    assert consolidated.facts == ("[investigador] ocupação 25,5% segundo investigador (ev-sint)",
                                  "[transferencia] ocupação 25,5% segundo transferencia (ev-sint)")
    assert [h.statement for h in consolidated.hypotheses] == ["[investigador] hipótese de investigador",
                                                              "[transferencia] hipótese de transferencia"]
    assert consolidated.evidence == ("ev-sint",)  # evidência deduplicada
    assert consolidated.confidence == 30  # o agente menos confiante limita a consolidação


def test_revisao_recebe_o_conjunto_correto_e_o_revisor_nao_e_autor():
    client = FakeClient()
    _run(client)
    review_request = client.requests[-1]
    target = review_request.review_target
    assert review_request.agent == "consolidacao"
    assert review_request.review_policy.required is True and review_request.review_policy.max_correction_attempts == 0
    assert [s.agent for s in target.sources] == ["investigador", "transferencia"]
    assert [s.run_id for s in target.sources] == ["run-investigador", "run-transferencia"]
    assert target.author_providers == ("anthropic",)  # o Orchestrator escolhe revisor fora deste conjunto
    assert len(target.output.facts) == 2


def test_falha_de_um_agente_nao_apaga_o_resultado_dos_demais():
    client = FakeClient(fail={"transferencia"})
    result = _run(client)
    assert [o.status for o in result.outcomes] == ["succeeded", "failed"]
    assert result.outcomes[0].output is not None
    assert result.consolidated.facts == ("[investigador] ocupação 25,5% segundo investigador (ev-sint)",)
    assert any("[transferencia] resultado indisponível" in item for item in result.consolidated.missing_data)
    assert [s.status for s in client.requests[-1].review_target.sources] == ["succeeded", "failed"]
    assert result.final_status == "needs_human"  # nunca "sucesso" com agente faltando, mesmo se o revisor aprovar


def test_todos_os_agentes_falham_sem_revisao_e_sem_resultado():
    client = FakeClient(fail={"investigador", "transferencia"})
    result = _run(client)
    assert result.final_status == "failed" and result.consolidated is None
    assert all(request.review_target is None for request in client.requests)  # não gasta revisão à toa


def test_aprovado_e_completo_vira_succeeded_mas_o_caso_continua_em_investigacao():
    result = _run(FakeClient(review_status="APPROVED"))
    assert result.final_status == "succeeded"
    assert result.case_state is CaseState.INVESTIGATING  # insumo, não diagnóstico
    with pytest.raises(IllegalTransition):
        assert_transition(CaseState.INVESTIGATING, CaseState.APPROVED)


def test_nenhum_agente_recebe_autoridade_de_acao():
    client = FakeClient(review_status="APPROVED")
    result = _run(client)
    for request in client.requests:
        assert request.agent_authority.model_dump() == {"can_recommend": False, "can_propose": False,
                                                         "can_approve": False, "can_execute": False}
    campos = set(result.consolidated.model_dump().keys())
    assert campos.isdisjoint({"approved_decision", "execute_action", "verified_ok", "decision", "action"})


@pytest.mark.parametrize("quality", ["insufficient"])
def test_rota_sem_investigacao_nao_chama_nenhum_agente(quality):
    route = _route(quality=quality)
    assert route.route != "MULTI_AGENT"
    client = FakeClient()
    with pytest.raises(RouteNotInvestigable):
        _run(client, route)
    assert client.requests == []


def test_consolidacao_vazia_quando_ninguem_produziu_resultado():
    assert consolidate(()) is None


def test_fluxo_sintetico_completo_ate_needs_human():
    """TAREFA 6: RECEIVED → QUALITY_GATE → DECISION_ROUTER → MULTI_AGENT → A → B → CONSOLIDATION → REVIEW → NEEDS_HUMAN."""
    client = FakeClient(review_status="REJECTED")
    result = _run(client)
    assert result.trace == (
        "RECEIVED", "QUALITY_GATE:pass", "DECISION_ROUTER:MULTI_AGENT",
        "AGENT:investigador:succeeded", "AGENT:transferencia:succeeded",
        "CONSOLIDATION:2/2", "REVIEW:REJECTED", "NEEDS_HUMAN",
    )
    assert result.final_status == "needs_human"
    assert result.case_state is CaseState.INVESTIGATING
    assert len(client.requests) == 3  # 2 agentes + 1 revisão consolidada; nenhuma chamada extra


def test_autoria_desconhecida_nao_permite_autorrevisao():
    """Se não dá para saber quem escreveu um resultado, os dois providers contam como autores (revisão humana)."""
    class SemAutoria(FakeClient):
        def run(self, request, **kwargs):
            result = super().run(request, **kwargs)
            if request.review_target is None:
                return result.model_copy(update={"usage": ()})
            return result

    client = SemAutoria()
    _run(client)
    assert client.requests[-1].review_target.author_providers == ("anthropic", "openai")


def test_execucao_rejeitada_preserva_run_id_e_uso_real_para_auditoria():
    """Regressão Fase 5G: 422 com uso real reportado não pode virar '0 chamadas, US$ 0' na auditoria."""
    client = FakeClient(fail={"investigador", "transferencia"})
    usage = ({"provider": "anthropic", "role": "author", "outcome": "success", "input_tokens": 8568, "output_tokens": 6863,
              "reserved_cost_usd": 0.4, "actual_cost_usd": "unknown"},)
    client.rejected_usage = {"investigador": usage, "transferencia": usage}
    result = _run(client)
    assert [o.run_id for o in result.outcomes] == ["run-investigador", "run-transferencia"]
    assert all(o.usage == usage for o in result.outcomes)
    assert all("facts.0" in o.error for o in result.outcomes)
    assert result.final_status == "failed"


# ── Política de caso (2026-09-18): 1 correção por agente + orçamento de US$ 3,50 por caso ────────────────


class ScriptedReviewClient(FakeClient):
    """Revisões em sequência (ex.: REJECTED e depois APPROVED) e reserva por execução, como o Orchestrator informa."""

    def __init__(self, reviews: list[str], reserve: dict[str, float] | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._reviews = list(reviews)
        self._reserve = reserve or {"agent": 0.4, "review": 1.0}

    def run(self, request, **kwargs):
        if request.review_target is not None:
            self._review_status = self._reviews.pop(0) if self._reviews else "REJECTED"
        result = super().run(request, **kwargs)
        kind = "review" if request.review_target is not None else "agent"
        if self._reserve[kind] > request.execution_limits.max_cost_usd_per_job:  # o Orchestrator bloquearia, sem custo
            raise AgentRunProviderFailure(402, "budget_exceeded", "Custo acumulado acima do limite do job.")
        usage = [dict(item, reserved_cost_usd=self._reserve[kind]) for item in result.usage]
        return result.model_copy(update={"usage": tuple(usage)})


def _run_policy(client, **overrides):
    return MultiAgentInvestigation(client, CONFIG).run(
        route=_route(), case_id="caso-sintetico", task_by_agent={}, default_task="Investigue a baixa ocupação sintética.",
        context_files=("ARCHITECTURE.md",), evidence=EVIDENCE, limits=LIMITS, review_task="Revise a consolidação.",
        correction_rounds=overrides.get("rounds", CORRECTION_ROUNDS), case_budget_usd=overrides.get("budget", CASE_BUDGET_USD),
    )


def test_politica_vigente_e_1_correcao_e_3_50_por_caso():
    assert (CORRECTION_ROUNDS, CASE_BUDGET_USD) == (1, 3.50)


def test_reprovado_gera_uma_correcao_por_agente_com_parecer_e_saida_anterior_e_nova_revisao():
    client = ScriptedReviewClient(["REJECTED", "APPROVED"], reserve={"agent": 0.4, "review": 0.4})
    result = _run_policy(client)
    assert [c.agent for c in result.corrections] == ["investigador", "transferencia"]
    correction_requests = [r for r in client.requests if r.review_target is None][2:]
    assert all("CORREÇÃO (1 de 1)" in r.task for r in correction_requests)
    assert all(r.previous_results[0].startswith("[SUA SAÍDA ANTERIOR]") for r in correction_requests)
    assert all("[PARECER DO REVISOR INDEPENDENTE" in r.previous_results[1] and "revisão do conjunto" in r.previous_results[1]
               for r in correction_requests)
    keys = [r.idempotency_key for r in client.requests]
    assert len(set(keys)) == len(keys) == 6  # 2 agentes + revisão + 2 correções + nova revisão, chaves distintas
    assert [r.get("status") for r in result.reviews] == ["REJECTED", "APPROVED"]
    assert result.final_status == "succeeded" and result.case_state.value == "INVESTIGATING"
    assert result.trace[-4:] == ("CORRECTION:transferencia:succeeded", "CONSOLIDATION:2/2", "REVIEW:APPROVED", "SUCCEEDED")
    assert result.case_reserved_usd == pytest.approx(0.4 * 6)


def test_aprovado_na_primeira_revisao_nao_gera_correcao():
    result = _run_policy(ScriptedReviewClient(["APPROVED"]))
    assert result.corrections == () and len(result.reviews) == 1


def test_no_maximo_uma_rodada_mesmo_reprovado_de_novo():
    client = ScriptedReviewClient(["REJECTED", "REJECTED"], reserve={"agent": 0.4, "review": 0.4})
    result = _run_policy(client)
    assert len(result.corrections) == 2 and len(result.reviews) == 2
    assert result.final_status == "needs_human"


def test_orcamento_do_caso_limita_o_job_e_bloqueia_o_que_nao_cabe():
    # reserva real medida: agente US$ 0,40 e revisão US$ 1,00 → 0,8 + 1,0 + 0,8 = 2,6; a 2ª revisão (1,0) não cabe em 3,50
    client = ScriptedReviewClient(["REJECTED", "APPROVED"])
    result = _run_policy(client)
    assert len(result.corrections) == 2
    assert result.reviews[-1]["status"] == "NOT_RUN" and "budget_exceeded" in result.reviews[-1]["error"]
    assert result.case_reserved_usd == pytest.approx(2.6) and result.case_reserved_usd <= CASE_BUDGET_USD
    last_review = client.requests[-1]
    assert last_review.execution_limits.max_cost_usd_per_job == pytest.approx(3.5 - 2.6)
    assert result.final_status == "needs_human"


def test_orcamento_esgotado_nao_envia_nada():
    client = ScriptedReviewClient(["REJECTED"], reserve={"agent": 2.0, "review": 1.0})
    result = _run_policy(client, budget=2.0)
    assert result.outcomes[1].error == "orçamento do caso esgotado: não executado"
    assert len([r for r in client.requests if r.review_target is None]) == 1  # o 2º agente nem saiu
    assert result.reviews[0]["status"] == "NOT_RUN"


def test_sem_politica_o_comportamento_anterior_e_mantido():
    client = FakeClient()
    result = _run(client)
    assert result.corrections == () and len(client.requests) == 3 and result.case_budget_usd is None
