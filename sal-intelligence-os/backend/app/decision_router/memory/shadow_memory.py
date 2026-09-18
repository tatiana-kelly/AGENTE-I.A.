"""Shadow mode com memória do Router: baseline × Router sem memória × Router com memória (real e hipotética).

    python -m app.decision_router.memory.shadow_memory --torre-data "C:\\Projeto ClaudeCode\\Torre-de-Controle\\data" \
        --mode SHADOW_SIMULATED_PERSISTENCE

- SHADOW_READ_ONLY (padrão): memória vazia (não há banco aprovado), nada é gravado.
- SHADOW_SIMULATED_PERSISTENCE: o histórico diário de transferências é roteado em ordem cronológica e gravado
  num repositório EM MEMÓRIA do processo (descartado ao final). Nenhum banco, arquivo da Torre ou sistema é alterado.

"Memória hipotética" responde: se cada caso anterior tivesse decisão aprovada, diagnóstico pronto, ação verificada ok
e aprendizado compatível, quantos alertas passariam nas condições ESTRUTURAIS de reuso? É teto, não economia.
Métrica: estimated_ai_calls_avoided (contagem de chamadas; nenhum valor financeiro).
"""

import argparse
import json
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from app.decision_router.adapters import TorreDataReader, TransferInvestigationAdapter, ledger_memory_entries
from app.decision_router.adapters.base import AdaptedAlert
from app.decision_router.adapters.torre_transferencias import DIRECTORY as TRANSFER_DIRECTORY
from app.decision_router.bands import classify_band
from app.decision_router.contract import UNKNOWN_CASE_TYPE, DecisionRoute
from app.decision_router.gates import learning_gate, reuse_failures, similarity_gate
from app.decision_router.inputs import (
    PatternStats,
    ReferenceAction,
    ReferenceCase,
    ReferenceDecision,
    ReferenceDiagnosis,
    ReferenceLearning,
)
from app.decision_router.memory.knowledge import classify_ledger_entry, classify_transfer_route
from app.decision_router.memory.providers import (
    MemoryPatternStatsProvider,
    MemoryPlaybookProvider,
    MemorySimilarityCaseProvider,
    reference_from_case,
)
from app.decision_router.memory.recorder import MemoryMode, MemoryRecorder, RepositoryRouteStore
from app.decision_router.memory.repository import CaseMemoryRepository, InMemoryCaseMemoryRepository
from app.decision_router.policy import RouterPolicy, build_default_policy
from app.decision_router.providers import InMemoryMemoryLedgerProvider
from app.decision_router.router import DecisionRouter
from app.decision_router.shadow_runner import BACKEND_ROOT, ShadowRun, compute_rules_version, run_shadow
from app.schemas.enums import DecisionOutcome, DecisionStatus, HypothesisStatus

DEFAULT_OUTPUT_ROOT = BACKEND_ROOT / "artifacts" / "decision-router" / "shadow-memory"
HYPOTHETICAL_ID = "HIPOTETICO"


class PinnedTorreReader(TorreDataReader):
    """Leitor somente leitura que fixa o arquivo "mais recente" de um diretório (replay de histórico)."""

    def __init__(self, data_dir: Path | str, pins: dict[str, str]) -> None:
        super().__init__(data_dir)
        self._pins = dict(pins)

    def latest(self, directory: str, pattern: str = "*.json") -> str | None:
        return self._pins.get(directory) or super().latest(directory, pattern)


@dataclass
class MemoryShadowRun:
    run_id: str
    started_at: str
    mode: str
    torre_data_dir: str
    without_memory: ShadowRun
    with_memory: ShadowRun
    reuse_analysis: list[dict] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)
    knowledge: dict = field(default_factory=dict)
    idempotency: dict = field(default_factory=dict)
    persistent_writes: int = 0


def hypothetical_reference(reference: ReferenceCase, missing_data: tuple[str, ...], policy: RouterPolicy) -> ReferenceCase:
    """Preenche SÓ os campos que dependem de humano; os estruturais (faixa, direção, regra, período) ficam reais."""
    return reference.model_copy(update={
        "diagnosis": ReferenceDiagnosis(
            confidence=policy.reuse.min_diagnosis_confidence,
            decision_status=DecisionStatus.READY_FOR_DECISION,
            hypothesis_statuses=(HypothesisStatus.CONFIRMED,),
            missing_data=missing_data,
        ),
        "decision": ReferenceDecision(decision_id=HYPOTHETICAL_ID, outcome=DecisionOutcome.APPROVED),
        "action": ReferenceAction(action_execution_id=HYPOTHETICAL_ID, outcome="ok", recurrence=False),
        "learning": ReferenceLearning(learning_id=HYPOTHETICAL_ID, predicted_impact=1.0, actual_impact=1.0),
    })


