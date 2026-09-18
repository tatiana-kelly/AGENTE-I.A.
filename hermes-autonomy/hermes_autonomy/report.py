"""Relatório diário consolidado — substitui a enxurrada de e-mails individuais."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, time
from typing import Any

from .models import now_local


def daily_report(store, automations: list[dict[str, Any]], settings, day: datetime | None = None) -> dict[str, Any]:
    now = now_local()
    start = datetime.combine((day or now).date(), time(0, 0), now.tzinfo)
    monitored = [a for a in automations if a.get("enabled", True)]
    latest = {c["automation_id"]: c for c in store.latest_checks(start)}
    incidents = [i for i in store.incidents(since=start, limit=1000) if not i["is_root"]]
    roots = [i for i in store.incidents(since=start, limit=200) if i["is_root"]]
    outcomes = Counter(i["outcome"] for i in incidents)

    success = sum(1 for a in monitored if latest.get(a["id"], {}).get("status") == "SUCCESS")
    recovered = outcomes["AUTO_RECOVERED"] + outcomes["ALREADY_OK"]
    delayed = sum(1 for i in incidents if i["type"] == "DELAYED_EXECUTION")
    escalated = [i for i in incidents if i["state"] == "ESCALATED" and i["type"] != "DELAYED_EXECUTION"]
    failed = sum(1 for a in monitored if latest.get(a["id"], {}).get("status") == "INCIDENT"
                 and latest[a["id"]].get("incident_type") != "DELAYED_EXECUTION")
    no_evidence = sum(1 for a in monitored if latest.get(a["id"], {}).get("status") == "INSUFFICIENT_EVIDENCE")
    top = Counter(i["cause_code"] or i["type"] for i in incidents if i["type"] != "DELAYED_EXECUTION").most_common(3)
    names = {a["id"]: a["name"] for a in automations}
    actions = [e for e in store.audit_entries(since=start, limit=500)
               if e["agent"] in ("hermes-repair-agent", "hermes-validator") and e["action"] != "idempotency_check"]
    pending = [i for i in escalated if i["human_action"] or i["outcome"] in ("ESCALATED", "CIRCUIT_BREAKER_OPEN",
                                                                              "DRY_RUN_PLANNED")]

    lines = [
        settings["report"]["title"] + "\n" + "=" * len(settings["report"]["title"]),
        f"Período:\n{start:%d/%m/%Y} (até {now:%H:%M})",
        f"Modo:\n{'DRY_RUN (somente leitura/simulação)' if settings.dry_run else 'LIVE'}"
        f"{' + AUTONOMOUS_REPAIR' if settings.live_repairs_enabled else ''}",
        f"Automações:\n{len(monitored)} monitoradas",
        f"SUCCESS:\n{success}",
        f"AUTO-RECOVERED:\n{recovered}",
        f"DELAYED:\n{delayed}",
        f"FAILED (última verificação em incidente):\n{failed}",
        f"ESCALATED:\n{len(escalated)}" + (f" (+{len(roots)} incidente(s) raiz)" if roots else ""),
        f"SEM EVIDÊNCIA VERIFICÁVEL:\n{no_evidence}",
        "Top problemas:\n" + ("\n".join(f"{n}. {code} ({count}x)" for n, (code, count) in enumerate(top, 1))
                               or "nenhum"),
        "Ações realizadas:\n" + ("\n".join(f"- {e['ts'][11:16]} {e['agent']} {e['action']} → {e['result']}"
                                          f"{' (simulado)' if e['dry_run'] else ''} [{names.get(e['automation'], e['automation'])}]"
                                          for e in actions[:15]) or "nenhuma"),
        "Ações pendentes:\n" + ("\n".join(
            f"- [{i['priority']}] {names.get(i['automation_id'], i['automation_id'])}: "
            f"{i['human_action'] or i['probable_cause'] or i['type']} ({i['id']})" for i in pending[:15]) or "nenhuma"),
    ]
    return {"text": "\n\n".join(lines), "counts": {
        "monitored": len(monitored), "success": success, "auto_recovered": recovered, "delayed": delayed,
        "failed": failed, "escalated": len(escalated), "insufficient_evidence": no_evidence}}
