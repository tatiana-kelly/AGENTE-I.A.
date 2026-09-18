"""Fase 5H — disciplina de evidência: os 6 problemas que o revisor independente reprovou na Fase 5G.

Dados 100% sintéticos (rota e números inventados). Nenhuma IA é chamada: as regras são determinísticas.
"""

from datetime import UTC, datetime

import pytest

from app.agent_bridge.contract import Evidence, EvidenceQuality, Hypothesis, InvestigationOutput
from app.agent_bridge.epistemics import (
    CONFIDENCE_CAPS,
    RANK,
    classify,
    detect_divergences,
    discipline,
    numeric_direction,
)
from app.agent_bridge.multi_agent import AgentOutcome, consolidate_disciplined


def _evidence(ocup_5du: float = 22.0, ocup_30d: float = 33.8, extra: dict | None = None) -> tuple[Evidence, ...]:
    janelas = {"janela_5du": {"valores": {"ocup": ocup_5du, "pct": 50.0}},
               "janela_30d": {"valores": {"ocup": ocup_30d, "pct": 48.0}}}
    return (Evidence(id="ev-sint-janelas", source="ROTA-FICTICIA (sintética)", period="5du", timestamp=datetime(2030, 3, 29, tzinfo=UTC),
                     filters={"synthetic_test": True}, quality=EvidenceQuality(source_quality="sintetica"),
                     data={"janelas": janelas, "frete": 18000.0, "custo": 9000.0, **(extra or {})}),)


EV = _evidence()


def _output(**fields) -> InvestigationOutput:
    return InvestigationOutput(**{"evidence": ("ev-sint-janelas",), "confidence": 70, **fields})


# ── A. interpretação não pode virar cálculo ──────────────────────────────────────────────────────────────
def test_a_calculo_com_formula_e_valores_permanece_calculo():
    assert classify("calculo", "custo percentual = 9000 / 18000 × 100 = 50% (ev-sint-janelas)", EV).kind == "calculo"


@pytest.mark.parametrize("texto", [
    "as janelas 22% < 33,8% indicam trajetória de queda contínua = 22 - 33,8",  # conta + interpretação
    "ocupação muito abaixo do ideal",                                           # sem fórmula nem valores
])
def test_a_interpretacao_ou_texto_sem_formula_sai_de_calculo(texto):
    verdict = classify("calculo", texto, EV)
    assert verdict.kind in ("inferencia", "contradicao", "hipotese")
    assert verdict.kind != "calculo" and verdict.limitations


# ── B. causa sem evidência vira inferência/hipótese ──────────────────────────────────────────────────────
def test_b_fato_causal_vira_inferencia():
    verdict = classify("fato", "o RPK caiu devido à baixa ocupação (ev-sint-janelas)", EV)
    assert verdict.kind == "inferencia"
    assert any("causal" in item for item in verdict.limitations)


@pytest.mark.parametrize("texto", [
    "a baixa ocupação, por si só, reduz o RPK",
    "a causa principal é o retorno ocioso",
    "o déficit ocorre independentemente da ocupação",
])
def test_b_causalidade_afirmada_como_certa_vira_hipotese(texto):
    assert classify("inferencia", texto, EV).kind == "hipotese"


def test_b_fato_sem_evidencia_citada_nao_e_fato():
    assert classify("fato", "a ocupação é baixa", EV).kind == "inferencia"


# ── C. preço/mix sem dado → hipótese + dado ausente ──────────────────────────────────────────────────────
def test_c_preco_e_mix_sem_dado_viram_hipotese_e_dado_ausente():
    out = discipline(_output(inferences=("há problema de precificação na rota", "o mix de carga é desfavorável")), "investigador", EV)
    assert out.output.inferences == ()
    statements = [h.statement for h in out.output.hypotheses]
    assert any("precificação" in s for s in statements) and any("mix" in s for s in statements)
    assert all(h.confidence <= 20 for h in out.output.hypotheses)
    assert any("preço/tarifa" in m for m in out.output.missing_data) and any("mix de carga" in m for m in out.output.missing_data)


def test_c_preco_com_dado_na_evidencia_nao_e_rebaixado():
    evidence = _evidence(extra={"tarifa_media_kg": 1.2})
    assert classify("inferencia", "a tarifa média está abaixo do custo", evidence).kind == "inferencia"


