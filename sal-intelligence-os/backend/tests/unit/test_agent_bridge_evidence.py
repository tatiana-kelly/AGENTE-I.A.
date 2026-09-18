"""Fase 5F — regressão da montagem de evidência (correções da auditoria do primeiro caso real).

Dados 100% sintéticos, montados no mesmo formato do motor da Torre. Nenhuma leitura do dado real.
"""

import json
from pathlib import Path

import pytest

from app.agent_bridge.evidence import (
    ENGINE_CONCLUSION_FIELDS,
    PARAMETERS,
    ROUTE_METRICS,
    WINDOW_FIELDS,
    build_transfer_route_evidence,
    engine_window_days,
)
from app.decision_router.adapters.base import TorreDataReader

ROTA = "ORIGEM-SINT→DESTINO-SINT"
OUTRA = "OUTRA-ROTA→QUALQUER"
DIAS = ["2026-08-20", "2026-09-01", "2026-09-04", "2026-09-08", "2026-09-10", "2026-09-14", "2026-09-15", "2026-09-16"]


def _janela(dias: int, ocup: float) -> dict:
    return {"dias": dias, "frete": 1000.0 * dias, "custo": 500.0 * dias, "pct": 50.0, "ocup": ocup, "peso": 800.0 * dias,
            "frete_dia": 1000.0, "custo_dia": 500.0}


def _rota(nome: str, janelas: dict) -> dict:
    return {
        "rota": nome, "tipo_perna": "RETORNO",
        "periodo_analisado": {"dias_disponiveis": DIAS, "dia_foco": "2026-09-18", **janelas},
        "ocupacao": "BAIXA", "ocupacao_peso": 25.5, "ocupacao_cubada": None, "ocupacao_visual": None,
        "frete": 5000.0, "custo": 2500.0, "custo_percentual": 50.0, "matriz": "CRITICO",
        "rpk": 1.25, "rpk_necessario": 3.5714, "gap_faturamento": 9285.71, "potencial_receita_mes": 40857.12,
        "tendencia": "PIORANDO", "score": 77.0, "score_componentes": {"x": 1}, "prioridade": "P1", "confianca": "ALTA",
        "causas_provaveis": ["CAUSA-DO-MOTOR-SINTETICA"], "evidencias": ["EVIDENCIA-DO-MOTOR"],
        "investigacoes": ["INVESTIGACAO-DO-MOTOR"], "acoes_recomendadas": {"COMERCIAL": ["ACAO-DO-MOTOR"]},
        "agentes_consultados": [{"agente": "x"}], "feedback_humano": None, "status": "AGUARDANDO_VALIDACAO_HUMANA",
    }


JANELAS_OK = {"d1": _janela(1, 20.5), "janela_5du": _janela(5, 25.5), "janela_7dc": _janela(4, 27.1), "janela_30d": _janela(8, 32.4)}


@pytest.fixture()
def torre(tmp_path: Path):
    def make(janelas: dict = JANELAS_OK) -> TorreDataReader:
        pasta = tmp_path / "transferencias_investigacao"
        pasta.mkdir(exist_ok=True)
        (pasta / "2026-09-18.json").write_text(json.dumps({
            "gerado_em": "2026-09-18T10:20:33", "dia_foco": "2026-09-18",
            "rotas": [_rota(ROTA, janelas), _rota(OUTRA, JANELAS_OK)],
        }), encoding="utf-8")
        (tmp_path / "config_investigador.json").write_text(json.dumps({
            "classes_ocupacao": {"BAIXA": [0, 50]}, "ocupacao_cheio": 85.0, "meta_pct_ideal": 17.5, "meta_pct_limite": 19,
            "janela_principal_dias_uteis": 5, "janela_complementar_dias_corridos": 7, "janela_tendencia_dias": 30,
            "score_pesos": {"nao": "enviar"}, "_regra": "interna",
        }), encoding="utf-8")
        return TorreDataReader(tmp_path)
    return make


def _janelas(reader):
    return build_transfer_route_evidence(reader, ROTA)[0].data["janelas"]


def test_janelas_de_1_5_7_e_30_dias_sao_distinguiveis_com_inicio_e_fim(torre):
    janelas = _janelas(torre())
    assert (janelas["d1"]["inicio"], janelas["d1"]["fim"]) == ("2026-09-16", "2026-09-16")
    assert (janelas["janela_5du"]["inicio"], janelas["janela_5du"]["fim"]) == ("2026-09-08", "2026-09-16")
    assert (janelas["janela_7dc"]["inicio"], janelas["janela_7dc"]["fim"]) == ("2026-09-10", "2026-09-16")
    assert (janelas["janela_30d"]["inicio"], janelas["janela_30d"]["fim"]) == ("2026-08-20", "2026-09-16")
    assert [len(janelas[w]["dias_com_registro"]) for w in ("d1", "janela_5du", "janela_7dc", "janela_30d")] == [1, 5, 4, 8]
    assert len({janelas[w]["regra_de_selecao"] for w in janelas}) == 4  # cada janela explica a própria regra


