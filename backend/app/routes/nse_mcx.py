"""NSE vs MCX crude oil — future and option chain side by side (client, 13-Aug).

NSE comes from Angel One (the only provider that carries NSE's commodity
segment), MCX from the existing Dhan option-chain service. Both are in-memory
reads; nothing here calls upstream or touches the database.

Two honest caveats the screen has to carry:
  * The FUTURES line up exactly - both expire 19-Aug-2026 - so that difference
    is clean.
  * The OPTION expiries never match. MCX runs 17-Sep, NSE 10-Sep. The same
    strike therefore holds ~7 days more time value on the MCX side, so part of
    any premium difference is time, not a real gap. The client chose to compare
    anyway with both dates on screen, so both dates are returned per row.
  * A dead NSE contract still prints an old LTP, so only bid/ask are compared
    and a leg with neither is reported as no market.
"""
from datetime import datetime

from fastapi import APIRouter, Query

from app.services import angel_feed, crude_iv_service

router = APIRouter(prefix="/api", tags=["nse-mcx"])


def _fut_expiry(symbol: str | None) -> str | None:
    """MCX future symbols read CRUDEOIL-19Aug2026-FUT."""
    if not symbol or "-" not in symbol:
        return None
    try:
        return datetime.strptime(symbol.split("-")[1], "%d%b%Y").date().isoformat()
    except Exception:  # noqa: BLE001
        return None


def _mid(leg: dict | None) -> float | None:
    if not leg:
        return None
    b, a = leg.get("bid"), leg.get("ask")
    if b and a:
        return round((b + a) / 2, 2)
    return b or a or None


def _diff(nse: float | None, mcx: float | None) -> dict:
    """Difference both ways, as the client asked: rupees and percent.
    Percent is against the MCX leg, the liquid one."""
    if nse is None or mcx is None:
        return {"rupees": None, "percent": None}
    d = round(nse - mcx, 2)
    return {"rupees": d, "percent": round(d / mcx * 100, 2) if mcx else None}


def _payload(window: int) -> dict:
    a = angel_feed.get_data()

    # Ask the MCX poller for the expiry nearest NSE's, then read the FULL chain
    # (both legs on every strike, not the calls-above/puts-below display layout).
    crude_iv_service.set_want_expiry("crude", a.get("opt_expiry"))
    m = crude_iv_service.get_full_chain("crude")

    mrows = {r["strike"]: r for r in (m.get("rows") or [])}
    mfut = m.get("future_price")
    nfut = _mid(a.get("future")) or (a.get("future") or {}).get("ltp")

    rows = []
    for r in (a.get("options") or []):
        if abs(r["strike"] - (a.get("atm") or r["strike"])) > window * 50:
            continue
        mr = mrows.get(r["strike"]) or {}
        out = {"strike": r["strike"], "atm": r["atm"]}
        for side in ("ce", "pe"):
            n_leg, m_leg = r.get(side), mr.get(side)
            n_mid = _mid(n_leg)
            m_mid = _mid(m_leg)
            out[side] = {
                "nse": {"bid": (n_leg or {}).get("bid"), "ask": (n_leg or {}).get("ask"),
                        "mid": n_mid, "oi": (n_leg or {}).get("oi"),
                        "traded": bool((n_leg or {}).get("bid") or (n_leg or {}).get("ask"))},
                "mcx": {"bid": (m_leg or {}).get("bid"), "ask": (m_leg or {}).get("ask"),
                        "mid": m_mid, "oi": (m_leg or {}).get("oi"),
                        "traded": bool((m_leg or {}).get("bid") or (m_leg or {}).get("ask"))},
                "diff": _diff(n_mid, m_mid),
            }
        rows.append(out)

    return {
        "commodity": "crude",
        "future": {
            "nse": {**(a.get("future") or {}), "mid": nfut},
            # the FUTURE's own expiry, taken from its symbol - m["expiry"] is the
            # option chain's date and showing it here was simply wrong
            "mcx": {"symbol": m.get("symbol"), "expiry": _fut_expiry(m.get("symbol")),
                    "mid": mfut},
            "diff": _diff(nfut, mfut),
            "same_expiry": _fut_expiry(m.get("symbol")) == (a.get("future") or {}).get("expiry"),
        },
        "options": {
            "nse_expiry": a.get("opt_expiry"),
            "mcx_expiry": m.get("expiry"),
            "same_expiry": (a.get("opt_expiry") or "") == (m.get("expiry") or ""),
            "atm": a.get("atm"),
            "rows": rows,
        },
        "usdinr": a.get("usdinr"),
        "nse": {"ok": a.get("ok"), "age": a.get("age"), "error": a.get("error")},
        "mcx": {"ok": m.get("ok"), "age": m.get("age"), "error": m.get("error")},
    }


@router.get("/nse-mcx-crude")
def nse_mcx_crude(window: int = Query(10, ge=1, le=25, description="strikes each side of ATM")):
    return _payload(window)
