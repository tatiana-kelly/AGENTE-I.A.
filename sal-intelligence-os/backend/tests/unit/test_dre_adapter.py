"""Adaptador DRE (realizado × orçado por linha, Pareto 70%) — dados 100% sintéticos."""

import json

from app.agent_bridge.declared_evidence import build_declared_evidence, load_declarations
from app.decision_router.adapters.base import TorreDataReader
from app.decision_router.adapters.dre_payload import SOURCE, DrePayloadAdapter
from app.decision_router.policy import build_default_policy
from app.decision_router.providers import (
    InMemoryMemoryLedgerProvider,
    InMemoryPatternStatsProvider,
    InMemoryPlaybookProvider,
    InMemoryRouteStore,
    InMemorySimilarityCaseProvider,
)
from app.decision_router.router import DecisionRouter


def _line(line_id, rotulo, orcado, realizado, sinal=-1, nivel="ANALITICA"):
    return {"linha_id": line_id, "rotulo": rotulo, "nivel": nivel, "classe": "CUSTO_VARIAVEL", "sinal_ebitda": sinal,
            "ORCADO": str(orcado), "REALIZADO": str(realizado), "FLEXIBILIZADO": str(orcado), "memoria": "LANCAMENTO-SIGILOSO",
            "variacao": "CONCLUSAO-DA-TELA"}


def _reader(tmp_path, lines):
    (tmp_path / "payload.json").write_text(json.dumps({
        "competencia": "2030-01", "status": "FECHADO", "gerado_em": "2030-02-15T10:00:00", "matriz": lines,
        "lancamentos": [{"fornecedor": "FORNECEDOR-REAL"}]}), encoding="utf-8")
    return TorreDataReader(tmp_path)


LINES = [
    _line(1, "Custo A", 100, 160),                 # −60 (custo acima do orçado)
    _line(2, "Custo B", 100, 130),                 # −30
    _line(3, "Custo C", 100, 110),                 # −10
    _line(4, "Receita", 1000, 900, sinal=1),       # −100 (receita abaixo)
    _line(5, "Custo econômico", 100, 50),          # +50 favorável: nunca entra
    _line(6, "Salário", 100, 900),                 # folha: fora do escopo
    _line(7, "Participação de Lucros", 10, 500),   # lucros: fora do escopo
    _line(250, "Linha restrita", 1, 9999),         # restrita (id ≥ 200)
    _line(8, "Grupo", 0, 9999, nivel="GRUPO"),     # só analíticas
]


def test_pareto_70_so_desfavoraveis_e_fora_folha_lucros_restritas(tmp_path):
    out = DrePayloadAdapter().adapt(_reader(tmp_path, LINES), "r")
    # desfavorável total = 100 + 60 + 30 + 10 = 200; 70% = 140 → Receita (100) + Custo A (60, cruza os 70%)
    assert [a.envelope.entity_id for a in out.alerts] == ["4", "1"]
    assert [a.envelope.alert.materiality for a in out.alerts] == [100.0, 60.0]
    skipped = {s.record_ref for s in out.skipped}
    assert {"matriz[linha_id=6]", "matriz[linha_id=7]", "matriz[linha_id=250]"} <= skipped


def test_evidencia_do_dre_nao_leva_memoria_lancamento_nem_fornecedor(tmp_path):
    reader = _reader(tmp_path, LINES)
    adapted = DrePayloadAdapter().adapt(reader, "r").alerts[0]
    evidence = build_declared_evidence(reader, adapted, load_declarations())
    text = json.dumps([e.model_dump(mode="json") for e in evidence], ensure_ascii=False)
    for forbidden in ("LANCAMENTO-SIGILOSO", "CONCLUSAO-DA-TELA", "FORNECEDOR-REAL", "memoria", "variacao"):
        assert forbidden not in text
    assert evidence[1].data["valores"]["REALIZADO"] == "900"


def test_roteador_manda_desvio_do_dre_para_financeiro_dre_e_custos(tmp_path):
    adapted = DrePayloadAdapter().adapt(_reader(tmp_path, LINES), "r").alerts[0]
    router = DecisionRouter(build_default_policy(), memory=InMemoryMemoryLedgerProvider(),
                            similarity=InMemorySimilarityCaseProvider(), pattern_stats=InMemoryPatternStatsProvider(),
                            playbooks=InMemoryPlaybookProvider(), route_store=InMemoryRouteStore())
    route = router.route(adapted.envelope)
    agents = {a.agent_name for a in route.selected_agents}
    assert route.status == "ROUTED" and route.route in ("ONE_AGENT", "MULTI_AGENT")
    assert {"financeiro-dre", "custos-orcamento-roi"} <= agents
    assert adapted.source == SOURCE
