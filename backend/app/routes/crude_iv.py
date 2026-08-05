"""Crude Oil screen — MCX and US option chains side by side, with implied
volatility and greeks on both. Two in-memory reads, zero DB, no upstream call
per request.

MCX comes from Dhan's REST option chain (the tick feed has no IV), US from the
IBKR monthly contract. Both are trimmed to the client's layout: 10 calls above
the money, the ATM row, 10 puts below.
"""
from fastapi import APIRouter, Query

from app.services import crude_iv_service, ibkr_feed

router = APIRouter(prefix="/api", tags=["crude-iv"])


def _payload(window: int) -> dict:
    ib = ibkr_feed.get_data()
    us = ib.get("crude_iv") or {}
    if window != 10 and us.get("rows"):
        atm = us.get("atm")
        us = {**us, "rows": [r for r in us["rows"] if abs(r["strike"] - atm) <= window * 0.5]} if atm else us
    return {
        "mcx": crude_iv_service.get_chain(window=window),
        "us": {**us, "connected": ib.get("connected"), "delayed": ib.get("delayed")},
        "server_time": ib.get("server_time"),
    }


@router.get("/crude-iv")
def crude_iv(window: int = Query(10, ge=1, le=25, description="strikes each side of ATM")):
    return _payload(window)
