"""Investigação MULTI_AGENT: Decision Router → agentes selecionados → consolidação → revisão consolidada.

Garantias (Fase 5F):
- TODO agente que o Router selecionou é executado, em ordem, cada um com request_id e idempotency_key próprios;
- a falha de um agente não apaga o resultado dos outros: ela vira missing_data da consolidação;
- a consolidação é DETERMINÍSTICA (sem IA): junta os resultados com a atribuição de cada agente;
- a revisão consolidada recebe o conjunto inteiro, e o revisor não pode ser nenhum dos autores;
- nada daqui cria diagnóstico, proposta, decisão, ação ou aprendizado: o caso continua em INVESTIGATING.

Fase 5H (disciplina de evidência): a saída de cada agente passa por `epistemics.discipline` antes da consolidação
(só rebaixa certeza; a saída original fica em `raw_output`); a consolidação registra divergências entre agentes sem
escolher um lado, restringe a confiança pela evidência e entrega itens tipados com origem, evidência e limitações.
"""

from dataclasses import dataclass, field

from app.agent_bridge.client import (
    AgentRunClient,
    AgentRunClientConfig,
    AgentRunError,
    build_investigation_request,
)
from app.agent_bridge.contract import (
    AgentRunResult,
    ConsolidationSource,
    Evidence,
    ExecutionLimits,
    Hypothesis,
    InvestigationOutput,
    ReviewPolicy,
    ReviewTarget,
)
from app.agent_bridge.epistemics import (
    CERTAINTY,
    AgentDivergence,
    DisciplinedOutput,
    EpistemicItem,
    detect_divergences,
    discipline,
    restrict_confidence,
)
from app.decision_cycle.states import CaseState
from app.decision_router.contract import DecisionRoute

CONSOLIDATION_AGENT = "consolidacao"
_INVESTIGATION_ROUTES = {"ONE_AGENT", "MULTI_AGENT"}


class RouteNotInvestigable(ValueError):
    """A rota do Decision Router não pede investigação por agentes (nenhuma IA é chamada)."""


@dataclass(frozen=True)
class AgentOutcome:
    agent: str
    status: str  # succeeded | needs_human | failed | <status do agent-run>
    request_id: str
    idempotency_key: str
    run_id: str | None = None
    author_provider: str | None = None
    output: InvestigationOutput | None = None
    error: str | None = None
    usage: tuple[dict, ...] = ()
    raw_output: InvestigationOutput | None = None      # saída do agente como veio (auditoria)
    discipline: DisciplinedOutput | None = None         # reclassificação 5H aplicada a `output`


@dataclass(frozen=True)
class Consolidation:
    output: InvestigationOutput
    items: tuple[EpistemicItem, ...]
    divergences: tuple[AgentDivergence, ...]
    confidence_basis: tuple[str, ...]


@dataclass(frozen=True)
class MultiAgentResult:
    case_id: str
    route: str
    selected_agents: tuple[str, ...]
    outcomes: tuple[AgentOutcome, ...]
    consolidated: InvestigationOutput | None
    review: dict | None
    final_status: str  # succeeded | needs_human | failed
    trace: tuple[str, ...]
    case_state: CaseState = CaseState.INVESTIGATING  # investigação NUNCA avança o caso sozinha
    review_usage: tuple[dict, ...] = field(default=())
    items: tuple[EpistemicItem, ...] = field(default=())
    divergences: tuple[AgentDivergence, ...] = field(default=())
    confidence_basis: tuple[str, ...] = field(default=())


#: Checklist do revisor independente (os 6 problemas reprovados na Fase 5G), anexado à tarefa de revisão.
REVIEW_CHECKLIST = (
    "Verifique obrigatoriamente: (1) nenhum cálculo contém interpretação e todo cálculo mostra fórmula e valores; "
    "(2) nenhuma causa é afirmada sem evidência causal (correlação fica como hipótese ou inferência); "
    "(3) afirmações sobre preço, tarifa ou mix sem esses dados na evidência estão como hipótese e dado ausente; "
    "(4) toda leitura de melhora, piora, alta, queda ou estabilidade confere com a direção numérica, e o que for "
    "ambíguo está como indeterminado; (5) divergências entre agentes estão registradas, sem escolha silenciosa; "
    "(6) a confiança é compatível com a evidência, os dados ausentes, as contradições e as divergências."
)


