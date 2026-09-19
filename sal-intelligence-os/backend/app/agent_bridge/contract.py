"""Contrato sal.agent-run/1.0 visto do lado do SAL OS (espelha src/agentRuns/contract.ts do Orchestrator).

O SAL OS envia investigação e recebe FATO / CÁLCULO / INFERÊNCIA / HIPÓTESE. O que volta é INSUMO:
não é diagnóstico aprovado, não é recomendação aceita, não é decisão e não autoriza ação.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

PROTOCOL_VERSION = "sal.agent-run/1.0"
OUTPUT_SCHEMA_VERSION = "sal.investigation-output/1.0"

LIMITS = {
    "body_bytes": 512 * 1024,
    "task_chars": 20_000,
    "previous_results_items": 20,
    "previous_result_item_chars": 100_000,
    "previous_results_total_chars": 300_000,
    "business_data_bytes": 256 * 1024,
    "timeout_seconds_max": 240,
    "attempts_max": 3,
    "max_cost_usd_per_call": 10.0,
    "max_cost_usd_per_job": 100.0,
}


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AgentAuthority(_Closed):
    """Investigação não recomenda, não propõe, não aprova e não executa."""

    can_recommend: bool = False
    can_propose: bool = False
    can_approve: Literal[False] = False
    can_execute: Literal[False] = False


class EvidenceQuality(_Closed):
    source_quality: str
    completeness_pct: float | None = Field(default=None, ge=0, le=100)
    checks: tuple[str, ...] = ()


class Evidence(_Closed):
    id: str
    source: str
    period: str
    timestamp: datetime
    filters: dict[str, Any] = Field(default_factory=dict)
    quality: EvidenceQuality
    limitations: tuple[str, ...] = ()
    data: Any


class AuthorizedContext(_Closed):
    project: str
    files: tuple[str, ...] = Field(min_length=1)


class ExecutionLimits(_Closed):
    timeout_seconds: int = Field(gt=0, le=LIMITS["timeout_seconds_max"])
    max_attempts: int = Field(gt=0, le=LIMITS["attempts_max"])
    max_cost_usd_per_call: float = Field(gt=0, le=LIMITS["max_cost_usd_per_call"])
    max_cost_usd_per_job: float = Field(gt=0, le=LIMITS["max_cost_usd_per_job"])


class OutputContract(_Closed):
    kind: Literal["investigation"] = "investigation"
    schema_version: Literal[OUTPUT_SCHEMA_VERSION] = OUTPUT_SCHEMA_VERSION
    require_json: Literal[True] = True


class ReviewPolicy(_Closed):
    required: bool = True
    max_correction_attempts: int = Field(default=1, ge=0, le=LIMITS["attempts_max"])


class Hypothesis(_Closed):
    statement: str
    favorable_evidence: tuple[str, ...] = ()
    contrary_evidence: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    confidence: float = Field(ge=0, le=100)


class RecommendedAction(_Closed):
    """Ação RECOMENDADA (decisão da Tatiana, 2026-09-19). Recomendar não é aprovar nem executar."""

    action: str
    owner_role: str
    deadline: str
    kpi: str
    evidence: tuple[str, ...] = ()
    risk_of_inaction: str = ""


class InvestigationOutput(_Closed):
    """Insumo de investigação. Não possui campo de decisão, ação ou resultado verificado — por construção."""

    facts: tuple[str, ...] = ()
    calculations: tuple[str, ...] = ()
    inferences: tuple[str, ...] = ()
    hypotheses: tuple[Hypothesis, ...] = ()
    contradictions: tuple[str, ...] = ()
    missing_data: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    confidence: float = Field(ge=0, le=100)
    # opcional: só aparece quando o agente foi autorizado a recomendar (agent_authority.can_recommend)
    recommended_actions: tuple[RecommendedAction, ...] | None = None


class ConsolidationSource(_Closed):
    agent: str
    status: str
    run_id: str | None = None
    request_id: str | None = None


class ReviewTarget(_Closed):
    """Revisão CONSOLIDADA (MULTI_AGENT): o artefato é a consolidação determinística feita pelo SAL OS."""

    kind: Literal["consolidated_investigation"] = "consolidated_investigation"
    output: InvestigationOutput
    author_providers: tuple[Literal["anthropic", "openai"], ...] = Field(min_length=1, max_length=2)
    sources: tuple[ConsolidationSource, ...] = Field(min_length=1, max_length=10)


class AgentRunRequest(_Closed):
    protocol_version: Literal[PROTOCOL_VERSION] = PROTOCOL_VERSION
    request_id: str
    idempotency_key: str = Field(min_length=16, max_length=200)
    principal: str
    permission: Literal["agent_run"] = "agent_run"
    project: str
    agent: str
    agent_version: str
    profile: Literal["fast", "balanced", "critical", "adversarial", "builder"]
    task: str = Field(min_length=1, max_length=LIMITS["task_chars"])
    authorized_context: AuthorizedContext
    evidence: tuple[Evidence, ...] = ()
    previous_results: tuple[str, ...] = ()
    business_data: dict[str, Any] = Field(default_factory=dict)
    execution_limits: ExecutionLimits
    output_contract: OutputContract = OutputContract()
    review_policy: ReviewPolicy = ReviewPolicy()
    agent_authority: AgentAuthority = AgentAuthority()
    review_target: ReviewTarget | None = None


class AgentRunResult(BaseModel):
    """Resposta do Orchestrator já validada pelo SAL OS."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    protocol_version: str
    request_id: str
    run_id: str
    status: str
    agent: str
    agent_version: str
    agent_authority: AgentAuthority
    output: InvestigationOutput | None = None
    output_validation: dict[str, Any]
    review: dict[str, Any]
    providers: dict[str, Any]
    usage: tuple[dict[str, Any], ...] = ()
    context: dict[str, Any]
    evidence_received: tuple[str, ...] = ()
    replayed: bool = False
    created_at: str
    mode: str = "investigation"

    @property
    def usable(self) -> bool:
        """Só há insumo aproveitável quando o output foi validado pelo contrato."""
        return self.output is not None and bool(self.output_validation.get("valid"))