# ── D. tendência respeita a direção numérica ─────────────────────────────────────────────────────────────
def test_d_direcao_numerica_e_indeterminada_quando_ambigua():
    assert numeric_direction(EV, "ocup")[0] == "queda"
    assert numeric_direction(_evidence(33.0, 33.8), "ocup")[0] == "indeterminada"  # dentro de 5%
    assert numeric_direction(_evidence(extra=None) + (), "inexistente")[0] == "indeterminada"


def test_d_melhora_contra_numeros_em_queda_vira_contradicao():
    hypothesis = Hypothesis(statement="ocupação 22% no recente vs 33,8% em 30d pode indicar melhora recente",
                            favorable_evidence=("ev-sint-janelas",), confidence=40)
    out = discipline(_output(hypotheses=(hypothesis,)), "transferencia", EV)
    assert out.output.hypotheses == ()
    assert any("contraria a direção numérica" in c for c in out.output.contradictions)


def test_d_direcao_coerente_e_mantida_com_ressalva_de_janelas():
    verdict = classify("inferencia", "a ocupação está em queda na janela recente (ev-sint-janelas)", EV)
    assert verdict.kind == "inferencia"
    assert any("não série temporal" in item for item in verdict.limitations)


def test_d_tendencia_ambigua_nao_e_fato():
    verdict = classify("fato", "a ocupação caiu (ev-sint-janelas)", _evidence(33.0, 33.8))
    assert verdict.kind == "inferencia" and any("indeterminada" in item for item in verdict.limitations)


# ── E. divergência entre agentes aparece na consolidação ─────────────────────────────────────────────────
def _outcome(agent: str, output: InvestigationOutput) -> AgentOutcome:
    return AgentOutcome(agent=agent, status="succeeded", request_id=f"req-{agent}", idempotency_key=f"idem-{agent}", output=output)


def test_e_divergencias_sao_registradas_com_posicoes_evidencias_e_dado_que_resolve():
    investigador = _output(
        facts=("ocupação 22% na janela_5du (ev-sint-janelas)",),
        inferences=("a ocupação está em queda (ev-sint-janelas)",),
        hypotheses=(Hypothesis(statement="padrão estrutural de retorno ocioso", favorable_evidence=("ev-sint-janelas",), confidence=40),),
        confidence=40,
    )
    transferencia = _output(
        facts=("ocupação 33,8% na janela_30d (ev-sint-janelas)",),
        inferences=("a ocupação vem em alta",),
        hypotheses=(Hypothesis(statement="evento pontual recente de demanda", favorable_evidence=("ev-sint-janelas",), confidence=45),),
        confidence=45,
    )
    consolidation = consolidate_disciplined((_outcome("investigador", investigador), _outcome("transferencia", transferencia)), EV)
    topics = {d.topic for d in consolidation.divergences}
    assert "direção de ocupação por peso" in topics
    assert any(topic.startswith("natureza da explicação principal") for topic in topics)
    rendered = [c for c in consolidation.output.contradictions if c.startswith("[DIVERGÊNCIA ENTRE AGENTES")]
    assert len(rendered) == len(consolidation.divergences)
    assert all("investigador:" in r and "transferencia:" in r and "dado que resolve:" in r for r in rendered)
    # nenhuma posição foi descartada: as duas hipóteses seguem na consolidação, atribuídas
    assert [h.statement.split("]")[0] for h in consolidation.output.hypotheses] == ["[investigador", "[transferencia"]
    assert any(item.kind == "divergencia" for item in consolidation.items)


def test_e_regressao_5g_estrutural_x_recente_com_negacao_e_por_metrica():
    """Frases reais (sintéticas) da tentativa 2 da 5G: o revisor apontou a divergência omitida."""
    investigador = _output(hypotheses=(
        Hypothesis(statement="A rota tem baixa demanda de carga de retorno, o que explica a ocupação por peso abaixo de 50%",
                   favorable_evidence=("ev-sint-janelas",), confidence=40),
        Hypothesis(statement="O preço praticado está estruturalmente descasado do custo", favorable_evidence=("ev-sint-janelas",), confidence=30),
        Hypothesis(statement="A queda de ocupação é um evento recente/pontual (d1 e 7dc abaixo da média de 30d), não um padrão estrutural de longo prazo.",
                   favorable_evidence=("ev-sint-janelas",), confidence=25),
    ), facts=("ocupação 28,4% (ev-sint-janelas)",), confidence=40)
    transferencia = _output(hypotheses=(
        Hypothesis(statement="A baixa ocupação por peso na perna RETORNO é um padrão estrutural recorrente, não um evento pontual.",
                   favorable_evidence=("ev-sint-janelas",), confidence=55),
    ), facts=("ocupação 28,4% (ev-sint-janelas)",), confidence=45)
    c = consolidate_disciplined((_outcome("investigador", investigador), _outcome("transferencia", transferencia)), EV)
    horizon = [d for d in c.divergences if d.topic == "natureza da explicação principal (ocupação por peso)"]
    assert len(horizon) == 1 and horizon[0].point == "investigador: pontual/recente; transferencia: estrutural"


