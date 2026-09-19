"""Freios do modo autônomo (decisão da Tatiana, 2026-09-19).

Os agentes podem investigar sozinhos, mas só dentro destes freios, verificados ANTES de cada caso:
- interruptor geral (`enabled`) — começa desligado; ligar é a ativação, que exige aprovação;
- interruptor por projeto — projeto só entra depois do contexto validado pela Tatiana;
- teto diário somando todos os projetos (US$ 10/dia) — o orçamento do caso nunca passa do que resta no dia;
- teto por caso (US$ 3,50), o mesmo de `multi_agent.CASE_BUDGET_USD`.

O dia é o do horário de Brasília (UTC−3, sem horário de verão desde 2019). A contabilidade usa a RESERVA
informada pelo Orchestrator (teto conservador), nunca o custo real — que os providers não informam.
"""

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from app.agent_bridge.multi_agent import CASE_BUDGET_USD

BRASILIA = timezone(timedelta(hours=-3))
DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[3] / "config" / "autonomy.json"
DEFAULT_LEDGER_PATH = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "sal-os" / "autonomy-ledger.json"


class AutonomyBlocked(RuntimeError):
    """O caso NÃO pode rodar agora: nenhum provider é chamado."""


@dataclass(frozen=True)
class AutonomyPolicy:
    enabled: bool
    daily_budget_usd: float
    case_budget_usd: float = CASE_BUDGET_USD
    projects: dict[str, bool] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path = DEFAULT_POLICY_PATH) -> "AutonomyPolicy":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(enabled=bool(raw["enabled"]), daily_budget_usd=float(raw["daily_budget_usd"]),
                   case_budget_usd=min(float(raw.get("case_budget_usd", CASE_BUDGET_USD)), CASE_BUDGET_USD),
                   projects={str(k): bool(v) for k, v in raw.get("projects", {}).items()})


class DailyLedger:
    """Reserva acumulada por dia (arquivo JSON local). Só cresce no dia; nunca apaga dias anteriores."""

    def __init__(self, path: Path = DEFAULT_LEDGER_PATH, clock=lambda: datetime.now(UTC)) -> None:
        self._path = Path(path)
        self._clock = clock

    def today(self) -> str:
        return self._clock().astimezone(BRASILIA).date().isoformat()

    def _read(self) -> dict:
        if not self._path.exists():
            return {}
        return json.loads(self._path.read_text(encoding="utf-8"))

    def spent(self, day: str | None = None) -> float:
        return round(float(self._read().get(day or self.today(), {}).get("reserved_usd", 0.0)), 6)

    def record(self, *, project: str, case_id: str, reserved_usd: float) -> float:
        data = self._read()
        day = data.setdefault(self.today(), {"reserved_usd": 0.0, "cases": []})
        day["reserved_usd"] = round(day["reserved_usd"] + max(0.0, float(reserved_usd)), 6)
        day["cases"].append({"project": project, "case_id": case_id, "reserved_usd": round(float(reserved_usd), 6),
                             "at": self._clock().isoformat()})
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._path)  # troca atômica: um caso interrompido nunca deixa o livro pela metade
        return day["reserved_usd"]


class AutonomyGate:
    def __init__(self, policy: AutonomyPolicy, ledger: DailyLedger) -> None:
        self.policy = policy
        self.ledger = ledger

    def case_budget(self, project: str) -> float:
        """Orçamento deste caso agora, ou AutonomyBlocked com o motivo. Nunca maior que o que resta no dia."""
        if not self.policy.enabled:
            raise AutonomyBlocked("modo autônomo desligado (interruptor geral)")
        if not self.policy.projects.get(project, False):
            raise AutonomyBlocked(f"projeto {project} desligado ou não cadastrado no modo autônomo")
        remaining = round(self.policy.daily_budget_usd - self.ledger.spent(), 6)
        if remaining <= 0:
            raise AutonomyBlocked(f"teto diário de US$ {self.policy.daily_budget_usd:g} atingido em {self.ledger.today()}")
        return min(self.policy.case_budget_usd, remaining)

    def record(self, *, project: str, case_id: str, reserved_usd: float) -> float:
        return self.ledger.record(project=project, case_id=case_id, reserved_usd=reserved_usd)
