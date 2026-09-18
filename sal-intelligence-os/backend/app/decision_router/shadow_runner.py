"""Shadow mode do Decision Router: alertas reais → rotas, sem IA, sem ação e sem gravar na origem.

    python -m app.decision_router.shadow_runner --torre-data "C:\\Projeto ClaudeCode\\Torre-de-Controle\\data"

Lê as saídas da Torre em modo somente leitura, executa o Router com memória real do registro de aprendizado
e provedores vazios (não há persistência nesta fase) e grava APENAS o relatório local em
artifacts/decision-router/shadow/<run_id>/ (pasta ignorada pelo git).

"IA evitada" é estimativa pelo próprio DecisionRoute contra a linha de base do pipeline atual do SAL OS
(services/orchestrator.py chama todos os agentes da rota de domain-routing.yaml + 1 extração).
Nenhum valor em dinheiro é calculado.
"""

import argparse
import hashlib
import json
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from app.decision_router.adapters import TorreDataReader, default_torre_adapters, ledger_memory_entries
from app.decision_router.adapters.base import AdaptedAlert, AdapterOutput
from app.decision_router.adapters.torre_divergencia import SOURCE as DIVERGENCE_SOURCE
from app.decision_router.bands import classify_band
from app.decision_router.contract import UNKNOWN_CASE_TYPE, DecisionRoute
from app.decision_router.policy import RouterPolicy, build_default_policy
from app.decision_router.providers import (
    InMemoryMemoryLedgerProvider,
    InMemoryPatternStatsProvider,
    InMemoryPlaybookProvider,
    InMemoryRouteStore,
    InMemorySimilarityCaseProvider,
)
from app.decision_router.router import DecisionRouter

BACKEND_ROOT = Path(__file__).resolve().parents[2]
CONFIG_ROOT = BACKEND_ROOT.parent / "config"
DEFAULT_OUTPUT_ROOT = BACKEND_ROOT / "artifacts" / "decision-router" / "shadow"
RULE_FILES_SAL = ("priority-scoring.yaml", "domain-routing.yaml")
RULE_FILES_TORRE = ("config_investigador.json", "config_projecao.json")


@dataclass
class ShadowRun:
    run_id: str
    started_at: str
    torre_data_dir: str
    rules_version: str
    results: list[dict] = field(default_factory=list)
    adapters: list[dict] = field(default_factory=list)
    memory_notes: tuple[str, ...] = ()
    ai_calls_actual: int = 0
    external_effects: int = 0


def compute_rules_version(reader: TorreDataReader) -> str:
    digest = hashlib.sha256()
    for name in RULE_FILES_SAL:
        digest.update(name.encode())
        digest.update((CONFIG_ROOT / name).read_bytes())
    for name in RULE_FILES_TORRE:
        digest.update(name.encode())
        digest.update(reader.sha256(name).encode() if reader.exists(name) else b"missing")
    return "rules:" + digest.hexdigest()[:16]


def case_type_resolution(policy: RouterPolicy, metric_id: str) -> str:
    metric = policy.metrics.get(metric_id)
    if metric is None:
        return "UNKNOWN_NO_POLICY"
    if metric.case_type == UNKNOWN_CASE_TYPE:
        return "UNKNOWN_POLICY_PENDING"
    return "POLICY_CONFIRMED" if metric.mapping_confirmed else "POLICY_PENDING_CONFIRMATION"


def _baseline_calls(policy: RouterPolicy, metric_id: str) -> int | None:
    metric = policy.metric(metric_id)
    if metric.case_type == UNKNOWN_CASE_TYPE or metric.case_type not in policy.routing:
        return None
    return len(policy.routing[metric.case_type]) + 1