def test_e_sem_divergencia_quando_os_agentes_concordam():
    same = _output(facts=("ocupação 22% (ev-sint-janelas)",), confidence=40)
    assert detect_divergences([("a", discipline(same, "a", EV)), ("b", discipline(same, "b", EV))]) == ()


# ── F. confiança considera evidência, contradição e dados ausentes ───────────────────────────────────────
def test_f_confianca_nao_passa_dos_tetos_da_evidencia():
    sem_fato = discipline(_output(inferences=("leitura qualquer",), confidence=90), "a", EV)
    assert sem_fato.output.confidence == CONFIDENCE_CAPS["sem_fato_com_evidencia"]
    com_ausente = discipline(_output(facts=("ocupação 22% (ev-sint-janelas)",), missing_data=("série diária",), confidence=90), "a", EV)
    assert com_ausente.output.confidence == CONFIDENCE_CAPS["dados_ausentes"]
    com_contradicao = discipline(_output(facts=("ocupação 22% (ev-sint-janelas)",), contradictions=("x",), confidence=90), "a", EV)
    assert com_contradicao.output.confidence == CONFIDENCE_CAPS["contradicao_ou_divergencia"]
    assert any("limitada a" in b for b in com_contradicao.confidence_basis)


def test_f_confianca_nunca_aumenta_e_hipotese_sem_evidencia_e_limitada():
    baixa = discipline(_output(facts=("ocupação 22% (ev-sint-janelas)",), confidence=10), "a", EV)
    assert baixa.output.confidence == 10
    sem_favoravel = discipline(_output(hypotheses=(Hypothesis(statement="retorno ocioso", confidence=80),)), "a", EV)
    assert sem_favoravel.output.hypotheses[0].confidence == 30


def test_f_divergencia_limita_a_confianca_consolidada():
    a = _output(facts=("ocupação 22% (ev-sint-janelas)",), inferences=("a ocupação está em queda (ev-sint-janelas)",), confidence=90)
    b = _output(facts=("ocupação 22% (ev-sint-janelas)",), inferences=("a ocupação vem em alta",), confidence=90)
    c = consolidate_disciplined((_outcome("investigador", a), _outcome("transferencia", b)), EV)
    assert c.divergences and c.output.confidence <= CONFIDENCE_CAPS["contradicao_ou_divergencia"]


# ── Tarefa 5: itens tipados e nenhuma promoção de certeza ────────────────────────────────────────────────
def test_itens_consolidados_tem_tipo_conteudo_origem_evidencia_certeza_e_limitacoes():
    out = discipline(_output(facts=("o RPK caiu devido à ocupação (ev-sint-janelas)",)), "investigador", EV)
    item = out.items[0]
    assert (item.kind, item.agent, item.evidence, item.origin_kind) == ("inferencia", "investigador", ("ev-sint-janelas",), "fato")
    assert item.certainty and item.limitations


@pytest.mark.parametrize("origin", ["fato", "calculo", "inferencia", "hipotese"])
@pytest.mark.parametrize("texto", [
    "ocupação 22% (ev-sint-janelas)", "custo percentual = 9000 / 18000 × 100 = 50%", "a causa principal é o preço",
    "o mix explica o déficit", "a ocupação vem melhorando", "a ocupação está em queda (ev-sint-janelas)", "texto neutro",
])
def test_nenhuma_regra_promove_certeza(origin, texto):
    assert RANK[classify(origin, texto, EV).kind] <= RANK[origin]


