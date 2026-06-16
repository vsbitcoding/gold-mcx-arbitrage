"""Live mean-reversion signals (watch-only).

GET /api/signals → currently-active cross-pair signals (direction/entry/target).
"""
from fastapi import APIRouter, Depends

from app.security import get_current_user
from app.services import signal_service

router = APIRouter(prefix="/api/signals", tags=["signals"])


@router.get("")
def get_signals(user: str = Depends(get_current_user)):
    return {
        "status": signal_service.status(),
        "signals": signal_service.get_active_signals(),
    }
