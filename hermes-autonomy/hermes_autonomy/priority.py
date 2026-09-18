"""Prioridade P0–P3: importância da automação, impacto, duração, recorrência, abrangência."""
from __future__ import annotations

from datetime import datetime
from typing import Any

_CRITICALITY = {"critical": 3, "high": 2, "medium": 1, "low": 0}
_TYPE_WEIGHT = {
    "DELAYED_EXECUTION": 0,
    "UNKNOWN_FAILURE": 1,
}
_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def compute_priority(automation: dict[str, Any], incident_type: str, *, recurrence: int = 0, affected: int = 1,
                     unresolved: bool = False, slot: str | None = None, now: datetime | None = None) -> str:
    score = _CRITICALITY.get(automation.get("criticality", "medium"), 1)
    score += _TYPE_WEIGHT.get(incident_type, 2)
    if recurrence >= 2:
        score += 1
    if affected >= 3:
        score += 1
    if unresolved:
        score += 1
    if slot and now:
        age_hours = (now - datetime.fromisoformat(slot)).total_seconds() / 3600
        if age_hours >= 4:
            score += 1
    if score >= 6:
        return "P0"
    if score >= 4:
        return "P1"
    if score >= 2:
        return "P2"
    return "P3"


def at_least(priority: str, threshold: str) -> bool:
    """True se `priority` é tão ou mais grave que `threshold` (P0 é o mais grave)."""
    return _ORDER.get(priority, 3) <= _ORDER.get(threshold, 1)
