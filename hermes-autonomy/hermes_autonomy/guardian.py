"""hermes-guardian — SUPERVISÃO. Compara EXPECTED (registry) vs ACTUAL (evidências). Nunca altera nada."""
from __future__ import annotations

import glob as globmod
import json
import os
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from .adapters import HttpGet, TaskInfo, default_http_get
from .knowledge import describe_task_result, match_causes
from .models import CheckResult, CheckStatus, Criterion, Evidence, IncidentType, iso, now_local
from .redact import redact
from .timeutil import last_slot, render_path

AGENT = "hermes-guardian"
START_TOLERANCE = timedelta(minutes=2)

_MISSING_CRITERION = {
    "output": Criterion.OUTPUT_EXISTS.value,
    "data": Criterion.DATA_UPDATED.value,
    "delivery": Criterion.DELIVERY_COMPLETED.value,
    "dependency": Criterion.DEPENDENCY_OK.value,
}
_CONTENT_CRITERION = {
    "log": Criterion.PROCESS_FINISHED.value,
    "output": Criterion.OUTPUT_VALID.value,
    "data": Criterion.DATA_UPDATED.value,
    "delivery": Criterion.DELIVERY_COMPLETED.value,
    "dependency": Criterion.DEPENDENCY_OK.value,
}
_TS_PATTERNS = [
    (re.compile(r"^\s*\[?(\d{4}-\d{2}-\d{2})[ T](\d{1,2}:\d{2}:\d{2})"), "%Y-%m-%d %H:%M:%S"),
    (re.compile(r"^\s*\[?(\d{2}/\d{2}/\d{4})\s+(\d{1,2}:\d{2}:\d{2})"), "%d/%m/%Y %H:%M:%S"),
]
_SPECIFIC_TYPES = {
    IncidentType.AUTHENTICATION_FAILURE.value, IncidentType.API_FAILURE.value,
    IncidentType.DEPENDENCY_FAILURE.value, IncidentType.RESOURCE_FAILURE.value,
}


def _line_time(line: str, fallback_day: datetime) -> datetime | None:
    for regex, fmt in _TS_PATTERNS:
        m = regex.match(line)
        if m:
            try:
                return datetime.strptime(f"{m.group(1)} {m.group(2)}", fmt).replace(tzinfo=fallback_day.tzinfo)
            except ValueError:
                return None
    m = re.match(r"^\s*\[(\d{2}:\d{2}:\d{2})\]", line)
    if m:
        h, mi, s = (int(x) for x in m.group(1).split(":"))
        return fallback_day.replace(hour=h, minute=mi, second=s)
    return None


_TS_ANYWHERE = re.compile(r"(\d{2}/\d{2}/\d{4})\s+(\d{1,2}:\d{2}:\d{2})")


def since_run_segment(text: str, run_start: datetime) -> str:
    """Mantém só as linhas do log cumulativo que pertencem à execução iniciada em `run_start`.

    Dois estilos de log:
      - carimbo no INÍCIO da linha (``2026-09-18 06:30:02 ...``): cada linha datada abre o trecho;
      - carimbo de FIM no meio da linha (``Fim 18/09/2026 10:26:02``): fecha o bloco — as linhas
        sem data antes dele pertencem à execução que ele encerra.
    """
    keep: list[str] = []
    buffer: list[str] = []
    include, last_kind = False, None
    threshold = run_start - START_TOLERANCE
    for line in text.splitlines():
        ts = _line_time(line, run_start)
        if ts is not None:
            include, last_kind, buffer = ts >= threshold, "start", []
            if include:
                keep.append(line)
            continue
        m = _TS_ANYWHERE.search(line)
        if m:
            try:
                end = datetime.strptime(f"{m.group(1)} {m.group(2)}", "%d/%m/%Y %H:%M:%S").replace(
                    tzinfo=run_start.tzinfo)
            except ValueError:
                end = None
            if end is not None:
                if end >= threshold:
                    keep.extend(buffer)
                    keep.append(line)
                include, last_kind, buffer = end >= threshold, "end", []
                continue
        if include:
            keep.append(line)
        elif last_kind in (None, "end"):
            buffer.append(line)  # linhas depois de um carimbo de FIM antigo pertencem à próxima execução
    if last_kind == "end":
        keep.extend(buffer)  # execução mais recente ainda sem carimbo de fim (em andamento ou abortada)
    return "\n".join(keep)


