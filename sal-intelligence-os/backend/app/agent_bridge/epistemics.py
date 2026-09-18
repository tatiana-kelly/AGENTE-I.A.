"""Disciplina de evidência (Fase 5H): regras DETERMINÍSTICAS, sem IA, sobre a saída de cada agente e a consolidação.

Por que existe: na Fase 5G o revisor independente reprovou a consolidação por (1) interpretação classificada como
cálculo, (2) causalidade sem evidência, (3) preço/mix sem dado, (4) tendência lida contra os números, (5) divergência
entre agentes omitida e (6) confiança incompatível com a evidência. As definições dos agentes pedem a disciplina; este
módulo a GARANTE no que é verificável mecanicamente.

Garantia central: as regras só REBAIXAM certeza — fato/cálculo → inferência → hipótese → contradição. Nenhuma regra
promove hipótese a fato, inferência a fato, correlação a causa ou cálculo a conclusão causal. Todo rebaixamento fica
registrado como limitação do item, visível ao revisor e à auditoria.

Limite honesto: a detecção é por padrões de linguagem e números da evidência. Ela pega os erros observados na 5G, não
substitui o revisor independente nem a validação humana.
"""

import re
import unicodedata
from dataclasses import dataclass, field

from app.agent_bridge.contract import Evidence, Hypothesis, InvestigationOutput

# ── tipos e grau de certeza ─────────────────────────────────────────────────────────────────────────────
CERTAINTY = {
    "fato": "observado na evidência",
    "calculo": "derivado por fórmula dos dados fornecidos",
    "inferencia": "interpretação, não comprovada",
    "hipotese": "explicação possível, não comprovada",
    "contradicao": "em conflito com a evidência ou entre agentes",
    "dado_ausente": "ausente",
    "divergencia": "divergência entre agentes, não resolvida",
}
#: Ordem de certeza. Uma regra só pode mover um item para um nível MENOR.
RANK = {"fato": 3, "calculo": 3, "inferencia": 2, "hipotese": 1, "contradicao": 0}

# ── restrições de confiança (Tarefa 4) ──────────────────────────────────────────────────────────────────
# Regra ATUAL, preservada: a confiança é autodeclarada pelo agente (0–100, sem fórmula) e a consolidação usa o
# MÍNIMO entre os agentes (Fase 5F). Downstream: diagnóstico só vira READY_FOR_DECISION com confiança >= 70
# (config/priority-scoring.yaml) e causal_confidence pesa 0,12 na prioridade.
# Reforço 5H: tetos que só REDUZEM o valor declarado quando a evidência não sustenta. Não é fórmula nova: nenhum teto
# aumenta confiança. Valores provisórios, para validação da Tatiana.
CONFIDENCE_CAPS = {
    "sem_fato_com_evidencia": 30,       # nenhum fato cita um id de evidência
    "contradicao_ou_divergencia": 50,   # há contradição registrada ou divergência entre agentes
    "reclassificacao": 60,              # a disciplina precisou rebaixar algum item do agente
    "dados_ausentes": 60,               # há dado ausente declarado
}
HYPOTHESIS_CAPS = {
    "sem_evidencia_favoravel": 30,      # hipótese sem nenhuma evidência favorável
    "criada_por_regra": 20,             # afirmação rebaixada a hipótese pela disciplina
}
DIRECTION_TOLERANCE_PCT = 5.0           # diferença relativa até 5% entre janelas = direção indeterminada
CONFIDENCE_GAP_DIVERGENCE = 25          # agentes com confiança distante >= 25 pontos = divergência registrada


def _norm(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).lower()


def _has(pattern: re.Pattern, text: str) -> bool:
    return bool(pattern.search(_norm(text)))


