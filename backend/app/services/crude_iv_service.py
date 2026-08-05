"""MCX crude-oil option chain WITH implied volatility and greeks (client, 05-Aug).

The live WebSocket feed carries bid/ask/ltp only — IV and greeks are not in the
tick stream at all. They come from Dhan's REST option-chain endpoint instead,
which returns implied_volatility plus delta/theta/gamma/vega for every strike in
one call.

Design constraints (same rules as every other feed here):
  * ZERO database writes — one small in-memory dict the route reads.
  * NEVER mints a Dhan token. It reuses the cached one the live feed already
    holds; minting a second token would invalidate the running feed's token.
  * Dhan allows ONE option-chain call every 3 seconds. We poll every 5 s, which
    leaves headroom and is far faster than a bullion desk can read a screen.
  * The underlying (front-month CRUDEOIL future) is resolved once and re-checked
    daily, not on every poll.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import threading
import time
from datetime import datetime, timedelta

import requests

from app.config import settings
from app.services import dhan_auth
from app.services.instrument_resolver import _download_csv

log = logging.getLogger("crude_iv")

_BASE = "https://api.dhan.co/v2"
_POLL_SECONDS = 5           # Dhan's floor is one call per 3 s
_UNDERLYING = "CRUDEOIL"
_SEGMENT = "MCX_COMM"

_state: dict = {
    "underlying_id": None,
    "underlying_name": None,
    "future_price": None,
    "expiry": None,
    "expiries": [],
    "atm": None,
    "rows": [],             # [{strike, ce:{...}, pe:{...}}] — full chain, trimmed by the route
    "ts": 0.0,
    "ok": False,
    "error": None,
}
_stop = threading.Event()


def _headers(tok: str) -> dict:
    return {"access-token": tok, "client-id": settings.DHAN_CLIENT_ID,
            "Content-Type": "application/json", "Accept": "application/json"}


def _resolve_underlying() -> tuple[str | None, str | None]:
    """Front-month CRUDEOIL future — the option chain's underlying scrip."""
    try:
        rows = list(csv.DictReader(io.StringIO(_download_csv())))
    except Exception as e:  # noqa: BLE001
        log.warning("crude IV: scrip master unavailable (%s)", e)
        return None, None
    today = datetime.now().strftime("%Y-%m-%d")
    futs = [r for r in rows
            if r.get("EXCH_ID") == "MCX"
            and r.get("UNDERLYING_SYMBOL") == _UNDERLYING
            and r.get("INSTRUMENT") == "FUTCOM"
            and (r.get("SM_EXPIRY_DATE") or "") >= today]
    futs.sort(key=lambda r: r.get("SM_EXPIRY_DATE") or "")
    if not futs:
        return None, None
    return futs[0]["SECURITY_ID"], futs[0].get("DISPLAY_NAME")


def _leg(d: dict | None) -> dict | None:
    if not d:
        return None
    g = d.get("greeks") or {}
    return {
        "ltp": d.get("last_price"),
        "bid": d.get("top_bid_price"),
        "ask": d.get("top_ask_price"),
        "iv": d.get("implied_volatility"),          # Dhan gives PERCENT (64.89)
        "delta": g.get("delta"),
        "theta": g.get("theta"),
        "gamma": g.get("gamma"),
        "vega": g.get("vega"),
        "oi": d.get("oi"),
        "volume": d.get("volume"),
        "prev_oi": d.get("previous_oi"),
    }


