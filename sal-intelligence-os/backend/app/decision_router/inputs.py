"""Entradas do Decision Router e modelos do estado que ele consulta (somente leitura).

AlertBase não é alterado: AlertEnvelope o envolve com o que a especificação exige e o alerta não traz
(motor de origem, entidade, momento da avaliação, versão das regras, sinais do motor).
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.alert import AlertBase
from app.schemas.enums import DecisionOutcome, DecisionStatus, HypothesisStatus

Direction = Literal["up", "down", "flat"]


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class QualityInputs(_Closed):
    last_updated_at: datetime | None = None
    max_age_hours: float | None = Field(default=None, gt=0)
    current_grain: str | None = None
    reference_grain: str | None = None


class EngineSignals(_Closed):
    """Resultados já calculados pelos motores existentes — o Router consulta, não recalcula."""

    single_day: bool = False
    window_class: str | None = None
    coverage_scope: str | None = None
    coverage_pct: float | None = Field(default=None, ge=0, le=100)
    category: str | None = None


class LoopState(_Closed):
    hop: int = Field(default=0, ge=0)
    reopen_count: int = Field(default=0, ge=0)
    is_reopen: bool = False


class AlertEnvelope(_Closed):
    alert: AlertBase
    engine_source: str = Field(min_length=1)
    entity_type: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    evaluated_at: datetime
    rules_version: str = Field(min_length=1)
    approval_flags: tuple[str, ...] = ()
    missing_data: tuple[str, ...] = ()
    quality_inputs: QualityInputs | None = None
    signals: EngineSignals = Field(default_factory=EngineSignals)
    loop: LoopState = Field(default_factory=LoopState)
    priority_dimensions: dict[str, float] | None = None


class MemoryEntry(_Closed):
    """Memória de conhecido/falso positivo no formato do registro de aprendizado da Torre."""

    engine_source: str
    direction: Direction
    delta: float | None = None
    magnitude_band: str
    status: Literal["ABERTA", "RESOLVIDA"]
    causa: str | None = None
    false_positive_active: bool = False
    false_positive_reason: str | None = None
    source_ref: str = Field(min_length=1)


class ReferenceDiagnosis(_Closed):
    confidence: float = Field(ge=0, le=100)
    decision_status: DecisionStatus
    hypothesis_statuses: tuple[HypothesisStatus, ...]
    missing_data: tuple[str, ...] = ()


class ReferenceDecision(_Closed):
    decision_id: str
    outcome: DecisionOutcome


class ReferenceAction(_Closed):
    action_execution_id: str
    outcome: Literal["ok", "partial", "fail"] | None
    recurrence: bool | None


class ReferenceLearning(_Closed):
    learning_id: str
    predicted_impact: float | None
    actual_impact: float | None


class ReferenceCase(_Closed):
    case_id: str
    period: str
    evaluated_at: datetime
    engine_source: str
    direction: Direction
    magnitude_band: str
    dominant_dimension: str | None
    rules_version: str
    approval_flags: tuple[str, ...] = ()
    reopen_count: int = Field(default=0, ge=0)
    diagnosis: ReferenceDiagnosis | None = None
    decision: ReferenceDecision | None = None
    action: ReferenceAction | None = None
    learning: ReferenceLearning | None = None


class PatternStats(_Closed):
    decisions_approved: int = Field(default=0, ge=0)
    verified_ok: int = Field(default=0, ge=0)
    verified_fail: int = Field(default=0, ge=0)
    reopen_total: int = Field(default=0, ge=0)
    reuse_verified_fail: int = Field(default=0, ge=0)
    reuse_blocked: bool = False
    reuse_blocked_reason: str | None = None
    ai_cases: int = Field(default=0, ge=0)
    ai_cost_usd_total: float = Field(default=0.0, ge=0)


class Playbook(_Closed):
    playbook_id: str
    version: int = Field(ge=1)
    status: Literal["draft", "pending_approval", "active", "suspended", "retired"]
    rules_version: str
    valid_from: datetime | None = None
    valid_until: datetime | None = None
