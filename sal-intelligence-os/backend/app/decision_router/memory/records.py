"""Registros da memória persistente do Decision Router (espelham a migration decision_router_memory).

Separação obrigatória de conceitos — cada um tem campo próprio e nunca é inferido de outro:
  APRENDIZADO (Torre/ledger)  ≠  DECISÃO PROPOSTA  ≠  DECISÃO APROVADA  ≠  AÇÃO  ≠  RESULTADO VERIFICADO
O Router só grava rota e referências; decisão, ação e verificação vêm dos fluxos humanos existentes
(decisions / action_executions / organizational_learnings) e aqui ficam apenas como id + status.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DecisionStatus = Literal["none", "proposed", "approved", "rejected", "request_more_evidence"]
ActionStatus = Literal["none", "open", "in_progress", "completed", "cancelled"]
VerificationStatus = Literal["none", "ok", "partial", "fail"]
PlaybookStatus = Literal["draft", "pending_approval", "active", "suspended", "retired"]


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CaseRecord(_Closed):
    id: str
    alert_id: str
    source: str
    metric_id: str
    case_type: str
    exact_fingerprint: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    pattern_key: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    lineage_key: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    status: Literal["ROUTED", "BLOCKED_DATA", "ESCALATED"]
    route: Literal["NO_AGENT", "REUSE_DECISION", "ONE_AGENT", "MULTI_AGENT", "INVESTIGATE_FIRST"]
    route_reason: str
    observed_at: datetime
    created_at: datetime
    updated_at: datetime
    period: str
    engine_source: str
    entity_type: str
    entity_id: str
    direction: Literal["up", "down", "flat"]
    dominant_dimension: str | None
    magnitude_band: str
    rules_version: str
    approval_flags: tuple[str, ...] = ()
    priority_score: float | None = None
    priority_label: str | None = None
    quality_passed: bool
    quality_score: int = Field(ge=0, le=100)
    source_quality: str
    selected_agents: tuple[str, ...] = ()
    estimated_ai_calls: int = Field(ge=0)
    deterministic_outcome: str | None = None
    # referências aos fluxos humanos existentes — nunca preenchidas pelo Router
    decision_id: str | None = None
    decision_status: DecisionStatus = "none"
    approved_at: datetime | None = None
    diagnosis_confidence: float | None = Field(default=None, ge=0, le=100)
    diagnosis_status: str | None = None
    hypotheses: tuple[dict, ...] = ()
    recommendation: dict | None = None
    action_id: str | None = None
    action_status: ActionStatus = "none"
    verification_status: VerificationStatus = "none"
    verification_result: str | None = None
    recurrence: bool | None = None
    learning_id: str | None = None
    learning_predicted_impact: float | None = None
    learning_actual_impact: float | None = None
    reopen_count: int = Field(default=0, ge=0)
    escalation_count: int = Field(default=0, ge=0)
    evidence: tuple[dict, ...] = ()
    route_payload: dict | None = None  # DecisionRoute completo, para idempotência (replay idêntico)


class PatternStatsRecord(_Closed):
    pattern_key: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    occurrences: int = Field(default=0, ge=0)
    false_positives: int = Field(default=0, ge=0)
    approved_decisions: int = Field(default=0, ge=0)
    reuse_count: int = Field(default=0, ge=0)
    reuse_verified_fail: int = Field(default=0, ge=0)
    verified_ok: int = Field(default=0, ge=0)
    verified_fail: int = Field(default=0, ge=0)
    reopened: int = Field(default=0, ge=0)
    agent_calls: int = Field(default=0, ge=0)
    useful_agent_calls: int = Field(default=0, ge=0)
    ai_routed_cases: int = Field(default=0, ge=0)
    last_seen_at: datetime | None = None
    rules_version: str | None = None
    current_magnitude_band: str | None = None
    reuse_blocked: bool = False
    reuse_blocked_reason: str | None = None
    updated_at: datetime | None = None

    @property
    def avg_calls(self) -> float | None:
        return round(self.agent_calls / self.ai_routed_cases, 2) if self.ai_routed_cases else None


class PlaybookRecord(_Closed):
    id: str
    pattern_key: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    case_type: str
    name: str
    version: int = Field(default=1, ge=1)
    conditions: dict
    recommended_action: dict
    rules_version: str
    magnitude_band: str
    approved_count: int = Field(default=0, ge=0)
    verified_ok_count: int = Field(default=0, ge=0)
    verified_fail_count: int = Field(default=0, ge=0)
    status: PlaybookStatus = "draft"
    approved_by: str | None = None
    approved_at: datetime | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    created_at: datetime
    updated_at: datetime
