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

Política de caso (decisão da Tatiana, 2026-09-18):
- CORRECTION_ROUNDS = 1: se o revisor reprovar, cada agente que produziu resultado corrige UMA vez, com o parecer do
  revisor e a própria saída anterior; a consolidação é refeita e revisada de novo (se couber no orçamento);
- CASE_BUDGET_USD = 3,50: teto de RESERVA do caso inteiro (agentes + revisões + correções + fallback). Antes de cada
  execução o limite do job é reduzido ao que resta no caso; o Orchestrator bloqueia a chamada que não couber, sem
  custo. Orçamento esgotado → para e vai para humano. Uso de execução que falhou também conta.
"""

from dataclasses import dataclass, field

from app.agent_bridge.client import (
    AgentRunClient,
    AgentRunClientConfig,
    AgentRunError,
    build_investigation_request,
)
from app.agent_bridge.contract import (
    AgentAuthority,
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
CORRECTION_ROUNDS = 1
CASE_BUDGET_USD = 3.50
#: Autoridade dos agentes (decisão da Tatiana, 2026-09-19): concluir e RECOMENDAR ações; aprovar/executar nunca.
AGENT_AUTHORITY = AgentAuthority(can_recommend=True, can_propose=True)
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
    corrections: tuple[AgentOutcome, ...] = field(default=())   # rodada de correção (auditoria), na ordem
    reviews: tuple[dict, ...] = field(default=())               # todas as revisões, na ordem
    case_budget_usd: float | None = None
    case_reserved_usd: float = 0.0


def reserved_of(usage: tuple[dict, ...] | list[dict]) -> float:
    """Reserva de UMA execução: o Orchestrator informa reserved_cost_usd ACUMULADO no job, então vale o maior."""
    return round(max((float(item.get("reserved_cost_usd") or 0) for item in usage), default=0.0), 6)


def correction_task(task: str, round_number: int, rounds: int) -> str:
    return (f"{task}\nCORREÇÃO ({round_number} de {rounds}): o revisor independente reprovou a consolidação. Corrija SOMENTE "
            "o que o parecer em PREVIOUS RESULTS aponta sobre a SUA parte, mantendo a disciplina de evidência. Devolva a "
            "investigação completa, no mesmo formato. Não acrescente conclusões novas sem evidência.")


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
        recommended_actions=tuple(
            action.model_copy(update={"action": f"[{agent}] {action.action}"})
            for agent, output in outputs for action in (output.recommended_actions or ())
        ) or None,
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
        correction_rounds: int = 0,
        case_budget_usd: float | None = None,
        authority: AgentAuthority | None = None,
    ) -> MultiAgentResult:
        """Executa o caso. `correction_rounds` e `case_budget_usd` vêm da política (CORRECTION_ROUNDS, CASE_BUDGET_USD);
        o padrão 0/None mantém o comportamento anterior para chamadores que não os informam."""
        trace = ["RECEIVED", f"QUALITY_GATE:{'pass' if route.quality.passed else 'blocked'}", f"DECISION_ROUTER:{route.route}"]
        if route.status != "ROUTED" or route.route not in _INVESTIGATION_ROUTES or not route.selected_agents:
            raise RouteNotInvestigable(f"rota {route.route}/{route.status} não pede investigação por agentes")
        agents = tuple(agent.agent_name for agent in route.selected_agents)
        fingerprint = route.fingerprints.exact
        evidence = tuple(evidence)
        spent = 0.0

        def budgeted() -> ExecutionLimits | None:
            """Limites da próxima execução, reduzidos ao que resta no caso; None = orçamento do caso esgotado."""
            if case_budget_usd is None:
                return limits
            remaining = round(case_budget_usd - spent, 6)
            if remaining <= 0:
                return None
            return limits.model_copy(update={"max_cost_usd_per_job": min(limits.max_cost_usd_per_job, remaining),
                                             "max_cost_usd_per_call": min(limits.max_cost_usd_per_call, remaining)})

        def run_agent(agent: str, task: str, run_attempt: int, previous: tuple[str, ...] = ()) -> AgentOutcome:
            nonlocal spent
            run_limits = budgeted()
            request = build_investigation_request(
                config=self._config, case_id=case_id, fingerprint=fingerprint, agent=agent, agent_version="1.0.0",
                task=task, context_files=context_files, evidence=evidence, attempt=run_attempt,
                limits=run_limits or limits, business_data=business_data, previous_results=previous,
                # a revisão acontece sobre o conjunto consolidado — não por agente
                review=ReviewPolicy(required=False, max_correction_attempts=0), authority=authority,
            )
            if run_limits is None:
                return AgentOutcome(agent=agent, status="failed", request_id=request.request_id,
                                    idempotency_key=request.idempotency_key, error="orçamento do caso esgotado: não executado")
            try:
                result = self._client.run(request)
                spent = round(spent + reserved_of(result.usage), 6)
                usable = result.usable and result.status in ("succeeded", "needs_human")
                disciplined = discipline(result.output, agent, evidence) if usable else None
                return AgentOutcome(
                    agent=agent, status=result.status if usable else "failed", request_id=request.request_id,
                    idempotency_key=request.idempotency_key, run_id=result.run_id,
                    author_provider=_author_provider(result), output=disciplined.output if disciplined else None,
                    error=None if usable else str(result.output_validation.get("reason", "")), usage=result.usage,
                    raw_output=result.output if usable else None, discipline=disciplined,
                )
            except AgentRunError as error:  # falha de um agente não interrompe os demais; o uso dela conta no caso
                spent = round(spent + reserved_of(error.usage), 6)
                return AgentOutcome(
                    agent=agent, status="failed", request_id=request.request_id,
                    idempotency_key=request.idempotency_key, run_id=error.run_id,
                    error=f"{error.status_code}/{error.code}: {error.detail}"[:500], usage=error.usage,
                )

        def review(consolidated: InvestigationOutput, outcomes: list[AgentOutcome], run_attempt: int) -> tuple[dict, tuple[dict, ...]]:
            nonlocal spent
            # quem escreveu cada resultado consolidado; se algum for desconhecido, os dois contam como autores
            # (sem revisor independente possível → revisão humana), nunca autorrevisão por suposição
            produced = [o.author_provider for o in outcomes if o.output is not None]
            known = all(provider in ("anthropic", "openai") for provider in produced)
            authors = tuple(sorted(set(produced))) if known else ("anthropic", "openai")
            run_limits = budgeted()
            if run_limits is None:
                return {"status": "NOT_RUN", "error": "orçamento do caso esgotado"}, ()
            review_request = build_investigation_request(
                config=self._config, case_id=case_id, fingerprint=fingerprint, agent=CONSOLIDATION_AGENT,
                agent_version="1.0.0", task=f"{review_task}\n{REVIEW_CHECKLIST}", context_files=context_files,
                evidence=evidence, attempt=run_attempt, limits=run_limits, business_data=business_data,
                # mesma autoridade dos agentes: a consolidação carrega as ações que ELES recomendaram
                review=ReviewPolicy(required=True, max_correction_attempts=0), authority=authority,
            ).model_copy(update={"review_target": ReviewTarget(
                output=consolidated,
                author_providers=authors,
                sources=tuple(ConsolidationSource(agent=o.agent, status=o.status, run_id=o.run_id, request_id=o.request_id)
                              for o in outcomes),
            )})
            try:
                reviewed = self._client.run(review_request)
                spent = round(spent + reserved_of(reviewed.usage), 6)
                return dict(reviewed.review), reviewed.usage
            except AgentRunError as error:
                spent = round(spent + reserved_of(error.usage), 6)
                return {"status": "NOT_RUN", "error": f"{error.status_code}/{error.code}: {error.detail}"[:500]}, error.usage

        outcomes: list[AgentOutcome] = []
        for agent in agents:
            outcomes.append(run_agent(agent, task_by_agent.get(agent, default_task), attempt))
            trace.append(f"AGENT:{agent}:{outcomes[-1].status}")

        consolidation = consolidate_disciplined(tuple(outcomes), evidence)
        if consolidation is None:
            trace += ["CONSOLIDATION:0", "REVIEW:NOT_RUN", "FAILED"]
            return MultiAgentResult(case_id, route.route, agents, tuple(outcomes), None, None, "failed", tuple(trace),
                                    case_budget_usd=case_budget_usd, case_reserved_usd=spent)
        trace.append(f"CONSOLIDATION:{sum(1 for o in outcomes if o.output is not None)}/{len(outcomes)}")
        current_review, usage = review(consolidation.output, outcomes, attempt)
        reviews, review_usage = [current_review], list(usage)
        trace.append(f"REVIEW:{current_review.get('status')}")

        corrections: list[AgentOutcome] = []
        for round_number in range(1, correction_rounds + 1):
            if current_review.get("status") != "REJECTED":
                break  # só corrige o que foi REPROVADO; NOT_RUN/APPROVED não geram correção
            feedback = str(current_review.get("summary") or current_review.get("rejections") or "")
            corrected: list[AgentOutcome] = []
            for outcome in outcomes:
                if outcome.output is None:  # agente que falhou não é "corrigido" (seria retentativa, não correção)
                    corrected.append(outcome)
                    continue
                previous = (
                    "[SUA SAÍDA ANTERIOR]\n" + (outcome.raw_output or outcome.output).model_dump_json(),
                    "[PARECER DO REVISOR INDEPENDENTE SOBRE A CONSOLIDAÇÃO]\n" + feedback,
                )
                fixed = run_agent(outcome.agent, correction_task(task_by_agent.get(outcome.agent, default_task),
                                  round_number, correction_rounds), attempt * 100 + round_number, previous)
                corrections.append(fixed)
                trace.append(f"CORRECTION:{outcome.agent}:{fixed.status}")
                corrected.append(fixed if fixed.output is not None else outcome)  # correção falha mantém a original
            outcomes = corrected
            consolidation = consolidate_disciplined(tuple(outcomes), evidence)
            trace.append(f"CONSOLIDATION:{sum(1 for o in outcomes if o.output is not None)}/{len(outcomes)}")
            current_review, usage = review(consolidation.output, outcomes, attempt * 100 + round_number)
            reviews.append(current_review)
            review_usage += list(usage)
            trace.append(f"REVIEW:{current_review.get('status')}")

        all_agents_ok = all(o.status == "succeeded" for o in outcomes)
        final = "succeeded" if all_agents_ok and current_review.get("status") == "APPROVED" else "needs_human"
        trace.append(final.upper())
        return MultiAgentResult(
            case_id, route.route, agents, tuple(outcomes), consolidation.output, current_review, final, tuple(trace),
            review_usage=tuple(review_usage), items=consolidation.items, divergences=consolidation.divergences,
            confidence_basis=consolidation.confidence_basis, corrections=tuple(corrections), reviews=tuple(reviews),
            case_budget_usd=case_budget_usd, case_reserved_usd=spent,
        )