def analyze_reuse(policy: RouterPolicy, repository: CaseMemoryRepository, adapted: AdaptedAlert,
                  route: DecisionRoute, baseline: int | None) -> dict:
    envelope = adapted.envelope
    metric = policy.metric(envelope.alert.metric_id)
    band = classify_band(metric, envelope)
    flags = tuple(sorted(set(metric.approval_flags) | set(envelope.approval_flags)))
    gates = {entry.gate for entry in route.gate_trace}
    record = {
        "alert_id": adapted.alert_id, "source": adapted.source, "route": route.route, "status": route.status,
        "magnitude_band": band.label, "baseline_calls": baseline, "estimated_ai_calls": route.estimated_ai_calls,
        "reached_decision_gate": "decision" in gates,
    }
    case = repository.latest_by_lineage(route.fingerprints.lineage_key, envelope.evaluated_at)
    if case is None:
        return {**record, "reference": None, "real_failures": ["sem caso anterior na memória"],
                "hypothetical_failures": ["sem caso anterior na memória"], "learning_veto": False,
                "material_change": None, "hypothetical_reuse": False}
    reference = reference_from_case(case)
    similarity = similarity_gate(envelope, band, reference)
    stats_record = repository.get_pattern_stats(route.fingerprints.pattern_key)
    stats = MemoryPatternStatsProvider(repository).get(route.fingerprints.pattern_key)
    real = reuse_failures(envelope, metric, band, flags, similarity.similarity, similarity.reference, stats, policy.reuse)
    veto = learning_gate(stats).veto
    hypothetical_stats = (stats or PatternStats()).model_copy(update={
        "decisions_approved": policy.reuse.first_reuse_min_approved_decisions,
        "verified_ok": policy.reuse.first_reuse_min_verified_ok,
    })
    hypo_ref = hypothetical_reference(reference, envelope.missing_data, policy)
    hypo_similarity = similarity_gate(envelope, band, hypo_ref)
    hypothetical = reuse_failures(envelope, metric, band, flags, hypo_similarity.similarity,
                                  hypo_similarity.reference, hypothetical_stats, policy.reuse)
    eligible = "decision" in gates and not hypothetical and not veto
    return {
        **record,
        "reference": {"case_id": case.id, "period": case.period, "magnitude_band": case.magnitude_band,
                      "route": case.route, "decision_status": case.decision_status,
                      "verification_status": case.verification_status},
        "pattern_occurrences": stats_record.occurrences if stats_record else 0,
        "material_change": similarity.similarity.material_change if similarity.similarity else None,
        "material_change_reasons": list(similarity.similarity.material_change_reasons) if similarity.similarity else [],
        "real_failures": list(real),
        "hypothetical_failures": list(hypothetical),
        "learning_veto": veto,
        "hypothetical_reuse": eligible,
    }


def _baseline_index(run: ShadowRun) -> dict[str, dict]:
    return {item["alert_id"]: item for item in run.results}


def replay_transfer_history(policy: RouterPolicy, torre_data_dir: Path | str, recorder: MemoryRecorder,
                            rules_version: str) -> list[dict]:
    reader = TorreDataReader(torre_data_dir)
    folder = reader.data_dir / TRANSFER_DIRECTORY
    names = sorted(path.name for path in folder.glob("*.json")) if folder.is_dir() else []
    repository = recorder.repository
    days = []
    for name in names[:-1]:  # o último arquivo é o snapshot atual, roteado na comparação principal
        pinned = PinnedTorreReader(torre_data_dir, {TRANSFER_DIRECTORY: f"{TRANSFER_DIRECTORY}/{name}"})
        output = TransferInvestigationAdapter().adapt(pinned, rules_version)
        router = DecisionRouter(
            policy, memory=InMemoryMemoryLedgerProvider(), similarity=MemorySimilarityCaseProvider(repository),
            pattern_stats=MemoryPatternStatsProvider(repository), playbooks=MemoryPlaybookProvider(repository),
            route_store=RepositoryRouteStore(repository),
        )
        routes = Counter()
        reuse = 0
        with_reference = 0
        for adapted in output.alerts:
            route = router.route(adapted.envelope)
            if repository.latest_by_lineage(route.fingerprints.lineage_key, adapted.envelope.evaluated_at):
                with_reference += 1
            recorder.record(adapted, route)
            routes[route.route] += 1
            reuse += route.route == "REUSE_DECISION"
        days.append({"file": name, "alerts": len(output.alerts), "routes": dict(routes),
                     "with_previous_case": with_reference, "reuse_decision": reuse,
                     "ai_calls_made": router.ai_calls_made})
    return days


