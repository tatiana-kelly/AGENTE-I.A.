"""hermes-repair-agent — executa SOMENTE correções autorizadas (matriz de permissões + registry).

Ordem de travas: ação existe → circuit breaker → autorizada no registry → risco ≤ máximo →
guarda de entrega (não duplicar envio) → idempotência declarada → rate limit → DRY_RUN.
"""
from __future__ import annotations

import glob as globmod
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable

from .models import RISK_ORDER, CheckResult, CheckStatus, Criterion, Diagnosis, now_local
from .registry import action_risk

AGENT = "hermes-repair-agent"


@dataclass
class RepairDecision:
    allowed: bool
    action: str | None
    reason: str
    live: bool = False
    outcome: str | None = None  # quando negado por trava específica (CIRCUIT_BREAKER_OPEN, RATE_LIMITED)


class RepairAgent:
    def __init__(self, settings, store, executor, guardian, clock: Callable[[], datetime] = now_local,
                 sleep: Callable[[float], None] = time.sleep):
        self.settings = settings
        self.store = store
        self.executor = executor
        self.guardian = guardian
        self.clock = clock
        self.sleep = sleep
        self._attempt_id: int | None = None

    # --------------------------------------------------------------- circuit breaker
    def circuit_open(self, automation_id: str) -> tuple[bool, str]:
        now = self.clock()
        cfg = self.settings["circuit_breaker"]
        circuit = self.store.get_circuit(automation_id)
        if circuit and circuit["state"] == "OPEN" and circuit["until"] and datetime.fromisoformat(circuit["until"]) > now:
            return True, f"circuit breaker ABERTO até {circuit['until'][:16]} ({circuit['reason']})"
        failures = self.store.count_failures(automation_id, now - timedelta(hours=cfg["window_hours"]))
        if failures >= cfg["failure_threshold"]:
            until = now + timedelta(hours=cfg["cooldown_hours"])
            reason = f"{failures} falhas em {cfg['window_hours']}h (limite {cfg['failure_threshold']})"
            self.store.set_circuit(automation_id, "OPEN", reason, until)
            self.store.audit(AGENT, "circuit_open", reason, "OPEN", automation=automation_id,
                             dry_run=self.settings.dry_run)
            return True, f"circuit breaker ABERTO: {reason} — REPEATED_FAILURE"
        if circuit and circuit["state"] == "OPEN":
            self.store.set_circuit(automation_id, "CLOSED", "cooldown expirado", None)
        return False, ""

    # --------------------------------------------------------------------- plano
    def plan(self, automation: dict[str, Any], diagnosis: Diagnosis, check: CheckResult) -> RepairDecision:
        action = diagnosis.auto_action
        if not action:
            return RepairDecision(False, None, "Nenhuma ação automática possível para esta causa")
        is_open, why = self.circuit_open(automation["id"])
        if is_open:
            return RepairDecision(False, action, why, outcome="CIRCUIT_BREAKER_OPEN")
        if check.slot:
            window = timedelta(hours=float(automation.get("repair_window_hours",
                                                          self.settings.data.get("repair_window_hours", 6))))
            age = self.clock() - datetime.fromisoformat(check.slot)
            if age > window:
                return RepairDecision(False, action, f"Janela de reparo expirada (esperado há "
                                                     f"{int(age.total_seconds() // 3600)}h, limite {window}) — "
                                                     "reexecutar agora não recupera aquela janela")
        if action not in automation.get("allowed_recovery_actions", []):
            return RepairDecision(False, action, f"Ação '{action}' não autorizada no registry desta automação")
        risk = action_risk(action)
        if risk == "high" or RISK_ORDER[risk] > RISK_ORDER[self.settings["max_repair_risk"]]:
            return RepairDecision(False, action, f"Ação '{action}' é de risco {risk} — não executada no MVP")
        if automation.get("rerun_guard") == "no_delivery" and any(
                e.passed and e.criterion == Criterion.DELIVERY_COMPLETED.value for e in check.evidence):
            return RepairDecision(False, action, "Entrega já realizada nesta janela — reexecutar duplicaria envio")
        if action in ("rerun_task", "rerun_command", "restart_task") and automation.get("idempotent") is not True:
            return RepairDecision(False, action, "Reexecução exige automação declarada idempotent=true no registry")
        now = self.clock()
        limits = self.settings["rate_limits"]
        if self.store.count_attempts(now - timedelta(hours=1)) >= limits["repairs_per_hour"]:
            return RepairDecision(False, action, "Rate limit global de reparos/hora atingido", outcome="RATE_LIMITED")
        if self.store.count_attempts(now - timedelta(days=1), automation["id"]) >= limits["repairs_per_automation_per_day"]:
            return RepairDecision(False, action, "Rate limit de reparos/dia desta automação atingido",
                                  outcome="RATE_LIMITED")
        live = self.settings.live_repairs_enabled
        return RepairDecision(True, action, "Autorizada (risco baixo, registry, idempotente)", live=live)

    # --------------------------------------------------------------- idempotência
    def already_ok(self, automation: dict[str, Any]) -> CheckResult | None:
        """Antes de agir: o estado esperado já foi atingido? Se sim, não executar de novo."""
        refresh = getattr(self.guardian.providers.get(automation["source"]), "refresh", None)
        if refresh:
            refresh()
        current = self.guardian.evaluate(automation, now=self.clock())
        return current if current.status == CheckStatus.SUCCESS.value else None

    def is_running(self, automation: dict[str, Any]) -> bool:
        if automation["source"] != "windows_task":
            return False
        return self.guardian.providers["windows_task"].get(automation["task_name"]).running

    # ----------------------------------------------------------------- execução
    def execute(self, automation: dict[str, Any], action: str, incident_id: str, attempt: int) -> tuple[bool, str]:
        attempt_id = self.store.begin_attempt(incident_id, automation["id"], attempt, action, dry_run=False)
        if attempt_id is None:
            return False, "IDEMPOTENCY: tentativa já registrada — não repetida"
        self._attempt_id = attempt_id
        if action == "rerun_task":
            ok, detail = self.executor.run_task(automation["task_name"])
        elif action == "restart_task":
            stopped, detail_stop = self.executor.stop_task(automation["task_name"])
            if stopped:
                self.sleep(2)
            ok, detail = self.executor.run_task(automation["task_name"])
            detail = f"{detail_stop}; {detail}"
        elif action == "rerun_command":
            timeout = int(automation.get("max_duration_minutes", 30)) * 60
            ok, detail = self.executor.run_command(automation["command"], automation.get("workdir"), timeout)
        elif action == "cleanup_temp":
            ok, detail = self._cleanup_temp(automation)
        else:
            ok, detail = False, f"ação {action} sem implementação"
        self.store.audit(AGENT, action, f"tentativa {attempt}", "OK" if ok else "FALHA", automation=automation["id"],
                         incident=incident_id, tool=action, validation=detail, risk_level=action_risk(action),
                         dry_run=False)
        return ok, detail

    def finish(self, result: str, validation: str) -> None:
        if getattr(self, "_attempt_id", None):
            self.store.finish_attempt(self._attempt_id, result, validation)
            self._attempt_id = None

    def _cleanup_temp(self, automation: dict[str, Any]) -> tuple[bool, str]:
        """Remove apenas arquivos temporários declarados em temp_globs, com mais de 1h."""
        removed, cutoff = 0, time.time() - 3600
        for pattern in automation.get("temp_globs", []):
            for path in globmod.glob(pattern):
                if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                    os.remove(path)
                    removed += 1
        return True, f"{removed} arquivo(s) temporário(s) removido(s)"