def _author_provider(result: AgentRunResult) -> str | None:
    authored = [item for item in result.usage if item.get("role") in ("author", "correction") and item.get("outcome", "success") == "success"]
    return str(authored[-1]["provider"]) if authored else None


def consolidate_disciplined(outcomes: tuple[AgentOutcome, ...], evidence: tuple[Evidence, ...] = ()) -> Consolidation | None:
    """Consolidação determinística: atribui cada item ao agente de origem; não interpreta, não resume, não escolhe.

    Cada saída passa pela disciplina 5H (se ainda não passou). Divergências entre agentes são registradas como
    contradições e seus dados de resolução como dado ausente; a confiança é o mínimo entre agentes, restringido
    pela evidência — nunca aumentado.
    """
    usable = [outcome for outcome in outcomes if outcome.output is not None]
    if not usable:
        return None
    disciplined = [(o.agent, o.discipline or discipline(o.output, o.agent, evidence)) for o in usable]
    outputs = [(agent, d.output) for agent, d in disciplined]

    def tagged(values: list[tuple[str, tuple[str, ...]]]) -> tuple[str, ...]:
        return tuple(f"[{agent}] {value}" for agent, items in values for value in items)

    evidence_ids: list[str] = []
    for _, output in outputs:
        for item in output.evidence:
            if item not in evidence_ids:
                evidence_ids.append(item)
    divergences = detect_divergences(disciplined)
    missing = list(tagged([(agent, output.missing_data) for agent, output in outputs]))
    missing += [f"[{o.agent}] resultado indisponível: {o.error or o.status}" for o in outcomes if o.output is None]
    missing += [f"[divergência: {d.topic}] {d.resolving_data}" for d in divergences]
    contradictions = tagged([(agent, output.contradictions) for agent, output in outputs]) + tuple(d.render() for d in divergences)
    facts = tagged([(agent, output.facts) for agent, output in outputs])
    # conservador: a consolidação não é mais confiável que seu agente menos confiável, e a evidência pode reduzir mais
    confidence, basis = restrict_confidence(
        min(output.confidence for _, output in outputs), evidenced_facts=len(facts),
        contradictions=sum(len(output.contradictions) for _, output in outputs), divergences=len(divergences),
        reclassified=sum(d.reclassified for _, d in disciplined), missing=len(missing),
    )
    consolidated = InvestigationOutput(
        facts=facts,
        calculations=tagged([(agent, output.calculations) for agent, output in outputs]),
        inferences=tagged([(agent, output.inferences) for agent, output in outputs]),
        hypotheses=tuple(
            Hypothesis(**{**hypothesis.model_dump(), "statement": f"[{agent}] {hypothesis.statement}"})
            for agent, output in outputs for hypothesis in output.hypotheses
        ),
        contradictions=contradictions,
        missing_data=tuple(missing),
        evidence=tuple(evidence_ids),
        confidence=confidence,
    )
    items = tuple(item for _, d in disciplined for item in d.items) + tuple(
        EpistemicItem("divergencia", d.render(), f"{d.agent_a}+{d.agent_b}", tuple(dict.fromkeys(d.evidence_a + d.evidence_b)),
                      CERTAINTY["divergencia"], (f"dado que resolve: {d.resolving_data}",))
        for d in divergences
    )
    return Consolidation(consolidated, items, divergences, basis)


def consolidate(outcomes: tuple[AgentOutcome, ...], evidence: tuple[Evidence, ...] = ()) -> InvestigationOutput | None:
    consolidation = consolidate_disciplined(outcomes, evidence)
    return consolidation.output if consolidation else None


