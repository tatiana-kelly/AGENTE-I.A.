import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.diagnosis import Diagnosis


class Alert(Base):
    """Espelha docs/DATA_MODEL.md#Alert e schemas/alert.schema.json."""

    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    metric_id: Mapped[str] = mapped_column(ForeignKey("metric_definitions.id"), nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(UTC))
    period: Mapped[str] = mapped_column(String, nullable=False)
    current_value: Mapped[float] = mapped_column(Float, nullable=False)
    reference_value: Mapped[float] = mapped_column(Float, nullable=False)
    absolute_delta: Mapped[float] = mapped_column(Float, nullable=False)
    percentage_delta: Mapped[float] = mapped_column(Float, nullable=False)
    materiality: Mapped[float] = mapped_column(Float, nullable=False)
    severity: Mapped[str] = mapped_column(String, nullable=False)  # low | medium | high | critical
    source_quality: Mapped[str] = mapped_column(String, nullable=False)  # ver DataQualityGate
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="NEEDS_INVESTIGATION"
    )  # NEEDS_INVESTIGATION | READY_FOR_DECISION | CONTAINMENT_ONLY | HUMAN_APPROVAL_REQUIRED
    concentration: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    diagnoses: Mapped[list["Diagnosis"]] = relationship(back_populates="alert")
