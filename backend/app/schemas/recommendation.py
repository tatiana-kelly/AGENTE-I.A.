from pydantic import BaseModel, ConfigDict, Field

from app.schemas.enums import Effort, RecommendationType, Reversibility, Risk


class RecommendationBase(BaseModel):
    """Espelha schemas/recommendation.schema.json. Ver .claude/rules/action-design.md: toda ação é
    verbo + objeto + dono + prazo + custo + benefício + risco + KPI + meta + evidência + contingência."""

    type: RecommendationType
    action: str
    expected_impact: str
    effort: Effort
    risk: Risk
    time_to_value: str
    reversibility: Reversibility
    dependencies: list[str] = Field(default_factory=list)
    owner_role: str
    deadline: str
    success_kpi: str
    success_target: str


class RecommendationCreate(RecommendationBase):
    diagnosis_id: str


class RecommendationOut(RecommendationBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    diagnosis_id: str