def _poll_once(sess: requests.Session, tok: str) -> None:
    sid = _state["underlying_id"]
    body = {"UnderlyingScrip": int(sid), "UnderlyingSeg": _SEGMENT}

    if not _state["expiry"]:
        r = sess.post(f"{_BASE}/optionchain/expirylist", headers=_headers(tok),
                      data=json.dumps(body), timeout=20)
        r.raise_for_status()
        exps = (r.json() or {}).get("data") or []
        if not exps:
            raise RuntimeError("no expiries returned")
        _state["expiries"] = exps
        _state["expiry"] = exps[0]
        time.sleep(3.2)                     # respect the one-call-per-3s rule

    r = sess.post(f"{_BASE}/optionchain", headers=_headers(tok),
                  data=json.dumps({**body, "Expiry": _state["expiry"]}), timeout=25)
    r.raise_for_status()
    data = (r.json() or {}).get("data") or {}
    oc = data.get("oc") or {}
    spot = data.get("last_price")

    rows = []
    for k, legs in oc.items():
        try:
            strike = float(k)
        except (TypeError, ValueError):
            continue
        ce, pe = _leg(legs.get("ce")), _leg(legs.get("pe"))
        # Dhan lists every listed strike; the far wings are empty all day.
        if not ce and not pe:
            continue
        rows.append({"strike": strike, "ce": ce, "pe": pe})
    rows.sort(key=lambda x: x["strike"])

    atm = min((r["strike"] for r in rows), key=lambda s: abs(s - spot)) if (rows and spot) else None
    _state.update({"future_price": spot, "rows": rows, "atm": atm,
                   "ts": time.time(), "ok": True, "error": None})


def _loop() -> None:
    sess = requests.Session()
    last_resolve = 0.0
    while not _stop.is_set():
        try:
            if not _state["underlying_id"] or (time.time() - last_resolve) > 12 * 3600:
                sid, name = _resolve_underlying()
                if sid:
                    if sid != _state["underlying_id"]:
                        _state["expiry"] = None          # contract rolled → re-read expiries
                    _state["underlying_id"], _state["underlying_name"] = sid, name
                    last_resolve = time.time()
                    log.info("crude IV: underlying %s (%s)", name, sid)
                else:
                    raise RuntimeError("CRUDEOIL future not found in scrip master")

            tok = dhan_auth.get_token(settings.DHAN_CLIENT_ID, settings.DHAN_MPIN,
                                      settings.DHAN_TOTP_SECRET).access_token
            _poll_once(sess, tok)
        except Exception as e:  # noqa: BLE001 — a bad poll must never kill the thread
            _state["ok"] = False
            _state["error"] = str(e)[:160]
            log.warning("crude IV poll failed: %s", _state["error"])
            # An expiry that has rolled off returns errors forever until re-read.
            if "Expiry" in str(e) or "400" in str(e):
                _state["expiry"] = None
            _stop.wait(15)
            continue
        _stop.wait(_POLL_SECONDS)


def get_chain(window: int = 10) -> dict:
    """ATM ±`window` strikes. Client's convention (same as the Commodity Options
    tab): CE above the money, PE below it, and BOTH sides on the ATM row."""
    rows, atm = _state["rows"], _state["atm"]
    out = []
    if rows and atm is not None:
        idx = next((i for i, r in enumerate(rows) if r["strike"] == atm), None)
        if idx is not None:
            lo, hi = max(0, idx - window), min(len(rows), idx + window + 1)
            for r in rows[lo:hi]:
                is_atm = r["strike"] == atm
                side = "ATM" if is_atm else ("CE" if r["strike"] > atm else "PE")
                out.append({
                    "strike": r["strike"],
                    "side": side,
                    "atm": is_atm,
                    "ce": r["ce"] if side in ("CE", "ATM") else None,
                    "pe": r["pe"] if side in ("PE", "ATM") else None,
                })
    age = round(time.time() - _state["ts"], 1) if _state["ts"] else None
    return {
        "exchange": "MCX",
        "symbol": _state["underlying_name"],
        "future_price": _state["future_price"],
        "expiry": _state["expiry"],
        "expiries": _state["expiries"],
        "atm": atm,
        "iv_unit": "percent",
        "age": age,
        "ok": _state["ok"],
        "error": _state["error"],
        "rows": out,
    }


def start_in_background() -> None:
    if not settings.CRUDE_IV_ENABLED:
        log.info("crude IV service disabled")
        return
    threading.Thread(target=_loop, daemon=True, name="crude-iv").start()
    log.info("crude IV service starting (Dhan MCX option chain, %ss poll, in-memory)", _POLL_SECONDS)