# padrões aplicados ao texto sem acento, em minúsculas
CAUSAL = re.compile(
    r"\b(causa\w*|causou|porque|devido a|em razao d[eoa]s?|provoc\w+|result\w* de|decorr\w+|lev(a|ou|am) a|"
    r"explica(m|do|da|r|ria)?\b|explicad[oa]|por conta d[eoa]s?|motivad[oa]s? por|responsave(l|is) por|por si so)"
)
DEFINITIVE = re.compile(
    r"\b(a causa (principal |raiz )?(e|foi)\b|causa raiz|comprova\w*|confirma(m|do|da)? que|demonstra\w* que|"
    r"prova(m)? que|causad[oa]s? por|independentemente d[eoa]s?|por si so|certamente|sem duvida)"
)
INTERPRETIVE = re.compile(
    r"\b(indica\w*|sugere\w*|sugerindo|mostra(m)? que|aponta\w*|trajetoria|tendencia|significa\w*|sinaliza\w*|"
    r"evidencia(m)? que|reflete\w*|confere\w*|faltante\w*)"
)
#: variação que muda de sentido entre janelas: é tendência INDETERMINADA, não contradição (5H, tentativa 3)
NON_MONOTONIC = re.compile(r"\b(nao monoton\w*|nao linear|nao estritamente|oscila\w*|irregular\w*|sem direcao (unica|clara))")
#: ausência de dado descrita como evidência contrária: é evidência FALTANTE (5H, tentativa 3)
ABSENCE = re.compile(
    r"\b(ausen\w*|nao ha (dado|registro|informac)\w*|sem (dado|registro|informac)\w*|falt\w*|"
    r"nao (disponive|informad|fornecid|const)\w*|inexist\w*|desconhecid\w*|indisponive\w*)"
)
TREND_CLAIM = re.compile(r"\b(tendencia|trajetoria|vem (caindo|subindo|piorando|melhorando)|deterior\w*|recupera\w*)")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_OPERATOR = re.compile(r"[-+×*/÷−]|\sx\s")

# "alta"/"baixa" sozinhos são nível ou nome de faixa (BAIXA/ALTA do motor), não direção: só "em alta" conta
UP = re.compile(r"\b(aument\w*|em alta|subi\w*|sobe|cresc\w*|elev(ou|aram|acao))\b")
DOWN = re.compile(r"\b(queda|cai\w*|caiu|redu\w*|diminu\w*|declin\w*)\b")
GOOD = re.compile(r"\b(melhora\w*|melhorou|melhoria|recupera\w*)\b")
BAD = re.compile(r"\b(piora\w*|piorou|deterior\w*|agrava\w*)\b")
STABLE = re.compile(r"\b(estavel|estabilidade|estabiliz\w*)\b")

#: métricas cuja direção é verificável nos valores das janelas da evidência (campo → termos e sentido de "melhor")
METRICS = {
    "ocup": {"label": "ocupação por peso", "terms": re.compile(r"\bocupa\w*(?!\s+(cubad|visual))"),
             "higher_is_better": True},
    "pct": {"label": "custo percentual", "terms": re.compile(r"custo percentual|custo ?/ ?frete|custo sobre frete|\bpct\b"),
            "higher_is_better": False},
}
RECENT_WINDOW, REFERENCE_WINDOW = "janela_5du", "janela_30d"

#: afirmações que exigem dado específico na evidência; sem ele, viram hipótese (Tarefa 6C)
TOPIC_REQUIREMENTS = {
    "preço/tarifa": (re.compile(r"\b(preco\w*|precifica\w*|tarifa\w*|pricing|tabela de frete)"), ("preco", "tarifa", "tabela")),
    "mix de carga": (re.compile(r"\bmix\b"), ("mix", "composicao")),
}

STRUCTURAL = re.compile(r"\b(estrutura\w*|recorrent\w*|persistent\w*|cronic\w*|sistemic\w*)")
EPISODIC = re.compile(r"\b(pontua\w*|recente\w*|evento\w*|atipic\w*|isolad\w*|temporari\w*|sazona\w*)")


@dataclass(frozen=True)
class EpistemicItem:
    """Item consolidado com tipo, conteúdo, origem, evidência, grau de certeza e limitações (Tarefa 5)."""

    kind: str
    content: str
    agent: str
    evidence: tuple[str, ...]
    certainty: str
    limitations: tuple[str, ...] = ()
    origin_kind: str | None = None  # tipo declarado pelo agente, quando a disciplina o rebaixou


