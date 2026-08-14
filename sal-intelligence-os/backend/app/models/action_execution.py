import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.decision import Decision


class ActionExecution(Base):
    """Espelha docs/DATA_MODEL.md#ActionExecution. Acompanha execução, evidência e resultado real."""

    __tablename__ = "action_executions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    decision_id: Mapped[str] = mapped_column(ForeignKey("decisions.id"), nullable=False)
    owner: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    evidence: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    actual_impact: Mapped[float | None] = mapped_column(Float, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String, nullable=True)
    recurrence: Mapped[bool | None] = mapped_column(nullable=True)

    decision: Mapped["Decision"] = relationship(back_populates="actions")
