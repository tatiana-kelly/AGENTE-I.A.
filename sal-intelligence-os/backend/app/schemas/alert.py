from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.enums import DecisionStatus, Severity


class Deviation(BaseModel):
    absolute: float
    percentage: float


class AlertBase(BaseModel):
    """Espelha schemas/alert.schema.json — validado à parte no Data Quality Gate antes de virar registro."""

    metric_id: str
    title: str
    period: str
    current_value: float
    reference_value: float
    materiality: float = Field(..., description="Impacto absoluto que justifica o alerta.")
    severity: Severity
    source_quality: str
    concentration: list[dict] = Field(default_factory=list)
    status: DecisionStatus = DecisionStatus.NEEDS_INVESTIGATION

    @property
    def deviation(self) -> Deviation:
        absolute = self.current_value - self.reference_value
        percentage = (absolute / self.reference_value * 100) if self.reference_value else 0.0
        return Deviation(absolute=absolute, percentage=percentage)


class AlertCreate(AlertBase):
    pass


class AlertOut(AlertBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    detected_at: datetime
    absolute_delta: float
    percentage_delta: float
