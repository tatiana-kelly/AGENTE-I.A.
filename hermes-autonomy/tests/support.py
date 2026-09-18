"""Infra de testes: relógio controlável, agendador falso, executor falso e fábrica de automações."""
from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from hermes_autonomy.adapters import CommandRunRecorder, TaskInfo
from hermes_autonomy.config import load_settings
from hermes_autonomy.orchestrator import Orchestrator

LOCAL_TZ = datetime.now().astimezone().tzinfo
NOW = datetime(2026, 9, 18, 10, 0, 0, tzinfo=LOCAL_TZ)


class Clock:
    def __init__(self, now: datetime = NOW):
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += timedelta(seconds=max(seconds, 1))


class FakeTasks:
    def __init__(self, tasks: dict[str, TaskInfo] | None = None):
        self.tasks = tasks or {}

    def get(self, name: str) -> TaskInfo:
        return self.tasks.get(name) or TaskInfo(name=name, exists=False)

    def refresh(self) -> None:
        pass


class FakeExecutor:
    """Registra chamadas; `effect(clock_now)` simula o que a reexecução produz no mundo."""

    def __init__(self, effect: Callable[[datetime], bool] | None = None, clock: Clock | None = None):
        self.effect = effect
        self.clock = clock
        self.calls: list[tuple[str, str]] = []

    def _apply(self) -> tuple[bool, str]:
        if self.effect and self.clock:
            self.clock.now += timedelta(seconds=5)
            ok = self.effect(self.clock.now)
            return True, f"exit={'0' if ok else '1'}"
        return True, "ok"

    def run_task(self, task_name: str) -> tuple[bool, str]:
        self.calls.append(("run_task", task_name))
        return self._apply()

    def stop_task(self, task_name: str) -> tuple[bool, str]:
        self.calls.append(("stop_task", task_name))
        return True, "stopped"

    def run_command(self, command, workdir, timeout) -> tuple[bool, str]:
        self.calls.append(("run_command", str(command)))
        return self._apply()


def write(path: Path, text: str, when: datetime, append: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a" if append else "w", encoding="utf-8") as handle:
        handle.write(text)
    ts = when.timestamp()
    os.utime(path, (ts, ts))
    return path


def log_line(when: datetime, level: str, message: str) -> str:
    return f"{when:%Y-%m-%d %H:%M:%S} | {level:<8} | {message}\n"


class Sandbox:
    """Diretório temporário com uma automação 'command' parecida com o canário."""

    def __init__(self, name: str = "job"):
        self.root = Path(tempfile.mkdtemp(prefix="ha-test-"))
        self.name = name

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def paths(self, day: datetime) -> dict[str, Path]:
        d = self.root / self.name
        return {"log": d / f"log_{day:%Y%m%d}.log", "out": d / f"out_{day:%Y%m%d}.json",
                "data": d / "table.json", "delivery": d / f"log_{day:%Y%m%d}.log"}

    def automation(self, **overrides: Any) -> dict[str, Any]:
        d = str(self.root / self.name).replace("\\", "/")
        base = {
            "id": self.name, "name": f"Job {self.name}", "source": "command", "command": ["noop"],
            "schedule": {"type": "daily", "times": ["07:00"]}, "grace_minutes": 0, "max_duration_minutes": 5,
            "dependencies": ["supabase"], "enabled": True, "idempotent": True, "risk_level": "low",
            "criticality": "high", "allowed_recovery_actions": ["rerun_command"],
            "expected_outputs": ["out.json", "table.json", "entrega"],
            "checks": [
                {"type": "file", "kind": "log", "label": "log", "path": d + "/log_{date:%Y%m%d}.log",
                 "segment": "since_run", "success_patterns": ["=== fim ==="],
                 "failure_patterns": ["\\|\\s*ERROR\\s*\\|"]},
                {"type": "file", "kind": "output", "label": "saída", "path": d + "/out_{date:%Y%m%d}.json",
                 "json_valid": True},
                {"type": "file", "kind": "data", "label": "banco", "path": d + "/table.json"},
                {"type": "file", "kind": "delivery", "label": "entrega", "path": d + "/log_{date:%Y%m%d}.log",
                 "segment": "since_run", "success_patterns": ["entrega: enviado"]},
            ],
        }
        base.update(overrides)
        return base

    # ---- cenários de execução
    def good_run(self, when: datetime, *, data: bool = True, delivery: bool = True, output: bool = True,
                 finish: bool = True) -> None:
        p = self.paths(when)
        text = log_line(when, "INFO", "=== inicio ===")
        if output:
            write(p["out"], '{"rows": 42}', when)
            text += log_line(when, "INFO", "saida gerada")
        if data:
            write(p["data"], '[{"updated_at": "x"}]', when)
            text += log_line(when, "INFO", "banco atualizado")
        if delivery:
            text += log_line(when, "INFO", "entrega: enviado")
        if finish:
            text += log_line(when, "INFO", "=== fim ===")
        write(p["log"], text, when, append=True)

    def failed_run(self, when: datetime, error: str) -> None:
        p = self.paths(when)
        write(p["log"], log_line(when, "INFO", "=== inicio ===") + log_line(when, "ERROR", error), when, append=True)


def make_orchestrator(state_dir: Path, automations: list[dict[str, Any]], clock: Clock, *,
                      executor: FakeExecutor | None = None, tasks: FakeTasks | None = None, live: bool = False,
                      overrides: dict[str, Any] | None = None) -> Orchestrator:
    cfg = {"validation": {"poll_seconds": 1, "timeout_seconds": 60, "settle_seconds": 0},
           "retry_backoff_seconds": [0, 1, 1], "notification": {"channels": [], "external_enabled": False}}
    if live:
        cfg.update(dry_run=False, autonomous_repair=True)
    else:
        cfg.update(dry_run=True, autonomous_repair=False)
    cfg.update(overrides or {})
    settings = load_settings(config_path=str(state_dir / "none.json"), state_dir=state_dir, overrides=cfg)
    providers = {"windows_task": tasks or FakeTasks(), "command": CommandRunRecorder(), "github_actions": FakeTasks()}
    return Orchestrator.build(settings, providers=providers, executor=executor or FakeExecutor(), clock=clock,
                              sleep=clock.sleep, automations=automations)
