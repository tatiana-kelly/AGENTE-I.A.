"""Contrato sal.decision-route/1.0 — saída do Decision Router.

O Router é uma camada NOVA e somente de leitura: recebe um AlertBase (envolvido por AlertEnvelope)
e devolve uma rota. Não chama IA, não grava Decision, não cria ação. Objeto fechado e imutável:
propriedades desconhecidas são rejeitadas e as invariantes de cada rota são verificadas na criação.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CONTRACT_VERSION = "sal.decision-route/1.0"
MISSING_BAND = "MISSING"
UNKNOWN_CASE_TYPE = "UNKNOWN"

Route = Literal["NO_AGENT", "REUSE_DECISION", "ONE_AGENT", "MULTI_AGENT", "INVESTIGATE_FIRST"]
RouteStatus = Literal["ROUTED", "BLOCKED_DATA", "ESCALATED"]
GateName = Literal[
    "loop_guard", "quality", "rule", "memory", "similar", "decision", "learning", "playbook", "ai"
]
# pass = a porta avaliou dados e não resolveu; skipped = não havia dado aplicável para a porta.
GateResult = Literal["pass", "blocked", "resolved", "skipped"]
AgentRole = Literal["investigate", "specialist", "challenge"]
CostBasis = Literal["pattern_history", "reserved_ceiling", "unknown"]
MappingConfidence = Literal["ALTA", "MEDIA", "UNKNOWN"]
NextAction = Literal["close_case", "monitor", "propose_decision", "run_agents", "collect_evidence", "await_human"]
OwnerSystem = Literal["sal-os", "ai-orchestrator", "torre-engine", "human"]

SHA256_TAGGED = r"^sha256:[a-f0-9]{64}$"
FIRST_ROUND_ROLES = {"investigate", "specialist", "challenge"}


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceItem(_Closed):
    kind: Literal[
        "alert", "data_quality", "rule", "memory_ledger", "similar_case", "decision", "learning", "playbook",
        "engine_signal",
    ]
    ref: str = Field(min_length=1, max_length=500)
    sha256: str = Field(pattern=SHA256_TAGGED)
    summary: str | None = Field(default=None, max_length=300)


class QualityStatus(_Closed):
    passed: bool
    score: int = Field(ge=0, le=100)
    reasons: tuple[str, ...] = ()


class PriorityStatus(_Closed):
    score: float | None = Field(ge=0, le=100)
    label: str | None
    human_approval_required: bool
    triggered_gates: tuple[str, ...] = ()


class SelectedAgent(_Closed):
    agent_name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
    role: AgentRole
    why: str = Field(min_length=1, max_length=300)


class DeterministicResolution(_Closed):
    resolved_by: Literal["quality_gate", "rule", "memory", "playbook"]
    outcome: Literal[
        "dismissed", "known_no_change", "false_positive", "monitor", "playbook_applied", "data_insufficient"
    ]
    rule_ref: str = Field(min_length=1, max_length=300)


class PlaybookRef(_Closed):
    playbook_id: str = Field(min_length=1)
    version: int = Field(ge=1)


class Fingerprints(_Closed):
    version: Literal["fp/1"]
    exact: str = Field(pattern=SHA256_TAGGED)
    pattern_key: str = Field(pattern=SHA256_TAGGED)
    lineage_key: str = Field(pattern=SHA256_TAGGED)


class SimilarityReference(_Closed):
    case_id: str = Field(min_length=1)
    match_level: Literal["exact", "similar"]
    material_change: bool
    material_change_reasons: tuple[str, ...] = ()


class NextStep(_Closed):
    action: NextAction
    owner_system: OwnerSystem
    missing_evidence: tuple[str, ...] = ()
    evidence_sources: tuple[str, ...] = ()


class GateTraceEntry(_Closed):
    gate: GateName
    result: GateResult
    reason: str = Field(min_length=1, max_length=500)
    rule_ref: str | None = None


class LoopGuard(_Closed):
    hop: int = Field(ge=0)
    max_hops: Literal[3] = 3
    reopen_count: int = Field(ge=0)
    max_reopen: Literal[2] = 2


class DecisionRoute(_Closed):
    contract_version: Literal["sal.decision-route/1.0"]
    status: RouteStatus
    route: Route
    reason: str = Field(min_length=1, max_length=1000)
    metric_id: str = Field(min_length=1)
    case_type: str = Field(min_length=1)
    mapping_confidence: MappingConfidence
    evaluated_at: datetime
    evidence: tuple[EvidenceItem, ...] = Field(max_length=50)
    quality: QualityStatus
    priority: PriorityStatus
    selected_agents: tuple[SelectedAgent, ...] = Field(max_length=6)
    deterministic_resolution: DeterministicResolution | None
    reused_decision_id: str | None
    reused_learning_id: str | None
    playbook: PlaybookRef | None
    fingerprints: Fingerprints
    similarity_reference: SimilarityReference | None
    estimated_ai_calls: int = Field(ge=0, le=8)
    estimated_ai_cost_avoided_usd: float | None = Field(ge=0)
    cost_basis: CostBasis
    confidence: float = Field(ge=0, le=100)
    requires_human_approval: bool
    next_step: NextStep
    gate_trace: tuple[GateTraceEntry, ...] = Field(min_length=1, max_length=10)
    loop_guard: LoopGuard

    @model_validator(mode="after")
    def _route_invariants(self) -> "DecisionRoute":
        errors: list[str] = []
        agents = self.selected_agents
        count = len(agents)
        roles = [agent.role for agent in agents]
        names = [agent.agent_name for agent in agents]

        if len(set(names)) != count:
            errors.append("selected_agents não pode repetir agente")
        if self.route in {"NO_AGENT", "REUSE_DECISION", "INVESTIGATE_FIRST"}:
            if count:
                errors.append(f"{self.route} exige selected_agents vazio")
            if self.estimated_ai_calls != 0:
                errors.append(f"{self.route} exige estimated_ai_calls = 0")
        if self.route == "NO_AGENT" and self.deterministic_resolution is None:
            errors.append("NO_AGENT exige deterministic_resolution")
        if self.route == "REUSE_DECISION":
            if not self.reused_decision_id:
                errors.append("REUSE_DECISION exige reused_decision_id")
            if not self.requires_human_approval:
                errors.append("REUSE_DECISION exige requires_human_approval = true")
            if self.similarity_reference is None or self.similarity_reference.material_change:
                errors.append("REUSE_DECISION exige referência sem material_change")
            if self.next_step.action != "propose_decision":
                errors.append("REUSE_DECISION exige next_step = propose_decision")
        elif self.reused_decision_id is not None:
            errors.append("reused_decision_id só é permitido em REUSE_DECISION")
        if self.route == "ONE_AGENT" and (count != 1 or roles[0] not in {"specialist", "investigate"}):
            errors.append("ONE_AGENT exige exatamente 1 especialista ou investigador")
        if self.route == "MULTI_AGENT":
            if count < 2:
                errors.append("MULTI_AGENT exige ao menos 2 agentes")
            if roles.count("specialist") > 2:
                errors.append("MULTI_AGENT permite no máximo 2 especialistas na primeira rodada")
            if roles.count("specialist") < 1:
                errors.append("MULTI_AGENT exige ao menos 1 especialista")
        if self.route in {"ONE_AGENT", "MULTI_AGENT"}:
            if self.estimated_ai_calls != count + 1:
                errors.append("estimated_ai_calls deve ser agentes + 1 (extração)")
            if self.next_step.action != "run_agents":
                errors.append(f"{self.route} exige next_step = run_agents")
            if not set(roles) <= FIRST_ROUND_ROLES:
                errors.append("papel de agente não permitido na primeira rodada")
        if self.route == "INVESTIGATE_FIRST":
            if self.next_step.action not in {"collect_evidence", "await_human"}:
                errors.append("INVESTIGATE_FIRST exige next_step collect_evidence ou await_human")
            if not self.next_step.missing_evidence:
                errors.append("INVESTIGATE_FIRST exige missing_evidence")
        if self.case_type == UNKNOWN_CASE_TYPE and count:
            errors.append("case_type UNKNOWN não permite selecionar agentes")
        if not self.quality.passed and (count or self.estimated_ai_calls):
            errors.append("qualidade reprovada não permite agentes nem chamadas de IA")
        if self.priority.human_approval_required and not self.requires_human_approval:
            errors.append("marca de aprovação humana exige requires_human_approval = true")
        resolution = self.deterministic_resolution
        if resolution is not None and resolution.resolved_by == "playbook":
            if self.playbook is None:
                errors.append("resolução por playbook exige playbook")
            if not self.requires_human_approval or self.next_step.action != "propose_decision":
                errors.append("playbook exige aprovação humana e next_step = propose_decision")
        if self.status == "ESCALATED":
            if self.route != "INVESTIGATE_FIRST" or count or not self.requires_human_approval:
                errors.append("ESCALATED exige INVESTIGATE_FIRST, sem agentes e com aprovação humana")
            if self.next_step.action != "await_human":
                errors.append("ESCALATED exige next_step = await_human")
        if self.estimated_ai_cost_avoided_usd is None and self.cost_basis != "unknown":
            errors.append("custo evitado nulo exige cost_basis = unknown")
        if self.estimated_ai_cost_avoided_usd is not None and self.cost_basis == "unknown":
            errors.append("cost_basis unknown não permite valor de custo evitado")
        if errors:
            raise ValueError("; ".join(errors))
        return self


def decision_route_json_schema() -> dict:
    """JSON Schema do contrato, derivado do modelo (fonte única)."""
    return DecisionRoute.model_json_schema()
