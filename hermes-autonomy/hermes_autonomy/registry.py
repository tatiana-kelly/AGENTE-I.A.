"""automation_registry: catálogo versionado (JSON no repositório) das automações supervisionadas."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from .redact import looks_like_secret

KNOWN_SOURCES = {"windows_task", "command", "github_actions", "hermes_cron"}
KNOWN_CHECKS = {"file", "http_status", "http_freshness", "command"}
KNOWN_KINDS = {"log", "output", "data", "delivery", "dependency"}
CRITICALITY = {"critical", "high", "medium", "low"}

# Matriz de permissões do Reparador (PRP §13). Ações HIGH nunca executam automaticamente.
ACTION_RISK: dict[str, str] = {
    "rerun_task": "low",
    "rerun_command": "low",
    "restart_task": "low",
    "cleanup_temp": "low",
    "validate_output": "low",
    "adjust_timeout": "medium",
    "switch_endpoint": "medium",
    "delete_data": "high",
    "alter_schema": "high",
    "rotate_credentials": "high",
    "modify_code": "high",
    "delete_files": "high",
}


class RegistryError(ValueError):
    pass


def _render_vars(value: Any, variables: dict[str, str]) -> Any:
    if isinstance(value, str):
        for key, val in variables.items():
            value = value.replace("{" + key + "}", str(val))
        return value
    if isinstance(value, list):
        return [_render_vars(v, variables) for v in value]
    if isinstance(value, dict):
        return {k: _render_vars(v, variables) for k, v in value.items()}
    return value


def _expand(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Uma entrada com `instances` vira N automações (ex.: mesma rotina em vários horários)."""
    instances = entry.get("instances")
    if not instances:
        return [entry]
    base = {k: v for k, v in entry.items() if k != "instances"}
    expanded = []
    for inst in instances:
        variables = inst.get("vars", {})
        item = _render_vars(deepcopy(base), variables)
        item.update({k: v for k, v in inst.items() if k not in ("vars", "suffix")})
        item["id"] = f"{base['id']}-{inst['suffix']}"
        item["name"] = f"{base['name']} {inst.get('label', inst['suffix'])}".strip()
        item["group"] = base["id"]
        expanded.append(item)
    return expanded


def validate_automation(a: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in ("id", "name", "source", "schedule", "enabled"):
        if key not in a:
            errors.append(f"{a.get('id', '?')}: campo obrigatório ausente: {key}")
    if a.get("source") not in KNOWN_SOURCES:
        errors.append(f"{a.get('id')}: source inválido {a.get('source')!r}")
    if a.get("source") == "windows_task" and not a.get("task_name"):
        errors.append(f"{a.get('id')}: windows_task exige task_name")
    if a.get("source") == "command" and not a.get("command"):
        errors.append(f"{a.get('id')}: source command exige command")
    for action in a.get("allowed_recovery_actions", []):
        if action not in ACTION_RISK:
            errors.append(f"{a.get('id')}: ação de recuperação desconhecida {action!r}")
    if a.get("risk_level", "low") not in ("low", "medium", "high"):
        errors.append(f"{a.get('id')}: risk_level inválido")
    if a.get("criticality", "medium") not in CRITICALITY:
        errors.append(f"{a.get('id')}: criticality inválida")
    for check in a.get("checks", []):
        if check.get("type") not in KNOWN_CHECKS:
            errors.append(f"{a.get('id')}: check type inválido {check.get('type')!r}")
        if check.get("kind", "output") not in KNOWN_KINDS:
            errors.append(f"{a.get('id')}: check kind inválido {check.get('kind')!r}")
    if looks_like_secret(json.dumps(a, ensure_ascii=False)):
        errors.append(f"{a.get('id')}: possível segredo literal no registry — use {{env:NOME}}")
    return errors


def load_registry(path: str | Path) -> list[dict[str, Any]]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    entries = document["automations"] if isinstance(document, dict) else document
    automations: list[dict[str, Any]] = []
    for entry in entries:
        automations.extend(_expand(entry))
    errors: list[str] = []
    seen: set[str] = set()
    for a in automations:
        errors.extend(validate_automation(a))
        if a.get("id") in seen:
            errors.append(f"id duplicado: {a.get('id')}")
        seen.add(a.get("id"))
    if errors:
        raise RegistryError("; ".join(errors))
    return automations


def action_risk(action: str) -> str:
    return ACTION_RISK.get(action, "high")
