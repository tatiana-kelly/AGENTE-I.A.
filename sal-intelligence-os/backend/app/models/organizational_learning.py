import uuid

from sqlalchemy import Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class OrganizationalLearning(Base):
    """Espelha docs/DATA_MODEL.md#OrganizationalLearning. Memória: previsão x realizado, por padrão de intervenção."""

    __tablename__ = "organizational_learnings"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    pattern: Mapped[str] = mapped_column(String, nullable=False)
    intervention: Mapped[str] = mapped_column(String, nullable=False)
    predicted_impact: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_impact: Mapped[float | None] = mapped_column(Float, nullable=True)
    conditions: Mapped[str | None] = mapped_column(String, nullable=True)
    lesson: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