@dataclass(frozen=True)
class AgentDivergence:
    """Divergência entre agentes (Tarefa 3): registrada, nunca resolvida em silêncio."""

    topic: str
    point: str
    agent_a: str
    position_a: str
    evidence_a: tuple[str, ...]
    agent_b: str
    position_b: str
    evidence_b: tuple[str, ...]
    resolving_data: str

    def render(self) -> str:
        ev_a = ", ".join(self.evidence_a) or "nenhuma citada"
        ev_b = ", ".join(self.evidence_b) or "nenhuma citada"
        return (f"[DIVERGÊNCIA ENTRE AGENTES: {self.topic}] ponto: {self.point} | {self.agent_a}: {self.position_a} "
                f"(evidências: {ev_a}) | {self.agent_b}: {self.position_b} (evidências: {ev_b}) | "
                f"dado que resolve: {self.resolving_data}")


@dataclass(frozen=True)
class DisciplinedOutput:
    output: InvestigationOutput
    items: tuple[EpistemicItem, ...]
    reclassified: int
    confidence_basis: tuple[str, ...] = field(default=())


# ── leitura da evidência ────────────────────────────────────────────────────────────────────────────────
def _evidence_keys(evidence: tuple[Evidence, ...]) -> set[str]:
    keys: set[str] = set()

    def walk(value) -> None:
        if isinstance(value, dict):
            for key, inner in value.items():
                keys.add(_norm(str(key)))
                walk(inner)
        elif isinstance(value, list | tuple):
            for inner in value:
                walk(inner)

    for item in evidence:
        walk(item.data)
    return keys


def _window_value(evidence: tuple[Evidence, ...], window: str, metric: str) -> float | None:
    for item in evidence:
        janelas = item.data.get("janelas")
        if isinstance(janelas, dict):
            value = ((janelas.get(window) or {}).get("valores") or {}).get(metric)
            if isinstance(value, int | float) and not isinstance(value, bool):
                return float(value)
    return None


def numeric_direction(evidence: tuple[Evidence, ...], metric: str) -> tuple[str, str]:
    """Direção NUMÉRICA de uma métrica: janela recente (5 dias com dado) contra a de 30 dias.

    Retorna alta | queda | estavel | indeterminada. Janelas se sobrepõem: isto compara janelas, não é série temporal.
    """
    recent, reference = _window_value(evidence, RECENT_WINDOW, metric), _window_value(evidence, REFERENCE_WINDOW, metric)
    if recent is None or reference is None:
        return "indeterminada", f"{metric}: valores de {RECENT_WINDOW}/{REFERENCE_WINDOW} ausentes na evidência"
    detail = f"{metric}: {RECENT_WINDOW}={recent:g} vs {REFERENCE_WINDOW}={reference:g}"
    if recent == reference:
        return "estavel", detail
    if reference == 0 or abs(recent - reference) / abs(reference) * 100 <= DIRECTION_TOLERANCE_PCT:
        return "indeterminada", f"{detail} (diferença dentro de {DIRECTION_TOLERANCE_PCT:g}%)"
    return ("alta" if recent > reference else "queda"), detail


def claimed_direction(text: str) -> dict[str, str]:
    """Direção numérica que o texto AFIRMA por métrica verificável (só quando a leitura é inequívoca)."""
    norm = _norm(text)
    mentioned = [metric for metric, spec in METRICS.items() if spec["terms"].search(norm)]
    if len(mentioned) != 1:
        return {}  # nenhuma ou várias métricas no mesmo item: não dá para atribuir a direção com segurança
    metric = mentioned[0]
    better = "alta" if METRICS[metric]["higher_is_better"] else "queda"
    worse = "queda" if better == "alta" else "alta"
    claims = set()
    if UP.search(norm):
        claims.add("alta")
    if DOWN.search(norm):
        claims.add("queda")
    if GOOD.search(norm):
        claims.add(better)
    if BAD.search(norm):
        claims.add(worse)
    if STABLE.search(norm):
        claims.add("estavel")
    return {metric: claims.pop()} if len(claims) == 1 else {}


