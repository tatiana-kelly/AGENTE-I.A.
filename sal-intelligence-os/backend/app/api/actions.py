from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.action_execution import ActionExecution
from app.schemas.action_execution import ActionExecutionCreate, ActionExecutionOut

router = APIRouter(prefix="/actions", tags=["actions"])


@router.post("", response_model=ActionExecutionOut, status_code=201)
def create_action(payload: ActionExecutionCreate, db: Session = Depends(get_db)) -> ActionExecution:
    row = ActionExecution(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/{action_id}", response_model=ActionExecutionOut)
def get_action(action_id: str, db: Session = Depends(get_db)) -> ActionExecution:
    row = db.get(ActionExecution, action_id)
    if row is None:
        raise HTTPException(status_code=404, detail="action não encontrada")
    return row