# ── Tarefa 1/2/4: as definições dos agentes carregam a disciplina ────────────────────────────────────────
@pytest.mark.parametrize("agente", ["investigador", "transferencia"])
def test_definicao_do_agente_tem_as_regras_de_evidencia(agente):
    from pathlib import Path

    texto = (Path(__file__).resolve().parents[3] / ".claude" / "agents" / f"{agente}.md").read_text(encoding="utf-8")
    for regra in ("DISCIPLINA DE EVIDÊNCIA", "- FATO:", "- CÁLCULO:", "- INFERÊNCIA:", "- HIPÓTESE:", "- DADO AUSENTE:",
                  "REGRA FUNDAMENTAL — CAUSALIDADE", "TENDÊNCIA:", "tendência indeterminada", "CONFIANÇA:", "NÃO é nota da resposta",
                  "NUNCA é evidência contrária", "HIPÓTESES CONCORRENTES:", "\"confere\"", "não monotônica"):
        assert regra in texto, regra
    assert len(texto) <= 20000  # LIMITS.agentDefinitionChars do agent-run


# ── 5H, tentativa 3: ajustes pedidos pelo revisor ────────────────────────────────────────────────────────
def test_t3_hipoteses_principais_concorrentes_ficam_lado_a_lado():
    a = _output(facts=("ocupação 28,4% (ev-sint-janelas)",), hypotheses=(Hypothesis(
        statement="baixa demanda ou captação de carga de retorno", favorable_evidence=("ev-sint-janelas",),
        missing_evidence=("volume de carga disponível no destino",), confidence=40),))
    b = _output(facts=("ocupação 28,4% (ev-sint-janelas)",), hypotheses=(Hypothesis(
        statement="excesso de frequência de viagens frente à demanda", favorable_evidence=("ev-sint-janelas",),
        missing_evidence=("número de viagens por dia",), confidence=45),))
    c = consolidate_disciplined((_outcome("investigador", a), _outcome("transferencia", b)), EV)
    concorrentes = [d for d in c.divergences if d.topic == "hipóteses principais concorrentes"]
    assert len(concorrentes) == 1
    d = concorrentes[0]
    assert "baixa demanda" in d.position_a and "excesso de frequência" in d.position_b
    assert "volume de carga disponível no destino" in d.resolving_data and "número de viagens por dia" in d.resolving_data
    assert len(c.output.hypotheses) == 2  # nenhuma foi descartada


@pytest.mark.parametrize("texto", [
    "rpk = 18000 ÷ 15000 = 1,2 R$/kg — confere com o valor reportado",
    "gap = 3,4286 - 1,2 = 2,2286 R$/kg faltantes",
])
def test_t3_confere_e_faltante_nao_ficam_em_calculo(texto):
    assert classify("calculo", texto, EV).kind == "inferencia"


def test_t3_variacao_nao_monotonica_e_tendencia_indeterminada_nao_contradicao():
    texto = "a ocupação varia de forma não monotônica entre as janelas (22% → 26,1% → 28,4% → 33,8%)"
    out = discipline(_output(facts=("ocupação 22% (ev-sint-janelas)",), contradictions=(texto,)), "transferencia", EV)
    assert out.output.contradictions == ()
    assert out.output.inferences and out.output.inferences[0].startswith("[tendência indeterminada]")
    assert out.items[-1].origin_kind == "contradicao" or any(i.origin_kind == "contradicao" for i in out.items)


def test_t3_ausencia_de_dado_nao_e_evidencia_contraria():
    h = Hypothesis(statement="excesso de frequência de viagens", favorable_evidence=("ev-sint-janelas",),
                   contrary_evidence=("não há dados de número de viagens", "ocupação de 33,8% em 30d"), confidence=40)
    out = discipline(_output(facts=("ocupação 22% (ev-sint-janelas)",), hypotheses=(h,)), "transferencia", EV)
    hyp = out.output.hypotheses[0]
    assert hyp.contrary_evidence == ("ocupação de 33,8% em 30d",)
    assert "não há dados de número de viagens" in hyp.missing_evidence


# ── 5H, tentativa 4: falsos positivos da própria disciplina (apontados pelo revisor) ─────────────────────
@pytest.mark.parametrize("texto", [
    "O motor classifica ocupação por peso em faixas: BAIXA [0-50], MODERADA [50-70], ALTA [70-85], CHEIO [85-100] (ev-sint-janelas)",
    "A ocupação por peso pode estar baixa porque a carga é volumetricamente densa (ocupação cubada alta)",
])
def test_t4_nome_de_faixa_e_ocupacao_cubada_nao_sao_direcao(texto):
    assert classify("fato", texto, EV).kind != "contradicao"
    assert classify("hipotese", texto, EV).kind == "hipotese"


def test_t4_direcao_real_continua_sendo_verificada():
    assert classify("inferencia", "a ocupação por peso está em alta", EV).kind == "contradicao"
    assert classify("inferencia", "a ocupação cresceu no período recente", EV).kind == "contradicao"
