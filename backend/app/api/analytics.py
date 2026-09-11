"""Analytics endpoint."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.schemas import AnalyticsSummary
from app.services import analytics_service

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("", response_model=AnalyticsSummary)
def summary(db: Session = Depends(get_db)):
    return analytics_service.summary(db)