def _result_record(
    run: ShadowRun, policy: RouterPolicy, adapted: AdaptedAlert, route: DecisionRoute, replayed: bool
) -> dict:
    envelope = adapted.envelope
    metric = policy.metric(envelope.alert.metric_id)
    band = classify_band(metric, envelope)
    baseline = _baseline_calls(policy, envelope.alert.metric_id)
    # Bloqueio por qualidade e investigação pendente NÃO contam como economia: a análise só foi adiada.
    if baseline is None:
        avoided = None
        ai_outcome = "unknown_baseline"
    elif route.status == "BLOCKED_DATA":
        avoided = 0
        ai_outcome = "blocked_by_quality"
    elif route.route in {"ONE_AGENT", "MULTI_AGENT"}:
        avoided = baseline - route.estimated_ai_calls
        ai_outcome = "reduced"
    elif route.route == "INVESTIGATE_FIRST":
        avoided = 0
        ai_outcome = "deferred"
    else:
        avoided = baseline
        ai_outcome = "avoided"
    return {
        "run_id": run.run_id,
        "timestamp": run.started_at,
        "source": adapted.source,
        "source_ref": adapted.source_ref,
        "alert_id": adapted.alert_id,
        "metric_id": envelope.alert.metric_id,
        "alert_title": envelope.alert.title,
        "period": envelope.alert.period,
        "entity": f"{envelope.entity_type}:{envelope.entity_id}",
        "case_type": route.case_type,
        "case_type_resolution": case_type_resolution(policy, envelope.alert.metric_id),
        "mapping_confidence": route.mapping_confidence,
        "magnitude_band": band.label,
        "fingerprint_exact": route.fingerprints.exact,
        "pattern_key": route.fingerprints.pattern_key,
        "lineage_key": route.fingerprints.lineage_key,
        "route": route.route,
        "status": route.status,
        "route_reason": route.reason,
        "deterministic_resolution": (
            route.deterministic_resolution.model_dump(mode="json") if route.deterministic_resolution else None
        ),
        "quality": route.quality.model_dump(mode="json"),
        "priority": route.priority.model_dump(mode="json"),
        "selected_agents": [agent.agent_name for agent in route.selected_agents],
        "estimated_ai_calls": route.estimated_ai_calls,
        "baseline_ai_calls_current_pipeline": baseline,
        "estimated_ai_calls_avoided": avoided,
        "ai_outcome": ai_outcome,
        "ai_calls_actual": 0,
        "external_effects": 0,
        "requires_human_approval": route.requires_human_approval,
        "next_step": route.next_step.model_dump(mode="json"),
        "gate_trace": [f"{entry.gate}:{entry.result}" for entry in route.gate_trace],
        "gate_reasons": [entry.reason for entry in route.gate_trace],
        "evidence": [{"kind": item.kind, "ref": item.ref, "sha256": item.sha256} for item in route.evidence],
        "transformations": list(adapted.transformations),
        "adapter_notes": list(adapted.notes),
        "replayed_identical_alert": replayed,
    }


def _adapter_summary(output: AdapterOutput) -> dict:
    return {
        "source": output.source,
        "source_file": output.source_file,
        "records_read": output.records_read,
        "alerts": len(output.alerts),
        "skipped": len(output.skipped),
        "skipped_reasons": dict(Counter(item.reason for item in output.skipped)),
        "notes": list(output.notes),
    }


def run_shadow(
    torre_data_dir: Path | str,
    *,
    policy: RouterPolicy | None = None,
    run_id: str | None = None,
    started_at: datetime | None = None,
    adapters: tuple | None = None,
    similarity=None,
    pattern_stats=None,
    playbooks=None,
    route_store=None,
    on_route=None,
) -> ShadowRun:
    """Sem provedores explícitos = Fase 2 (sem memória do Router). on_route(adapted, route) recebe cada rota."""
    reader = TorreDataReader(torre_data_dir)
    policy = policy or build_default_policy()
    rules_version = compute_rules_version(reader)
    run = ShadowRun(
        run_id=run_id or uuid.uuid4().hex,
        started_at=(started_at or datetime.now(UTC)).isoformat(),
        torre_data_dir=str(Path(torre_data_dir)),
        rules_version=rules_version,
    )
    outputs = [adapter.adapt(reader, rules_version) for adapter in (adapters or default_torre_adapters())]
    run.adapters = [_adapter_summary(output) for output in outputs]

    route_memory, run.memory_notes = ledger_memory_entries(reader)
    probe = DecisionRouter(
        policy, memory=InMemoryMemoryLedgerProvider(), similarity=InMemorySimilarityCaseProvider(),
        pattern_stats=InMemoryPatternStatsProvider(), playbooks=InMemoryPlaybookProvider(),
        route_store=InMemoryRouteStore(),
    )
    memory_by_lineage = {}
    for output in outputs:
        for adapted in output.alerts:
            if adapted.source == DIVERGENCE_SOURCE and adapted.envelope.entity_id in route_memory:
                key = probe.keys_for(adapted.envelope).lineage_key
                memory_by_lineage[key] = route_memory[adapted.envelope.entity_id]

    router = DecisionRouter(
        policy,
        memory=InMemoryMemoryLedgerProvider(memory_by_lineage),
        similarity=similarity or InMemorySimilarityCaseProvider(),
        pattern_stats=pattern_stats or InMemoryPatternStatsProvider(),
        playbooks=playbooks or InMemoryPlaybookProvider(),
        route_store=route_store or InMemoryRouteStore(),
    )
    for output in outputs:
        for adapted in output.alerts:
            replays_before = router.replays
            route = router.route(adapted.envelope)
            if on_route is not None:
                on_route(adapted, route)
            run.results.append(_result_record(run, policy, adapted, route, router.replays > replays_before))
    run.ai_calls_actual = router.ai_calls_made
    return run