def knowledge_report(torre_data_dir: Path | str) -> dict:
    reader = TorreDataReader(torre_data_dir)
    entries, _ = ledger_memory_entries(reader)
    ledger = Counter()
    for entry in entries.values():
        status = classify_ledger_entry(entry)
        ledger.update(key for key, value in status.as_dict().items() if value is True)
    transfers = Counter()
    latest = reader.latest(TRANSFER_DIRECTORY)
    routes = 0
    if latest:
        document = reader.read_json(latest)
        for item in document.get("rotas") or []:
            routes += 1
            status = classify_transfer_route(item, document.get("validacoes_humanas"))
            transfers.update(key for key, value in status.as_dict().items() if value is True)
    categories = ("known", "false_positive", "cause_known", "cause_missing", "decision_known",
                  "decision_approved", "result_known")
    return {
        "ledger_routes": len(entries),
        "ledger": {key: ledger.get(key, 0) for key in categories},
        "transfer_file": latest,
        "transfer_routes": routes,
        "transfers": {key: transfers.get(key, 0) for key in categories},
        "rule": "aprendizado ≠ decisão ≠ decisão aprovada ≠ ação ≠ resultado verificado; nada foi promovido",
    }


def run_memory_shadow(
    torre_data_dir: Path | str,
    *,
    mode: MemoryMode = MemoryMode.SHADOW_READ_ONLY,
    policy: RouterPolicy | None = None,
    run_id: str | None = None,
    started_at: datetime | None = None,
    adapters: tuple | None = None,
) -> MemoryShadowRun:
    if mode is MemoryMode.PERSIST:
        raise ValueError("PERSIST não é permitido em shadow mode")
    policy = policy or build_default_policy()
    started = started_at or datetime.now(UTC)
    run_id = run_id or uuid.uuid4().hex
    reader = TorreDataReader(torre_data_dir)
    rules_version = compute_rules_version(reader)
    repository = InMemoryCaseMemoryRepository()
    recorder = MemoryRecorder(policy, repository, mode)

    history = replay_transfer_history(policy, torre_data_dir, recorder, rules_version)
    without = run_shadow(torre_data_dir, policy=policy, run_id=f"{run_id}-sem-memoria", started_at=started,
                         adapters=adapters)

    analysis: list[dict] = []
    baseline = _baseline_index(without)

    def on_route(adapted: AdaptedAlert, route: DecisionRoute) -> None:
        item = baseline.get(adapted.alert_id) or {}
        analysis.append(analyze_reuse(policy, repository, adapted, route,
                                      item.get("baseline_ai_calls_current_pipeline")))
        recorder.record(adapted, route)

    with_memory = run_shadow(
        torre_data_dir, policy=policy, run_id=f"{run_id}-com-memoria", started_at=started, adapters=adapters,
        similarity=MemorySimilarityCaseProvider(repository), pattern_stats=MemoryPatternStatsProvider(repository),
        playbooks=MemoryPlaybookProvider(repository), route_store=RepositoryRouteStore(repository),
        on_route=on_route,
    )

    inserted_first = recorder.inserted
    idempotency = {"mode": mode.value, "inserted_until_first_run": inserted_first, "reruns": []}
    if mode is MemoryMode.SHADOW_SIMULATED_PERSISTENCE:
        for attempt in (2, 3):
            before_inserted, before_dup = recorder.inserted, recorder.duplicates
            run_shadow(torre_data_dir, policy=policy, run_id=f"{run_id}-rerun-{attempt}", started_at=started,
                       adapters=adapters, similarity=MemorySimilarityCaseProvider(repository),
                       pattern_stats=MemoryPatternStatsProvider(repository),
                       playbooks=MemoryPlaybookProvider(repository), route_store=RepositoryRouteStore(repository),
                       on_route=recorder.record)
            idempotency["reruns"].append({"run": attempt, "inserted": recorder.inserted - before_inserted,
                                          "duplicates_ignored": recorder.duplicates - before_dup})
    idempotency["cases_in_memory"] = len(repository.all_cases())

    return MemoryShadowRun(
        run_id=run_id, started_at=started.isoformat(), mode=mode.value, torre_data_dir=str(Path(torre_data_dir)),
        without_memory=without, with_memory=with_memory, reuse_analysis=analysis, history=history,
        knowledge=knowledge_report(torre_data_dir), idempotency=idempotency, persistent_writes=0,
    )


def _avoided(run: ShadowRun) -> int:
    return sum(item["estimated_ai_calls_avoided"] or 0 for item in run.results)


