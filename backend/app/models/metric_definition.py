import uuid

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class MetricDefinition(Base):
    """Espelha docs/DATA_MODEL.md#MetricDefinition — fórmula oficial, dono e limites de uma métrica."""

    __tablename__ = "metric_definitions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    objective: Mapped[str] = mapped_column(String, nullable=False)
    formula: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    grain: Mapped[str] = mapped_column(String, nullable=False)
    owner: Mapped[str] = mapped_column(String, nullable=False)
    target: Mapped[float | None] = mapped_column(nullable=True)
    warning_threshold: Mapped[float | None] = mapped_column(nullable=True)
    critical_threshold: Mapped[float | None] = mapped_column(nullable=True)
    materiality_rule: Mapped[str] = mapped_column(String, nullable=False)
    update_frequency: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
