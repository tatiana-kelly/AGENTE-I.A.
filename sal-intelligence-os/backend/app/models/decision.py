import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.action_execution import ActionExecution
    from app.models.recommendation import Recommendation


class Decision(Base):
    """Espelha docs/DATA_MODEL.md#Decision. Registra a decisão humana sobre uma Recommendation."""

    __tablename__ = "decisions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    recommendation_id: Mapped[str] = mapped_column(ForeignKey("recommendations.id"), nullable=False)
    decision: Mapped[str] = mapped_column(String, nullable=False)  # approved | rejected | request_more_evidence
    human_owner: Mapped[str] = mapped_column(String, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(UTC))
    rationale: Mapped[str | None] = mapped_column(String, nullable=True)

    recommendation: Mapped["Recommendation"] = relationship(back_populates="decisions")
    actions: Mapped[list["ActionExecution"]] = relationship(back_populates="decision")
