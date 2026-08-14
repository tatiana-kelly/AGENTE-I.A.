from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.alert import Alert
from app.schemas.alert import AlertCreate, AlertOut

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.post("", response_model=AlertOut, status_code=201)
def create_alert(payload: AlertCreate, db: Session = Depends(get_db)) -> Alert:
    deviation = payload.deviation
    row = Alert(
        **payload.model_dump(exclude={"status"}),
        status=payload.status,
        absolute_delta=deviation.absolute,
        percentage_delta=deviation.percentage,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("", response_model=list[AlertOut])
def list_alerts(db: Session = Depends(get_db)) -> list[Alert]:
    return db.query(Alert).order_by(Alert.detected_at.desc()).all()


@router.get("/{alert_id}", response_model=AlertOut)
def get_alert(alert_id: str, db: Session = Depends(get_db)) -> Alert:
    from fastapi import HTTPException

    row = db.get(Alert, alert_id)
    if row is None:
        raise HTTPException(status_code=404, detail="alert não encontrado")
    return row