class MultiAgentInvestigation:
    def __init__(self, client: AgentRunClient, config: AgentRunClientConfig) -> None:
        self._client = client
        self._config = config

    def run(
        self,
        *,
        route: DecisionRoute,
        case_id: str,
        task_by_agent: dict[str, str],
        default_task: str,
        context_files: tuple[str, ...],
        evidence: tuple[Evidence, ...],
        limits: ExecutionLimits,
        review_task: str,
        attempt: int = 1,
        business_data: dict | None = None,
    ) -> MultiAgentResult:
        trace = ["RECEIVED", f"QUALITY_GATE:{'pass' if route.quality.passed else 'blocked'}", f"DECISION_ROUTER:{route.route}"]
        if route.status != "ROUTED" or route.route not in _INVESTIGATION_ROUTES or not route.selected_agents:
            raise RouteNotInvestigable(f"rota {route.route}/{route.status} não pede investigação por agentes")
        agents = tuple(agent.agent_name for agent in route.selected_agents)
        fingerprint = route.fingerprints.exact

        outcomes: list[AgentOutcome] = []
        for agent in agents:
            request = build_investigation_request(
                config=self._config, case_id=case_id, fingerprint=fingerprint, agent=agent, agent_version="1.0.0",
                task=task_by_agent.get(agent, default_task), context_files=context_files, evidence=evidence,
                attempt=attempt, limits=limits, business_data=business_data,
                # a revisão acontece UMA vez, sobre o conjunto consolidado — não por agente
                review=ReviewPolicy(required=False, max_correction_attempts=0),
            )
            try:
                result = self._client.run(request)
                usable = result.usable and result.status in ("succeeded", "needs_human")
                disciplined = discipline(result.output, agent, tuple(evidence)) if usable else None
                outcomes.append(AgentOutcome(
                    agent=agent, status=result.status if usable else "failed", request_id=request.request_id,
                    idempotency_key=request.idempotency_key, run_id=result.run_id,
                    author_provider=_author_provider(result), output=disciplined.output if disciplined else None,
                    error=None if usable else str(result.output_validation.get("reason", "")), usage=result.usage,
                    raw_output=result.output if usable else None, discipline=disciplined,
                ))
            except AgentRunError as error:  # falha de um agente não interrompe os demais
                outcomes.append(AgentOutcome(
                    agent=agent, status="failed", request_id=request.request_id,
                    idempotency_key=request.idempotency_key, run_id=error.run_id,
                    error=f"{error.status_code}/{error.code}: {error.detail}"[:500], usage=error.usage,
                ))
            trace.append(f"AGENT:{agent}:{outcomes[-1].status}")

        consolidation = consolidate_disciplined(tuple(outcomes), tuple(evidence))
        consolidated = consolidation.output if consolidation else None
        if consolidated is None:
            trace += ["CONSOLIDATION:0", "REVIEW:NOT_RUN", "FAILED"]
            return MultiAgentResult(case_id, route.route, agents, tuple(outcomes), None, None, "failed", tuple(trace))
        trace.append(f"CONSOLIDATION:{sum(1 for o in outcomes if o.output is not None)}/{len(outcomes)}")

        # quem escreveu cada resultado consolidado; se algum for desconhecido, os dois contam como autores
        # (sem revisor independente possível → revisão humana), nunca autorrevisão por suposição
        produced = [o.author_provider for o in outcomes if o.output is not None]
        known = all(provider in ("anthropic", "openai") for provider in produced)
        authors = tuple(sorted(set(produced))) if known else ("anthropic", "openai")
        review: dict | None = None
        review_usage: tuple[dict, ...] = ()
        review_request = build_investigation_request(
            config=self._config, case_id=case_id, fingerprint=fingerprint, agent=CONSOLIDATION_AGENT,
            agent_version="1.0.0", task=f"{review_task}\n{REVIEW_CHECKLIST}", context_files=context_files, evidence=evidence,
            attempt=attempt, limits=limits, business_data=business_data,
            review=ReviewPolicy(required=True, max_correction_attempts=0),
        ).model_copy(update={"review_target": ReviewTarget(
            output=consolidated,
            author_providers=authors,
            sources=tuple(ConsolidationSource(agent=o.agent, status=o.status, run_id=o.run_id, request_id=o.request_id) for o in outcomes),
        )})
        try:
            reviewed = self._client.run(review_request)
            review = dict(reviewed.review)
            review_usage = reviewed.usage
        except AgentRunError as error:
            review = {"status": "NOT_RUN", "error": f"{error.status_code}/{error.code}: {error.detail}"[:500]}
            review_usage = error.usage
        trace.append(f"REVIEW:{review.get('status')}")

        all_agents_ok = all(o.status == "succeeded" for o in outcomes)
        final = "succeeded" if all_agents_ok and review.get("status") == "APPROVED" else "needs_human"
        trace.append(final.upper())
        return MultiAgentResult(
            case_id, route.route, agents, tuple(outcomes), consolidated, review, final, tuple(trace),
            review_usage=review_usage, items=consolidation.items, divergences=consolidation.divergences,
            confidence_basis=consolidation.confidence_basis,
        )
