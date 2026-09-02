"""NSE vs MCX — future and option chain side by side (client, 13-Aug).

Crude oil first, natural gas added 13-Aug on the client's ask. Those are the
only two NSE commodities worth comparing: bullion and base metals are listed
there but dead, bid 0 / ask 0 against a months-old LTP.

NSE comes from Angel One (the only provider that carries NSE's commodity
segment), MCX from the existing Dhan option-chain service. Both are in-memory
reads; nothing here calls upstream or touches the database.

Honest caveats the screen has to carry:
  * The FUTURES line up on both commodities - crude 19-Aug, gas 26-Aug - so
    those differences are clean.
  * The OPTION expiries do not. Crude runs NSE 10-Sep vs MCX 17-Sep, gas NSE
    20-Aug vs MCX 24-Aug, so the same strike holds more time value on the MCX
    side and part of any premium difference is time, not a real gap. The client
    chose to compare anyway with both dates on screen, so both dates go out.
  * A dead contract still prints an old LTP, so only bid/ask are compared and a
    leg with neither is reported as no market.
"""
from datetime import date, datetime

from fastapi import APIRouter, Query

from app.services import (angel_feed, crude_iv_service, iv_calc, mcx_opt_stream,
                          nse_mcx_history)

router = APIRouter(prefix="/api", tags=["nse-mcx"])

COMMODITIES = ("crude", "natgas")


def _fut_expiry(symbol: str | None) -> str | None:
    """MCX future symbols read CRUDEOIL-19Aug2026-FUT."""
    if not symbol or "-" not in symbol:
        return None
    try:
        return datetime.strptime(symbol.split("-")[1], "%d%b%Y").date().isoformat()
    except Exception:  # noqa: BLE001
        return None


def _mid(leg: dict | None) -> float | None:
    """Mid only when BOTH sides are quoted.

    A one-sided quote makes the "mid" whatever that single side happens to be.
    On 13-Aug natural gas, NSE showed a 0.05 bid with no ask on the 275 put
    against MCX's 13.30, and this came out as a -13.25 "difference" that is not
    a difference at all. The dashboard already refused those legs and drew a
    dash; the API has to refuse them too, or the app prints exactly the number
    the screen deliberately hides.
    """
    if not leg:
        return None
    b, a = leg.get("bid"), leg.get("ask")
    return round((b + a) / 2, 2) if (b and a) else None


# A two-way quote can still be untradeable. Natural gas 260 CE quoted
# 0.05 / 16.85 has a "mid" of 8.45 that nobody can deal at, and the difference
# built on it is arithmetic, not a market. The dashboard tints these amber and
# appends "?"; the flag has to travel in the API too, or the app renders them
# as solid numbers.
_WIDE_SPREAD = 0.25

# One side going quiet is worse than both going quiet, because the screen keeps
# subtracting. On 14-Aug the NSE session died at midnight and the feed served
# 00:00 prices until 09:40 while MCX stayed live - every difference on the page
# was last night's NSE against this morning's MCX, and nothing said so. A
# difference is only a difference if both sides are current.
_FRESH_SECONDS = 120


def _age_of(*ages) -> float | None:
    """The worst age among the clocks a side has. None means never updated."""
    seen = [a for a in ages if a is not None]
    return max(seen) if seen else None


def _leg(leg: dict | None) -> dict:
    b, a = (leg or {}).get("bid"), (leg or {}).get("ask")
    mid = _mid(leg)
    return {
        "bid": b, "ask": a, "mid": mid,
        "oi": (leg or {}).get("oi"),
        "traded": bool(b or a),
        "wide": bool(mid and (a - b) / mid > _WIDE_SPREAD),
    }


def _years(expiry: str | None) -> float | None:
    """Time to expiry, counting the part of today already gone (client, 19-Aug).
    NSE and MCX expire on different dates - 10-Sep vs 17-Sep on crude - so each
    side gets its own."""
    return iv_calc.years_to(expiry)


def _forward(rows: list[dict], ex: str) -> tuple[float | None, int, float | None]:
    """The forward this exchange's own option prices imply, by put-call parity.

    NOT the future on the screen. That is the front month, and the chain is the
    month after - the error that makes Dhan's published MCX IV disagree with
    itself by 9.8 points at a single strike. Measured 18-Aug: NSE's front future
    was 60.8 away from where its own options said the forward was, MCX's 49.8.

    Returns (forward, how many strikes voted, how far apart the votes were). The
    spread is the chain's own consistency check - tight means trust it.
    """
    pairs, votes = [], []
    for r in rows or []:
        c = ((r.get("ce") or {}).get(ex) or {}).get("mid")
        p = ((r.get("pe") or {}).get(ex) or {}).get("mid")
        if c and p:
            pairs.append((r["strike"], c, p))
            votes.append(r["strike"] + c - p)
    return iv_calc.forward_from_parity(pairs), len(pairs), iv_calc.spread(votes)


