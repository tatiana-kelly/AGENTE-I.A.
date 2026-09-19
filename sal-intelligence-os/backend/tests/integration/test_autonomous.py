"""Modo autônomo: executor diário com freios, Pareto, evidência declarada, fila de decisões e agenda semanal.

100% sintético e sem IA: adaptador, roteador e cliente são dublês; o Decision Router real gera a rota MULTI_AGENT.
"""

import json
from datetime import UTC, datetime
from types import SimpleNamespace

from app.agent_bridge import AgentRunClientConfig, AgentRunProviderFailure
from app.agent_bridge.autonomous import run_daily, weekly_agenda
from app.agent_bridge.autonomy import AutonomyGate, AutonomyPolicy, DailyLedger
from app.agent_bridge.contract import AgentRunResult
from app.agent_bridge.declared_evidence import build_declared_evidence, resolve_record
from app.decision_router.adapters.base import PRIORITY_SEVERITY, AdaptedAlert, AdapterOutput, TorreDataReader
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

CONFIG = AgentRunClientConfig(base_url="http://127.0.0.1:3100", principal="service:sal-intelligence-os",
                              project="sal-intelligence-os", secret="segredo-de-teste-autonomo-com-32+chars")
NOW = datetime(2026, 9, 19, 13, tzinfo=UTC)
SOURCE = "torre.teste_declarado"
FILE = "divergencia.json"


def _envelope(entity: str, materiality: float) -> AlertEnvelope:
    alert = AlertBase(metric_id="ocupacao-transferencia", title=f"Desvio sintético {entity}", period="5du:P1",
                      current_value=25.5, reference_value=85.0, materiality=materiality, severity=PRIORITY_SEVERITY["P1"],
                      source_quality="real", concentration=[{"dimension": "rota", "value": entity, "share_pct": 100}])
    return AlertEnvelope(alert=alert, engine_source=SOURCE, entity_type="rota", entity_id=entity, evaluated_at=NOW,
                         rules_version="rules:sintetico", signals=EngineSignals(single_day=False, window_class="BAIXA"))


ROUTE = DecisionRouter(build_default_policy(), memory=InMemoryMemoryLedgerProvider(), similarity=InMemorySimilarityCaseProvider(),
                       pattern_stats=InMemoryPatternStatsProvider(), playbooks=InMemoryPlaybookProvider(),
                       route_store=InMemoryRouteStore()).route(_envelope("R-X", 1000.0))


class Adapter:
    def __init__(self, items):
        self.items = items

    def adapt(self, reader, rules_version):
        alerts = tuple(AdaptedAlert(alert_id=f"{SOURCE}:{name}", source=SOURCE, envelope=_envelope(name, value),
                                    source_ref=f"{FILE} rotas_divergentes[rota={name}]", transformations=("sintético",))
                       for name, value in self.items)
        return AdapterOutput(SOURCE, FILE, len(alerts), alerts)


class Router:
    def __init__(self, human: set[str] = frozenset()):
        self.human = human

    def route(self, envelope):
        if envelope.entity_id in self.human:
            return SimpleNamespace(status="ROUTED", route="HUMAN_REVIEW", selected_agents=())
        return ROUTE


class Client:
    """Reserva como o Orchestrator informa: agente US$ 0,40; revisão US$ 1,00; bloqueia o que não cabe no job."""

    def __init__(self):
        self.requests = []

    def run(self, request, **_):
        self.requests.append(request)
        review = request.review_target is not None
        reserve = 1.0 if review else 0.4
        if reserve > request.execution_limits.max_cost_usd_per_job:
            raise AgentRunProviderFailure(402, "budget_exceeded", "acima do limite do job")
        output = request.review_target.output.model_dump(mode="json") if review else {
            "facts": [f"delta sintético ({request.evidence[0].id})"], "calculations": [], "inferences": [], "hypotheses": [],
            "contradictions": [], "missing_data": [], "evidence": [request.evidence[0].id], "confidence": 40,
            "recommended_actions": [{"action": "Conferir a rota no SSW", "owner_role": "analista de custos", "deadline": "2 dias",
                                     "kpi": "delta < 1%", "evidence": [request.evidence[0].id]}]}
        return AgentRunResult.model_validate({
            "protocol_version": "sal.agent-run/1.0", "request_id": request.request_id, "run_id": f"run-{len(self.requests)}",
            "status": "succeeded", "agent": request.agent, "agent_version": "1.0.0",
            "agent_authority": request.agent_authority.model_dump(), "output": output,
            "output_validation": {"valid": True, "reason": "ok"},
            "review": {"required": review, "reviewed": review, "status": "APPROVED" if review else "NOT_RUN", "corrections": 0},
            "providers": {"primary": "openai" if review else "anthropic"},
            "usage": [{"role": "reviewer" if review else "author", "provider": "openai" if review else "anthropic",
                       "outcome": "success", "reserved_cost_usd": reserve}],
            "context": {}, "created_at": NOW.isoformat()})


def _reader(tmp_path) -> TorreDataReader:
    rows = [{"rota": name, "oficial_ssw": 120.0, "bi": 100.0, "delta": 20.0, "delta_pct": 20.0,
             "causa": "CAUSA-DO-MOTOR", "sentido": "OFICIAL_MAIOR", "principais_ctrbs": ["x"]}
            for name in ("R-A", "R-B", "R-C", "R-D")]
    (tmp_path / FILE).write_text(json.dumps({"rotas_divergentes": rows}), encoding="utf-8")
    return TorreDataReader(tmp_path)


DECLARATIONS = {SOURCE: {"materiality_unit": "R$", "fields": {
    "rota": {"significado": "rota", "unidade": "texto"}, "delta": {"significado": "oficial − bi", "unidade": "R$"},
    "delta_pct": {"significado": "delta sobre bi", "unidade": "%"}}}}


