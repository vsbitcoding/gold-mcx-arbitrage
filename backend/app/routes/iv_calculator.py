"""Standalone option calculator - the client's own reference tool, in-house.

He sent option-price.com and a note mapping its fields to what he trades:

    Underlying Value  -> Future Price
    Strike Price      -> our strike, 8100 / 8200 / etc
    Days Until Expiry -> days to expiry
    Interest Rate     -> 0
    Dividend Yield    -> 0
    Market Price      -> that call / put price

That mapping is correct: Black-Scholes with a futures underlying and no carry is
Black-76, the market convention for options on futures.

His site's own endpoint takes volatility IN and returns a price - the opposite of
what he wants. Its implied-vol page runs in the browser, so there is nothing to
call. Neither matters: fed the site's own example (77.5 / 100 / 87 days / 25% /
5% / 1%) this returns call 0.087999 and put 21.587797 against its 0.088000 and
21.587799, and solving back from its own put price returns 25.00%.

Both directions live here, so one page answers "what is this worth at 25 vol"
and "what vol is the market paying", which is all his calculator ever did.
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.services import iv_calc

router = APIRouter(prefix="/api", tags=["iv-calculator"])


def _calc(underlying: float, strike: float, days: float, rate: float,
          dividend: float, vol: float | None, market: float | None,
          side: str) -> dict:
    """One shared body so the dashboard and the app API cannot drift apart."""
    call = side != "pe"
    r, q = rate / 100.0, dividend / 100.0
    T = days / iv_calc.DAYS_YEAR

    out = {
        "input": {"underlying": underlying, "strike": strike, "days": days,
                  "rate": rate, "dividend": dividend, "vol": vol,
                  "market": market, "side": "pe" if not call else "ce"},
        "model": "Black-Scholes / Black-76",
        "years": round(T, 6),
        "implied_vol": None, "price": None, "greeks": None,
        "intrinsic": round(max(0.0, (underlying - strike) if call
                               else (strike - underlying)), 6),
        "note": None,
    }
    if days <= 0:
        out["note"] = "Days until expiration must be more than zero."
        return out

    # Market price given -> solve for volatility. This is the direction the
    # client actually wants and the one his reference site cannot serve.
    if market is not None:
        out["implied_vol"] = iv_calc.implied_vol(market, underlying, strike, T, call, r, q)
        if out["implied_vol"] is None:
            # Say WHY rather than show a blank. Below intrinsic is the common
            # one and it means the quote is stale, not that the maths failed.
            out["note"] = ("No implied volatility exists for that price. It is at or "
                           "below the option's intrinsic value, or beyond what any "
                           "volatility can produce - usually a stale quote.")
            return out
        vol = out["implied_vol"]

    if vol is None:
        out["note"] = "Give either a market price (to get implied volatility) or a volatility."
        return out

    v = vol / 100.0
    out["price"] = round(iv_calc.price(underlying, strike, T, v, call, r, q), 6)
    out["greeks"] = iv_calc.greeks(underlying, strike, T, v, call, r, q)
    out["time_value"] = round(out["price"] - out["intrinsic"], 6)
    # Both sides at the same volatility, because a trader reading one wants the
    # other, and put-call parity across them is a free check on this page.
    other = iv_calc.price(underlying, strike, T, v, not call, r, q)
    out["call_price"] = round(out["price"] if call else other, 6)
    out["put_price"] = round(other if call else out["price"], 6)
    return out


@router.get("/iv-calculator")
def iv_calculator(
    underlying: float = Query(..., gt=0, description="future price"),
    strike: float = Query(..., gt=0),
    days: float = Query(..., description="calendar days until expiry"),
    rate: float = Query(0.0, description="interest rate %, client uses 0"),
    dividend: float = Query(0.0, description="dividend yield %, client uses 0"),
    vol: float | None = Query(None, gt=0, description="volatility %, to price forwards"),
    market: float | None = Query(None, description="option market price, to solve for IV"),
    side: str = Query("ce", pattern="^(ce|pe)$"),
):
    """Implied volatility from a market price, or a price and greeks from a vol.

    Pass `market` for the implied-volatility direction, `vol` for the pricing
    direction. Both -> `market` wins and `vol` is ignored, since a solved IV is
    the answer and the supplied one would only contradict it.
    """
    return _calc(underlying, strike, days, rate, dividend, vol, market, side)
