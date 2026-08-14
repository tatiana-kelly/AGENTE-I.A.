from pydantic import BaseModel, ConfigDict, Field


class OrganizationalLearningBase(BaseModel):
    """Espelha schemas/organizational_learning.schema.json."""

    pattern: str
    intervention: str
    predicted_impact: float | None = None
    actual_impact: float | None = None
    conditions: str | None = None
    lesson: str
    confidence: float = Field(..., ge=0, le=100)


class OrganizationalLearningCreate(OrganizationalLearningBase):
    pass


class OrganizationalLearningOut(OrganizationalLearningBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
