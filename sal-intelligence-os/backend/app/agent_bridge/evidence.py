"""Montagem de evidência para investigação de rota de transferência (Fase 5F — correções da auditoria).

Correções aplicadas (REVIEW-AUDIT do primeiro caso real):
- cada janela vai com INÍCIO, FIM, dias com dado e a lista de dias — reproduzidos pela MESMA regra do motor
  (`snapshot/investigador_transferencias.py::_janela`) e conferidos contra a contagem `dias` do próprio motor;
  se a reprodução não bater, as datas NÃO são enviadas (nada é inferido);
- cada campo vai com significado, unidade, fórmula e janela de referência, tirados do código do motor;
- nada que seja conclusão, classificação ou recomendação do motor é enviado: só medições e cálculos
  determinísticos, mais os parâmetros oficiais do motor.

Lê a Torre SOMENTE LEITURA. Não envia outras rotas, dados pessoais ou dados de cliente.
"""

import datetime as dt

from app.agent_bridge.contract import Evidence, EvidenceQuality
from app.decision_router.adapters.base import TorreDataReader

ENGINE_REF = "Torre snapshot/investigador_transferencias.py"
TRANSFER_DIRECTORY = "transferencias_investigacao"
WINDOWS = ("d1", "janela_5du", "janela_7dc", "janela_30d")

#: Conclusões/classificações/recomendações do motor — NUNCA enviadas ao agente.
ENGINE_CONCLUSION_FIELDS = (
    "causas_provaveis", "acoes_recomendadas", "investigacoes", "agentes_consultados", "evidencias", "matriz",
    "score", "score_componentes", "prioridade", "confianca", "ocupacao", "tendencia", "status", "feedback_humano",
)

#: Campos de janela: significado e unidade conforme `_janela` do motor.
WINDOW_FIELDS = {
    "dias": {"significado": "quantidade de dias com registro dentro da janela", "unidade": "dias"},
    "frete": {"significado": "soma do frete faturado nos dias da janela", "unidade": "R$"},
    "custo": {"significado": "soma do custo da transferência nos dias da janela", "unidade": "R$"},
    "pct": {"significado": "custo ÷ frete × 100 da janela (nulo se frete < R$ 1)", "unidade": "%"},
    "ocup": {"significado": "média simples da ocupação por PESO diária, nos dias com ocupação medida", "unidade": "%"},
    "peso": {"significado": "soma do peso transportado nos dias da janela", "unidade": "kg"},
    "frete_dia": {"significado": "frete ÷ dias da janela", "unidade": "R$/dia"},
    "custo_dia": {"significado": "custo ÷ dias da janela", "unidade": "R$/dia"},
}

WINDOW_RULES = {
    "d1": "último dia com registro até o dia foco",
    "janela_5du": "últimos 5 dias COM REGISTRO até o dia foco (no motor, 'dias úteis' = dias com dado, não calendário)",
    "janela_7dc": "dias com registro nos 7 dias corridos que terminam no último dia com registro até o dia foco",
    "janela_30d": "dias com registro nos 30 dias corridos que terminam no último dia com registro até o dia foco",
}

#: Métricas da rota: todas calculadas pelo motor sobre a janela de 5 dias com dado (janela_5du).
ROUTE_METRICS = {
    "frete": {"significado": "frete da janela_5du", "unidade": "R$", "formula": "soma do frete na janela_5du"},
    "custo": {"significado": "custo da janela_5du", "unidade": "R$", "formula": "soma do custo na janela_5du"},
    "custo_percentual": {"significado": "custo sobre frete na janela_5du", "unidade": "%", "formula": "custo ÷ frete × 100"},
    "ocupacao_peso": {"significado": "ocupação média por peso na janela_5du", "unidade": "%", "formula": "média da ocupação diária por peso"},
    "rpk": {"significado": "receita por kg transportado", "unidade": "R$/kg", "formula": "frete ÷ peso da janela_5du"},
    "rpk_necessario": {"significado": "receita por kg necessária para o custo ficar em meta_pct_ideal do frete",
                       "unidade": "R$/kg", "formula": "(custo ÷ (meta_pct_ideal ÷ 100)) ÷ peso da janela_5du"},
    "gap_faturamento": {"significado": "faturamento que faltou para o custo ficar em meta_pct_ideal do frete",
                        "unidade": "R$", "formula": "max(0, custo ÷ (meta_pct_ideal ÷ 100) − frete), na janela_5du"},
    "potencial_receita_mes": {"significado": "gap_faturamento projetado para um mês pelo fator fixo do motor",
                              "unidade": "R$/mês", "formula": "gap_faturamento ÷ dias da janela_5du × 22"},
    "ocupacao_cubada": {"significado": "ocupação por volume cubado", "unidade": "%", "formula": "não calculada pelo motor (sem peso cubado na fonte)"},
    "ocupacao_visual": {"significado": "ocupação estimada por foto", "unidade": "%", "formula": "não calculada pelo motor para a rota"},
}

PARAMETERS = {
    "classes_ocupacao": {"significado": "faixas de classificação da ocupação por peso usadas pelo motor", "unidade": "%"},
    "ocupacao_cheio": {"significado": "ocupação a partir da qual o motor considera o veículo cheio", "unidade": "%"},
    "meta_pct_ideal": {"significado": "custo sobre frete considerado ideal pelo motor (base de rpk_necessario e gap_faturamento)", "unidade": "%"},
    "meta_pct_limite": {"significado": "custo sobre frete limite usado pelo motor", "unidade": "%"},
    "janela_principal_dias_uteis": {"significado": "tamanho da janela_5du", "unidade": "dias com dado"},
    "janela_complementar_dias_corridos": {"significado": "tamanho da janela_7dc", "unidade": "dias corridos"},
    "janela_tendencia_dias": {"significado": "tamanho da janela_30d", "unidade": "dias corridos"},
}


