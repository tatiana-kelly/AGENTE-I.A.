"""Adapters de evidência (ACTUAL) e de execução.

Reaproveitam o que já existe na máquina — Agendador de Tarefas do Windows (via PowerShell nativo),
API do GitHub (via urllib + GITHUB_TOKEN do ambiente), HTTP/Supabase REST e subprocess — sem
dependências novas. Todos são injetáveis para testes.
"""
from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Protocol

from .redact import redact

NEVER_RUN_YEAR = 2000  # o Agendador devolve 30/11/1999 para "nunca executou"

# Códigos LastTaskResult relevantes do Agendador de Tarefas
TASK_RUNNING = 0x41301
TASK_NOT_YET_RUN = 0x41303


@dataclass
class TaskInfo:
    name: str
    exists: bool = True
    state: str = "Unknown"  # Ready | Running | Disabled | Queued | Unknown
    last_run: datetime | None = None
    last_result: int | None = None
    next_run: datetime | None = None
    action: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def running(self) -> bool:
        return self.state in ("Running", "Queued", "in_progress", "queued")


class TaskProvider(Protocol):
    def get(self, task_name: str) -> TaskInfo: ...


class Executor(Protocol):
    def run_task(self, task_name: str) -> tuple[bool, str]: ...
    def stop_task(self, task_name: str) -> tuple[bool, str]: ...
    def run_command(self, command: list[str] | str, workdir: str | None, timeout: int) -> tuple[bool, str]: ...


HttpGet = Callable[[str, dict[str, str], int], tuple[int, str]]


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.astimezone()
    if dt.year < NEVER_RUN_YEAR:
        return None
    return dt.astimezone().replace(microsecond=0)


def _split_task(task_name: str) -> tuple[str, str]:
    name = task_name if task_name.startswith("\\") else "\\" + task_name
    path, _, leaf = name.rpartition("\\")
    return (path or "") + "\\", leaf


def _powershell(script: str, timeout: int = 90) -> subprocess.CompletedProcess:
    prefix = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; $ErrorActionPreference='Stop'; "
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", prefix + script],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
    )


class WindowsTaskProvider:
    """Lê TODAS as tarefas não-Microsoft numa única chamada PowerShell (cache por execução)."""

    _SCRIPT = (
        "Get-ScheduledTask | Where-Object { $_.TaskPath -notlike '\\Microsoft\\*' } | ForEach-Object { "
        "$i = $_ | Get-ScheduledTaskInfo; "
        "[pscustomobject]@{ path=$_.TaskPath + $_.TaskName; state=[string]$_.State; "
        "last=$(if($i.LastRunTime){$i.LastRunTime.ToString('o')}else{$null}); "
        "result=[int64]$i.LastTaskResult; "
        "next=$(if($i.NextRunTime){$i.NextRunTime.ToString('o')}else{$null}); "
        "action=(($_.Actions | ForEach-Object { \"$($_.Execute) $($_.Arguments)\" }) -join ' | ') } "
        "} | ConvertTo-Json -Depth 3 -Compress"
    )

    def __init__(self) -> None:
        self._cache: dict[str, TaskInfo] | None = None

    def refresh(self) -> None:
        self._cache = None

    def _load(self) -> dict[str, TaskInfo]:
        proc = _powershell(self._SCRIPT)
        if proc.returncode != 0:
            raise RuntimeError(f"Get-ScheduledTask falhou: {redact(proc.stderr)[:400]}")
        raw = json.loads(proc.stdout or "[]")
        if isinstance(raw, dict):
            raw = [raw]
        tasks: dict[str, TaskInfo] = {}
        for item in raw:
            result = item.get("result")
            if result is not None and result < 0:
                result &= 0xFFFFFFFF
            tasks[item["path"].lower()] = TaskInfo(
                name=item["path"], state=item.get("state") or "Unknown", last_run=_parse_dt(item.get("last")),
                last_result=result, next_run=_parse_dt(item.get("next")), action=item.get("action") or "",
            )
        return tasks

    def all(self) -> dict[str, TaskInfo]:
        if self._cache is None:
            self._cache = self._load()
        return self._cache

    def get(self, task_name: str) -> TaskInfo:
        key = (task_name if task_name.startswith("\\") else "\\" + task_name).lower()
        return self.all().get(key) or TaskInfo(name=task_name, exists=False)


