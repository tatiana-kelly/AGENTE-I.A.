from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.recommendation import Recommendation
from app.schemas.recommendation import RecommendationOut

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.get("/{recommendation_id}", response_model=RecommendationOut)
def get_recommendation(recommendation_id: str, db: Session = Depends(get_db)) -> Recommendation:
    row = db.get(Recommendation, recommendation_id)
    if row is None:
        raise HTTPException(status_code=404, detail="recommendation não encontrada")
    return row


@router.get("", response_model=list[RecommendationOut])
def list_recommendations(diagnosis_id: str | None = None, db: Session = Depends(get_db)) -> list[Recommendation]:
    query = db.query(Recommendation)
    if diagnosis_id:
        query = query.filter(Recommendation.diagnosis_id == diagnosis_id)
    return query.all()
