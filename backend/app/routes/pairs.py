from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import get_current_user
from app.services.snapshot import build_live_payload

router = APIRouter(prefix="/api/pairs", tags=["pairs"])


@router.get("/live")
def live(db: Session = Depends(get_db), user: str = Depends(get_current_user)):
    return build_live_payload(db)
