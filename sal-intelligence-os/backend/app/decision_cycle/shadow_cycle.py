"""Simulação do ciclo governado sobre os alertas reais — sem IA, sem ação, sem aprovação inventada.

    python -m app.decision_cycle.shadow_cycle --torre-data "C:\\Projeto ClaudeCode\\Torre-de-Controle\\data"

Para cada alerta: rota (Fase 1/2) → estado do ciclo → o que falta para virar proposta. Nenhuma proposta é
criada sem diagnóstico real, nenhuma aprovação é simulada e nenhuma ação é sugerida como executada.
"""

import argparse
import json
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from app.decision_cycle.governance import HUMAN_MUST, MACHINE_MAY, MACHINE_MUST_NOT
from app.decision_cycle.states import CaseState
from app.decision_router.contract import UNKNOWN_CASE_TYPE
from app.decision_router.policy import RouterPolicy
from app.decision_router.shadow_runner import BACKEND_ROOT, run_shadow

DEFAULT_OUTPUT_ROOT = BACKEND_ROOT / "artifacts" / "decision-cycle-shadow"

#: O que falta, hoje, para o caso chegar a uma proposta de decisão.
BLOCKER_BY_STATE = {
    CaseState.GATED: "dados insuficientes: coletar evidência antes de investigar",
    CaseState.INVESTIGATING: "falta diagnóstico (exige investigação por agentes — não habilitada nesta fase)",
    CaseState.ESCALATED: "decisão humana de escalonamento",
    CaseState.CLOSED: "nenhum: caso encerrado deterministicamente",
    CaseState.PROPOSED: "nenhum: já há base para propor",
}


@dataclass
class CycleShadowRun:
    run_id: str
    started_at: str
    torre_data_dir: str
    cases: list[dict] = field(default_factory=list)
    ai_calls: int = 0
    actions_executed: int = 0
    approvals: int = 0
    notifications: int = 0


def _case_record(item: dict, state: CaseState) -> dict:
    needs_investigation = state is CaseState.INVESTIGATING
    return {
        "case_id": item["alert_id"],
        "source": item["source"],
        "metric_id": item["metric_id"],
        "case_type": item["case_type"],
        "route": item["route"],
        "router_status": item["status"],
        "state": state.value,
        "blocker_to_proposal": BLOCKER_BY_STATE.get(state, "indefinido"),
        "can_propose_now": state is CaseState.PROPOSED,
        "would_need_diagnosis": needs_investigation,
        "agents_that_would_investigate": item["selected_agents"],
        "estimated_ai_calls_if_enabled": item["estimated_ai_calls"],
        "requires_human_approval": item["requires_human_approval"],
        "proposal_created": False,
        "approved": False,
        "action_linked": False,
        "action_executed": False,
        "verification_verdict": None,
        "learning_recorded": False,
    }


def run_cycle_shadow(torre_data_dir: Path | str, *, policy: RouterPolicy | None = None,
                     run_id: str | None = None, started_at: datetime | None = None) -> CycleShadowRun:
    started = started_at or datetime.now(UTC)
    shadow = run_shadow(torre_data_dir, policy=policy, run_id=f"{run_id or 'cycle'}-routes", started_at=started)
    run = CycleShadowRun(run_id=run_id or uuid.uuid4().hex, started_at=started.isoformat(),
                         torre_data_dir=str(Path(torre_data_dir)), ai_calls=shadow.ai_calls_actual)
    for item in shadow.results:
        state = CaseState.GATED if item["status"] == "BLOCKED_DATA" else (
            CaseState.ESCALATED if item["status"] == "ESCALATED" else (
                CaseState.PROPOSED if item["route"] == "REUSE_DECISION" else CaseState.INVESTIGATING))
        run.cases.append(_case_record(item, state))
    return run


def cycle_report(run: CycleShadowRun) -> dict:
    cases = run.cases
    states = Counter(item["state"] for item in cases)
    investigating = [item for item in cases if item["state"] == CaseState.INVESTIGATING.value]
    return {
        "run_id": run.run_id,
        "timestamp": run.started_at,
        "cases_received": len(cases),
        "states": dict(states),
        "cases_blocked_by_data": states.get(CaseState.GATED.value, 0),
        "cases_that_could_generate_proposal_now": sum(1 for item in cases if item["can_propose_now"]),
        "cases_waiting_human_approval": sum(1 for item in cases if item["state"]
                                            == CaseState.WAITING_HUMAN_APPROVAL.value),
        "cases_needing_investigation_first": len(investigating),
        "actions_that_would_be_suggested": 0,
        "verifications_that_would_be_needed": 0,
        "cases_that_could_learn_in_the_future": len(investigating),
        "unknown_case_types": sum(1 for item in cases if item["case_type"] == UNKNOWN_CASE_TYPE),
        "blockers": dict(Counter(item["blocker_to_proposal"] for item in cases)),
        "estimated_ai_calls_if_investigation_enabled": sum(item["estimated_ai_calls_if_enabled"] for item in cases),
        "governance": {
            "machine_may": list(MACHINE_MAY),
            "human_must": list(HUMAN_MUST),
            "machine_must_not": list(MACHINE_MUST_NOT),
        },
        "effects": {
            "ai_calls": run.ai_calls,
            "proposals_created": sum(1 for item in cases if item["proposal_created"]),
            "approvals": run.approvals,
            "actions_linked": sum(1 for item in cases if item["action_linked"]),
            "actions_executed": run.actions_executed,
            "verifications": sum(1 for item in cases if item["verification_verdict"] is not None),
            "learnings": sum(1 for item in cases if item["learning_recorded"]),
            "notifications": run.notifications,
        },
        "note": ("nenhuma proposta, aprovação, ação, verificação ou aprendizado foi criado: "
                 "diagnóstico exige investigação por agentes, que não é executada nesta fase"),
    }


def write_cycle_report(run: CycleShadowRun, output_root: Path | str = DEFAULT_OUTPUT_ROOT) -> Path:
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    ignore = root / ".gitignore"
    if not ignore.exists():
        ignore.write_text("# relatórios de shadow contêm dados operacionais reais: não versionar\n*\n",
                          encoding="utf-8")
    target = root / run.run_id
    target.mkdir(parents=True, exist_ok=False)
    (target / "summary.json").write_text(json.dumps(cycle_report(run), ensure_ascii=False, indent=2),
                                         encoding="utf-8")
    with (target / "cases.jsonl").open("w", encoding="utf-8") as handle:
        for item in run.cases:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ciclo de decisão governado em shadow mode")
    parser.add_argument("--torre-data", required=True)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_ROOT))
    args = parser.parse_args(argv)
    run = run_cycle_shadow(args.torre_data)
    target = write_cycle_report(run, args.output)
    report = cycle_report(run)
    report.pop("governance")
    print(json.dumps({"report": str(target), **report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
