import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.alert import Alert
    from app.models.hypothesis import Hypothesis
    from app.models.recommendation import Recommendation


class Diagnosis(Base):
    """Espelha docs/DATA_MODEL.md#Diagnosis e schemas/diagnosis.schema.json."""

    __tablename__ = "diagnoses"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    alert_id: Mapped[str] = mapped_column(ForeignKey("alerts.id"), nullable=False)
    facts: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    calculations: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    concentration: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    probable_cause: Mapped[str | None] = mapped_column(String, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    missing_data: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    consequence_no_action: Mapped[str | None] = mapped_column(String, nullable=True)
    owner: Mapped[str | None] = mapped_column(String, nullable=True)
    deadline: Mapped[str | None] = mapped_column(String, nullable=True)
    success_kpi: Mapped[str | None] = mapped_column(String, nullable=True)
    success_target: Mapped[str | None] = mapped_column(String, nullable=True)
    decision_status: Mapped[str] = mapped_column(String, nullable=False, default="NEEDS_INVESTIGATION")
    agent_versions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(UTC))

    alert: Mapped["Alert"] = relationship(back_populates="diagnoses")
    hypotheses: Mapped[list["Hypothesis"]] = relationship(back_populates="diagnosis")
    recommendations: Mapped[list["Recommendation"]] = relationship(back_populates="diagnosis")
