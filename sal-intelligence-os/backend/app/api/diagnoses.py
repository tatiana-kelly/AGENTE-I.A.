from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.diagnosis import Diagnosis
from app.models.hypothesis import Hypothesis
from app.models.recommendation import Recommendation
from app.schemas.diagnosis import DiagnosisCreate, DiagnosisOut

router = APIRouter(prefix="/diagnoses", tags=["diagnoses"])


@router.post("", response_model=DiagnosisOut, status_code=201)
def create_diagnosis(payload: DiagnosisCreate, db: Session = Depends(get_db)) -> Diagnosis:
    row = Diagnosis(
        alert_id=payload.alert_id,
        facts=payload.facts,
        calculations=payload.calculations,
        concentration=payload.concentration,
        probable_cause=payload.probable_cause,
        confidence=payload.confidence,
        missing_data=payload.missing_data,
        consequence_no_action=payload.consequence_no_action,
        owner=payload.owner,
        deadline=payload.deadline,
        success_kpi=payload.success_kpi,
        success_target=payload.success_target,
        decision_status=payload.decision_status,
    )
    db.add(row)
    db.flush()

    for h in payload.hypotheses:
        db.add(Hypothesis(diagnosis_id=row.id, **h.model_dump()))
    for r in payload.recommendations:
        db.add(Recommendation(diagnosis_id=row.id, **r.model_dump()))

    db.commit()
    db.refresh(row)
    return row


@router.get("/{diagnosis_id}", response_model=DiagnosisOut)
def get_diagnosis(diagnosis_id: str, db: Session = Depends(get_db)) -> Diagnosis:
    row = db.get(Diagnosis, diagnosis_id)
    if row is None:
        raise HTTPException(status_code=404, detail="diagnosis não encontrado")
    return row
