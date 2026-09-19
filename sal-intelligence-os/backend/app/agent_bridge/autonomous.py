"""Execução autônoma diária (decisão da Tatiana, 2026-09-19): os agentes investigam sozinhos; a pessoa decide.

Um ciclo por projeto:
1. adaptadores leem os motores (só leitura) → alertas;
2. Decision Router decide a rota de cada alerta (sem IA);
3. só rotas de investigação (ONE_AGENT/MULTI_AGENT) seguem, em rodízio por fonte e Pareto dentro de cada fonte;
4. antes de cada caso, os freios (`AutonomyGate`): interruptor geral, interruptor do projeto, teto diário;
5. evidência: montador dedicado (transferências) ou evidência DECLARADA; fonte sem declaração não sai;
6. agentes + consolidação + revisão + 1 correção, com autoridade de RECOMENDAR (nunca aprovar/executar);
7. o resultado vai para a fila de decisões (arquivo por caso) e o gasto reservado entra no livro do dia.

Nada aqui aprova, executa, altera motor ou fonte, nem envia mensagem. O caso termina em INVESTIGATING/NEEDS_HUMAN.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.agent_bridge.autonomy import AutonomyBlocked, AutonomyGate
from app.agent_bridge.contract import ExecutionLimits
from app.agent_bridge.declared_evidence import EvidenceNotDeclared, build_declared_evidence
from app.agent_bridge.evidence import build_transfer_route_evidence
from app.agent_bridge.multi_agent import AGENT_AUTHORITY, CORRECTION_ROUNDS, MultiAgentInvestigation
from app.decision_router.adapters.base import AdaptedAlert, TorreDataReader
from app.decision_router.adapters.torre_transferencias import SOURCE as TRANSFER_SOURCE

INVESTIGATION_ROUTES = {"ONE_AGENT", "MULTI_AGENT"}
DEFAULT_LIMITS = ExecutionLimits(timeout_seconds=180, max_attempts=2, max_cost_usd_per_call=1.0, max_cost_usd_per_job=3.0)
DEFAULT_CONTEXT = ("ARCHITECTURE.md", "DATA_MODEL.md", "AGENT_WORKFLOW.md")

TASK = ("Investigue o desvio da métrica {metric} em {entity} (fonte {source}, período {period}) usando exclusivamente as evidências e o contexto "
        "autorizado. Siga a disciplina de evidência da sua definição: FATO só com id de evidência; CÁLCULO com fórmula, "
        "valores e resultado; causa só com evidência causal; tendência só pela direção numérica; dados ausentes explícitos; "
        "confidence compatível com a evidência. Você PODE recomendar ações em recommended_actions (o quê, papel, prazo, KPI, "
        "evidência, risco de não agir); NÃO aprova, NÃO executa e NÃO declara resultado verificado.")
REVIEW = ("Revise a consolidação dos agentes sobre a métrica {metric} em {entity}: fatos, cálculos, hipóteses, divergências, dados ausentes, "
          "confiança e se cada ação recomendada é sustentada pela evidência. Não aprove decisão nem execute ação.")


@dataclass
class DailyRunReport:
    project: str
    started_at: str
    alerts: int = 0
    investigable: int = 0
    cases: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)
    stopped_reason: str | None = None


def _slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-")[:80]


def evidence_for(reader: TorreDataReader, adapted: AdaptedAlert, declarations: dict[str, dict[str, Any]]):
    if adapted.source == TRANSFER_SOURCE:
        return tuple(build_transfer_route_evidence(reader, adapted.envelope.entity_id))
    return build_declared_evidence(reader, adapted, declarations)


def prioritize(candidates: list[tuple[AdaptedAlert, Any]]) -> list[tuple[AdaptedAlert, Any]]:
    """Rodízio por fonte e Pareto dentro de cada fonte: o maior desvio de cada motor antes do 2º de qualquer um.

    Materialidade de fontes diferentes não é comparável (R$ × kg × contagem); só dentro da mesma fonte ela ordena.
    """
    by_source: dict[str, list[tuple[AdaptedAlert, Any]]] = {}
    for item in candidates:
        by_source.setdefault(item[0].source, []).append(item)
    ranked = []
    for source, items in by_source.items():
        items.sort(key=lambda item: item[0].envelope.alert.materiality, reverse=True)
        ranked += [(rank, source, item) for rank, item in enumerate(items)]
    ranked.sort(key=lambda entry: (entry[0], entry[1]))  # rodada, depois fonte em ordem estável
    return [item for _, _, item in ranked]


def run_daily(
    *,
    project: str,
    reader: TorreDataReader,
    adapters: list,
    router,
    client,
    config,
    gate: AutonomyGate,
    declarations: dict[str, dict[str, Any]],
    queue_dir: Path,
    rules_version: str = "rules:autonomo",
    limits: ExecutionLimits = DEFAULT_LIMITS,
    context_files: tuple[str, ...] = DEFAULT_CONTEXT,
    clock=lambda: datetime.now(UTC),
) -> DailyRunReport:
    report = DailyRunReport(project=project, started_at=clock().isoformat())
    try:  # freio geral e do projeto ANTES de ler qualquer coisa
        gate.case_budget(project)
    except AutonomyBlocked as blocked:
        report.stopped_reason = str(blocked)
        return report

    candidates: list[tuple[AdaptedAlert, Any]] = []
    for adapter in adapters:
        output = adapter.adapt(reader, rules_version)
        report.alerts += len(output.alerts)
        for adapted in output.alerts:
            route = router.route(adapted.envelope)
            if route.status == "ROUTED" and route.route in INVESTIGATION_ROUTES and route.selected_agents:
                candidates.append((adapted, route))
            else:
                report.skipped.append({"alerta": adapted.alert_id, "motivo": f"rota {route.route}/{route.status} não pede IA"})
    report.investigable = len(candidates)
    candidates = prioritize(candidates)

    queue_dir = Path(queue_dir)
    queue_dir.mkdir(parents=True, exist_ok=True)
    investigation = MultiAgentInvestigation(client, config)
    for index, (adapted, route) in enumerate(candidates):
        try:
            budget = gate.case_budget(project)
        except AutonomyBlocked as blocked:  # teto do dia atingido: o resto fica para amanhã, registrado
            report.stopped_reason = str(blocked)
            report.skipped += [{"alerta": a.alert_id, "motivo": str(blocked)} for a, _ in candidates[index:]]
            break
        try:
            evidence = evidence_for(reader, adapted, declarations)
        except (EvidenceNotDeclared, KeyError, ValueError) as missing:
            report.skipped.append({"alerta": adapted.alert_id, "motivo": f"evidência indisponível: {missing}"})
            continue
        alert = adapted.envelope.alert
        # título do alerta NÃO vai para a IA: ele carrega a classificação do motor (ex.: "categoria D", "BAIXA")
        values = {"metric": alert.metric_id, "entity": f"{adapted.envelope.entity_type} {adapted.envelope.entity_id}",
                  "source": adapted.source, "period": alert.period}
        result = investigation.run(
            route=route, case_id=f"{project}:{adapted.alert_id}", task_by_agent={}, default_task=TASK.format(**values),
            context_files=context_files, evidence=evidence, limits=limits, review_task=REVIEW.format(**values),
            business_data={"project": project, "source": adapted.source, "synthetic_test": False},
            correction_rounds=CORRECTION_ROUNDS, case_budget_usd=budget, authority=AGENT_AUTHORITY,
        )
        gate.record(project=project, case_id=result.case_id, reserved_usd=result.case_reserved_usd)
        case = {
            "alerta": adapted.alert_id, "projeto": project, "fonte": adapted.source, "titulo": alert.title,
            "materialidade": alert.materiality, "rota": route.route, "status": result.final_status,
            "estado_do_caso": result.case_state.value, "trace": list(result.trace), "reservado_usd": result.case_reserved_usd,
            "revisao": result.review, "consolidacao": result.consolidated.model_dump(mode="json") if result.consolidated else None,
            "divergencias": [d.render() for d in result.divergences], "confianca_base": list(result.confidence_basis),
            "gerado_em": clock().isoformat(),
        }
        (queue_dir / f"{clock():%Y%m%d}-{_slug(adapted.alert_id)}.json").write_text(
            json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")
        report.cases.append({k: case[k] for k in ("alerta", "titulo", "materialidade", "status", "reservado_usd")})
    return report


def weekly_agenda(queue_dir: Path, *, now: datetime | None = None, top: int = 3) -> str:
    """Agenda executiva: as `top` decisões de maior materialidade da semana, somando todos os projetos."""
    now = now or datetime.now(UTC)
    since = now - timedelta(days=7)
    cases = []
    for path in sorted(Path(queue_dir).glob("*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        if datetime.fromisoformat(case["gerado_em"]) >= since and case.get("consolidacao"):
            cases.append(case)
    cases.sort(key=lambda c: c["materialidade"], reverse=True)
    lines = [f"AGENDA EXECUTIVA — semana até {now:%d/%m/%Y}: {len(cases)} caso(s) investigado(s); as {top} de maior impacto:"]
    for n, case in enumerate(cases[:top], 1):
        actions = case["consolidacao"].get("recommended_actions") or []
        lines.append(f"{n}. [{case['projeto']}] {case['titulo']} — materialidade {case['materialidade']:,.2f} — "
                     f"confiança {case['consolidacao']['confidence']:g} — revisão {case['revisao'].get('status') if case['revisao'] else 'n/a'}")
        lines += [f"   • {a['action']} (responsável: {a['owner_role']}; prazo: {a['deadline']}; KPI: {a['kpi']})" for a in actions[:3]]
        if not actions:
            lines.append("   • sem ação recomendada sustentada pela evidência: decidir se investiga mais")
    if not cases:
        lines.append("Nenhum caso investigado na semana.")
    lines.append("A decisão e a execução são suas: nada foi aprovado nem executado pelos agentes.")
    return "\n".join(lines)