def _is_formula(text: str) -> bool:
    return "=" in text and len(_NUMBER.findall(text)) >= 2 and bool(_OPERATOR.search(text))


def _cited(text: str, ids: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(i for i in ids if i in text)


# ── classificação de um item ────────────────────────────────────────────────────────────────────────────
@dataclass
class _Verdict:
    kind: str
    limitations: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    def lower(self, kind: str, reason: str) -> None:
        if RANK[kind] < RANK[self.kind]:  # SÓ rebaixa
            self.kind = kind
            self.limitations.append(reason)


def classify(kind: str, text: str, evidence: tuple[Evidence, ...], keys: set[str] | None = None) -> _Verdict:
    """Aplica as regras 5H a um item declarado como `kind` (fato | calculo | inferencia | hipotese)."""
    keys = _evidence_keys(evidence) if keys is None else keys
    ids = tuple(item.id for item in evidence)
    verdict = _Verdict(kind)

    # A — cálculo é fórmula aplicada aos dados, com valores; interpretação não é cálculo
    if kind == "calculo":
        if not _is_formula(text):
            verdict.lower("inferencia", "cálculo sem fórmula e valores explícitos → inferência")
        elif _has(INTERPRETIVE, text):
            verdict.lower("inferencia", "cálculo contém interpretação → inferência (separe a conta da leitura)")
    # B — causalidade sem evidência causal nunca é fato nem cálculo; afirmada como certa, vira hipótese
    if verdict.kind in ("fato", "calculo") and _has(CAUSAL, text):
        verdict.lower("inferencia", "afirmação causal sem evidência causal → inferência")
    if kind == "fato" and not _cited(text, ids):
        verdict.lower("inferencia", "fato sem id de evidência citado → inferência")
    if verdict.kind in ("fato", "calculo") and _has(NON_MONOTONIC, text):
        verdict.lower("inferencia", "variação não monotônica: tendência indeterminada → inferência")
    if verdict.kind in ("fato", "calculo") and _has(TREND_CLAIM, text):
        verdict.lower("inferencia", "tendência não é fato: as janelas se sobrepõem e não formam série temporal")
    if verdict.kind != "hipotese" and _has(DEFINITIVE, text):
        verdict.lower("hipotese", "causalidade afirmada como certa sem evidência causal → hipótese")
    # C — preço/mix (e afins) sem o dado na evidência: hipótese + dado ausente declarado
    for topic, (pattern, required_keys) in TOPIC_REQUIREMENTS.items():
        if _has(pattern, text) and not any(req in key for key in keys for req in required_keys):
            verdict.missing.append(f"{topic}: dado não consta na evidência (necessário para confirmar ou refutar)")
            verdict.lower("hipotese", f"{topic} sem dado na evidência → hipótese")
    # D — direção afirmada tem de bater com a direção numérica; ambígua = indeterminada
    for metric, claimed in claimed_direction(text).items():
        actual, detail = numeric_direction(evidence, metric)
        if actual == "indeterminada":
            if verdict.kind in ("fato", "calculo"):
                verdict.lower("inferencia", f"tendência indeterminada ({detail}) → inferência")
            else:
                verdict.limitations.append(f"tendência indeterminada: {detail}")
        elif claimed != actual:
            verdict.lower("contradicao", f"direção afirmada ({claimed}) contraria a direção numérica ({actual}; {detail})")
        else:
            verdict.limitations.append(f"direção confere com os números ({detail}); comparação de janelas, não série temporal")
    return verdict


def _render(text: str, verdict: _Verdict, origin: str) -> str:
    if verdict.kind == origin:
        return text
    return f"{text} [reclassificado de {origin}: {verdict.limitations[-1] if verdict.limitations else 'regra 5H'}]"


def restrict_confidence(declared: float, *, evidenced_facts: int, contradictions: int, divergences: int,
                        reclassified: int, missing: int) -> tuple[float, tuple[str, ...]]:
    """Aplica os tetos de CONFIDENCE_CAPS ao valor declarado. Nunca aumenta."""
    value, basis = float(declared), [f"declarada: {declared:g}"]
    checks = (
        ("sem_fato_com_evidencia", evidenced_facts == 0, "nenhum fato cita evidência"),
        ("contradicao_ou_divergencia", contradictions + divergences > 0,
         f"{contradictions} contradição(ões), {divergences} divergência(s) entre agentes"),
        ("reclassificacao", reclassified > 0, f"{reclassified} item(ns) rebaixado(s) pela disciplina de evidência"),
        ("dados_ausentes", missing > 0, f"{missing} dado(s) ausente(s)"),
    )
    for name, applies, reason in checks:
        cap = CONFIDENCE_CAPS[name]
        if applies and value > cap:
            value = float(cap)
            basis.append(f"limitada a {cap}: {reason}")
    return value, tuple(basis)


def discipline(output: InvestigationOutput, agent: str, evidence: tuple[Evidence, ...]) -> DisciplinedOutput:
    """Reclassifica a saída de UM agente segundo as regras 5H. Só rebaixa; registra cada rebaixamento."""
    keys = _evidence_keys(evidence)
    ids = tuple(item.id for item in evidence)
    # Exceção documentada à ordem RANK: uma "contradição" que só descreve variação não monotônica não afirma conflito;
    # vira inferência rotulada "tendência indeterminada" — a afirmação fica MAIS fraca, não mais forte.
    indeterminate = [text for text in output.contradictions if _has(NON_MONOTONIC, text)]
    kept_contradictions = [text for text in output.contradictions if text not in indeterminate]
    buckets: dict[str, list[str]] = {"fato": [], "calculo": [], "inferencia": [], "contradicao": list(kept_contradictions)}
    hypotheses: list[Hypothesis] = []
    missing: list[str] = list(output.missing_data)
    items: list[EpistemicItem] = []
    reclassified = 0

    def add_missing(values: list[str]) -> None:
        for value in values:
            if value not in missing:
                missing.append(value)

    for origin, values in (("fato", output.facts), ("calculo", output.calculations), ("inferencia", output.inferences)):
        for text in values:
            verdict = classify(origin, text, evidence, keys)
            add_missing(verdict.missing)
            reclassified += verdict.kind != origin
            cited = _cited(text, ids)
            if verdict.kind == "hipotese":
                hypotheses.append(Hypothesis(
                    statement=_render(text, verdict, origin), favorable_evidence=cited,
                    missing_evidence=tuple(verdict.missing) or ("evidência causal (série antes/depois, dado de demanda ou teste)",),
                    confidence=min(output.confidence, HYPOTHESIS_CAPS["criada_por_regra"]),
                ))
            else:
                buckets[verdict.kind].append(_render(text, verdict, origin))
            items.append(EpistemicItem(verdict.kind, text, agent, cited, CERTAINTY[verdict.kind], tuple(verdict.limitations),
                                       origin if verdict.kind != origin else None))

    for text in indeterminate:
        reclassified += 1
        reason = "variação não monotônica: tendência indeterminada, não contradição"
        buckets["inferencia"].append(f"[tendência indeterminada] {text} [reclassificado de contradição: {reason}]")
        items.append(EpistemicItem("inferencia", text, agent, _cited(text, ids), CERTAINTY["inferencia"], (reason,), "contradicao"))

    for hypothesis in output.hypotheses:
        verdict = classify("hipotese", hypothesis.statement, evidence, keys)
        add_missing(verdict.missing)
        cited = tuple(dict.fromkeys(_cited(hypothesis.statement, ids) + tuple(hypothesis.favorable_evidence)))
        limitations = list(verdict.limitations)
        absent = tuple(item for item in hypothesis.contrary_evidence if _has(ABSENCE, item))
        if absent:
            reclassified += 1
            limitations.append(f"{len(absent)} ausência(s) de dado estavam como evidência contrária → evidência faltante")
            hypothesis = hypothesis.model_copy(update={
                "contrary_evidence": tuple(item for item in hypothesis.contrary_evidence if item not in absent),
                "missing_evidence": tuple(dict.fromkeys(tuple(hypothesis.missing_evidence) + absent)),
            })
        if verdict.kind == "contradicao":  # B/D: hipótese que contraria os números não é mantida como explicação
            reclassified += 1
            buckets["contradicao"].append(_render(hypothesis.statement, verdict, "hipotese"))
        else:
            confidence = hypothesis.confidence
            if not hypothesis.favorable_evidence and confidence > HYPOTHESIS_CAPS["sem_evidencia_favoravel"]:
                confidence = HYPOTHESIS_CAPS["sem_evidencia_favoravel"]
                limitations.append(f"sem evidência favorável: confiança limitada a {confidence}")
            if verdict.missing:
                confidence = min(confidence, HYPOTHESIS_CAPS["criada_por_regra"])
            hypotheses.append(hypothesis.model_copy(update={
                "missing_evidence": tuple(dict.fromkeys(tuple(hypothesis.missing_evidence) + tuple(verdict.missing))),
                "confidence": confidence,
            }))
        items.append(EpistemicItem(verdict.kind, hypothesis.statement, agent, cited, CERTAINTY[verdict.kind],
                                   tuple(limitations), "hipotese" if verdict.kind != "hipotese" else None))

    items += [EpistemicItem("contradicao", text, agent, _cited(text, ids), CERTAINTY["contradicao"]) for text in kept_contradictions]
    items += [EpistemicItem("dado_ausente", text, agent, (), CERTAINTY["dado_ausente"]) for text in missing]
    confidence, basis = restrict_confidence(
        output.confidence, evidenced_facts=len(buckets["fato"]), contradictions=len(buckets["contradicao"]),
        divergences=0, reclassified=reclassified, missing=len(missing),
    )
    disciplined = InvestigationOutput(
        facts=tuple(buckets["fato"]), calculations=tuple(buckets["calculo"]), inferences=tuple(buckets["inferencia"]),
        hypotheses=tuple(hypotheses), contradictions=tuple(buckets["contradicao"]), missing_data=tuple(missing),
        evidence=output.evidence, confidence=confidence,
    )
    return DisciplinedOutput(disciplined, tuple(items), reclassified, basis)


# ── divergência entre agentes (Tarefa 3) ────────────────────────────────────────────────────────────────
#: "X, não Y" / "X e não Y" / "X, não apenas Y": só X é a posição afirmada
_NEGATED_TAIL = re.compile(r",?\s+(e\s+)?nao\s+(apenas|so|somente|um|uma|de|o|a)?\b")


def _horizon(text: str) -> str | None:
    asserted = _NEGATED_TAIL.split(_norm(text), maxsplit=1)[0]
    structural, episodic = bool(STRUCTURAL.search(asserted)), bool(EPISODIC.search(asserted))
    return "estrutural" if structural and not episodic else "pontual/recente" if episodic and not structural else None


def _principal_horizon(out: DisciplinedOutput, metric_terms: re.Pattern | None) -> tuple[str, str, tuple[str, ...]] | None:
    """Horizonte (estrutural x pontual/recente) da posição principal do agente sobre a métrica: a hipótese mais
    confiante que afirma um horizonte; sem hipótese, a primeira inferência que o afirma."""
    def about(text: str) -> bool:
        return metric_terms is None or bool(metric_terms.search(_norm(text)))

    for hypothesis in sorted(out.output.hypotheses, key=lambda h: h.confidence, reverse=True):
        if about(hypothesis.statement) and (horizon := _horizon(hypothesis.statement)):
            return horizon, hypothesis.statement, tuple(hypothesis.favorable_evidence)
    for inference in out.output.inferences:
        if about(inference) and (horizon := _horizon(inference)):
            return horizon, inference, ()
    return None


def detect_divergences(disciplined: list[tuple[str, DisciplinedOutput]]) -> tuple[AgentDivergence, ...]:
    """Divergências verificáveis entre pares de agentes. A consolidação as registra; não escolhe um lado."""
    found: list[AgentDivergence] = []
    for index, (agent_a, out_a) in enumerate(disciplined):
        for agent_b, out_b in disciplined[index + 1:]:
            # direção da mesma métrica afirmada em sentidos opostos
            for metric, spec in METRICS.items():
                pos_a = next(((i, d[metric]) for i in out_a.items if (d := claimed_direction(i.content)).get(metric)), None)
                pos_b = next(((i, d[metric]) for i in out_b.items if (d := claimed_direction(i.content)).get(metric)), None)
                if pos_a and pos_b and pos_a[1] != pos_b[1]:
                    found.append(AgentDivergence(
                        topic=f"direção de {spec['label']}", point=f"{agent_a} lê {pos_a[1]}, {agent_b} lê {pos_b[1]}",
                        agent_a=agent_a, position_a=pos_a[0].content, evidence_a=pos_a[0].evidence,
                        agent_b=agent_b, position_b=pos_b[0].content, evidence_b=pos_b[0].evidence,
                        resolving_data=f"série diária de {spec['label']} sem sobreposição de janelas",
                    ))
            # natureza da explicação principal: padrão estrutural x evento pontual/recente
            # por métrica verificável primeiro; sem posição sobre nenhuma métrica, compara a explicação geral
            scopes = [(spec["label"], spec["terms"]) for spec in METRICS.values()]
            pairs = [(label, _principal_horizon(out_a, terms), _principal_horizon(out_b, terms)) for label, terms in scopes]
            if not any(a and b for _, a, b in pairs):
                pairs = [("explicação geral", _principal_horizon(out_a, None), _principal_horizon(out_b, None))]
            for label, pos_a, pos_b in pairs:
                if pos_a and pos_b and pos_a[0] != pos_b[0]:
                    found.append(AgentDivergence(
                        topic=f"natureza da explicação principal ({label})", point=f"{agent_a}: {pos_a[0]}; {agent_b}: {pos_b[0]}",
                        agent_a=agent_a, position_a=pos_a[1], evidence_a=pos_a[2],
                        agent_b=agent_b, position_b=pos_b[1], evidence_b=pos_b[2],
                        resolving_data="série histórica por dia ou semana que mostre se o padrão antecede o período recente",
                    ))
            # hipóteses principais concorrentes: cada agente prioriza uma explicação; nenhuma é escolhida
            top_a = max(out_a.output.hypotheses, key=lambda h: h.confidence, default=None)
            top_b = max(out_b.output.hypotheses, key=lambda h: h.confidence, default=None)
            already = any(d.agent_a == agent_a and d.agent_b == agent_b and top_a and top_b
                          and d.position_a == top_a.statement and d.position_b == top_b.statement for d in found)
            if top_a and top_b and _norm(top_a.statement) != _norm(top_b.statement) and not already:
                discriminating = tuple(dict.fromkeys(tuple(top_a.missing_evidence) + tuple(top_b.missing_evidence)))[:3]
                found.append(AgentDivergence(
                    topic="hipóteses principais concorrentes",
                    point=f"a hipótese de maior confiança difere entre os agentes ({agent_a}: {top_a.confidence:g}; "
                          f"{agent_b}: {top_b.confidence:g}), conforme as hipóteses de cada um nesta consolidação",
                    agent_a=agent_a, position_a=top_a.statement, evidence_a=tuple(top_a.favorable_evidence),
                    agent_b=agent_b, position_b=top_b.statement, evidence_b=tuple(top_b.favorable_evidence),
                    resolving_data="; ".join(discriminating) or "evidência que confirme uma explicação e refute a outra",
                ))
            # grau de confiança muito diferente sobre o mesmo caso
            gap = abs(out_a.output.confidence - out_b.output.confidence)
            if gap >= CONFIDENCE_GAP_DIVERGENCE:
                found.append(AgentDivergence(
                    topic="grau de confiança", point=f"diferença de {gap:g} pontos",
                    agent_a=agent_a, position_a=f"confiança {out_a.output.confidence:g}", evidence_a=out_a.output.evidence,
                    agent_b=agent_b, position_b=f"confiança {out_b.output.confidence:g}", evidence_b=out_b.output.evidence,
                    resolving_data="evidência que sustente ou refute a hipótese principal de cada agente",
                ))
    return tuple(found)
