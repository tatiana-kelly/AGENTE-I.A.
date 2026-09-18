"""Ponte Hermes → SAL OS: construção, validação e outbox LOCAL do evento AUTOMATION_INCIDENT
(`sal.automation-incident/1.0`, contracts/automation_incident.v1.schema.json).

Só prepara e grava localmente. NÃO há consumidor, NÃO envia ao SAL OS, NÃO chama IA.
Decisão empresarial, aprovação e verificação de resultado de negócio não existem neste módulo — o contrato
as proíbe (lista de chaves bloqueadas em FORBIDDEN_KEY, idêntica à do AI Orchestrator).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .config import PACKAGE_ROOT
from .models import now_local
from .redact import looks_like_secret, redact
from .registry import action_risk

SCHEMA_PATH = PACKAGE_ROOT / "contracts" / "automation_incident.v1.schema.json"
SCHEMA_VERSION = "sal.automation-incident/1.0"
FORBIDDEN_KEY = re.compile(r"^(approved_?decision|execute_?action|executed_?action|verified_?ok)$", re.IGNORECASE)
# chave=valor dentro de texto livre (o build_event já redige; isto barra evento montado à mão)
_INLINE_SECRET = re.compile(r"(?i)\b(api[_-]?key|apikey|[a-z_]*token|[a-z_]*secret|password|senha)\s*[:=]\s*"
                            r"(?!\[REDACTED\])[A-Za-z0-9_\-\.]{12,}")
_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None), "integer": int,
          "number": (int, float)}


def load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def event_id_for(incident_id: str, lifecycle_state: str) -> str:
    return "sha256:" + hashlib.sha256(f"{incident_id}|{lifecycle_state}".encode("utf-8")).hexdigest()


# ------------------------------------------------------------------------------------------ validação
def _schema_errors(node: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """Subconjunto de JSON Schema usado pelo contrato (sem dependência externa)."""
    errors: list[str] = []
    if "type" in schema:
        allowed = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(isinstance(node, _TYPES[t]) and not (t in ("integer", "number") and isinstance(node, bool))
                   for t in allowed):
            return [f"{path}: tipo {type(node).__name__} não permitido ({allowed})"]
    if "const" in schema and node != schema["const"]:
        errors.append(f"{path}: deve ser {schema['const']!r}")
    if "enum" in schema and node not in schema["enum"]:
        errors.append(f"{path}: {node!r} fora do enum")
    if isinstance(node, (int, float)) and not isinstance(node, bool):
        if "minimum" in schema and node < schema["minimum"]:
            errors.append(f"{path}: abaixo do mínimo")
        if "maximum" in schema and node > schema["maximum"]:
            errors.append(f"{path}: acima do máximo")
    if isinstance(node, str):
        if "pattern" in schema and not re.search(schema["pattern"], node):
            errors.append(f"{path}: não casa o padrão")
        if len(node) < schema.get("minLength", 0):
            errors.append(f"{path}: curto demais")
    if isinstance(node, dict):
        errors += [f"{path}: falta '{k}'" for k in schema.get("required", []) if k not in node]
        props = schema.get("properties", {})
        for key, value in node.items():
            if FORBIDDEN_KEY.match(key):
                errors.append(f"{path}.{key}: chave PROIBIDA (decisão empresarial não pertence ao Hermes)")
            if "propertyNames" in schema:
                errors += _schema_errors(key, schema["propertyNames"], f"{path}.<{key}>")
            if key in props:
                errors += _schema_errors(value, props[key], f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}.{key}: propriedade não permitida")
            elif isinstance(schema.get("additionalProperties"), dict):
                errors += _schema_errors(value, schema["additionalProperties"], f"{path}.{key}")
    if isinstance(node, list):
        if "maxItems" in schema and len(node) > schema["maxItems"]:
            errors.append(f"{path}: itens demais")
        for i, item in enumerate(node) if "items" in schema else []:
            errors += _schema_errors(item, schema["items"], f"{path}[{i}]")
    return errors


def _forbidden_anywhere(node: Any, path: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if FORBIDDEN_KEY.match(key):
                found.append(f"{path}.{key}")
            found += _forbidden_anywhere(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            found += _forbidden_anywhere(value, f"{path}[{i}]")
    return found


def validate_event(event: dict[str, Any], schema: dict[str, Any] | None = None) -> list[str]:
    """Schema + regras semânticas da ponte. Lista vazia = válido."""
    errors = _schema_errors(event, schema or load_schema())
    errors += [f"{p}: chave PROIBIDA" for p in _forbidden_anywhere(event) if f"{p}: chave PROIBIDA" not in errors]
    if errors:
        return sorted(set(errors))
    if event["event_id"] != event_id_for(event.get("incident_id", ""), event.get("lifecycle_state", "")):
        errors.append("event_id não corresponde a sha256(incident_id|lifecycle_state)")
    ctx, signals = event["routing_context"], event["ai_review_signals"]
    if "metric_id" in ctx and not event["requires_business_decision"]:
        errors.append("routing_context.metric_id só é permitido quando requires_business_decision=true "
                      "(incidente técnico não carrega métrica empresarial)")
    if ctx["entity_id"] != event["automation_id"]:
        errors.append("routing_context.entity_id deve ser o automation_id")
    if signals["confidence"] != event["confidence"]:
        errors.append("ai_review_signals.confidence deve espelhar confidence")
    if signals["unknown_cause"] != (event["diagnosis"]["cause_code"] == "UNKNOWN_CAUSE"):
        errors.append("ai_review_signals.unknown_cause inconsistente com diagnosis.cause_code")
    if signals["actions_attempted"] != len(event["actions_attempted"]):
        errors.append("ai_review_signals.actions_attempted deve ser o total de actions_attempted")
    if event["validation"]["status"] == "TECHNICAL_OK" and event.get("lifecycle_state") != "RESOLVED":
        errors.append("validation TECHNICAL_OK exige lifecycle_state RESOLVED")
    dump = json.dumps(event, ensure_ascii=False)
    if looks_like_secret(dump) or _INLINE_SECRET.search(dump):
        errors.append("evento contém texto com cara de segredo")
    return errors


# ------------------------------------------------------------------------------------------ construção
def registry_version(path: str | Path) -> str:
    return "registry@" + hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]


def _redact_tree(node: Any) -> Any:
    if isinstance(node, str):
        return redact(node)
    if isinstance(node, list):
        return [_redact_tree(v) for v in node]
    if isinstance(node, dict):
        return {k: _redact_tree(v) for k, v in node.items()}
    return node


def _criteria_results(evidence: list[dict[str, Any]]) -> dict[str, str]:
    results: dict[str, str] = {}
    for e in evidence:
        verdict = {True: "pass", False: "fail", None: "unverifiable"}[e.get("passed")]
        current = results.get(e["criterion"])
        if current == "fail" or (current == "pass" and verdict == "unverifiable"):
            continue
        results[e["criterion"]] = verdict
    return results


def _validation(incident: dict[str, Any], attempts: list[dict[str, Any]], check: dict[str, Any]) -> dict[str, Any]:
    live = [a for a in attempts if not a["dry_run"]]
    validated_by: list[str] = []
    if incident["state"] == "RESOLVED" and incident.get("outcome") in ("AUTO_RECOVERED", "ALREADY_OK", "DELAY_RECORDED"):
        ok = next((a for a in reversed(live) if a["result"] == "SUCCESS"), None)
        if ok and ok.get("validation"):
            validated_by = [c.strip() for c in ok["validation"].split(",") if c.strip()]
        else:
            validated_by = [e["criterion"] for e in check.get("evidence", []) if e.get("passed")]
        status = "TECHNICAL_OK"
    elif check.get("status") == "INSUFFICIENT_EVIDENCE":
        status = "INSUFFICIENT_EVIDENCE"
    elif live:
        status = "TECHNICAL_FAIL"
    else:
        status = "NOT_RUN"
    return {"scope": "technical", "status": status, "validated_by": sorted(set(validated_by))}


def build_event(store, automation: dict[str, Any], incident_id: str, settings, *, reg_version: str,
                now: datetime | None = None) -> dict[str, Any]:
    """Monta o AUTOMATION_INCIDENT a partir da memória técnica (Store). Não decide nada: só relata."""
    now = now or now_local()
    incident = store.get_incident(incident_id)
    if incident is None:
        raise KeyError(incident_id)
    check = json.loads(incident.get("check_json") or "{}")
    diagnosis = json.loads(incident.get("diagnosis_json") or "{}")
    attempts = store.attempts_for(incident_id)
    evidence = check.get("evidence", [])
    cause_code = incident.get("cause_code") or diagnosis.get("cause_code") or "UNKNOWN_CAUSE"
    confidence = float(incident.get("confidence") if incident.get("confidence") is not None
                       else diagnosis.get("confidence", 0.0))

    window_h = int(settings["circuit_breaker"]["window_hours"])
    failures = store.count_failures(automation["id"], now - timedelta(hours=window_h))
    circuit = store.get_circuit(automation["id"])
    circuit_open = bool(circuit and circuit["state"] == "OPEN")
    same_cause = store.history(automation["id"], cause_code, exclude_id=incident_id)
    hit_codes = list(dict.fromkeys(h["code"] for h in check.get("cause_hits", [])))
    from .knowledge import pattern_by_code
    hit_types = {pattern_by_code(c).incident_type for c in hit_codes if pattern_by_code(c)}

    last_ok = store.db.execute(
        "SELECT checked_at FROM checks WHERE automation_id=? AND status='SUCCESS' ORDER BY id DESC LIMIT 1",
        (automation["id"],)).fetchone()
    last_success_at = last_ok[0] if last_ok else None
    stale_hours = round((now - datetime.fromisoformat(last_success_at)).total_seconds() / 3600, 1) \
        if last_success_at else None
    verifiable = [e for e in evidence if e.get("passed") is not None]
    missing = sorted({e["criterion"] for e in evidence if e.get("passed") is None})
    requires_business = bool(automation.get("feeds_business_decision")) and incident["state"] == "ESCALATED"
    actions = [{"attempt": int(a["attempt"]), "action": a["action"], "risk_level": action_risk(a["action"]),
                "dry_run": bool(a["dry_run"]), "result": a["result"] or "PENDING"} for a in attempts]

    routing_context: dict[str, Any] = {
        "entity_type": "automation", "entity_id": automation["id"],
        "period": (incident.get("slot") or now.isoformat())[:10], "registry_version": reg_version,
        "last_success_at": last_success_at, "stale_hours": stale_hours,
        "max_age_hours": automation.get("max_age_hours"),
        "affected_outputs": list(automation.get("expected_outputs", [])), "missing_data": missing,
        "evidence_completeness_pct": round(100 * len(verifiable) / len(evidence), 1) if evidence else 0.0,
    }
    if requires_business and automation.get("business_metric_id"):
        routing_context["metric_id"] = automation["business_metric_id"]

    event = {
        "schema_version": SCHEMA_VERSION, "event_type": "AUTOMATION_INCIDENT",
        "event_id": event_id_for(incident_id, incident["state"]), "source": "hermes-autonomy",
        "automation_id": automation["id"], "automation_name": automation.get("name", automation["id"]),
        "project_id": automation.get("project_id"), "incident_id": incident_id,
        "root_cause_id": incident.get("root_cause_id"), "timestamp": now.isoformat(),
        "severity": incident.get("priority") or "P2", "incident_type": incident["type"],
        "lifecycle_state": incident["state"], "outcome": incident.get("outcome"),
        "expected": {"window": incident.get("slot"),
                     "criteria": sorted({e["criterion"] for e in evidence}),
                     "outputs": list(automation.get("expected_outputs", []))},
        "actual": {"run_started_at": check.get("run_started_at"), "criteria_results": _criteria_results(evidence),
                   "summary": (check.get("findings") or [""])[0][:500]},
        "evidence": [{"criterion": e["criterion"], "result": {True: "pass", False: "fail", None: "unverifiable"}[
                      e.get("passed")], "source": e.get("source", "?"), "detail": e.get("detail", "")[:500],
                      "ref": automation.get("task_name") if e.get("source") == "task_scheduler" else None}
                     for e in evidence[:50]],
        "diagnosis": {"cause_code": cause_code, "probable_cause": incident.get("probable_cause")
                      or diagnosis.get("probable_cause", ""), "cause_key": incident.get("cause_key")
                      or diagnosis.get("cause_key", ""), "transient": bool(diagnosis.get("transient", False)),
                      "investigation_steps": [{"step": s["step"], "name": s["name"], "result": s["result"][:300]}
                                              for s in diagnosis.get("steps", [])]},
        "confidence": confidence,
        "actions_attempted": actions,
        "validation": _validation(incident, attempts, check),
        "recurrence": {"count": len(same_cause), "last_resolution": diagnosis.get("last_resolution"),
                       "circuit_breaker_open": circuit_open},
        "requires_human": incident["state"] == "ESCALATED",
        "human_action": incident.get("human_action"),
        "requires_business_decision": requires_business,
        "business_impact": automation.get("impact"),
        "authority": {"can_repair_technical_low_risk": bool(automation.get("allowed_recovery_actions"))
                      and automation.get("idempotent") is True,
                      "can_approve_business_decision": False, "can_execute_business_action": False,
                      "can_declare_business_verified": False},
        "ai_review_signals": {
            "unknown_cause": cause_code == "UNKNOWN_CAUSE", "confidence": confidence,
            "conflicting_evidence": {"present": len(hit_types) >= 2, "cause_codes": hit_codes},
            "repeated_failure": {"present": failures >= 2 or circuit_open, "count_window": failures,
                                 "window_hours": window_h,
                                 "auto_recovered_same_cause": sum(1 for r in same_cause
                                                                  if r.get("outcome") == "AUTO_RECOVERED"),
                                 "circuit_breaker_open": circuit_open},
            "actions_attempted": len(actions)},
        "routing_context": routing_context,
        "audit_ref": incident_id,
    }
    return _redact_tree(event)


# ------------------------------------------------------------------------------------------ outbox
class IncidentOutbox:
    """Outbox LOCAL append-only. Só grava evento VÁLIDO; inválido vai para rejected.jsonl com os erros.
    Idempotente por event_id. Sem consumidor: nada sai desta máquina."""

    def __init__(self, directory: str | Path):
        self.dir = Path(directory)
        self.path = self.dir / "automation_incidents.jsonl"
        self.rejected = self.dir / "rejected.jsonl"

    def _ids(self) -> set[str]:
        if not self.path.exists():
            return set()
        with open(self.path, encoding="utf-8") as fh:
            return {json.loads(line)["event_id"] for line in fh if line.strip()}

    def _append(self, path: Path, record: dict[str, Any]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def emit(self, event: dict[str, Any]) -> tuple[str, list[str]]:
        errors = validate_event(event)
        if errors:
            self._append(self.rejected, {"rejected_at": now_local().isoformat(), "event_id": event.get("event_id"),
                                         "incident_id": event.get("incident_id"), "errors": errors})
            return "REJECTED", errors
        if event["event_id"] in self._ids():
            return "DUPLICATE", []
        self._append(self.path, event)
        return "WRITTEN", []

    def events(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with open(self.path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]
