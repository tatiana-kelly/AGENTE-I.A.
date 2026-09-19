"""CLI: python -m hermes_autonomy <comando>  (rode dentro de AGENTE-I.A/hermes-autonomy)."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from typing import Any

from .config import load_settings
from .models import now_local


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass


def _settings(args, overrides: dict[str, Any] | None = None):
    overrides = dict(overrides or {})
    if getattr(args, "live", False):
        overrides.update(dry_run=False, autonomous_repair=True)
    if getattr(args, "fast", False):
        overrides.update(retry_backoff_seconds=[0, 1, 1],
                         validation={"poll_seconds": 1, "timeout_seconds": 120, "settle_seconds": 0})
    return load_settings(args.config, args.registry, args.state_dir, overrides)


def _orchestrator(args, overrides=None):
    from .orchestrator import Orchestrator
    return Orchestrator.build(_settings(args, overrides))


def _only(args) -> list[str] | None:
    return [x.strip() for x in args.only.split(",")] if getattr(args, "only", None) else None


def _print_summary(summary: dict[str, Any]) -> None:
    mode = "DRY_RUN" if summary["dry_run"] else ("LIVE+REPAIR" if summary["live_repairs"] else "LIVE")
    print(f"[hermes-autonomy] rodada #{summary['run_id']} ({summary['mode']}, {mode}) — "
          f"{summary['checked']} verificadas: {summary['statuses']}")
    for inc in summary["incidents"]:
        print(f"  [{inc['priority']}] {inc['automation']}: {inc['type']} / {inc['cause']} → {inc['outcome']}")
        print(f"        {inc['reason'][:220]}")
    for root in summary.get("root_causes", []):
        print(f"  ROOT_CAUSE_INCIDENT {root['id']}: {root['cause_key']} ({root['members']} automações)")
    if summary["skipped_idempotent"]:
        print(f"  já tratados nesta janela (idempotência): {len(summary['skipped_idempotent'])}")


# ------------------------------------------------------------------ comandos
def cmd_tick(args) -> int:
    orch = _orchestrator(args)
    summary = orch.run(only=_only(args), mode="hermes-cron" if args.hermes else "tick",
                       include_disabled=args.include_disabled)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, default=str, indent=2))
    elif not (args.hermes and not summary["incidents"]):
        _print_summary(summary)  # no cron Hermes: stdout vazio = silencioso quando tudo OK
    return 0


def cmd_health(args) -> int:
    """Somente leitura: EXPECTED vs ACTUAL agora, sem registrar incidente nem reparar."""
    orch = _orchestrator(args)
    rows = []
    for automation in orch.select(_only(args), args.include_disabled):
        check = orch._safe_evaluate(automation)
        rows.append(check)
        slot = check.slot[5:16].replace("T", " ") if check.slot else "-"
        label = check.incident_type or check.status
        print(f"{check.status:<22} {label:<24} {slot:<12} {automation['id']}")
        if args.verbose or check.is_incident:
            for finding in check.findings[:3]:
                print(f"{'':<22} · {finding[:150]}")
            if check.is_incident and check.cause_hint:
                print(f"{'':<22} · causa indicada: {check.cause_hint}")
        if args.verbose and check.status == "SUCCESS":
            print(f"{'':<22} · validado por: {check.validated_by()}")
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.status] = counts.get(r.status, 0) + 1
    print(f"\nTotal: {len(rows)} → {counts}")
    return 0


def cmd_status(args) -> int:
    settings = _settings(args)
    from .store import Store
    store = Store(settings.state_dir / "autonomy.db")
    last = store._rows("SELECT * FROM runs ORDER BY id DESC LIMIT 1")
    print(f"DRY_RUN={settings.dry_run}  AUTONOMOUS_REPAIR={settings.autonomous_repair}  "
          f"external_notifications={settings['notification']['external_enabled']}")
    print(f"state: {settings.state_dir}\nregistry: {settings.registry_path}")
    if last:
        summary = json.loads(last[0]["summary_json"] or "{}")
        print(f"última rodada: #{last[0]['id']} {last[0]['started_at'][:19]} ({last[0]['mode']}) "
              f"{summary.get('statuses')}")
    open_ = store.incidents(limit=15)
    print(f"\nIncidentes recentes ({len(open_)}):")
    for i in open_:
        print(f"  {i['id']} [{i['priority']}] {i['automation_id']:<34} {i['type']:<22} {i['state']:<10} "
              f"{i['outcome'] or ''} {i['cause_code'] or ''}")
    circuits = store._rows("SELECT * FROM circuit WHERE state='OPEN'")
    for c in circuits:
        print(f"  CIRCUIT OPEN: {c['automation_id']} até {c['until']} — {c['reason']}")
    try:
        import subprocess
        proc = subprocess.run(["hermes", "cron", "list"], capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=60)
        print("\nHermes cron:\n" + "\n".join(l for l in proc.stdout.splitlines() if l.strip())[:1500])
    except (OSError, subprocess.SubprocessError):
        print("\nHermes cron: CLI `hermes` indisponível")
    return 0


def cmd_report(args) -> int:
    settings = _settings(args)
    from .notify import Notification
    from .orchestrator import Orchestrator
    from .report import daily_report
    orch = Orchestrator.build(settings)
    day = datetime.fromisoformat(args.date).astimezone() if args.date else None
    report = daily_report(orch.store, orch.automations, settings, day)
    if args.send:
        stamp = (day or now_local()).strftime("%Y-%m-%d")
        # e-mail só com o que não rodou e não foi corrigido; o relatório completo segue no terminal/arquivo
        pending = len(report["unresolved"])
        result = orch.notifier.notify(Notification(kind="daily_report",
                                                   subject=f"HERMES — {pending} automação(ões) sem correção em {stamp}",
                                                   body=report["email_text"], priority="P3", dedupe_key=f"daily:{stamp}",
                                                   tag="RESUMO DIÁRIO"))
        if not args.hermes:
            print(report["text"])
            print(f"\nentrega: {result}")
    else:
        print(report["text"])
    return 0


def cmd_incidents(args) -> int:
    settings = _settings(args)
    from .store import Store
    store = Store(settings.state_dir / "autonomy.db")
    for i in store.incidents(automation_id=args.automation, cause_code=args.cause, limit=args.limit):
        rec = f"{i['recovery_seconds']}s" if i["recovery_seconds"] is not None else "-"
        print(f"{i['id']} {i['detected_at'][:16]} [{i['priority']}] {i['automation_id']:<34} {i['type']:<22} "
              f"{i['cause_code'] or '':<22} {i['state']:<10} {i['outcome'] or '':<30} tentativas={i['attempts']} "
              f"recuperação={rec}")
    return 0


def cmd_incident(args) -> int:
    settings = _settings(args)
    from .store import Store
    store = Store(settings.state_dir / "autonomy.db")
    incident = store.get_incident(args.id)
    if not incident:
        print("incidente não encontrado")
        return 1
    diagnosis = json.loads(incident.pop("diagnosis_json") or "{}")
    check = json.loads(incident.pop("check_json") or "{}")
    for key, value in incident.items():
        print(f"{key:>18}: {value}")
    if diagnosis:
        print("\nDIAGNÓSTICO (ordem de investigação):")
        for s in diagnosis.get("steps", []):
            print(f"  {s['step']:>2}. {s['name']}: {s['result'][:160]}")
        print("  evidências:\n    - " + "\n    - ".join(diagnosis.get("evidence", [])))
    if check.get("evidence"):
        print("\nEVIDÊNCIAS (EXPECTED vs ACTUAL):")
        for e in check["evidence"]:
            flag = {True: "OK   ", False: "FALHA", None: "N/D  "}[e["passed"]]
            print(f"  {flag} {e['criterion']:<20} {e['detail'][:150]}")
    print("\nCICLO DE VIDA:")
    for e in store.events(args.id):
        print(f"  {e['ts'][11:19]} {e['from_state'] or '-':>10} → {e['to_state']:<10} {e['agent']:<22} {e['note'][:120]}")
    attempts = store.attempts_for(args.id)
    if attempts:
        print("\nTENTATIVAS DE REPARO:")
        for a in attempts:
            print(f"  #{a['attempt']} {a['action']} dry_run={a['dry_run']} → {a['result']} | {(a['validation'] or '')[:140]}")
    print("\nAUDITORIA:")
    for a in reversed(store.audit_entries(incident=args.id)):
        print(f"  {a['ts'][11:19]} {a['agent']:<22} {a['action']:<18} {a['result'][:40]:<40} risco={a['risk_level']}"
              f" dry_run={a['dry_run']}")
    return 0


def cmd_history(args) -> int:
    """'Essa automação já teve esse problema?' / 'Como resolvemos da última vez?'"""
    settings = _settings(args)
    from .store import Store
    store = Store(settings.state_dir / "autonomy.db")
    rows = store.history(args.automation, args.cause)
    print(f"{args.automation}: {len(rows)} incidente(s)" + (f" com causa {args.cause}" if args.cause else ""))
    for r in rows[:20]:
        print(f"  {r['detected_at'][:16]} {r['type']:<22} {r['cause_code'] or '':<22} {r['outcome'] or r['state']}"
              f"{' — solução: ' + r['resolution'] if r['resolution'] else ''}")
    if args.cause:
        fix = store.last_resolution(args.automation, args.cause) or store.last_resolution(None, args.cause)
        print(f"\nÚltima solução validada para {args.cause}: "
              f"{fix['resolution'] + ' (' + fix['automation_id'] + ', ' + fix['resolved_at'][:16] + ')' if fix else 'nenhuma registrada'}")
    return 0


def cmd_logs(args) -> int:
    settings = _settings(args)
    from .store import Store
    store = Store(settings.state_dir / "autonomy.db")
    for e in reversed(store.audit_entries(limit=args.limit)):
        print(f"{e['ts'][:19]} {e['agent']:<22} {e['automation'] or '-':<30} {e['action']:<20} {e['result'][:50]:<50} "
              f"risco={e['risk_level']} dry_run={e['dry_run']} inc={e['incident'] or '-'}")
    return 0


def cmd_registry(args) -> int:
    from .registry import load_registry
    settings = _settings(args)
    automations = load_registry(settings.registry_path)
    enabled = [a for a in automations if a.get("enabled", True)]
    print(f"registry OK: {len(automations)} automações ({len(enabled)} habilitadas) — {settings.registry_path}")
    if args.list:
        for a in automations:
            actions = ",".join(a.get("allowed_recovery_actions", [])) or "-"
            print(f"  {'ON ' if a.get('enabled', True) else 'off'} {a['id']:<36} {a['source']:<15} "
                  f"crit={a.get('criticality', 'medium'):<8} reparo={actions}")
    return 0


def cmd_discover(args) -> int:
    """Automações no Agendador do Windows ainda fora do registry."""
    from .adapters import WindowsTaskProvider
    from .registry import load_registry
    settings = _settings(args)
    known = {a.get("task_name", "").lower() for a in load_registry(settings.registry_path)}
    ignore = ("onedrive", "powertoys", "activation-renewal")
    for task in WindowsTaskProvider().all().values():
        if task.name.lower() in known or any(x in task.name.lower() for x in ignore):
            continue
        last = f"{task.last_run:%d/%m %H:%M}" if task.last_run else "nunca"
        print(f"NÃO REGISTRADA: {task.name} [{task.state}] última={last} rc={task.last_result} :: {task.action[:120]}")
    return 0


def cmd_event(args) -> int:
    """Gatilho orientado a evento: um script/webhook avisa falha → Guardião roda na hora só para ela."""
    orch = _orchestrator(args)
    orch.store.audit("hermes-guardian", "event_received", args.message or "evento externo", "RECEIVED",
                     automation=args.automation, tool="event", dry_run=orch.settings.dry_run)
    _print_summary(orch.run(only=[args.automation], mode="event"))
    return 0


def cmd_demo(args) -> int:
    """Prova controlada: canário (sandbox) — recuperação automática e escalonamento."""
    from pathlib import Path

    from .canary import set_mode
    from .config import PACKAGE_ROOT
    args.registry = args.registry or str(PACKAGE_ROOT / "registry" / "sandbox.json")
    settings = _settings(args)
    canary = settings.state_dir / "canary"
    if canary.exists():
        shutil.rmtree(canary)
    from .canary import run as run_canary
    from .orchestrator import Orchestrator
    scenario = args.scenario
    print(f"=== DEMO '{scenario}' — sandbox em {canary} — DRY_RUN={settings.dry_run} "
          f"AUTONOMOUS_REPAIR={settings.autonomous_repair}")
    mode = {"recover": "fail_once", "escalate": "fail_always", "credential": "credential_missing",
            "partial": "partial", "ok": "ok"}[scenario]
    set_mode(Path(settings.state_dir), mode)
    rc = run_canary(Path(settings.state_dir))  # a "execução agendada" que falhou
    print(f"execução agendada simulada do canário terminou com exit={rc}")
    orch = Orchestrator.build(settings)
    summary = orch.run(only=["hermes-canary"], mode=f"demo-{scenario}")
    _print_summary(summary)
    for inc in summary["incidents"]:
        print(f"\nDetalhe: python -m hermes_autonomy incident {inc['incident_id']}"
              + (f" --state-dir {args.state_dir}" if args.state_dir else ""))
    return 0


def cmd_install(args) -> int:
    from .install import install
    for line in install(with_cron=not args.no_cron, with_skills=not args.no_skills):
        print(line)
    return 0


def cmd_uninstall(args) -> int:
    from .install import uninstall
    for line in uninstall():
        print(line)
    return 0


def cmd_start_stop(args) -> int:
    import subprocess

    from .install import existing_jobs
    verb = "resume" if args.command == "start" else "pause"
    for name, job_id in existing_jobs().items():
        proc = subprocess.run(["hermes", "cron", verb, job_id], capture_output=True, text=True, encoding="utf-8",
                              errors="replace")
        print(f"{verb} {name} ({job_id}) → rc={proc.returncode} {(proc.stdout + proc.stderr).strip()[:160]}")
    return 0


def cmd_outbox(args) -> int:
    """Outbox LOCAL do AUTOMATION_INCIDENT (ponte Hermes → SAL OS). Nada é enviado a lugar nenhum."""
    from .contract import IncidentOutbox, validate_event
    settings = _settings(args)
    outbox = IncidentOutbox(settings.state_dir / "events")
    if args.action == "list":
        events = outbox.events()
        print(f"{len(events)} evento(s) em {outbox.path}")
        for e in events:
            print(f"  {e['timestamp'][:16]} {e['automation_id']:<30} {e['incident_type']:<22} "
                  f"{e['lifecycle_state']:<9} business={e['requires_business_decision']} {e['event_id'][:19]}…")
        return 0
    if args.action == "validate":
        with open(args.target, encoding="utf-8") as fh:
            docs = [json.loads(l) for l in fh if l.strip()] if args.target.endswith(".jsonl") else [json.load(fh)]
        bad = 0
        for doc in docs:
            errors = validate_event(doc)
            bad += bool(errors)
            print(f"{'OK     ' if not errors else 'INVÁLIDO'} {doc.get('event_id', '?')[:19]}… "
                  + ("" if not errors else "; ".join(errors[:5])))
        return 1 if bad else 0
    from .orchestrator import Orchestrator
    orch = Orchestrator.build(settings)
    print(orch.emit_to_outbox([args.target]))
    return 0


TICKER_TASK = "Hermes - Cron Tick"


def cmd_ticker(args) -> int:
    """Liga/desliga o 'relógio' do cron Hermes sem subir o gateway de mensagens (HUMAN_REQUIRED: decisão)."""
    import shutil as sh
    import subprocess
    if args.action == "status":
        proc = subprocess.run(["powershell.exe", "-NoProfile", "-Command",
                               f"Get-ScheduledTask -TaskName '{TICKER_TASK}' -ErrorAction SilentlyContinue | "
                               "Select-Object TaskName,State | Format-List"], capture_output=True, text=True)
        print(proc.stdout.strip() or f"'{TICKER_TASK}' não instalado — cron Hermes só dispara com gateway ou tick manual")
        return 0
    if not args.yes:
        print("Ação persistente no Agendador do Windows. Confirme com --yes "
              f"(cria/remove a tarefa '{TICKER_TASK}' que roda `hermes cron tick` a cada {args.minutes} min).")
        return 2
    if args.action == "remove":
        script = f"Unregister-ScheduledTask -TaskName '{TICKER_TASK}' -Confirm:$false"
    else:
        hermes = sh.which("hermes") or "hermes"
        script = (
            f"$a = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "
            f"'-NoProfile -WindowStyle Hidden -Command \"& ''{hermes}'' cron tick\"'; "
            f"$t = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) "
            f"-RepetitionInterval (New-TimeSpan -Minutes {args.minutes}); "
            "$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew "
            f"-ExecutionTimeLimit (New-TimeSpan -Minutes {max(args.minutes - 1, 5)}); "
            f"Register-ScheduledTask -TaskName '{TICKER_TASK}' -Action $a -Trigger $t -Settings $s "
            "-Description 'Dispara os cron jobs do Hermes (hermes-autonomy). Remover: ha.py ticker remove --yes' -Force"
        )
    proc = subprocess.run(["powershell.exe", "-NoProfile", "-Command", script], capture_output=True, text=True)
    print(f"ticker {args.action} → rc={proc.returncode} {(proc.stdout + proc.stderr).strip()[:300]}")
    return proc.returncode


def cmd_skills(args) -> int:
    settings = _settings(args)
    from .store import Store
    store = Store(settings.state_dir / "autonomy.db")
    rows = store.skill_candidates()
    print(f"{len(rows)} Skill(s) candidata(s) (publicação exige revisão humana no MVP):")
    for r in rows:
        print(f"  {r['cause_code']} → {r['action']} em {r['automation_id']} (validada {r['success_count']}x, {r['status']})")
    return 0


def cmd_circuit(args) -> int:
    settings = _settings(args)
    from .store import Store
    store = Store(settings.state_dir / "autonomy.db")
    store.set_circuit(args.automation, "CLOSED", "reset manual", None)
    store.audit("human", "circuit_reset", "reset manual via CLI", "CLOSED", automation=args.automation,
                dry_run=settings.dry_run)
    print(f"circuit breaker de {args.automation} fechado")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hermes_autonomy", description="Hermes Autonomy — Guardião das Automações")
    parser.add_argument("--config")
    parser.add_argument("--registry")
    parser.add_argument("--state-dir")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, fn, help_: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_)
        p.set_defaults(fn=fn)
        for flag in ("--config", "--registry", "--state-dir"):
            p.add_argument(flag, default=argparse.SUPPRESS)
        return p

    p = add("tick", cmd_tick, "Ciclo completo: guardian→diagnóstico→reparo→validação→escalonamento")
    p.add_argument("--only")
    p.add_argument("--include-disabled", action="store_true")
    p.add_argument("--live", action="store_true", help="DRY_RUN=false + AUTONOMOUS_REPAIR=true só nesta execução")
    p.add_argument("--fast", action="store_true")
    p.add_argument("--hermes", action="store_true", help="modo cron Hermes (silencioso quando tudo OK)")
    p.add_argument("--json", action="store_true")
    p = add("health", cmd_health, "Verificação somente leitura (EXPECTED vs ACTUAL agora)")
    p.add_argument("--only")
    p.add_argument("--include-disabled", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    add("status", cmd_status, "Modo, última rodada, incidentes recentes, circuitos e cron Hermes")
    p = add("report", cmd_report, "Relatório diário consolidado")
    p.add_argument("--date")
    p.add_argument("--send", action="store_true")
    p.add_argument("--hermes", action="store_true")
    p = add("incidents", cmd_incidents, "Lista incidentes")
    p.add_argument("--automation")
    p.add_argument("--cause")
    p.add_argument("--limit", type=int, default=30)
    p = add("incident", cmd_incident, "Detalhe completo de um incidente")
    p.add_argument("id")
    p = add("history", cmd_history, "Já teve esse problema? Como resolvemos?")
    p.add_argument("automation")
    p.add_argument("--cause")
    p = add("logs", cmd_logs, "Log de auditoria das ações autônomas")
    p.add_argument("--limit", type=int, default=40)
    p = add("registry", cmd_registry, "Valida (e lista) o automation_registry")
    p.add_argument("--list", action="store_true")
    add("discover", cmd_discover, "Tarefas do Agendador ainda fora do registry")
    p = add("event", cmd_event, "Gatilho por evento para uma automação")
    p.add_argument("automation")
    p.add_argument("--message")
    p = add("demo", cmd_demo, "Prova controlada com o canário (sandbox)")
    p.add_argument("scenario", choices=["recover", "escalate", "credential", "partial", "ok"])
    p.add_argument("--live", action="store_true")
    p.add_argument("--fast", action="store_true")
    p = add("install", cmd_install, "Instala no Hermes (app, wrappers, skills, cron jobs)")
    p.add_argument("--no-cron", action="store_true")
    p.add_argument("--no-skills", action="store_true")
    add("uninstall", cmd_uninstall, "Rollback da instalação no Hermes (preserva o histórico)")
    add("start", cmd_start_stop, "Retoma os cron jobs Hermes do guardião")
    add("stop", cmd_start_stop, "Pausa os cron jobs Hermes do guardião")
    add("skills", cmd_skills, "Skills candidatas geradas por soluções validadas")
    p = add("outbox", cmd_outbox, "Outbox local do AUTOMATION_INCIDENT: list | validate <arquivo> | emit <incident_id>")
    p.add_argument("action", choices=["list", "validate", "emit"])
    p.add_argument("target", nargs="?")
    p = add("ticker", cmd_ticker, "Relógio do cron Hermes via Agendador (sem gateway) — exige --yes")
    p.add_argument("action", choices=["install", "remove", "status"])
    p.add_argument("--minutes", type=int, default=15)
    p.add_argument("--yes", action="store_true")
    p = add("circuit-reset", cmd_circuit, "Fecha manualmente o circuit breaker de uma automação")
    p.add_argument("automation")
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_stdout()
    args = build_parser().parse_args(argv)
    for attr in ("config", "registry", "state_dir"):
        if not hasattr(args, attr):
            setattr(args, attr, None)
    return int(args.fn(args) or 0)