def _add_iv(leg: dict, strike: float, T: float | None, fwd: float | None,
            call: bool) -> None:
    """One IV off the mid, plus the bid and ask ones, in place.

    The screen shows the single mid figure - the client asked for two on 18-Aug,
    saw them, and asked for one on 19-Aug. The pair stays in the payload for the
    app API and for the tooltip, because it is free and it is the honest width
    of the answer on a thin NSE strike quoted 712.4 / 721.8.

    BOTH sides must be quoted or neither IV is computed. This is the same rule
    the rest of the app applies to prices, and it matters more here because the
    arithmetic does not fail loudly. Live examples from the first deploy: NSE's
    8700 put had no bid and a 2,950 ask, which solves to 329.97% - and its 8800
    to 9200 calls had bids of 1.7 down to 0.8 with no ask, solving to 15% to 20%
    where the smile beside them reads 52%. Every one of those is a number a
    reader would act on, and none is a market. The existing `wide` flag cannot
    catch them: it needs two sides to measure a spread, so a one-sided leg comes
    through flagged as fine.
    """
    bid, ask = leg.get("bid"), leg.get("ask")
    if not (T and fwd and strike and bid and ask):
        leg["iv"] = leg["iv_bid"] = leg["iv_ask"] = None
        return
    leg["iv"] = iv_calc.implied_vol(leg.get("mid") or (bid + ask) / 2,
                                    fwd, strike, T, call)
    leg["iv_bid"] = iv_calc.implied_vol(bid, fwd, strike, T, call)
    leg["iv_ask"] = iv_calc.implied_vol(ask, fwd, strike, T, call)


def _num_diff(n: float | None, m: float | None, wide: bool = False,
              fresh: bool = True) -> dict:
    """Difference both ways, as the client asked: rupees and percent.
    Percent is against the MCX leg, the liquid one."""
    if n is None or m is None or not fresh:
        return {"rupees": None, "percent": None, "wide": False}
    d = round(n - m, 2)
    return {"rupees": d, "percent": round(d / m * 100, 2) if m else None, "wide": wide}


def _diff(nse: dict, mcx: dict, fresh: bool = True) -> dict:
    return _num_diff(nse["mid"], mcx["mid"], nse["wide"] or mcx["wide"], fresh)


