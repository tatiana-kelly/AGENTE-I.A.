"""Metric Registry — docs/ARCHITECTURE.md item 4: fórmulas oficiais, metas, limites, periodicidade, dono e fonte."""

from sqlalchemy.orm import Session

from app.models.metric_definition import MetricDefinition
from app.schemas.metric_definition import MetricDefinitionCreate


class MetricRegistry:
    def __init__(self, db: Session) -> None:
        self.db = db

    def register(self, metric: MetricDefinitionCreate) -> MetricDefinition:
        existing = self.get_by_name(metric.name)
        if existing:
            for field_name, value in metric.model_dump().items():
                setattr(existing, field_name, value)
            existing.version += 1
            self.db.commit()
            self.db.refresh(existing)
            return existing

        row = MetricDefinition(**metric.model_dump())
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def get_by_name(self, name: str) -> MetricDefinition | None:
        return self.db.query(MetricDefinition).filter(MetricDefinition.name == name).first()

    def list_all(self) -> list[MetricDefinition]:
        return self.db.query(MetricDefinition).all()
