from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.enums import DecisionStatus
from app.schemas.hypothesis import HypothesisBase
from app.schemas.recommendation import RecommendationBase


class DiagnosisBase(BaseModel):
    """Espelha schemas/diagnosis.schema.json — inclui a validação estrutural de exatamente 3 recomendações
    (containment/structural/optimization), que é a aplicação em código da regra §75 do CLAUDE.md."""

    facts: list[dict] = Field(default_factory=list)
    calculations: list[dict] = Field(default_factory=list)
    concentration: list[dict] = Field(default_factory=list)
    hypotheses: list[HypothesisBase] = Field(..., min_length=1)
    probable_cause: str
    confidence: float = Field(..., ge=0, le=100)
    missing_data: list[str] = Field(default_factory=list)
    consequence_no_action: str | None = None
    recommendations: list[RecommendationBase] = Field(..., min_length=3, max_length=3)
    owner: str
    deadline: str | None = None
    success_kpi: str
    success_target: str | None = None
    decision_status: DecisionStatus = DecisionStatus.NEEDS_INVESTIGATION

    @field_validator("recommendations")
    @classmethod
    def must_cover_three_horizons(cls, value: list[RecommendationBase]) -> list[RecommendationBase]:
        types = {r.type for r in value}
        expected = {"containment", "structural", "optimization"}
        if types != expected:
            raise ValueError(
                f"as 3 recomendações devem cobrir contenção, correção estrutural e otimização; recebido: {types}"
            )
        return value

    @field_validator("decision_status")
    @classmethod
    def ready_requires_minimum_confidence(cls, value: DecisionStatus, info) -> DecisionStatus:
        confidence = info.data.get("confidence")
        if value == DecisionStatus.READY_FOR_DECISION and confidence is not None and confidence < 70:
            raise ValueError(
                "READY_FOR_DECISION exige confidence >= 70 "
                "(config/priority-scoring.yaml: minimum_confidence_ready_for_decision)"
            )
        return value


class DiagnosisCreate(DiagnosisBase):
    alert_id: str


class DiagnosisOut(DiagnosisBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    alert_id: str
    created_at: datetime
    agent_versions: list[str] = Field(default_factory=list)