def test_janelas_terminam_no_ultimo_dia_com_registro_e_nao_no_dia_foco(torre):
    """Regressão do fato F9 reprovado: sem dado em 18/09, as janelas terminam em 16/09 — e isso é declarado."""
    evidencia = build_transfer_route_evidence(torre(), ROTA)[0]
    assert all(entrada["fim"] == "2026-09-16" for entrada in evidencia.data["janelas"].values())
    assert any("terminam no último dia com registro (2026-09-16)" in item for item in evidencia.limitations)
    assert any("horário não registrado" in item for item in evidencia.limitations)  # data sem hora inventada


def test_reproducao_que_nao_confere_com_o_motor_nao_envia_datas(torre):
    janelas = dict(JANELAS_OK, janela_7dc=_janela(6, 27.1))  # motor diz 6 dias; a regra dá 4
    evidencia = build_transfer_route_evidence(torre(janelas), ROTA)[0]
    assert "inicio" not in evidencia.data["janelas"]["janela_7dc"]
    assert "inicio" in evidencia.data["janelas"]["janela_5du"]
    assert any("datas não enviadas para janela_7dc" in item for item in evidencia.limitations)


def test_regra_de_janela_espelha_o_motor():
    assert engine_window_days(DIAS, "2026-09-18", business=5) == DIAS[-5:]
    assert engine_window_days(DIAS, "2026-09-15", business=1) == ["2026-09-15"]
    assert engine_window_days(DIAS, "2026-09-18", calendar=7) == ["2026-09-10", "2026-09-14", "2026-09-15", "2026-09-16"]


def test_todo_campo_tem_significado_e_unidade(torre):
    janelas, metricas, parametros = build_transfer_route_evidence(torre(), ROTA)
    for dicionario in (janelas.data["dicionario_campos_janela"], metricas.data["dicionario_metricas"],
                       parametros.data["dicionario_parametros"]):
        assert all(item["significado"] and item["unidade"] for item in dicionario.values())
    assert set(janelas.data["janelas"]["janela_5du"]["valores"]) == set(WINDOW_FIELDS)
    assert set(metricas.data["metricas"]) == set(ROUTE_METRICS)
    assert metricas.data["janela_de_referencia"] == "janela_5du"
    assert (metricas.data["janela_de_referencia_inicio"], metricas.data["janela_de_referencia_fim"]) == ("2026-09-08", "2026-09-16")
    assert "max(0, custo ÷ (meta_pct_ideal ÷ 100) − frete)" in ROUTE_METRICS["gap_faturamento"]["formula"]
    assert set(parametros.data["parametros"]) == set(PARAMETERS)  # score_pesos e _regra do motor ficam de fora


def test_nenhuma_conclusao_do_motor_nem_outra_rota_vaza(torre):
    texto = json.dumps([e.model_dump(mode="json") for e in build_transfer_route_evidence(torre(), ROTA)], ensure_ascii=False)
    for campo in ENGINE_CONCLUSION_FIELDS:
        assert f'"{campo}"' not in texto, campo
    for valor in ("CAUSA-DO-MOTOR-SINTETICA", "EVIDENCIA-DO-MOTOR", "INVESTIGACAO-DO-MOTOR", "ACAO-DO-MOTOR",
                  "PIORANDO", "CRITICO", "AGUARDANDO_VALIDACAO_HUMANA", "score_pesos", "interna"):
        assert valor not in texto, valor
    assert OUTRA not in texto
    assert '"P1"' not in texto and '"ALTA"' not in texto  # prioridade e confiança do motor não vão


def test_nenhum_dado_adicional_alem_do_permitido(torre):
    janelas, metricas, parametros = build_transfer_route_evidence(torre(), ROTA)
    assert set(janelas.data) == {"rota", "tipo_perna", "dia_foco", "janelas", "dicionario_campos_janela"}
    assert set(metricas.data) == {"rota", "tipo_perna", "dia_foco", "janela_de_referencia", "janela_de_referencia_inicio",
                                  "janela_de_referencia_fim", "metricas", "dicionario_metricas"}
    assert set(parametros.data) == {"parametros", "dicionario_parametros"}
    for entrada in janelas.data["janelas"].values():
        assert set(entrada) <= {"regra_de_selecao", "granularidade", "valores", "inicio", "fim", "dias_com_registro"}
    texto = json.dumps([e.model_dump(mode="json") for e in (janelas, metricas, parametros)], ensure_ascii=False).lower()
    for pessoal in ("cpf", "cnpj", "motorista", "placa", "cliente", "email", "telefone"):
        assert pessoal not in texto
