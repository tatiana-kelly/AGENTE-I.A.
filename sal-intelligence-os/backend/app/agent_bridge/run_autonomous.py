"""Ponto de entrada do ciclo autônomo diário — o que o agendador (n8n) chama.

    python -m app.agent_bridge.run_autonomous --project torre-controle --dry-run
    python -m app.agent_bridge.run_autonomous --project torre-controle
    python -m app.agent_bridge.run_autonomous --agenda

--dry-run: dado real lido localmente, cliente dublê — nada é enviado a provider, nada entra no livro do dia.
Sem --dry-run: exige Orchestrator no ar e os freios de config/autonomy.json (interruptor geral começa desligado).
"""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from app.agent_bridge import AgentRunClient, config_from_settings
from app.agent_bridge.autonomous import run_daily, weekly_agenda
from app.agent_bridge.autonomy import AutonomyGate, AutonomyPolicy, DailyLedger
from app.agent_bridge.contract import AgentRunResult
from app.agent_bridge.declared_evidence import load_declarations
from app.decision_router.adapters import (
    torre_apuracao,
    torre_clientes,
    torre_custos,
    torre_divergencia,
    torre_projecao,
    torre_transferencias,
)
from app.decision_router.adapters.base import TorreDataReader
from app.decision_router.policy import build_default_policy
from app.decision_router.providers import (
    InMemoryMemoryLedgerProvider,
    InMemoryPatternStatsProvider,
    InMemoryPlaybookProvider,
    InMemoryRouteStore,
    InMemorySimilarityCaseProvider,
)
from app.decision_router.router import DecisionRouter

STATE = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "sal-os"
PROJECTS = {
    "torre-controle": {
        "data_dir": r"C:\Projeto ClaudeCode\Torre-de-Controle\data",
        "modules": (torre_transferencias, torre_custos, torre_apuracao, torre_clientes, torre_divergencia, torre_projecao),
    },
}


class DryClient:
    """Simulação: responde sem IA, com a reserva que o Orchestrator informaria."""

    def run(self, request, **_):
        review = request.review_target is not None
        output = request.review_target.output.model_dump(mode="json") if review else {
            "facts": [], "calculations": [], "inferences": [], "hypotheses": [], "contradictions": [],
            "missing_data": ["simulação: nenhuma IA foi chamada"], "evidence": [e.id for e in request.evidence], "confidence": 0}
        return AgentRunResult.model_validate({
            "protocol_version": "sal.agent-run/1.0", "request_id": request.request_id, "run_id": "dry-run",
            "status": "succeeded", "agent": request.agent, "agent_version": "1.0.0",
            "agent_authority": request.agent_authority.model_dump(), "output": output,
            "output_validation": {"valid": True, "reason": "dry-run"}, "review": {"status": "APPROVED" if review else "NOT_RUN"},
            "providers": {}, "usage": [{"role": "reviewer" if review else "author", "outcome": "success",
                                        "provider": "openai" if review else "anthropic",
                                        "reserved_cost_usd": 1.0 if review else 0.4}],
            "context": {}, "created_at": "dry-run"})


def _adapters(modules) -> list:
    return [cls() for module in modules for name, cls in vars(module).items()
            if name.endswith("Adapter") and isinstance(cls, type) and hasattr(cls, "adapt") and cls.__module__ == module.__name__]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ciclo autônomo diário dos agentes (recomendam; nunca executam).")
    parser.add_argument("--project", choices=sorted(PROJECTS))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--agenda", action="store_true", help="imprime a agenda executiva da semana")
    parser.add_argument("--queue-dir", default=str(STATE / "fila-decisoes"))
    args = parser.parse_args(argv)
    if args.agenda:
        print(weekly_agenda(Path(args.queue_dir)))
        return 0
    if not args.project:
        parser.error("informe --project ou --agenda")

    project = PROJECTS[args.project]
    policy = AutonomyPolicy.load()
    if args.dry_run:  # simulação: freios ligados só para enxergar o ciclo; livro e fila temporários
        scratch = Path(tempfile.mkdtemp(prefix="sal-os-dry-"))
        policy = AutonomyPolicy(enabled=True, daily_budget_usd=policy.daily_budget_usd,
                                case_budget_usd=policy.case_budget_usd, projects={args.project: True})
        ledger, queue_dir, client = DailyLedger(scratch / "ledger.json"), scratch / "fila", DryClient()
    else:
        ledger, queue_dir = DailyLedger(STATE / "autonomy-ledger.json"), Path(args.queue_dir)
        client = AgentRunClient(config_from_settings())
    router = DecisionRouter(build_default_policy(), memory=InMemoryMemoryLedgerProvider(),
                            similarity=InMemorySimilarityCaseProvider(), pattern_stats=InMemoryPatternStatsProvider(),
                            playbooks=InMemoryPlaybookProvider(), route_store=InMemoryRouteStore())
    report = run_daily(project=args.project, reader=TorreDataReader(project["data_dir"]), adapters=_adapters(project["modules"]),
                       router=router, client=client, config=config_from_settings(), gate=AutonomyGate(policy, ledger),
                       declarations=load_declarations(), queue_dir=queue_dir)
    print(json.dumps({"modo": "dry-run" if args.dry_run else "real", "projeto": report.project, "alertas": report.alerts,
                      "investigaveis": report.investigable, "casos": report.cases, "parou": report.stopped_reason,
                      "pulados": len(report.skipped), "fila": str(queue_dir)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
