from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.enums import DecisionOutcome


class DecisionBase(BaseModel):
    """Espelha schemas/decision.schema.json."""

    decision: DecisionOutcome
    human_owner: str
    rationale: str | None = None


class DecisionCreate(DecisionBase):
    recommendation_id: str


class DecisionOut(DecisionBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    recommendation_id: str
    timestamp: datetime
