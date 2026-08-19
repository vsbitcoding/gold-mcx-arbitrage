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


def _payload(window: int, commodity: str = "crude", currency: str = "usd") -> dict:
    commodity = commodity if commodity in _US_KEY else "crude"
    ib = ibkr_feed.get_data()
    us = ib.get(_US_KEY[commodity]) or {}
    if window != 10 and us.get("rows"):
        atm = us.get("atm")
        us = {**us, "rows": [r for r in us["rows"] if abs(r["strike"] - atm) <= window * 0.5]} if atm else us
    pf = premium_feed.get_inputs()
    us = {**us, "connected": ib.get("connected"), "delayed": ib.get("delayed")}
    # The FUTURE rate, which is what the client specified and what premium_feed
    # already serves - a spot two minutes old was replaced on 14-Aug for exactly
    # this reason.
    if currency == "inr":
        us = _to_inr(us, pf.get("usdinr"))
    return {
        "commodity": commodity,
        "currency": "INR" if currency == "inr" else "USD",
        "mcx": crude_iv_service.get_chain(commodity=commodity, window=window),
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
    window: int = Query(10, ge=1, le=25, description="strikes each side of ATM"),
    currency: str = Query("usd", pattern="^(usd|inr)$",
                          description="inr restates the US chain in rupees at the USD/INR future"),
):
    return _payload(window, commodity, currency)
