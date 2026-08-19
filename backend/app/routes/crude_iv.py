"""Crude Oil screen — MCX and US option chains side by side, with implied
volatility and greeks on both. Two in-memory reads, zero DB, no upstream call
per request.

MCX comes from Dhan's REST option chain (the tick feed has no IV), US from the
IBKR monthly contract. Both are trimmed to the client's layout: 10 calls above
the money, the ATM row, 10 puts below.
"""
from fastapi import APIRouter, Query

from app.services import (crude_iv_history, crude_iv_service, ibkr_feed,
                          premium_feed)

router = APIRouter(prefix="/api", tags=["crude-iv"])


# IBKR keeps the next month as its own chain, already subscribed - the Quote
# Booster pack bought exactly that. Both months' option expiries line up with
# MCX to the day (17-Sep and 15-Oct on crude), so the comparison stays clean in
# either month.
_US_KEY = {
    ("crude", 0): "crude_iv", ("crude", 1): "crude_iv_next",
    ("natgas", 0): "natgas_iv", ("natgas", 1): "natgas_iv_next",
}
COMMODITIES = ("crude", "natgas")


def _to_inr(us: dict, rate: float | None) -> dict:
    """The US chain restated in rupees at the USD/INR FUTURE (client, 19-Aug).

    MCX quotes in rupees and NYMEX in dollars, so on the side-by-side screen the
    two panels cannot be read against each other without doing the arithmetic in
    your head on every line. This does it, on its own tab, leaving the dollar one
    exactly as it was.

    **The IV does not change and is not touched.** Black-76 is homogeneous of
    degree 1 in (forward, strike, price): multiply all three by the same number
    and the price scales with them, so the volatility that reproduces it is
    identical. Verified on the client's own figures - 85.03 / 85 / 4.39 gives
    45.80%, and 8130.6 / 8127.7 / 419.8 gives 45.80%, to the last decimal. What
    the conversion buys is comparable PREMIUMS, not a different volatility.

    The greeks are SCALED rather than recomputed - delta invariant, gamma over
    the rate, vega and theta times it - because scaling is exact for a
    homogeneous function and it keeps IBKR's own model. LO options are American
    and ours is European; recomputing would quietly substitute one for the other.

    One rate for every field, from one read, or the conversion introduces an
    error where it was meant to remove one: put a rate half a percent stale on
    the price alone and the IV moves 0.23 points for no reason at all.
    """
    if not rate or not us:
        return {**us, "currency": "USD", "inr_rate": None,
                "inr_error": "USD/INR future not available"}

    def px(v, f=1.0):
        # 6 places, not 4: gamma in rupees is ~0.00038 and four would round it to
        # 0.0004, throwing away most of the number. Prices are formatted by the
        # screen anyway, so there is no cost to carrying the extra digits.
        return round(v * rate * f, 6) if isinstance(v, (int, float)) else v

    rows = []
    for r in us.get("rows") or []:
        out = {**r, "strike": px(r.get("strike"))}
        for side in ("ce", "pe"):
            leg = r.get(side)
            if not leg:
                continue
            out[side] = {
                **leg,
                "bid": px(leg.get("bid")), "ask": px(leg.get("ask")),
                "last": px(leg.get("last")), "mid": px(leg.get("mid")),
                "iv": leg.get("iv"),                      # unchanged, by proof
                "delta": leg.get("delta"),                # dimensionless
                "gamma": px(leg.get("gamma"), 1 / (rate * rate)),   # 1/price units
                "vega": px(leg.get("vega")), "theta": px(leg.get("theta")),
            }
        rows.append(out)
    return {
        **us,
        "currency": "INR",
        "inr_rate": rate,
        "future_price": px(us.get("future_price")),
        "atm": px(us.get("atm")),
        "rows": rows,
    }


# What each month shows by default, matching what ibkr_feed streams. The client
# asked for five more strikes each side (19-Aug); the front month gets them and
# the next month gives some back, because widening all four chains needs a second
# Quote Booster pack and there is not the runway for it. See ibkr_feed.
_DEFAULT_WINDOW = {0: 15, 1: 7}


_WIDE_LEG = 0.25


