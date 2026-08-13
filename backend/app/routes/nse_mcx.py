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
from datetime import datetime

from fastapi import APIRouter, Query

from app.services import angel_feed, crude_iv_service, nse_mcx_history

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


def _diff(nse: float | None, mcx: float | None) -> dict:
    """Difference both ways, as the client asked: rupees and percent.
    Percent is against the MCX leg, the liquid one."""
    if nse is None or mcx is None:
        return {"rupees": None, "percent": None}
    d = round(nse - mcx, 2)
    return {"rupees": d, "percent": round(d / mcx * 100, 2) if mcx else None}


def payload(commodity: str = "crude", window: int = 10) -> dict:
    key = commodity if commodity in COMMODITIES else "crude"
    a = angel_feed.get_data(key)

    # Ask the MCX poller for the expiry nearest NSE's, then read the FULL chain
    # (both legs on every strike, not the calls-above/puts-below display layout).
    crude_iv_service.set_want_expiry(key, a.get("opt_expiry"))
    m = crude_iv_service.get_full_chain(key)

    mrows = {r["strike"]: r for r in (m.get("rows") or [])}
    mfut = m.get("future_price")
    nfut = _mid(a.get("future")) or (a.get("future") or {}).get("ltp")

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
        "commodity": key,
        "label": (crude_iv_service.COMMODITIES.get(key) or {}).get("label", "").replace("MCX ", ""),
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
        "nse": {"ok": a.get("ok"), "age": a.get("age"),
                "chain_age": a.get("chain_age"), "error": a.get("error")},
        "mcx": {"ok": m.get("ok"), "age": m.get("age"), "error": m.get("error")},
    }


@router.get("/nse-mcx")
def nse_mcx(commodity: str = Query("crude", pattern="^(crude|natgas)$"),
            window: int = Query(10, ge=1, le=25, description="strikes each side of ATM")):
    return payload(commodity, window)


@router.get("/nse-mcx-crude")
def nse_mcx_crude(commodity: str = Query("crude", pattern="^(crude|natgas)$"),
                  window: int = Query(10, ge=1, le=25)):
    """Kept because the dashboard and the client's app both already call it."""
    return payload(commodity, window)


@router.get("/nse-mcx/history")
def nse_mcx_history_view(commodity: str = Query("crude", pattern="^(crude|natgas)$"),
                         slot: str = Query("all", pattern="^(all|10:00|12:00|15:00)$"),
                         days: int = Query(7, ge=1, le=60),
                         date: str | None = Query(None, description="YYYY-MM-DD")):
    """Stored 10:00 / 12:00 / 15:00 IST boards, newest first. Each snapshot's
    `board` is exactly the live shape, so one component renders both views."""
    return nse_mcx_history.get_history(commodity=commodity, slot=slot, days=days, date=date)