def engine_window_days(days: list[str], focus_day: str, *, business: int | None = None,
                       calendar: int | None = None) -> list[str]:
    """Reprodução fiel de `_janela` do motor (seleção dos dias). Não calcula nada além da seleção."""
    selected = sorted(day for day in days if day <= focus_day)
    if calendar and selected:
        start = dt.date.fromisoformat(selected[-1]) - dt.timedelta(days=calendar - 1)
        return [day for day in selected if dt.date.fromisoformat(day) >= start]
    if business:
        return selected[-business:]
    return selected


def _window_days(name: str, days: list[str], focus_day: str, config: dict) -> list[str]:
    if name == "d1":
        return engine_window_days(days, focus_day, business=1)
    if name == "janela_5du":
        return engine_window_days(days, focus_day, business=int(config["janela_principal_dias_uteis"]))
    if name == "janela_7dc":
        return engine_window_days(days, focus_day, calendar=int(config["janela_complementar_dias_corridos"]))
    return engine_window_days(days, focus_day, calendar=int(config["janela_tendencia_dias"]))


def _slug(route: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in route.lower()).strip("-")


def build_transfer_route_evidence(reader: TorreDataReader, route: str, *, source_file: str | None = None) -> tuple[Evidence, ...]:
    source_file = source_file or reader.latest(TRANSFER_DIRECTORY)
    document = reader.read_json(source_file)
    record = next(item for item in document["rotas"] if item["rota"] == route)
    config = reader.read_json("config_investigador.json")
    period = record.get("periodo_analisado") or {}
    days = list(period.get("dias_disponiveis") or [])
    focus_day = period.get("dia_foco") or document.get("dia_foco")
    generated = dt.datetime.fromisoformat(document["gerado_em"] + "-03:00")
    slug = _slug(route)

    windows: dict[str, dict] = {}
    unverified: list[str] = []
    for name in WINDOWS:
        values = period.get(name)
        if not values:
            continue
        selected = _window_days(name, days, focus_day, config)
        entry = {
            "regra_de_selecao": WINDOW_RULES[name],
            "granularidade": "dia (a fonte não registra horário)",
            "valores": {field: values.get(field) for field in WINDOW_FIELDS},
        }
        if len(selected) == values.get("dias"):
            entry.update({"inicio": selected[0], "fim": selected[-1], "dias_com_registro": selected})
        else:  # a reprodução não bateu com o motor: não arriscamos datas
            unverified.append(name)
        windows[name] = entry

    limitations = [
        "horário não registrado na fonte: início e fim são datas (granularidade diária)",
        "números calculados pelo motor da Torre a partir da base operacional; não auditados por humano",
        "ocupação disponível apenas por peso: cubada e visual não calculadas pelo motor",
    ]
    if focus_day and days and max(day for day in days if day <= focus_day) != focus_day:
        last = max(day for day in days if day <= focus_day)
        limitations.append(f"sem registro no dia foco {focus_day}: as janelas terminam no último dia com registro ({last})")
    if unverified:
        limitations.append(f"datas não enviadas para {', '.join(unverified)}: a reprodução da janela não conferiu com o motor")

    base = {"rota": route, "tipo_perna": record.get("tipo_perna"), "dia_foco": focus_day}
    return (
        Evidence(
            id=f"ev-{slug}-janelas",
            source=f"Torre de Controle — {source_file} rotas[rota={route}].periodo_analisado ({ENGINE_REF}::_janela)",
            period=f"janelas até {focus_day}",
            timestamp=generated,
            filters={"rota": route, "tipo_perna": record.get("tipo_perna")},
            quality=EvidenceQuality(source_quality="real", checks=tuple(
                f"{name}: {len(entry.get('dias_com_registro', []))} dia(s) reproduzidos = dias do motor"
                for name, entry in windows.items() if "inicio" in entry)),
            limitations=tuple(limitations),
            data={**base, "janelas": windows, "dicionario_campos_janela": WINDOW_FIELDS},
        ),
        Evidence(
            id=f"ev-{slug}-metricas-5du",
            source=f"Torre de Controle — {source_file} rotas[rota={route}] ({ENGINE_REF}, diagnostico_rpk.py, diagnostico_rentabilidade.py)",
            period="janela_5du",
            timestamp=generated,
            filters={"rota": route},
            quality=EvidenceQuality(source_quality="real", checks=("todas as métricas referem-se à janela_5du",)),
            limitations=("fórmulas documentadas a partir do código do motor; valores não recalculados pelo SAL OS",),
            data={**base, "janela_de_referencia": "janela_5du",
                  "janela_de_referencia_inicio": windows.get("janela_5du", {}).get("inicio"),
                  "janela_de_referencia_fim": windows.get("janela_5du", {}).get("fim"),
                  "metricas": {field: record.get(field) for field in ROUTE_METRICS},
                  "dicionario_metricas": ROUTE_METRICS},
        ),
        Evidence(
            id="ev-parametros-motor",
            source="Torre de Controle — config_investigador.json",
            period="vigente",
            timestamp=generated,
            quality=EvidenceQuality(source_quality="configuracao", checks=("parâmetros oficiais do motor de transferências",)),
            limitations=("parâmetros do motor, não metas comerciais aprovadas pela diretoria",),
            data={"parametros": {key: config.get(key) for key in PARAMETERS}, "dicionario_parametros": PARAMETERS},
        ),
    )
