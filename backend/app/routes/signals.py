"""Fire-once mean-reversion signals + accuracy track record (watch-only).

GET /api/signals          → currently-open signals (frozen entry/target/probability)
GET /api/signals/history  → resolved signals, each marked right / wrong
GET /api/signals/accuracy → overall + per-pair accuracy
"""
from fastapi import APIRouter, Depends, Query

from app.security import get_current_user
from app.services import signal_service

router = APIRouter(prefix="/api/signals", tags=["signals"])


@router.get("")
def get_signals(user: str = Depends(get_current_user)):
    return {"status": signal_service.status(), "signals": signal_service.get_active_signals()}


@router.get("/history")
def get_history(limit: int = Query(100, ge=1, le=500), user: str = Depends(get_current_user)):
    return {"history": signal_service.get_history(limit)}


@router.get("/accuracy")
def get_accuracy(user: str = Depends(get_current_user)):
    return signal_service.get_accuracy()
