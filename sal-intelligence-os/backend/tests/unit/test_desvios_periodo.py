"""Motor de desvios por janela (mes, trimestre, semestre, ano).

Pedido da Tatiana em 28/09/2026: identificar os desvios macro, nao so os do mes.
O que estes testes protegem e a distincao que da sentido ao pedido -- separar a
conta que desvia todo mes da que estourou uma vez.
"""

from decimal import Decimal

import pytest

from app.services import desvios_periodo as dp


def linha(linha_id, rotulo, realizado, flexibilizado, sinal=-1, classe="CUSTO_FIXO"):
    return {
        "linha_id": linha_id, "rotulo": rotulo, "nivel": "ANALITICA", "classe": classe,
        "REALIZADO": str(realizado), "FLEXIBILIZADO": str(flexibilizado),
        "ORCADO": str(flexibilizado), "sinal_ebitda": sinal,
    }


def serie_de(meses):
    """meses: {competencia: [linha, ...]}"""
    return {c: {"competencia": c, "matriz": linhas} for c, linhas in meses.items()}


# `Embalagens` estoura R$ 30 mil **todo mes** -- passa o piso nas quatro janelas
# (20k no mes, 60k no trimestre, 120k no semestre, 240k no ano) e e tendencia.
# `Avaria` estoura R$ 45 mil **uma vez**: passa o piso do mes e nao passa o do
# trimestre, e por isso some das janelas longas, como deve.
def serie_padrao():
    meses = {}
    for i in range(1, 9):
        competencia = f"2026-{i:02d}"
        linhas = [linha(50, "Embalagens", 130000, 100000)]
        if competencia == "2026-08":
            linhas.append(linha(51, "Avaria", 145000, 100000))
        else:
            linhas.append(linha(51, "Avaria", 100000, 100000))
        meses[competencia] = linhas
    for i in range(1, 13):
        meses.setdefault(f"2025-{i:02d}", [linha(50, "Embalagens", 100000, 100000),
                                           linha(51, "Avaria", 100000, 100000)])
    return serie_de(meses)


def test_as_quatro_janelas_terminam_no_mes_pedido():
    serie = serie_padrao()
    janelas = {j.tipo: j for j in dp.janelas_de("2026-08", list(serie))}

    assert janelas["mes"].competencias == ("2026-08",)
    assert janelas["trimestre"].competencias == ("2026-06", "2026-07", "2026-08")
    assert len(janelas["semestre"].competencias) == 6
    assert len(janelas["ano"].competencias) == 12
    assert all(j.completa for j in janelas.values())


def test_janela_incompleta_e_marcada_em_vez_de_escondida():
    """O ano corrente tem oito meses, nao doze. Esconder isso seria esconder que a
    comparacao anual esta apoiada em dois tercos do periodo."""
    serie = serie_de({f"2026-{i:02d}": [linha(50, "Embalagens", 130000, 100000)] for i in range(1, 9)})
    janelas = {j.tipo: j for j in dp.janelas_de("2026-08", list(serie))}

    assert janelas["ano"].completa is False
    assert len(janelas["ano"].competencias) == 8
    assert janelas["semestre"].completa is True


def test_impacto_usa_o_sinal_da_conta_no_ebitda():
    """Custo acima do previsto TIRA do EBITDA: o impacto tem de sair negativo."""
    serie = serie_de({"2026-08": [linha(50, "Embalagens", 130000, 100000, sinal=-1)]})
    desvio = dp.desvios_da_janela(serie, dp.janelas_de("2026-08", list(serie))[0], "FLEXIBILIZADO")[0]

    assert desvio.impacto == Decimal("-30000.00")
    assert desvio.realizado == Decimal("130000.00")
    assert desvio.referencia == Decimal("100000.00")


def test_receita_abaixo_do_previsto_tambem_tira_do_ebitda():
    serie = serie_de({"2026-08": [linha(3, "Renda", 900000, 1000000, sinal=1, classe="RENDA_BRUTA")]})
    desvio = dp.desvios_da_janela(serie, dp.janelas_de("2026-08", list(serie))[0], "FLEXIBILIZADO")[0]

    assert desvio.impacto == Decimal("-100000.00")


def test_conta_pequena_nao_entra_por_percentual_grande():
    """Sem piso, a lista enche de conta minuscula com variacao de tres digitos --
    foi o que aconteceu com PIS a +1.055% na sazonalidade do planejamento."""
    serie = serie_de({"2026-08": [linha(50, "Conta pequena", 1500, 100)]})
    janela = dp.janelas_de("2026-08", list(serie))[0]

    assert dp.desvios_da_janela(serie, janela, "FLEXIBILIZADO") == []
    fino = dp.desvios_da_janela(serie, janela, "FLEXIBILIZADO", materialidade=Decimal(100))
    assert len(fino) == 1