def economy_report(run: MemoryShadowRun) -> dict:
    without, with_memory = run.without_memory.results, run.with_memory.results
    analysis = run.reuse_analysis
    with_reference = [item for item in analysis if item["reference"] is not None]
    reached = [item for item in with_reference if item["reached_decision_gate"]]

    def blocked_by(fragment: str) -> int:
        return sum(1 for item in reached if any(fragment in failure for failure in item["real_failures"]))

    hypothetical = [item for item in analysis if item["hypothetical_reuse"]]
    hypothetical_blockers = Counter(
        failure.split(" (")[0] for item in reached if not item["hypothetical_reuse"] for failure in item["hypothetical_failures"]
    )
    return {
        "run_id": run.run_id,
        "timestamp": run.started_at,
        "memory_mode": run.mode,
        "persistent_writes": run.persistent_writes,
        "ai_calls_actual": run.without_memory.ai_calls_actual + run.with_memory.ai_calls_actual,
        "alerts_processed": len(with_memory),
        "baseline_calls": sum(item["baseline_ai_calls_current_pipeline"] or 0 for item in without
                              if item["baseline_ai_calls_current_pipeline"] is not None),
        "alerts_without_baseline": sum(1 for item in without if item["baseline_ai_calls_current_pipeline"] is None),
        "router_without_memory_calls": sum(item["estimated_ai_calls"] for item in without),
        "router_with_memory_calls": sum(item["estimated_ai_calls"] for item in with_memory),
        "estimated_ai_calls_avoided_by_routing": _avoided(run.without_memory),
        "estimated_ai_calls_avoided_by_memory": _avoided(run.with_memory) - _avoided(run.without_memory),
        "reuse_candidates": sum(1 for item in with_memory if item["route"] == "REUSE_DECISION"),
        "alerts_with_previous_case": len(with_reference),
        "alerts_with_previous_case_reaching_decision_gate": len(reached),
        "reuse_blocked_by_material_change": blocked_by("material_change"),
        "reuse_blocked_by_missing_band": blocked_by("magnitude_band MISSING"),
        "reuse_blocked_by_no_approval": blocked_by("decisão anterior não aprovada"),
        "reuse_blocked_by_learning": sum(1 for item in reached if item["learning_veto"]),
        "unknown_cases": sum(1 for item in with_memory if item["case_type"] == UNKNOWN_CASE_TYPE),
        "policy_not_confirmed_cases": sum(1 for item in with_memory
                                          if item["case_type_resolution"] != "POLICY_CONFIRMED"),
        "blocked_quality": sum(1 for item in with_memory if item["status"] == "BLOCKED_DATA"),
        "routes_without_memory": dict(Counter(item["route"] for item in without)),
        "routes_with_memory": dict(Counter(item["route"] for item in with_memory)),
        "hypothetical_memory": {
            "label": "HIPOTÉTICO — supõe decisão aprovada + ação verificada ok em todo caso anterior; NÃO é economia",
            "structurally_reusable_alerts": len(hypothetical),
            "calls_that_would_be_avoided_upper_bound": sum(item["baseline_calls"] or 0 for item in hypothetical),
            "blockers_even_with_approval": dict(hypothetical_blockers.most_common()),
            "reuse_policy": "default (1 decisão aprovada; B7 não aplicada)",
        },
        "history_replay": {
            "days": len(run.history),
            "alerts": sum(day["alerts"] for day in run.history),
            "reuse_decision": sum(day["reuse_decision"] for day in run.history),
            "ai_calls_made": sum(day["ai_calls_made"] for day in run.history),
        },
        "knowledge": run.knowledge,
        "idempotency": run.idempotency,
        "basis": "contagem de chamadas estimadas pelo DecisionRoute; nenhum valor financeiro",
    }


def write_memory_report(run: MemoryShadowRun, output_root: Path | str = DEFAULT_OUTPUT_ROOT) -> Path:
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    ignore = root / ".gitignore"
    if not ignore.exists():
        ignore.write_text("# relatórios de shadow mode contêm dados operacionais reais: não versionar\n*\n",
                          encoding="utf-8")
    target = root / run.run_id
    target.mkdir(parents=True, exist_ok=False)
    (target / "economy.json").write_text(json.dumps(economy_report(run), ensure_ascii=False, indent=2),
                                         encoding="utf-8")
    (target / "history.json").write_text(json.dumps(run.history, ensure_ascii=False, indent=2), encoding="utf-8")
    with (target / "reuse_analysis.jsonl").open("w", encoding="utf-8") as handle:
        for item in run.reuse_analysis:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Decision Router com memória em shadow mode")
    parser.add_argument("--torre-data", required=True)
    parser.add_argument("--mode", default=MemoryMode.SHADOW_READ_ONLY.value,
                        choices=[MemoryMode.SHADOW_READ_ONLY.value, MemoryMode.SHADOW_SIMULATED_PERSISTENCE.value])
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_ROOT))
    args = parser.parse_args(argv)
    run = run_memory_shadow(args.torre_data, mode=MemoryMode(args.mode))
    target = write_memory_report(run, args.output)
    report = economy_report(run)
    report.pop("knowledge")
    print(json.dumps({"report": str(target), **report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