def payload(commodity: str = "crude", window: int = 10, month: int = 0) -> dict:
    key = commodity if commodity in COMMODITIES else "crude"
    month = 1 if month else 0
    a = angel_feed.get_data(key, month)

    # Ask the MCX poller for the expiry nearest NSE's and read back exactly that
    # chain. Naming it matters now there are two months in play: taking whatever
    # alternate happened to be loaded would pair September's NSE strikes against
    # October's MCX ones on the month the user is not even looking at.
    want = crude_iv_service.set_want_expiry(key, a.get("opt_expiry"))
    m = crude_iv_service.get_full_chain(key, want, month)

    # The MCX legs come off the LIVE socket, not the REST chain. This screen
    # compares bid against bid and never reads IV, which is the only thing the
    # chain endpoint has that the socket does not - so there is no reason to
    # inherit its one-call-per-3s. The chain stays as the fallback for the few
    # seconds after a restart before the socket has ticked, and for any expiry
    # that turns out not to be subscribed.
    live_rows = mcx_opt_stream.get_chain(key, want)
    live_age = mcx_opt_stream.age(key, want)
    if live_rows:
        mrows = {r["strike"]: r for r in live_rows}
        m_age_src, m_src = live_age, "socket"
    else:
        mrows = {r["strike"]: r for r in (m.get("rows") or [])}
        m_age_src, m_src = m.get("age"), "chain"
    mfut = m.get("future_price")
    nfut = _mid(a.get("future")) or (a.get("future") or {}).get("ltp")

    n_age = _age_of(a.get("age"), a.get("chain_age"))
    m_age = _age_of(m_age_src)
    n_stale = n_age is None or n_age > _FRESH_SECONDS
    m_stale = m_age is None or m_age > _FRESH_SECONDS
    fresh = not (n_stale or m_stale)

    # Narrow by POSITION, not by price. Crude strikes step 50 and gas steps 5,
    # so any "within N x step" arithmetic silently returns one row for gas.
    src = a.get("options") or []
    atm_i = next((i for i, r in enumerate(src) if r.get("atm")), None)
    if atm_i is not None:
        src = src[max(0, atm_i - window): atm_i + window + 1]

    rows = []
    for r in src:
        mr = mrows.get(r["strike"]) or {}
        out = {"strike": r["strike"], "atm": r["atm"]}
        for side in ("ce", "pe"):
            # NOT `m` - that name holds the MCX chain for the rest of this
            # function, and shadowing it blanked the contract symbol, both
            # expiries and the feed status for an hour on 13-Aug.
            n_leg, m_leg = _leg(r.get(side)), _leg(mr.get(side))
            out[side] = {"nse": n_leg, "mcx": m_leg,
                         "diff": _diff(n_leg, m_leg, fresh)}
        rows.append(out)

    # Implied volatility, computed here rather than taken from Dhan - whose
    # figure is demonstrably wrong, and who has none for NSE at all. Two per leg,
    # off the bid and off the ask, per the client's choice on 18-Aug.
    #
    # Each exchange gets its own forward and its own time to expiry, because they
    # are genuinely different contracts: on crude, NSE expires 10-Sep and MCX
    # 17-Sep. Sharing either number across the two would produce exactly the kind
    # of quietly-wrong figure this whole exercise is about.
    nse_T, mcx_T = _years(a.get("opt_expiry")), _years(m.get("expiry"))
    nse_fwd, nse_n, nse_sp = _forward(rows, "nse")
    mcx_fwd, mcx_n, mcx_sp = _forward(rows, "mcx")
    for r in rows:
        for side, call in (("ce", True), ("pe", False)):
            _add_iv(r[side]["nse"], r["strike"], nse_T, nse_fwd, call)
            _add_iv(r[side]["mcx"], r["strike"], mcx_T, mcx_fwd, call)

    return {
        "commodity": key,
        "month": month,
        "label": (crude_iv_service.COMMODITIES.get(key) or {}).get("label", "").replace("MCX ", ""),
        "future": {
            "nse": {**(a.get("future") or {}), "mid": nfut},
            # the FUTURE's own expiry, taken from its symbol - m["expiry"] is the
            # option chain's date and showing it here was simply wrong
            "mcx": {"symbol": m.get("symbol"), "expiry": _fut_expiry(m.get("symbol")),
                    "mid": mfut, "bid": m.get("future_bid"), "ask": m.get("future_ask")},
            "diff": _num_diff(nfut, mfut, fresh=fresh),
            "same_expiry": _fut_expiry(m.get("symbol")) == (a.get("future") or {}).get("expiry"),
        },
        "fresh": fresh,
        # Everything the IV was derived from, so the screen can show its own
        # workings and a wrong answer is traceable instead of mysterious.
        # `strikes` is how many voted on the forward and `vote_spread` how far
        # apart they were; a tight spread over many strikes means the chain is
        # arbitrage-free and the forward is trustworthy.
        "iv_basis": {
            "nse": {"forward": nse_fwd, "strikes": nse_n, "vote_spread": nse_sp,
                    "expiry": a.get("opt_expiry"),
                    "days": round(nse_T * iv_calc.DAYS_YEAR) if nse_T else None},
            "mcx": {"forward": mcx_fwd, "strikes": mcx_n, "vote_spread": mcx_sp,
                    "expiry": m.get("expiry"),
                    "days": round(mcx_T * iv_calc.DAYS_YEAR) if mcx_T else None},
            "rate": 0.0, "dividend": 0.0, "model": "Black-76 (Black-Scholes, S=future, r=q=0)",
        },
        "options": {
            "nse_expiry": a.get("opt_expiry"),
            "mcx_expiry": m.get("expiry"),
            "same_expiry": (a.get("opt_expiry") or "") == (m.get("expiry") or ""),
            "atm": a.get("atm"),
            "rows": rows,
        },
        "usdinr": a.get("usdinr"),
        "nse": {"ok": a.get("ok"), "age": a.get("age"), "chain_age": a.get("chain_age"),
                "stale": n_stale, "stale_seconds": n_age if n_stale else None,
                "error": a.get("error")},
        "mcx": {"ok": m.get("ok"), "age": m_age_src, "source": m_src,
                "stale": m_stale, "stale_seconds": m_age if m_stale else None,
                "error": m.get("error")},
    }