def last_block_segment(text: str, block_end: str) -> str:
    """Logs cumulativos SEM data: cada execução termina com o marcador `block_end`.
    Se há texto depois do último marcador, a execução mais recente não terminou → é ela que vale."""
    ends = list(re.finditer(block_end, text, re.MULTILINE))
    if not ends:
        return text
    trailing = text[ends[-1].end():]
    if trailing.strip():
        return trailing
    start = ends[-2].end() if len(ends) >= 2 else 0
    return text[start:]


class Guardian:
    def __init__(self, settings, providers: dict[str, Any], http_get: HttpGet | None = None,
                 clock: Callable[[], datetime] = now_local):
        self.settings = settings
        self.providers = providers
        self.http_get = http_get or default_http_get
        self.clock = clock
        self.http_calls = 0

    # ------------------------------------------------------------------ API
    def snapshot(self, automation: dict[str, Any], when: datetime) -> dict[str, tuple[int, float]]:
        """Baseline (tamanho, mtime) dos arquivos verificados — usado pelo Validador para ler SÓ o que a
        reexecução escreveu (offset) e exigir que o arquivo tenha mudado de fato."""
        baseline: dict[str, tuple[int, float]] = {}
        for check in automation.get("checks", []):
            if check.get("type") != "file":
                continue
            path = self._resolve_path(check, automation, when)
            if path is not None and path.exists():
                stat = path.stat()
                baseline[str(path)] = (stat.st_size, stat.st_mtime)
        return baseline

    def evaluate(self, automation: dict[str, Any], now: datetime | None = None,
                 run_after: datetime | None = None,
                 baseline: dict[str, tuple[int, float]] | None = None) -> CheckResult:
        now = now or self.clock()
        result = CheckResult(automation_id=automation["id"], status=CheckStatus.SUCCESS.value, checked_at=iso(now))
        if not automation.get("enabled", True):
            result.status = CheckStatus.DISABLED.value
            return result

        defaults = self.settings["defaults"]
        grace = timedelta(minutes=automation.get("grace_minutes", defaults["grace_minutes"]))
        if run_after is not None:
            slot = run_after
        else:
            slot = last_slot(automation.get("schedule"), now - grace)
            upcoming = last_slot(automation.get("schedule"), now)
            if upcoming and slot and upcoming > slot:
                result.findings.append(f"Janela {upcoming:%d/%m %H:%M} ainda dentro da tolerância ({grace}).")
        if slot is None:
            result.status = CheckStatus.NOT_SCHEDULED.value
            return result
        result.slot = iso(slot)

        ctx: dict[str, Any] = {"texts": [], "run_start": slot, "hung": False, "missed": False, "exit_failed": False,
                               "baseline": baseline or {}}
        task = self._task_evidence(automation, slot, now, result, ctx)
        if result.status == CheckStatus.PENDING.value:
            return result
        if not ctx["missed"]:
            for check in automation.get("checks", []):
                self._run_check(check, automation, slot, ctx["run_start"], result, ctx)
        result.run_started_at = None if ctx["missed"] else iso(ctx["run_start"])
        self._classify(result, ctx)
        return result

    # ------------------------------------------------------------ processo
    def _task_evidence(self, automation, slot, now, result, ctx) -> TaskInfo | None:
        source = automation["source"]
        if source == "command":
            return None
        key = automation.get("task_name") or automation.get("github", "")
        task: TaskInfo = self.providers[source].get(key)
        defaults = self.settings["defaults"]
        max_duration = timedelta(minutes=automation.get("max_duration_minutes", defaults["max_duration_minutes"]))
        delay_tol = timedelta(minutes=automation.get("delay_tolerance_minutes", defaults["delay_tolerance_minutes"]))
        src = "task_scheduler" if source == "windows_task" else source

        if not task.exists:
            result.evidence.append(Evidence(Criterion.PROCESS_STARTED.value, False, src,
                                            f"Tarefa '{key}' não existe no agendador"))
            ctx.update(missed=True, hint="TASK_NOT_FOUND")
            return task
        if task.extra.get("unverifiable"):
            result.evidence.append(Evidence(Criterion.PROCESS_STARTED.value, None, src,
                                            f"Não verificável: {task.extra['unverifiable']}"))
            return task
        if task.state == "Disabled":
            result.evidence.append(Evidence(Criterion.PROCESS_STARTED.value, False, src,
                                            "Tarefa desabilitada no agendador, mas o registry espera execução"))
            ctx.update(missed=True, hint="TASK_DISABLED")
            return task

        started = task.last_run is not None and task.last_run >= slot - START_TOLERANCE
        if not started:
            last = f"{task.last_run:%d/%m %H:%M}" if task.last_run else "nunca"
            detail = f"Esperado às {slot:%d/%m %H:%M}; última execução registrada: {last}"
            if task.running and task.last_run:
                detail += f" (execução anterior ainda rodando há {int((now - task.last_run).total_seconds() // 60)} min)"
                ctx["hint"] = "TASK_OVERLAP"
            result.evidence.append(Evidence(Criterion.PROCESS_STARTED.value, False, src, detail))
            ctx["missed"] = True
            return task

        ctx["run_start"] = task.last_run
        result.evidence.append(Evidence(Criterion.PROCESS_STARTED.value, True, src,
                                        f"Iniciou às {task.last_run:%d/%m %H:%M:%S}"))
        delay = task.last_run - slot
        result.evidence.append(Evidence(Criterion.ON_TIME.value, delay <= delay_tol, src,
                                        f"Atraso de {int(delay.total_seconds() // 60)} min (tolerância {delay_tol})"))
        if task.running:
            elapsed = now - task.last_run
            if elapsed > max_duration:
                result.evidence.append(Evidence(Criterion.PROCESS_FINISHED.value, False, src,
                                                f"Ainda rodando há {int(elapsed.total_seconds() // 60)} min "
                                                f"(limite {max_duration})"))
                ctx.update(hung=True, hint="TASK_HUNG")
            else:
                result.status = CheckStatus.PENDING.value
                result.findings.append(f"Em execução há {int(elapsed.total_seconds() // 60)} min (limite {max_duration}).")
            return task
        if task.last_result == 0 or (task.last_result is None and source != "github_actions"):
            result.evidence.append(Evidence(Criterion.PROCESS_FINISHED.value, True, src,
                                            f"Terminou com código {task.last_result}"))
        else:
            code, desc, _, _ = describe_task_result(task.last_result)
            extra = f" ({task.extra.get('conclusion')})" if task.extra.get("conclusion") else ""
            result.evidence.append(Evidence(Criterion.PROCESS_FINISHED.value, False, src, desc + extra,
                                            {"code": task.last_result}))
            ctx["texts"].append(desc)
            ctx.update(exit_failed=True, hint=code)
        return task

    # --------------------------------------------------------------- checks
    def _run_check(self, check, automation, slot, run_start, result, ctx) -> None:
        kind = check.get("kind", "output")
        ctype = check["type"]
        try:
            if ctype == "file":
                self._check_file(check, kind, automation, slot, run_start, result, ctx)
            elif ctype in ("http_status", "http_freshness"):
                self._check_http(check, kind, run_start, result, ctx)
            elif ctype == "command":
                self._check_command(check, kind, result, ctx)
        except Exception as exc:  # evidência indisponível não é sucesso nem falha
            result.evidence.append(Evidence(_CONTENT_CRITERION.get(kind, "OUTPUT_VALID"), None, ctype,
                                            f"Erro ao coletar evidência: {type(exc).__name__}: {redact(str(exc))[:200]}"))

    def _resolve_path(self, check, automation, slot) -> Path | None:
        variables = automation.get("vars", {})
        if check.get("glob"):
            pattern = render_path(check["glob"], slot, variables)
            matches = [Path(p) for p in globmod.glob(pattern)]
            return max(matches, key=lambda p: p.stat().st_mtime) if matches else None
        return Path(render_path(check["path"], slot, variables))

    def _check_file(self, check, kind, automation, slot, run_start, result, ctx) -> None:
        label = check.get("label") or kind
        path = self._resolve_path(check, automation, slot)
        missing_criterion = (Criterion.PROCESS_STARTED.value if automation["source"] == "command"
                             else Criterion.PROCESS_FINISHED.value) if kind == "log" else _MISSING_CRITERION[kind]
        if path is None or not path.exists():
            shown = path or check.get("glob")
            result.evidence.append(Evidence(missing_criterion, False, "filesystem",
                                            f"{label}: arquivo não encontrado ({shown})", {"missing": True}))
            return
        stat = path.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime).astimezone()
        base = ctx["baseline"].get(str(path))
        if base:  # validação pós-reparo: o arquivo precisa ter mudado desde o baseline
            stale = stat.st_mtime <= base[1] and stat.st_size == base[0]
        else:
            stale = mtime < run_start - START_TOLERANCE
        if check.get("fresh", True) and stale:
            result.evidence.append(Evidence(missing_criterion, False, "filesystem",
                                            f"{label}: {path.name} não foi atualizado nesta execução "
                                            f"(modificado {mtime:%d/%m %H:%M})", {"stale": True, "missing": True}))
            return
        # Existência/atualização só é evidência positiva quando não há marcador de conteúdo decidindo
        # (ex.: "entrega" lida do mesmo log: o arquivo existir não prova que o e-mail saiu).
        if kind in ("log", "output") or not check.get("success_patterns"):
            exists_criterion = Criterion.PROCESS_STARTED.value if kind == "log" else missing_criterion
            result.evidence.append(Evidence(exists_criterion, True, "filesystem",
                                            f"{label}: {path.name} atualizado {mtime:%d/%m %H:%M}"))
        if stat.st_size < int(check.get("min_bytes", 0)):
            result.evidence.append(Evidence(_CONTENT_CRITERION[kind], False, "filesystem",
                                            f"{label}: {stat.st_size} bytes < mínimo {check['min_bytes']}"))
        needs_text = check.get("success_patterns") or check.get("failure_patterns") or check.get("json_valid")
        if not needs_text:
            return
        text = self._read_segment(path, check, run_start, base[0] if base else None)
        if check.get("json_valid"):
            try:
                json.loads(path.read_text(encoding="utf-8"))
                result.evidence.append(Evidence("OUTPUT_VALID", True, "filesystem", f"{label}: JSON válido"))
            except ValueError as exc:
                result.evidence.append(Evidence("OUTPUT_VALID", False, "filesystem", f"{label}: JSON inválido ({exc})"))
        self._apply_patterns(check, kind, label, text, result, ctx)

    def _read_segment(self, path: Path, check, run_start, offset: int | None = None) -> str:
        tail = int(check.get("tail_bytes", 262_144))
        with open(path, "rb") as handle:
            size = os.fstat(handle.fileno()).st_size
            appended_only = offset is not None and size >= offset and check.get("segment") in ("since_run",
                                                                                                "last_block")
            handle.seek(offset if appended_only else max(0, size - tail))
            text = handle.read().decode("utf-8", errors="replace")
        if appended_only:
            return text  # só o que a reexecução escreveu — delimitação exata
        if check.get("segment") == "since_run":
            text = since_run_segment(text, run_start)
        elif check.get("segment") == "last_block":
            text = last_block_segment(text, check["block_end"])
        return text

    def _apply_patterns(self, check, kind, label, text, result, ctx) -> None:
        criterion = _CONTENT_CRITERION[kind]
        failures = []
        for pattern in check.get("failure_patterns", []):
            m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if m:
                line_start = text.rfind("\n", 0, m.start()) + 1
                line_end = text.find("\n", m.end())
                failures.append(text[line_start:line_end if line_end != -1 else None].strip()[:240])
        if failures:
            result.evidence.append(Evidence(criterion, False, "log",
                                            f"{label}: erro registrado — {redact(failures[0])}", {"lines": failures}))
            ctx["texts"].append(text)
        success = check.get("success_patterns", [])
        if success:
            missing = [p for p in success if not re.search(p, text, re.IGNORECASE | re.MULTILINE)]
            if missing:
                result.evidence.append(Evidence(criterion, False, "log",
                                                f"{label}: marcador de sucesso ausente ({missing[0]})"))
                ctx["texts"].append(text)
            elif not failures:
                result.evidence.append(Evidence(criterion, True, "log", f"{label}: marcador de sucesso presente"))

    def _limit_http(self) -> bool:
        self.http_calls += 1
        return self.http_calls > int(self.settings["rate_limits"]["http_calls_per_run"])

    def _render_headers(self, check, run_start) -> tuple[dict[str, str], list[str]]:
        headers, missing = {}, []
        for key, value in (check.get("headers") or {}).items():
            for env in re.findall(r"\{env:([A-Z0-9_]+)\}", value):
                if not os.environ.get(env):
                    missing.append(env)
            headers[key] = render_path(value, run_start)
        return headers, missing

    def _check_http(self, check, kind, run_start, result, ctx) -> None:
        criterion = _CONTENT_CRITERION.get(kind, Criterion.DEPENDENCY_OK.value)
        url = render_path(check["url"], run_start)
        headers, missing_env = self._render_headers(check, run_start)
        missing_env += [e for e in re.findall(r"\{env:([A-Z0-9_]+)\}", check["url"]) if not os.environ.get(e)]
        if missing_env:
            result.evidence.append(Evidence(criterion, None, check["type"],
                                            f"Não verificável: variável(is) {', '.join(sorted(set(missing_env)))} "
                                            "ausente(s) no ambiente do Guardião"))
            return
        if self._limit_http():
            result.evidence.append(Evidence(criterion, None, check["type"], "Rate limit de chamadas HTTP da rodada"))
            return
        status, body = self.http_get(url, headers, int(check.get("timeout", 20)))
        expected = check.get("expect_status", [200])
        if status not in expected:
            text = f"HTTP {status} {body[:300]}"
            ctx["texts"].append(text)
            result.evidence.append(Evidence(criterion, False, check["type"],
                                            f"{check.get('label', url)}: {redact(text)[:200]}", {"status": status}))
            return
        if check["type"] == "http_status":
            result.evidence.append(Evidence(criterion, True, "http", f"{check.get('label', 'API')}: HTTP {status}"))
            return
        payload = json.loads(body)
        record = payload[0] if isinstance(payload, list) and payload else payload
        value = record.get(check["field"]) if isinstance(record, dict) else None
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00")) if value else None
        if ts is not None and ts.tzinfo is None:
            ts = ts.astimezone()
        ok = ts is not None and ts >= run_start - START_TOLERANCE
        result.evidence.append(Evidence(criterion, ok, "http",
                                        f"{check.get('label', 'dado')}: último registro "
                                        f"{ts:%d/%m %H:%M}" if ts else f"{check.get('label', 'dado')}: sem registros"))

    def _check_command(self, check, kind, result, ctx) -> None:
        criterion = _CONTENT_CRITERION.get(kind, Criterion.OUTPUT_VALID.value)
        proc = subprocess.run(check["command"], capture_output=True, text=True, timeout=int(check.get("timeout", 60)),
                              shell=isinstance(check["command"], str))
        ok = proc.returncode == int(check.get("expect_exit", 0))
        if not ok:
            ctx["texts"].append(proc.stdout + proc.stderr)
        result.evidence.append(Evidence(criterion, ok, "command",
                                        f"{check.get('label', 'check')}: exit={proc.returncode}"))

    # ---------------------------------------------------------- classificação
    def _classify(self, result: CheckResult, ctx: dict[str, Any]) -> None:
        failed = [e for e in result.evidence if e.passed is False]
        known = [e for e in result.evidence if e.passed is not None]
        text = "\n".join(ctx["texts"])
        hits = match_causes(text) if failed else []
        result.cause_hits = [{"code": p.code, "line": redact(line)} for p, line in hits]
        hint = ctx.get("hint")
        if hits and hint in (None, "SCRIPT_EXIT_NONZERO", "UNKNOWN_RESULT"):
            hint = hits[0][0].code  # evidência textual do log é mais específica que o código de saída
        result.cause_hint = hint
        result.log_excerpt = redact("\n".join(text.splitlines()[-25:]))[-3000:]
        result.findings.extend(e.detail for e in failed)

        if not failed:
            if not known:
                result.status = CheckStatus.INSUFFICIENT_EVIDENCE.value
                result.findings.append("Nenhuma evidência verificável — sucesso NÃO declarado.")
            else:
                result.status = CheckStatus.SUCCESS.value
            return
        result.status = CheckStatus.INCIDENT.value
        kinds = {e.criterion for e in failed}
        if kinds == {Criterion.ON_TIME.value}:
            result.incident_type = IncidentType.DELAYED_EXECUTION.value
            return
        kinds.discard(Criterion.ON_TIME.value)
        if ctx["missed"]:
            result.incident_type = IncidentType.MISSED_EXECUTION.value
        elif ctx["hung"]:
            result.incident_type = IncidentType.FAILED_EXECUTION.value
        elif hits and hits[0][0].incident_type in _SPECIFIC_TYPES:
            result.incident_type = hits[0][0].incident_type
        elif ctx["exit_failed"]:
            result.incident_type = IncidentType.FAILED_EXECUTION.value
        elif Criterion.OUTPUT_EXISTS.value in kinds and kinds <= {Criterion.OUTPUT_EXISTS.value,
                                                                   Criterion.OUTPUT_VALID.value}:
            result.incident_type = IncidentType.MISSING_OUTPUT.value
        elif kinds == {Criterion.OUTPUT_VALID.value}:
            result.incident_type = IncidentType.INVALID_OUTPUT.value
        elif kinds == {Criterion.DATA_UPDATED.value}:
            result.incident_type = IncidentType.DATA_NOT_UPDATED.value
        elif kinds == {Criterion.DELIVERY_COMPLETED.value}:
            result.incident_type = IncidentType.DELIVERY_FAILURE.value
        elif kinds == {Criterion.DEPENDENCY_OK.value}:
            result.incident_type = IncidentType.DEPENDENCY_FAILURE.value
        elif hits:
            result.incident_type = hits[0][0].incident_type
        elif any(e.passed for e in result.evidence if e.criterion == Criterion.PROCESS_STARTED.value):
            result.incident_type = IncidentType.PARTIAL_EXECUTION.value
        else:
            result.incident_type = IncidentType.UNKNOWN_FAILURE.value
