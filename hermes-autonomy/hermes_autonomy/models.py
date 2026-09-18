"""Tipos de domínio do Hermes Autonomy (Guardião Autônomo das Automações)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class IncidentType(str, Enum):
    MISSED_EXECUTION = "MISSED_EXECUTION"
    DELAYED_EXECUTION = "DELAYED_EXECUTION"
    FAILED_EXECUTION = "FAILED_EXECUTION"
    PARTIAL_EXECUTION = "PARTIAL_EXECUTION"
    MISSING_OUTPUT = "MISSING_OUTPUT"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    DATA_NOT_UPDATED = "DATA_NOT_UPDATED"
    DELIVERY_FAILURE = "DELIVERY_FAILURE"
    AUTHENTICATION_FAILURE = "AUTHENTICATION_FAILURE"
    API_FAILURE = "API_FAILURE"
    DEPENDENCY_FAILURE = "DEPENDENCY_FAILURE"
    RESOURCE_FAILURE = "RESOURCE_FAILURE"
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"
    RECURRING_FAILURE = "RECURRING_FAILURE"
    ROOT_CAUSE_INCIDENT = "ROOT_CAUSE_INCIDENT"


class CheckStatus(str, Enum):
    SUCCESS = "SUCCESS"
    INCIDENT = "INCIDENT"
    PENDING = "PENDING"  # ainda dentro da janela / rodando dentro do limite
    NOT_SCHEDULED = "NOT_SCHEDULED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    DISABLED = "DISABLED"


class Criterion(str, Enum):
    PROCESS_STARTED = "PROCESS_STARTED"
    ON_TIME = "ON_TIME"
    PROCESS_FINISHED = "PROCESS_FINISHED"
    OUTPUT_EXISTS = "OUTPUT_EXISTS"
    OUTPUT_VALID = "OUTPUT_VALID"
    DATA_UPDATED = "DATA_UPDATED"
    DELIVERY_COMPLETED = "DELIVERY_COMPLETED"
    DEPENDENCY_OK = "DEPENDENCY_OK"


class Lifecycle(str, Enum):
    DETECTED = "DETECTED"
    CLASSIFIED = "CLASSIFIED"
    DIAGNOSING = "DIAGNOSING"
    DIAGNOSED = "DIAGNOSED"
    REPAIRING = "REPAIRING"
    VALIDATING = "VALIDATING"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


TERMINAL_STATES = {Lifecycle.RESOLVED.value, Lifecycle.ESCALATED.value}


class Outcome(str, Enum):
    AUTO_RECOVERED = "AUTO_RECOVERED"
    ALREADY_OK = "ALREADY_OK"  # idempotência: estado esperado já presente, nada executado
    ESCALATED = "ESCALATED"
    ESCALATED_WITH_ACTION_REQUIRED = "ESCALATED_WITH_ACTION_REQUIRED"
    CIRCUIT_BREAKER_OPEN = "CIRCUIT_BREAKER_OPEN"
    DRY_RUN_PLANNED = "DRY_RUN_PLANNED"
    RATE_LIMITED = "RATE_LIMITED"
    DELAY_RECORDED = "DELAY_RECORDED"  # executou atrasado mas com saídas validadas: registra, não repara


class Priority(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


RISK_ORDER = {"low": 0, "medium": 1, "high": 2}


@dataclass
class Evidence:
    criterion: str
    passed: bool | None  # None = não verificável
    source: str
    detail: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class CheckResult:
    automation_id: str
    status: str
    checked_at: str
    slot: str | None = None
    incident_type: str | None = None
    evidence: list[Evidence] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    log_excerpt: str = ""
    cause_hint: str | None = None  # código de causa detectado já no Guardião (padrões de log/código)
    cause_hits: list[dict[str, str]] = field(default_factory=list)  # [{code, line}] evidência textual
    run_started_at: str | None = None

    @property
    def is_incident(self) -> bool:
        return self.status == CheckStatus.INCIDENT.value

    def validated_by(self) -> str:
        ok = [e.criterion for e in self.evidence if e.passed]
        return ", ".join(dict.fromkeys(ok)) or "nenhuma evidência positiva"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Diagnosis:
    cause_code: str
    probable_cause: str
    evidence: list[str]
    confidence: float
    impact: str
    recommended_action: str
    auto_action: str | None
    risk: str
    transient: bool
    human_action_required: str | None
    cause_key: str
    steps: list[dict[str, str]] = field(default_factory=list)
    recurrence: int = 0
    last_resolution: str | None = None

    @property
    def confidence_label(self) -> str:
        if self.confidence >= 0.8:
            return "ALTA"
        if self.confidence >= 0.5:
            return "MÉDIA"
        return "BAIXA"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def now_local() -> datetime:
    return datetime.now().astimezone().replace(microsecond=0)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None