def _gate(tmp_path, *, enabled=True, daily=10.0):
    policy = AutonomyPolicy(enabled=enabled, daily_budget_usd=daily, case_budget_usd=3.5, projects={"torre-controle": True})
    return AutonomyGate(policy, DailyLedger(tmp_path / "ledger.json", lambda: NOW))


def _run(tmp_path, *, items, gate=None, router=None, declarations=DECLARATIONS, client=None):
    client = client or Client()
    report = run_daily(project="torre-controle", reader=_reader(tmp_path), adapters=[Adapter(items)], router=router or Router(),
                       client=client, config=CONFIG, gate=gate or _gate(tmp_path), declarations=declarations,
                       queue_dir=tmp_path / "fila", clock=lambda: NOW)
    return report, client


def test_freio_geral_desligado_nao_le_nem_chama_nada(tmp_path):
    report, client = _run(tmp_path, items=[("R-A", 10.0)], gate=_gate(tmp_path, enabled=False))
    assert report.stopped_reason and "interruptor geral" in report.stopped_reason
    assert report.alerts == 0 and client.requests == []


def test_pareto_maior_materialidade_primeiro_e_rotas_sem_ia_ficam_de_fora(tmp_path):
    report, _ = _run(tmp_path, items=[("R-A", 10.0), ("R-B", 900.0), ("R-C", 50.0)], router=Router(human={"R-C"}))
    assert [c["alerta"] for c in report.cases] == [f"{SOURCE}:R-B", f"{SOURCE}:R-A"]
    assert any("HUMAN_REVIEW" in s["motivo"] for s in report.skipped)
    assert all(c["reservado_usd"] == 1.8 for c in report.cases)


def test_teto_diario_para_o_ciclo_e_registra_o_que_ficou_para_amanha(tmp_path):
    gate = _gate(tmp_path, daily=3.6)
    report, _ = _run(tmp_path, items=[("R-A", 3.0), ("R-B", 2.0), ("R-C", 1.0)], gate=gate)
    assert len(report.cases) == 2 and "teto diário" in report.stopped_reason
    assert [s["alerta"] for s in report.skipped] == [f"{SOURCE}:R-C"]
    assert gate.ledger.spent() == 3.6


def test_fonte_sem_declaracao_nao_sai(tmp_path):
    report, client = _run(tmp_path, items=[("R-A", 10.0)], declarations={})
    assert report.cases == [] and client.requests == []
    assert "sem evidência declarada" in report.skipped[0]["motivo"]


def test_evidencia_declarada_so_leva_campos_da_lista_fechada(tmp_path):
    reader = _reader(tmp_path)
    adapted = Adapter([("R-B", 1.0)]).adapt(reader, "r").alerts[0]
    alerta, registro = build_declared_evidence(reader, adapted, DECLARATIONS)
    assert set(registro.data["valores"]) == {"rota", "delta", "delta_pct"}
    text = json.dumps([alerta.model_dump(mode="json"), registro.model_dump(mode="json")], ensure_ascii=False)
    for proibido in ("CAUSA-DO-MOTOR", "OFICIAL_MAIOR", "principais_ctrbs", "oficial_ssw"):
        assert proibido not in text
    assert registro.data["dicionario"]["delta"]["unidade"] == "R$"


def test_resolve_record_por_indice_e_por_chave():
    doc = {"a": {"b": [{"k": "x", "v": 1}, {"k": "y", "v": 2}]}}
    assert resolve_record(doc, "a.b[1]") == {"k": "y", "v": 2}
    assert resolve_record(doc, "a.b[k=x]") == {"k": "x", "v": 1}
    assert resolve_record(doc, "a.b[k=z]") is None


def test_fila_de_decisoes_e_agenda_semanal(tmp_path):
    _, client = _run(tmp_path, items=[("R-A", 10.0), ("R-B", 900.0)])
    assert all(r.agent_authority.can_recommend and not r.agent_authority.can_execute for r in client.requests)
    files = sorted((tmp_path / "fila").glob("*.json"))
    assert len(files) == 2
    case = json.loads(files[0].read_text(encoding="utf-8"))
    assert case["estado_do_caso"] == "INVESTIGATING" and case["consolidacao"]["recommended_actions"]
    agenda = weekly_agenda(tmp_path / "fila", now=NOW)
    assert agenda.index("R-B") < agenda.index("R-A")  # maior impacto primeiro
    assert "Conferir a rota no SSW" in agenda and "nada foi aprovado nem executado" in agenda


def test_rodizio_por_fonte_da_vez_a_todos_os_motores():
    from app.agent_bridge.autonomous import prioritize

    def item(source, name, value):
        return (SimpleNamespace(source=source, alert_id=f"{source}:{name}",
                                envelope=SimpleNamespace(alert=SimpleNamespace(materiality=value))), None)
    ordered = prioritize([item("transf", "a", 90000), item("transf", "b", 80000), item("transf", "c", 70000),
                          item("projecao", "p", 5), item("custos", "x", 300), item("custos", "y", 900)])
    assert [i[0].alert_id for i in ordered] == ["custos:y", "projecao:p", "transf:a", "custos:x", "transf:b", "transf:c"]


def test_titulo_do_alerta_com_conclusao_do_motor_nao_vai_para_a_ia(tmp_path):
    _, client = _run(tmp_path, items=[("R-A", 10.0)])
    assert client.requests
    for request in client.requests:
        assert "Desvio sintético" not in request.task  # o título é do motor; a tarefa usa métrica + entidade
        assert "ocupacao-transferencia" in request.task or request.review_target is not None