def summarize(run: ShadowRun) -> dict:
    results = run.results
    routes = Counter(item["route"] for item in results)
    avoided = [item["estimated_ai_calls_avoided"] for item in results if item["estimated_ai_calls_avoided"] is not None]
    unclassified = [
        {"alert_id": item["alert_id"], "case_type_resolution": item["case_type_resolution"],
         "route": item["route"], "status": item["status"], "reason": item["route_reason"]}
        for item in results
        if item["case_type_resolution"] != "POLICY_CONFIRMED" or item["status"] == "BLOCKED_DATA"
    ]
    return {
        "run_id": run.run_id,
        "timestamp": run.started_at,
        "torre_data_dir": run.torre_data_dir,
        "rules_version": run.rules_version,
        "alerts_processed": len(results),
        "routes": {name: routes.get(name, 0) for name in
                   ("NO_AGENT", "REUSE_DECISION", "ONE_AGENT", "MULTI_AGENT", "INVESTIGATE_FIRST")},
        "status": dict(Counter(item["status"] for item in results)),
        "blocked_data": sum(1 for item in results if item["status"] == "BLOCKED_DATA"),
        "escalated": sum(1 for item in results if item["status"] == "ESCALATED"),
        "case_type_unknown": sum(1 for item in results if item["case_type"] == UNKNOWN_CASE_TYPE),
        "case_type_resolution": dict(Counter(item["case_type_resolution"] for item in results)),
        "magnitude_band_missing": sum(1 for item in results if item["magnitude_band"] == "MISSING"),
        "requires_human_approval": sum(1 for item in results if item["requires_human_approval"]),
        "by_source": {source: dict(Counter(item["route"] for item in results if item["source"] == source))
                      for source in sorted({item["source"] for item in results})},
        "ai": {
            "estimated_calls_routed": sum(item["estimated_ai_calls"] for item in results),
            "baseline_calls_current_pipeline_known": sum(
                item["baseline_ai_calls_current_pipeline"] or 0 for item in results
                if item["baseline_ai_calls_current_pipeline"] is not None
            ),
            "estimated_calls_avoided": sum(avoided),
            "alerts_without_baseline": sum(1 for item in results if item["baseline_ai_calls_current_pipeline"] is None),
            "outcomes": dict(Counter(item["ai_outcome"] for item in results)),
            "basis": "contagem de chamadas pelo DecisionRoute vs pipeline atual (domain-routing + extração); sem valor em dinheiro",
        },
        "ai_calls_actual": run.ai_calls_actual,
        "external_effects": run.external_effects,
        "unclassified_or_blocked": unclassified,
        "replayed_identical_alerts": sum(1 for item in results if item["replayed_identical_alert"]),
    }


def data_quality_report(run: ShadowRun) -> dict:
    failures = defaultdict(Counter)
    for item in run.results:
        for reason in item["quality"]["reasons"]:
            failures[item["source"]][reason] += 1
    return {
        "run_id": run.run_id,
        "adapters": run.adapters,
        "memory_ledger": list(run.memory_notes),
        "quality_failures_by_source": {source: dict(counter) for source, counter in failures.items()},
        "insufficient_sources": dict(Counter(
            item["source"] for item in run.results if item["quality"]["passed"] is False
        )),
        "engine_band_mismatch": [
            {"alert_id": item["alert_id"], "router_band": item["magnitude_band"], "engine": item["adapter_notes"]}
            for item in run.results
            if item["source"] == "torre.investigador_transferencias"
            and not any(f"ocupacao={item['magnitude_band']} " in note for note in item["adapter_notes"])
        ],
    }


def agent_demand_report(run: ShadowRun) -> dict:
    by_agent = Counter()
    by_case_type = defaultdict(Counter)
    by_source = defaultdict(Counter)
    for item in run.results:
        for agent in item["selected_agents"]:
            by_agent[agent] += 1
            by_case_type[item["case_type"]][agent] += 1
            by_source[item["source"]][agent] += 1
    return {
        "run_id": run.run_id,
        "agents": dict(by_agent.most_common()),
        "by_case_type": {key: dict(value) for key, value in by_case_type.items()},
        "by_source": {key: dict(value) for key, value in by_source.items()},
        "note": "agentes que SERIAM chamados; nenhum foi chamado nesta fase",
    }


def write_report(run: ShadowRun, output_root: Path | str = DEFAULT_OUTPUT_ROOT) -> Path:
    """Única escrita do shadow mode: relatório local, fora dos sistemas de origem."""
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    ignore = root / ".gitignore"
    if not ignore.exists():
        ignore.write_text("# relatórios de shadow mode contêm dados operacionais reais: não versionar\n*\n",
                          encoding="utf-8")
    target = root / run.run_id
    target.mkdir(parents=True, exist_ok=False)
    (target / "summary.json").write_text(json.dumps(summarize(run), ensure_ascii=False, indent=2), encoding="utf-8")
    (target / "data_quality.json").write_text(
        json.dumps(data_quality_report(run), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (target / "agent_demand.json").write_text(
        json.dumps(agent_demand_report(run), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (target / "routes.jsonl").open("w", encoding="utf-8") as handle:
        for item in run.results:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Decision Router em shadow mode sobre dados reais da Torre")
    parser.add_argument("--torre-data", required=True, help="diretório data/ da Torre de Controle (somente leitura)")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_ROOT), help="pasta raiz do relatório local")
    args = parser.parse_args(argv)
    run = run_shadow(args.torre_data)
    target = write_report(run, args.output)
    summary = summarize(run)
    print(json.dumps({"report": str(target), "alerts_processed": summary["alerts_processed"],
                      "routes": summary["routes"], "blocked_data": summary["blocked_data"],
                      "ai_calls_actual": summary["ai_calls_actual"],
                      "external_effects": summary["external_effects"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
