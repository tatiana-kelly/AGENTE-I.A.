from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.rbac import Role, get_current_role, require_approval_role
from app.db.session import get_db
from app.models.decision import Decision
from app.schemas.decision import DecisionCreate, DecisionOut

router = APIRouter(prefix="/decisions", tags=["decisions"])


@router.post("", response_model=DecisionOut, status_code=201)
def create_decision(
    payload: DecisionCreate,
    db: Session = Depends(get_db),
    role: Role = Depends(get_current_role),
) -> Decision:
    require_approval_role(role)
    row = Decision(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("", response_model=list[DecisionOut])
def list_decisions(db: Session = Depends(get_db)) -> list[Decision]:
    return db.query(Decision).order_by(Decision.timestamp.desc()).all()
