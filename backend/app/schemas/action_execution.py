from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ActionExecutionBase(BaseModel):
    """Espelha schemas/action_execution.schema.json."""

    owner: str
    due_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    evidence: list[str] = Field(default_factory=list)
    actual_impact: float | None = None
    outcome: str | None = None
    recurrence: bool | None = None


class ActionExecutionCreate(ActionExecutionBase):
    decision_id: str


class ActionExecutionOut(ActionExecutionBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    decision_id: str
