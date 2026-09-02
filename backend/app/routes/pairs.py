from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_db
from app.security import get_current_user
from app.services.snapshot import build_live_payload

router = APIRouter(prefix="/api/pairs", tags=["pairs"])


@router.get("/live")
def live(db: Session = Depends(get_db), user: str = Depends(get_current_user)):
    return build_live_payload(db)


@router.get("/history-pairs")
def history_pairs(user: str = Depends(get_current_user)):
    """Every pair the history dialog may show: live ones plus remembered
    expired ones (client, 03-Sep: expiry must not erase a pair's history)."""
    from app.services.spread_close_history import list_pairs
    return {"pairs": list_pairs()}


@router.get("/spread-history")
def spread_history(pair: str, days: int = 120,
                   user: str = Depends(get_current_user)):
    """Day-by-day spread of one calendar pair, from each leg's DAILY CLOSE -
    one value per day, the client's rule (02-Sep: "increase-decrease karta
    single value aapi de, based on closing price"). Computed on demand from
    Dhan candles behind an hour's cache; nothing is stored."""
    days = max(7, min(int(days), 400))
    from app.services.spread_close_history import pair_history
    return pair_history(pair, days)


# --------------------------------------------------------------------------- #
# Multi-year close-based history from MCX bhavcopy (client, 02-Sep-2026)
# --------------------------------------------------------------------------- #
@router.get("/bhav/options")
def bhav_options(user: str = Depends(get_current_user)):
    """What the dialog can offer: symbols with their stored expiries, the cross
    templates, and how far the data reaches."""
    from app.services import bhav_history as bh
    from app.services.pair_generator import CROSS_TEMPLATES
    return {
        "coverage": bh.coverage(),
        "symbols": [{"key": k, "label": bh.LABELS[k], "expiries": bh.expiries(k)}
                    for k in bh.SYMBOLS],
        "cross": [{"big": b, "small": s, "mode": m,
                   "label": f"{bh.LABELS[b]} / {bh.LABELS[s]}"}
                  for b, s, _bl, _sl, m in CROSS_TEMPLATES],
    }


@router.get("/bhav/series")
def bhav_series(
    kind: str = Query("calendar", pattern="^(calendar|cross)$"),
    big: str = Query(...), small: str | None = Query(None),
    big_exp: str | None = Query(None), small_exp: str | None = Query(None),
    mode: str = Query("continuous", pattern="^(continuous|month)$"),
    rank: int = Query(0, ge=0, le=4),
    start: str = Query("2021-01-01"), end: str | None = Query(None),
    user: str = Depends(get_current_user),
):
    """One close-based value per day.

    calendar: big = symbol; month mode needs big_exp (near) + small_exp (far);
              continuous rolls M1-M2 (rank 0), M2-M3 (rank 1) ...
    cross   : big/small = the template's legs; month mode needs both expiries;
              continuous uses the template's month matching on every day.
    """
    from datetime import date
    from app.services import bhav_history as bh
    from app.services.pair_generator import CROSS_TEMPLATES
    end = end or date.today().isoformat()
    if big not in bh.SYMBOLS or (small and small not in bh.SYMBOLS):
        raise HTTPException(status_code=400, detail="unknown symbol")
    if kind == "calendar":
        if mode == "month" and big_exp and not small_exp:
            # far defaults to the next listed month after the chosen near one
            later = [e for e in bh.expiries(big) if e > big_exp]
            small_exp = later[0] if later else None
        rows = bh.calendar_series(big, big_exp, small_exp, start, end,
                                  continuous=(mode == "continuous"), rank=rank)
        label = f"{bh.LABELS[big]} calendar"
        legs = {"near_exp": big_exp, "far_exp": small_exp} if mode == "month" else {}
        legs["std_unit"] = bh.STD_UNIT.get(big, "per 10 gm")
        legs["std_mult"] = bh.MULTIPLIERS.get(big, 1.0)
    else:
        tpl = next((t for t in CROSS_TEMPLATES if t[0] == big and t[1] == small), None)
        if not tpl:
            raise HTTPException(status_code=400, detail="not a board cross pair")
        if mode == "month" and big_exp and not small_exp:
            # the small leg follows the template's month rule, like the board
            small_exp = bh._match(bh.expiries(small), big_exp, tpl[4])
        rows = bh.cross_series(big, small, tpl[4], big_exp, small_exp, start, end,
                               continuous=(mode == "continuous"))
        label = f"{bh.LABELS[big]} / {bh.LABELS[small]}"
        legs = {"big_exp": big_exp, "small_exp": small_exp} if mode == "month" else {}
    rows.reverse()                                   # newest first for the table
    return {"kind": kind, "mode": mode, "label": label, "count": len(rows),
            "rows": rows, **legs}
