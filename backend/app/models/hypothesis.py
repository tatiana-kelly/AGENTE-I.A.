import uuid
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.diagnosis import Diagnosis


class Hypothesis(Base):
    """Espelha docs/DATA_MODEL.md#Hypothesis. Toda hipótese carrega evidência a favor, contra e o que falta."""

    __tablename__ = "hypotheses"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    diagnosis_id: Mapped[str] = mapped_column(ForeignKey("diagnoses.id"), nullable=False)
    statement: Mapped[str] = mapped_column(String, nullable=False)
    favorable_evidence: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    contrary_evidence: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    missing_evidence: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="untested"
    )  # untested | confirmed | refuted | inconclusive

    diagnosis: Mapped["Diagnosis"] = relationship(back_populates="hypotheses")
