"""Integração com o runtime Hermes: copia o app para o HERMES_HOME, instala wrappers em
<HERMES_HOME>/scripts (exigência do `hermes cron --script`), publica as Skills e cria os cron jobs
nativos (--no-agent: sem LLM, sem custo de tokens). Reversível via `uninstall`."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from .config import PACKAGE_ROOT

JOBS = {
    "hermes-autonomy-guardian": ("every 30m", "hermes_autonomy_tick.py", ["tick", "--hermes"]),
    "hermes-autonomy-daily-report": ("0 10 * * *", "hermes_autonomy_report.py", ["report", "--send"]),
}
WRAPPER = '''"""Gerado por hermes_autonomy install — não editar (fonte: AGENTE-I.A/hermes-autonomy)."""
import sys
APP = r"{app}"
sys.path.insert(0, APP)
from hermes_autonomy.cli import main
sys.exit(main({args!r}))
'''


def hermes_home() -> Path:
    if os.environ.get("HERMES_HOME"):
        return Path(os.environ["HERMES_HOME"])
    local = os.environ.get("LOCALAPPDATA")
    if local and (Path(local) / "hermes").exists():
        return Path(local) / "hermes"
    return Path.home() / ".hermes"


def _hermes(*args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(["hermes", *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, env=env)


def existing_jobs() -> dict[str, str]:
    """nome → id dos cron jobs Hermes já existentes."""
    proc = _hermes("cron", "list")
    jobs: dict[str, str] = {}
    current_id = None
    for line in proc.stdout.splitlines():
        header = re.match(r"^\s*([0-9a-f]{8,})\s+\[\w+\]", line)  # "  fdddd6004c02 [active]"
        if header:
            current_id = header.group(1)
            continue
        name = re.match(r"^\s*Name:\s+(\S+)", line)
        if name and current_id and name.group(1) in JOBS:
            jobs[name.group(1)] = current_id
    return jobs


def install(with_cron: bool = True, with_skills: bool = True) -> list[str]:
    home = hermes_home()
    log: list[str] = []
    app = home / "autonomy" / "app"
    if app.exists():
        shutil.rmtree(app)
    app.mkdir(parents=True)
    shutil.copytree(PACKAGE_ROOT / "hermes_autonomy", app / "hermes_autonomy",
                    ignore=shutil.ignore_patterns("__pycache__"))
    for folder in ("registry", "config"):
        if (PACKAGE_ROOT / folder).exists():
            shutil.copytree(PACKAGE_ROOT / folder, app / folder)
    shutil.copy2(PACKAGE_ROOT / "ha.py", app / "ha.py")
    log.append(f"app copiado → {app}")

    scripts = home / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    for _, (_, script, args) in JOBS.items():
        (scripts / script).write_text(WRAPPER.format(app=str(app), args=args), encoding="utf-8")
        log.append(f"wrapper → {scripts / script}")

    if with_skills:
        target = home / "skills" / "autonomy"
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(PACKAGE_ROOT / "skills", target)
        log.append(f"skills → {target} ({', '.join(sorted(p.name for p in target.iterdir()))})")

    if with_cron:
        present = existing_jobs()
        for name, (schedule, script, _) in JOBS.items():
            if name in present:
                log.append(f"cron '{name}' já existe — mantido (idempotente)")
                continue
            proc = _hermes("cron", "create", schedule, "--name", name, "--no-agent", "--script", script,
                           "--deliver", "local")
            log.append(f"cron '{name}' ({schedule}) → rc={proc.returncode} {(proc.stdout + proc.stderr).strip()[:200]}")
    return log


def uninstall() -> list[str]:
    home = hermes_home()
    log: list[str] = []
    for name, job_id in existing_jobs().items():
        proc = _hermes("cron", "remove", job_id)
        log.append(f"cron '{name}' removido → rc={proc.returncode} {(proc.stdout + proc.stderr).strip()[:160]}")
    for _, (_, script, _) in JOBS.items():
        path = home / "scripts" / script
        if path.exists():
            path.unlink()
            log.append(f"wrapper removido: {path}")
    for path in (home / "skills" / "autonomy", home / "autonomy" / "app"):
        if path.exists():
            shutil.rmtree(path)
            log.append(f"removido: {path}")
    log.append(f"histórico preservado (autonomy.db, outbox): {home / 'autonomy'}")
    return log
