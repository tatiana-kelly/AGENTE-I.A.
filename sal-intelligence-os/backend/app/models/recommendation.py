import uuid
from typing import TYPE_CHECKING

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.decision import Decision
    from app.models.diagnosis import Diagnosis


class Recommendation(Base):
    """Espelha docs/DATA_MODEL.md#Recommendation. Toda Diagnosis READY_FOR_DECISION exige exatamente 3
    (containment | structural | optimization) — reforçado em schemas/diagnosis.schema.json."""

    __tablename__ = "recommendations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    diagnosis_id: Mapped[str] = mapped_column(ForeignKey("diagnoses.id"), nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)  # containment | structural | optimization
    action: Mapped[str] = mapped_column(String, nullable=False)
    expected_impact: Mapped[str] = mapped_column(String, nullable=False)
    effort: Mapped[str] = mapped_column(String, nullable=False)
    risk: Mapped[str] = mapped_column(String, nullable=False)
    time_to_value: Mapped[str] = mapped_column(String, nullable=False)
    reversibility: Mapped[str] = mapped_column(String, nullable=False)
    dependencies: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    owner_role: Mapped[str] = mapped_column(String, nullable=False)
    deadline: Mapped[str] = mapped_column(String, nullable=False)
    success_kpi: Mapped[str] = mapped_column(String, nullable=False)
    success_target: Mapped[str] = mapped_column(String, nullable=False)

    diagnosis: Mapped["Diagnosis"] = relationship(back_populates="recommendations")
    decisions: Mapped[list["Decision"]] = relationship(back_populates="recommendation")
