"""Crude Oil screen — MCX and US option chains side by side, with implied
volatility and greeks on both. Two in-memory reads, zero DB, no upstream call
per request.

MCX comes from Dhan's REST option chain (the tick feed has no IV), US from the
IBKR monthly contract. Both are trimmed to the client's layout: 10 calls above
the money, the ATM row, 10 puts below.
"""
from fastapi import APIRouter, Query

from app.services import crude_iv_service, ibkr_feed, premium_feed

router = APIRouter(prefix="/api", tags=["crude-iv"])


_US_KEY = {"crude": "crude_iv", "natgas": "natgas_iv"}


def _payload(window: int, commodity: str = "crude") -> dict:
    commodity = commodity if commodity in _US_KEY else "crude"
    ib = ibkr_feed.get_data()
    us = ib.get(_US_KEY[commodity]) or {}
    if window != 10 and us.get("rows"):
        atm = us.get("atm")
        us = {**us, "rows": [r for r in us["rows"] if abs(r["strike"] - atm) <= window * 0.5]} if atm else us
    pf = premium_feed.get_inputs()
    return {
        "commodity": commodity,
        "mcx": crude_iv_service.get_chain(commodity=commodity, window=window),
        "us": {**us, "connected": ib.get("connected"), "delayed": ib.get("delayed")},
        # client wants the rate on this screen too - MCX quotes in rupees and
        # the US chain in dollars, so it is the number he converts with
        "usdinr": {"price": pf.get("usdinr"), "age": pf.get("usdinr_age"),
                   "source": pf.get("usdinr_source")},
        "server_time": ib.get("server_time"),
    }


@router.get("/crude-iv")
def crude_iv(
    commodity: str = Query("crude", description="crude | natgas"),
    window: int = Query(10, ge=1, le=25, description="strikes each side of ATM"),
):
    return _payload(window, commodity)
