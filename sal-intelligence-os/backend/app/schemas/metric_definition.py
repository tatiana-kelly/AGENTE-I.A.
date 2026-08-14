from pydantic import BaseModel, ConfigDict


class MetricDefinitionBase(BaseModel):
    name: str
    objective: str
    formula: str
    source: str
    grain: str
    owner: str
    target: float | None = None
    warning_threshold: float | None = None
    critical_threshold: float | None = None
    materiality_rule: str
    update_frequency: str
    version: int = 1


class MetricDefinitionCreate(MetricDefinitionBase):
    pass


class MetricDefinitionOut(MetricDefinitionBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
