"""hermes-diagnostician — descobre a causa provável com evidência. Sem evidência: UNKNOWN_CAUSE."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .knowledge import TASK_RESULT_CODES, pattern_by_code
from .models import CheckResult, Criterion, Diagnosis, IncidentType

AGENT = "hermes-diagnostician"

# Causas de processo detectadas pelo Guardião (não vêm de texto de log)
_PROCESS_CAUSES: dict[str, tuple[str, bool, str | None, str | None, float]] = {
    # code: (causa, transitória, ação humana, ação automática, confiança)
    "TASK_HUNG": ("Processo travado: excedeu a duração máxima declarada", True, None, "restart_task", 0.8),
    "TASK_OVERLAP": ("Execução anterior ainda em andamento impediu a nova janela", True, None, "restart_task", 0.75),
    "TASK_DISABLED": ("Tarefa desabilitada no Agendador, mas o registry espera execução", False,
                      "Reabilitar a tarefa no Agendador ou marcar enabled:false no registry", None, 0.95),
    "TASK_NOT_FOUND": ("Tarefa agendada não existe mais", False,
                       "Recriar a tarefa agendada ou atualizar o registry", None, 0.95),
    "TASK_NOT_TRIGGERED": ("Agendador não disparou na janela (máquina desligada/suspensa ou gatilho perdido)", True,
                           None, "rerun", 0.6),
}
_GROUPABLE = {"NETWORK_TIMEOUT", "CONNECTION_FAILED", "HTTP_5XX", "RATE_LIMITED", "AUTH_EXPIRED", "AUTH_DENIED",
              "CREDENTIAL_MISSING", "DISK_FULL", "TASK_NOT_TRIGGERED", "BROWSER_TIMEOUT", "TASK_REFUSED"}


class Diagnostician:
    def __init__(self, store):
        self.store = store

    def diagnose(self, automation: dict[str, Any], check: CheckResult, incident_id: str | None = None) -> Diagnosis:
        steps: list[dict[str, str]] = []
        evidence: list[str] = []

        def step(n: int, name: str, text: str) -> None:
            steps.append({"step": str(n), "name": name, "result": text})

        by_criterion: dict[str, list] = {}
        for e in check.evidence:
            by_criterion.setdefault(e.criterion, []).append(e)

        step(1, "estado atual", f"{check.status} / {check.incident_type}")
        started = by_criterion.get(Criterion.PROCESS_STARTED.value, [])
        step(2, "última execução", "; ".join(e.detail for e in started) or "sem evidência de processo")
        last_ok = self.store.db.execute(
            "SELECT checked_at FROM checks WHERE automation_id=? AND status='SUCCESS' ORDER BY id DESC LIMIT 1",
            (automation["id"],)).fetchone()
        last_ok_at = last_ok[0] if last_ok else None
        step(3, "última execução bem-sucedida", last_ok_at or "nenhuma registrada pelo Guardião")
        step(4, "logs", "; ".join(f"{h['code']}: {h['line']}" for h in check.cause_hits[:3]) or "sem padrão conhecido")
        finished = by_criterion.get(Criterion.PROCESS_FINISHED.value, [])
        step(5, "processo", "; ".join(e.detail for e in finished) or "n/d")
        outputs = by_criterion.get(Criterion.OUTPUT_EXISTS.value, []) + by_criterion.get(Criterion.OUTPUT_VALID.value, [])
        step(6, "arquivos", "; ".join(f"{'OK' if e.passed else 'FALHA'} {e.detail}" for e in outputs) or "n/d")
        data = by_criterion.get(Criterion.DATA_UPDATED.value, [])
        step(7, "banco", "; ".join(f"{'OK' if e.passed else 'FALHA'} {e.detail}" for e in data) or "sem check de banco")
        api = by_criterion.get(Criterion.DEPENDENCY_OK.value, [])
        api_hits = [h for h in check.cause_hits if h["code"] in ("NETWORK_TIMEOUT", "CONNECTION_FAILED", "HTTP_5XX",
                                                                  "RATE_LIMITED", "BROWSER_TIMEOUT")]
        step(8, "API", "; ".join([e.detail for e in api] + [h["line"] for h in api_hits]) or "sem evidência de API")
        auth_hits = [h for h in check.cause_hits if h["code"] in ("AUTH_EXPIRED", "AUTH_DENIED", "CREDENTIAL_MISSING")]
        step(9, "autenticação", "; ".join(h["line"] for h in auth_hits) or "sem evidência de falha de autenticação")

        script = automation.get("script")
        script_missing = bool(script) and not Path(script).exists()
        step(10, "dependências", f"script ausente: {script}" if script_missing else
             ("script presente" if script else "script não declarado"))
        recent_change = None
        if script and not script_missing and last_ok_at:
            mtime = datetime.fromtimestamp(Path(script).stat().st_mtime).astimezone()
            if mtime > datetime.fromisoformat(last_ok_at):
                recent_change = f"script alterado em {mtime:%d/%m %H:%M}, depois do último sucesso"
        step(11, "alterações recentes", recent_change or "nenhuma alteração do script após o último sucesso")

        # ------- escolha da causa (apenas com evidência)
        hint = check.cause_hint
        if check.incident_type == IncidentType.MISSED_EXECUTION.value and not hint:
            hint = "TASK_NOT_TRIGGERED"
        pattern = pattern_by_code(hint) if hint else None
        dependency = "generic"
        if script_missing:
            code, cause, transient, human, auto, conf = ("SCRIPT_MISSING", f"Script da automação não existe: {script}",
                                                         False, "Restaurar o script ou corrigir o caminho no registry",
                                                         None, 0.95)
        elif hint in _PROCESS_CAUSES:
            cause, transient, human, auto, conf = _PROCESS_CAUSES[hint]
            code = hint
            dependency = "host" if hint == "TASK_NOT_TRIGGERED" else automation["id"]
        elif pattern is not None:
            code, cause, transient, human = pattern.code, pattern.cause, pattern.transient, pattern.human_action
            auto, conf, dependency = ("rerun" if transient else None), 0.85, pattern.dependency
        elif hint and any(hint == v[0] for v in TASK_RESULT_CODES.values()):
            entry = next(v for v in TASK_RESULT_CODES.values() if v[0] == hint)
            code, cause, transient, human = entry
            auto = "rerun" if transient else None
            conf = 0.5 if code == "SCRIPT_EXIT_NONZERO" else 0.9
            dependency = automation["id"]
        else:
            code, cause, transient, human, auto, conf = ("UNKNOWN_CAUSE", "Causa não identificada com a evidência "
                                                         "disponível", False, None, "rerun", 0.2)
            dependency = automation["id"]
        if check.cause_hits:
            evidence.extend(f"[{h['code']}] {h['line']}" for h in check.cause_hits[:3])
        evidence.extend(e.detail for e in check.evidence if e.passed is False)

        history = self.store.history(automation["id"], code, exclude_id=incident_id)
        last_fix = self.store.last_resolution(automation["id"], code) or self.store.last_resolution(None, code)
        step(12, "histórico de incidentes",
             f"{len(history)} ocorrência(s) anteriores de {code}" +
             (f"; última solução: {last_fix['resolution']}" if last_fix else ""))
        if recent_change and code in ("UNKNOWN_CAUSE", "SCRIPT_EXIT_NONZERO"):
            cause += f" — possível regressão: {recent_change}"
            conf = max(conf, 0.4)

        auto_action = self._resolve_action(auto, automation)
        primary = automation.get("primary_dependency") or (automation.get("dependencies") or [dependency])[0]
        cause_key = f"{code}@{'host' if code == 'TASK_NOT_TRIGGERED' else primary}" if code in _GROUPABLE \
            else f"{code}@{automation['id']}"
        impact = automation.get("impact") or (
            "Saída esperada não disponível: " + ", ".join(automation.get("expected_outputs", [])[:3])
            if automation.get("expected_outputs") else f"Automação {automation['name']} sem resultado confirmado")
        recommended = human or (f"Executar recuperação automática: {auto_action}" if auto_action
                                else "Investigação humana: evidência insuficiente para correção automática")
        return Diagnosis(
            cause_code=code, probable_cause=cause, evidence=evidence[:8], confidence=conf, impact=impact,
            recommended_action=recommended, auto_action=auto_action if not human else None,
            risk=automation.get("risk_level", "low"), transient=transient, human_action_required=human,
            cause_key=cause_key, steps=steps, recurrence=len(history),
            last_resolution=last_fix["resolution"] if last_fix else None,
        )

    @staticmethod
    def _resolve_action(auto: str | None, automation: dict[str, Any]) -> str | None:
        if auto is None:
            return None
        source = automation["source"]
        if auto == "rerun":
            return {"windows_task": "rerun_task", "command": "rerun_command"}.get(source)
        if auto == "restart_task":
            return "restart_task" if source == "windows_task" else None
        return auto