def _mark_wide(chain: dict) -> dict:
    """Flag US legs whose two sides are too far apart to price off, same rule as
    the MCX side. IBKR sends no such flag, and gas hits it: 9 of 55 front-month
    legs were wider than 25% on 19-Aug, the worst at 100%."""
    for r in chain.get("rows") or []:
        for side in ("ce", "pe"):
            leg = r.get(side)
            if not leg:
                continue
            b, a, mid = leg.get("bid"), leg.get("ask"), leg.get("mid")
            leg["wide"] = bool(b and a and mid and (a - b) / mid > _WIDE_LEG)
    return chain


def _payload(window: int | None, commodity: str = "crude", currency: str = "usd",
             month: int = 0) -> dict:
    commodity = commodity if commodity in COMMODITIES else "crude"
    month = 1 if month == 1 else 0
    win = _DEFAULT_WINDOW[month] if window is None else window
    ib = ibkr_feed.get_data()
    us = ib.get(_US_KEY[(commodity, month)]) or {}
    # Trim by POSITION from the money, not by price distance. The old test was
    # `abs(strike - atm) <= window * 0.5`, which hard-codes crude's 0.5 strike
    # step; natural gas steps 0.05, so on gas it kept ten times too many strikes
    # or, on a wider ladder, almost none. Ranking by distance needs no step at
    # all and is the same rule the NSE-vs-MCX screen was rebuilt around.
    rows = us.get("rows") or []
    atm = us.get("atm")
    if rows and atm is not None and len(rows) > win * 2 + 1:
        keep = {r["strike"] for r in
                sorted(rows, key=lambda r: abs(r["strike"] - atm))[: win * 2 + 1]}
        us = {**us, "rows": [r for r in rows if r["strike"] in keep]}
    pf = premium_feed.get_inputs()
    us = _mark_wide({**us, "connected": ib.get("connected"), "delayed": ib.get("delayed")})
    # The FUTURE rate, which is what the client specified and what premium_feed
    # already serves - a spot two minutes old was replaced on 14-Aug for exactly
    # this reason.
    if currency == "inr":
        us = _to_inr(us, pf.get("usdinr"))
    return {
        "commodity": commodity,
        "month": month,
        "currency": "INR" if currency == "inr" else "USD",
        "mcx": crude_iv_service.get_chain(commodity=commodity, window=win, month=month),
        "us": us,
        # client wants the rate on this screen too - MCX quotes in rupees and
        # the US chain in dollars, so it is the number he converts with
        "usdinr": {"price": pf.get("usdinr"), "age": pf.get("usdinr_age"),
                   "source": pf.get("usdinr_source")},
        "server_time": ib.get("server_time"),
    }


@router.get("/crude-iv")
def crude_iv(
    commodity: str = Query("crude", description="crude | natgas"),
    window: int | None = Query(None, ge=1, le=25,
                               description="strikes each side of ATM; default 15 front month, 7 next"),
    currency: str = Query("usd", pattern="^(usd|inr)$",
                          description="inr restates the US chain in rupees at the USD/INR future"),
    month: int = Query(0, ge=0, le=1, description="0 = front expiry, 1 = the one after"),
):
    return _payload(window, commodity, currency, month)


@router.get("/crude-iv/history")
def crude_iv_history_view(
    commodity: str = Query("crude", pattern="^(crude|natgas)$"),
    month: int = Query(0, ge=0, le=1, description="0 = front expiry, 1 = the one after"),
    slot: str = Query("all", description="all, or one of 09:00 .. 23:30"),
    days: int = Query(3, ge=1, le=30),
    date: str | None = Query(None, description="YYYY-MM-DD => that day only"),
):
    """Stored MCX-vs-US boards, newest first - every half hour, 09:00 to 23:30 IST.

    Rows are flat lists, not dicts; `cols_mcx` and `cols_us` name the columns in
    order. Keeping the live shape would have cost 433 MB a year to store symbols
    and volumes nobody reads back.

    Static once written - fetch on a control change, do not poll. A slot is
    missing when one exchange was not quoting two-way at the time, which is the
    honest record of a thin half hour.
    """
    return crude_iv_history.get_history(commodity=commodity, month=month,
                                        slot=slot, days=days, date=date)
