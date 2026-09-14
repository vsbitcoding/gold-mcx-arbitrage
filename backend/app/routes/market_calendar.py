"""Market Holidays page (client, 14-Sep-2026): the exchange calendar the
whole app keeps time by. Everyone may read it; only the admin edits."""
from fastapi import APIRouter, Depends, HTTPException, Query

from app.security import get_current_user, require_admin
from app.services import market_calendar

router = APIRouter(prefix="/api/market-calendar", tags=["market-calendar"])


@router.get("")
def list_holidays(year: int | None = Query(None), user: str = Depends(get_current_user)):
    y = year or market_calendar._now().year
    return {"year": y, "years": market_calendar.years(), "rows": market_calendar.list_year(y),
            "now": {"mcx": market_calendar.state("MCX"), "nse": market_calendar.state("NSE")}}


@router.post("")
def save_holiday(body: dict, user: str = Depends(require_admin)):
    try:
        return market_calendar.upsert(body or {}, user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{holiday_id}")
def delete_holiday(holiday_id: int, user: str = Depends(require_admin)):
    if not market_calendar.delete(holiday_id):
        raise HTTPException(status_code=404, detail="no such holiday")
    return {"ok": True}


@router.post("/refresh")
def refresh(year: int | None = Query(None), user: str = Depends(require_admin)):
    try:
        return market_calendar.refresh_from_nse(year)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"NSE holiday master: {e}")