class GithubRunsProvider:
    """Última execução de um workflow do GitHub Actions. Sem GITHUB_TOKEN → evidência indisponível."""

    def __init__(self, http_get: HttpGet | None = None, token_env: str = "GITHUB_TOKEN"):
        self.http_get = http_get or default_http_get
        self.token_env = token_env

    def get(self, task_name: str) -> TaskInfo:
        repo, _, workflow = task_name.partition(":")
        token = os.environ.get(self.token_env)
        if not token:
            return TaskInfo(name=task_name, exists=True, state="Unknown",
                            extra={"unverifiable": f"{self.token_env} ausente no ambiente"})
        url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}/runs?per_page=1"
        status, body = self.http_get(url, {"Authorization": f"Bearer {token}",
                                           "Accept": "application/vnd.github+json"}, 20)
        if status != 200:
            return TaskInfo(name=task_name, exists=True, state="Unknown",
                            extra={"unverifiable": f"GitHub API HTTP {status}"})
        runs = json.loads(body).get("workflow_runs", [])
        if not runs:
            return TaskInfo(name=task_name, exists=True, state="Ready")
        run = runs[0]
        conclusion = run.get("conclusion")
        return TaskInfo(
            name=task_name, exists=True,
            state="Running" if run.get("status") in ("queued", "in_progress") else "Ready",
            last_run=_parse_dt(run.get("run_started_at") or run.get("created_at")),
            last_result=None if conclusion is None else (0 if conclusion == "success" else 1),
            extra={"conclusion": conclusion, "url": run.get("html_url")},
        )


def default_http_get(url: str, headers: dict[str, str], timeout: int) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "hermes-autonomy", **headers})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (URL do registry)
            return response.status, response.read(1_000_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(20_000).decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return 0, f"{type(exc).__name__}: {exc}"


class SystemExecutor:
    """Executor real. Só é chamado pelo Reparador quando DRY_RUN=false e AUTONOMOUS_REPAIR=true."""

    def run_task(self, task_name: str) -> tuple[bool, str]:
        path, leaf = _split_task(task_name)
        proc = _powershell(f"Start-ScheduledTask -TaskPath '{path}' -TaskName '{leaf}'")
        return proc.returncode == 0, redact((proc.stdout + proc.stderr).strip()) or "Start-ScheduledTask ok"

    def stop_task(self, task_name: str) -> tuple[bool, str]:
        path, leaf = _split_task(task_name)
        proc = _powershell(f"Stop-ScheduledTask -TaskPath '{path}' -TaskName '{leaf}'")
        return proc.returncode == 0, redact((proc.stdout + proc.stderr).strip()) or "Stop-ScheduledTask ok"

    def run_command(self, command: list[str] | str, workdir: str | None, timeout: int) -> tuple[bool, str]:
        try:
            proc = subprocess.run(command, cwd=workdir, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=timeout, shell=isinstance(command, str))
        except subprocess.TimeoutExpired:
            return False, f"timeout após {timeout}s"
        output = redact((proc.stdout + proc.stderr)[-2000:])
        return proc.returncode == 0, f"exit={proc.returncode} {output}".strip()


class CommandRunRecorder:
    """Para automações `source: command` (sem agendador externo) o 'processo' é inferido pelo log."""

    def get(self, task_name: str) -> TaskInfo:
        return TaskInfo(name=task_name, exists=True, state="Unknown", extra={"inferred_from_log": True})