def _elec_payload(month: int = 0) -> dict:
    """Electricity is futures-only (NSE lists no ELECMBL options), so it skips
    the whole chain machinery: two live futures, one difference - the client's
    single-value rule - and the dash discipline via the legs themselves."""
    from app.services import elec_service
    month = 1 if month else 0
    a = angel_feed.get_data("electricity", month)
    nse_fut = dict(a.get("future") or {})
    mcx = elec_service.mcx_future(month) or {}
    n_age = a.get("age")
    n_fresh = a.get("ok") and n_age is not None and n_age <= _FRESH_SECONDS
    fresh = bool(n_fresh and mcx.get("fresh"))
    n_ltp, m_ltp = nse_fut.get("ltp"), mcx.get("ltp")
    diff = round(m_ltp - n_ltp, 2) if (fresh and n_ltp and m_ltp) else None
    return {
        "commodity": "electricity", "month": month, "fresh": fresh,
        "nse": {"label": "NSE ELECTRICITY", "future": nse_fut or None,
                "age": n_age, "connected": bool(a.get("ok")), "error": a.get("error")},
        "mcx": {"label": "MCX ELECTRICITY", "future": mcx or None,
                "age": mcx.get("age")},
        "diff": diff,
        "pct": (round(diff / n_ltp * 100, 2) if diff is not None and n_ltp else None),
    }


@router.get("/nse-mcx")
def nse_mcx(commodity: str = Query("crude", pattern="^(crude|natgas|electricity)$"),
            month: int = Query(0, ge=0, le=1, description="0 = near month, 1 = the one after"),
            window: int = Query(10, ge=1, le=25, description="strikes each side of ATM")):
    if commodity == "electricity":
        return _elec_payload(month)
    return payload(commodity, window, month)


@router.get("/nse-mcx-crude")
def nse_mcx_crude(commodity: str = Query("crude", pattern="^(crude|natgas)$"),
                  month: int = Query(0, ge=0, le=1),
                  window: int = Query(10, ge=1, le=25)):
    """Kept because the dashboard and the client's app both already call it."""
    return payload(commodity, window, month)


@router.get("/nse-mcx/elec-hourly")
def elec_hourly(month: int = Query(0, ge=0, le=1),
                days: int = Query(30, ge=1, le=365)):
    """The stored hourly rows - one difference per hour, recorded live since
    02-Sep-2026. Older cannot exist: Angel's historical API has no NCO segment,
    so there is nothing to backfill the NSE side from."""
    from app.services import elec_service
    return elec_service.history(month=month, days=days)


def _strike_arg(raw: str | None) -> float | str | None:
    """Query strikes arrive as text so that "future" can share the parameter."""
    if raw is None or raw == "":
        return None
    if str(raw).lower() == nse_mcx_history.FUTURE:
        return nse_mcx_history.FUTURE
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


@router.get("/nse-mcx/graph")
def nse_mcx_graph(commodity: str = Query("crude", pattern="^(crude|natgas)$"),
                  strike: str | None = Query(None, description='a strike, "future", or omit to just list them'),
                  side: str = Query("ce", pattern="^(ce|pe)$"),
                  month: int = Query(0, ge=0, le=1),
                  days: int = Query(30, ge=1, le=60)):
    """One strike's tradeable difference over time: MCX bid minus NSE ask.

    The client buys on NSE and sells on MCX, so that is the number he nets - not
    mid against mid, which is the midpoint of a spread nobody fills at. Both are
    returned per point; the screen draws them as two lines.

    `strike=future` graphs the futures pair instead of an option.
    """
    return nse_mcx_history.series(commodity=commodity, strike=_strike_arg(strike),
                                  side=side, days=days, month=month)


@router.get("/nse-mcx/history")
def nse_mcx_history_view(commodity: str = Query("crude", pattern="^(crude|natgas)$"),
                         slot: str = Query("all", pattern="^(all|10:00|12:00|14:00|15:00|16:00|18:00|20:00|22:00|23:15)$"),
                         days: int = Query(7, ge=1, le=60),
                         month: int = Query(0, ge=0, le=1),
                         date: str | None = Query(None, description="YYYY-MM-DD")):
    """Stored 10:00 / 12:00 / 15:00 IST boards, newest first. Each snapshot's
    `board` is exactly the live shape, so one component renders both views."""
    return nse_mcx_history.get_history(commodity=commodity, slot=slot, days=days, date=date, month=month)
