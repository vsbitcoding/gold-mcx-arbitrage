"""MCX option strikes for the NSE-vs-MCX screen, over the LIVE WebSocket.

That screen was reading its MCX half from Dhan's REST option-chain endpoint,
which allows one call every 3 s. With four boards taking turns the far month
was arriving 30 s old, and the client is comparing prices - old numbers on one
side of a difference are worse than no numbers.

The chain endpoint exists for one reason: it is the only place IV and greeks
come from. **This screen uses neither.** It compares bid against bid. So the
strikes it needs are subscribed on the Dhan WebSocket the app already runs, the
same way `goldopt_service` streams its option spreads, and the REST chain is
left to the Crude/Gas IV tab that genuinely needs it.

Design rules, same as every other feed here:
  * ZERO database writes. Quotes land in the shared in-memory quote_store.
  * No new connection and no new credential - these ride the one Dhan socket.
  * Resolved once at feed start and re-checked daily, never per request.
"""
from __future__ import annotations

import logging
from datetime import datetime

from app.services.goldopt_service import _parse_all, _resolve_futures
from app.services.instrument_resolver import _download_csv
from app.services.market_data import clean_sides, quote_store

log = logging.getLogger("mcx_opt_stream")

# Underlyings this screen compares, and the strike step the NSE ladder uses -
# subscribing MCX's own 50-point crude strikes would double the contract count
# for rows the screen never draws.
COMMODITIES: dict[str, dict] = {
    "crude":  {"underlying": "CRUDEOIL",   "step": 100},
    "natgas": {"underlying": "NATURALGAS", "step": 5},
}
# Strikes each side of the money. The screen shows 21; the extra sit there so a
# day's drift cannot walk out of the subscribed window, which is fixed at
# startup because that is when the socket subscribes.
_WINDOW = 15
# How many expiries forward to carry. The screen wants the MCX expiry nearest
# NSE's for two months, and those are not always MCX's own first two.
_EXPIRIES = 3

# commodity -> {"expiries": [date], "by_exp": {iso: {(strike, side): sid}}}
_state: dict[str, dict] = {}


def refresh() -> None:
    """Resolve the strikes to stream. Called at feed startup, like its siblings."""
    try:
        csv_text = _download_csv()
        opt = _parse_all(csv_text)
        futs = _resolve_futures(csv_text)
    except Exception as e:  # noqa: BLE001 - never take the feed down with us
        log.warning("mcx option stream: scrip master unavailable (%s)", e)
        return

    today = datetime.now()
    for key, cfg in COMMODITIES.items():
        under, step = cfg["underlying"], cfg["step"]
        by_expiry = opt.get(under, {})
        exps = sorted(e for e in by_expiry if e >= today)[:_EXPIRIES]
        if not exps:
            log.warning("mcx option stream: no %s option expiries", under)
            continue

        # Centre on the front future. Its price survives a restart in the quote
        # store, so a cold start still picks a sane window instead of the
        # middle of every strike ever listed.
        fut = futs.get(under) or {}
        q = quote_store.get(fut.get("security_id") or "")
        c_bid, c_ask = clean_sides(q)
        centre = q.ltp or ((c_bid + c_ask) / 2 if (c_bid and c_ask) else None)

        out: dict = {}
        for exp in exps:
            legs = by_expiry[exp]
            strikes = sorted({s for (s, _t) in legs if s % step == 0})
            if not strikes:
                continue
            mid = centre or strikes[len(strikes) // 2]
            atm = min(strikes, key=lambda s: abs(s - mid))
            window = sorted(strikes, key=lambda s: abs(s - atm))[: _WINDOW * 2 + 1]
            picked = {}
            for s in window:
                for side in ("CE", "PE"):
                    rec = legs.get((s, side))
                    if rec:
                        picked[(float(s), side)] = rec["security_id"]
            if picked:
                out[exp.date().isoformat()] = picked

        _state[key] = {"expiries": [e.date().isoformat() for e in exps], "by_exp": out}
        log.info("mcx option stream: %s %d expiries, %d contracts (centre %s)",
                 key, len(out), sum(len(v) for v in out.values()), centre)


def get_subscription_meta() -> dict:
    """{security_id: meta} for the Dhan feed to subscribe."""
    meta: dict = {}
    for key, st in _state.items():
        for exp, legs in st.get("by_exp", {}).items():
            for (strike, side), sid in legs.items():
                meta[sid] = {
                    "short": f"nm_{key}_{exp}_{strike:g}{side}",
                    "trading_symbol": "",
                    "kind": "nse_mcx_option", "commodity": key,
                    "strike": strike, "option_type": side, "expiry": exp,
                }
    return meta


def expiries(commodity: str) -> list[str]:
    return (_state.get(commodity) or {}).get("expiries", [])


def get_chain(commodity: str, expiry: str | None) -> list[dict]:
    """Live rows for one expiry: [{strike, ce:{bid,ask}, pe:{bid,ask}}].

    Returns [] for an expiry that is not streamed, rather than the nearest one -
    a chain wearing the wrong month's label is the one mistake this screen must
    never make.
    """
    st = _state.get(commodity) or {}
    legs = (st.get("by_exp") or {}).get(expiry or "")
    if not legs:
        return []

    rows: dict[float, dict] = {}
    for (strike, side), sid in legs.items():
        q = quote_store.get(sid)
        row = rows.setdefault(strike, {"strike": strike, "ce": None, "pe": None})
        row["ce" if side == "CE" else "pe"] = {
            **dict(zip(("bid", "ask"), clean_sides(q))),
            "ltp": q.ltp or None, "oi": None,
        }
    return [rows[s] for s in sorted(rows)]


def age(commodity: str, expiry: str | None) -> float | None:
    """Seconds since the freshest tick on this chain. None if nothing has ticked.

    The newest timestamp, not the oldest: an untraded wing strike is silent all
    day and would otherwise make a busy chain look dead.
    """
    st = _state.get(commodity) or {}
    legs = (st.get("by_exp") or {}).get(expiry or "")
    if not legs:
        return None
    import time
    newest = max((quote_store.get(sid).timestamp for sid in legs.values()), default=0)
    return round(time.time() - newest, 1) if newest else None