def test_tendencia_e_evento_sao_separados():
    """O ponto do pedido: `Embalagens` desvia em todas as janelas, `Avaria` so no
    mes. Tratar as duas igual e o que faz alerta virar ruido."""
    macro = {d.rotulo: d for d in dp.desvios_macro(serie_padrao(), "2026-08")}

    assert macro["Embalagens"].veredito == dp.TENDENCIA
    assert macro["Embalagens"].persistencia == 4
    assert "não é do mês" in macro["Embalagens"].observacao

    assert macro["Avaria"].veredito == dp.EVENTO
    assert macro["Avaria"].persistencia == 1
    assert "confirmar antes de tratar como recorrente" in macro["Avaria"].observacao


def test_alternancia_quando_a_conta_muda_de_lado():
    """Desfavoravel numa janela e favoravel noutra: o numero de uma janela so nao
    sustenta conclusao, e o agente precisa receber isso dito."""
    meses = {f"2026-{i:02d}": [linha(50, "Embalagens", 40000, 100000)] for i in range(1, 8)}
    meses["2026-08"] = [linha(50, "Embalagens", 200000, 100000)]
    macro = {d.rotulo: d for d in dp.desvios_macro(serie_de(meses), "2026-08")}

    assert macro["Embalagens"].veredito == dp.ALTERNANCIA
    assert "não sustenta conclusão" in macro["Embalagens"].observacao


def test_base_ano_anterior_compara_a_mesma_janela_doze_meses_atras():
    serie = serie_de({"2026-08": [linha(50, "Embalagens", 130000, 130000)],
                      "2025-08": [linha(50, "Embalagens", 100000, 100000)]})
    janela = dp.janelas_de("2026-08", list(serie))[0]
    desvio = dp.desvios_da_janela(serie, janela, "ANO_ANTERIOR")[0]

    assert desvio.referencia == Decimal("100000.00")
    assert desvio.impacto == Decimal("-30000.00")


def test_sem_ano_anterior_nao_inventa_comparacao():
    serie = serie_de({"2026-08": [linha(50, "Embalagens", 130000, 100000)]})
    janela = dp.janelas_de("2026-08", list(serie))[0]

    assert dp.desvios_da_janela(serie, janela, "ANO_ANTERIOR") == []


def test_folha_e_linha_restrita_ficam_fora():
    """Escopo herdado do DrePayloadAdapter, decisao da Tatiana em 19/09/2026 -- a
    regra mora num lugar so."""
    serie = serie_de({"2026-08": [
        linha(70, "Salário", 900000, 100000),
        linha(71, "Provisão 13º Salário", 900000, 100000),
        linha(252, "Impostos LM e BELLA", 900000, 100000),
        linha(50, "Embalagens", 130000, 100000),
    ]})
    rotulos = [d.rotulo for d in dp.desvios_da_janela(serie, dp.janelas_de("2026-08", list(serie))[0],
                                                      "FLEXIBILIZADO")]
    assert rotulos == ["Embalagens"]


def test_participacao_soma_cem_por_cento_do_desvio_desfavoravel():
    serie = serie_de({"2026-08": [linha(50, "A", 175000, 100000), linha(51, "B", 125000, 100000)]})
    desvios = dp.desvios_da_janela(serie, dp.janelas_de("2026-08", list(serie))[0], "FLEXIBILIZADO")

    assert sum(d.participacao for d in desvios) == Decimal("100.00")
    assert desvios[0].participacao == Decimal("75.00")


def test_resumo_e_serializavel_e_traz_as_tres_partes():
    import json

    pacote = dp.resumo(serie_padrao(), "2026-08")
    json.dumps(pacote)  # nao pode ter Decimal solto: o agente recebe texto

    assert {"competencia_final", "base", "janelas", "por_janela", "macro"} <= set(pacote)
    assert len(pacote["janelas"]) == 4
    assert any(m["veredito"] == dp.TENDENCIA for m in pacote["macro"])


@pytest.mark.parametrize("tipo,tamanho", [("mes", 1), ("trimestre", 3), ("semestre", 6), ("ano", 12)])
def test_tamanho_das_janelas(tipo, tamanho):
    assert dp.TAMANHO[tipo] == tamanho
