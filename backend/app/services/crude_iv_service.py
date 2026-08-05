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
from app.services.instrument_resolver import _download_csv, _parse_expiry

log = logging.getLogger("option_iv")

_BASE = "https://api.dhan.co/v2"
_SEGMENT = "MCX_COMM"
# Dhan's floor is one option-chain call per 3 s. With two commodities that is
# one call each per 8 s - still far faster than a desk reads a screen.
_GAP_SECONDS = 4.0
_ROUND_SECONDS = 8

COMMODITIES: dict[str, dict] = {
    "crude":  {"underlying": "CRUDEOIL",   "label": "MCX CRUDE OIL",   "decimals": 1},
    "natgas": {"underlying": "NATURALGAS", "label": "MCX NATURAL GAS", "decimals": 2},
}


def _blank() -> dict:
    return {"underlying_id": None, "underlying_name": None, "future_price": None,
            "expiry": None, "expiries": [], "atm": None, "rows": [],
            "ts": 0.0, "ok": False, "error": None}


_state: dict[str, dict] = {k: _blank() for k in COMMODITIES}
_stop = threading.Event()


def _headers(tok: str) -> dict:
    return {"access-token": tok, "client-id": settings.DHAN_CLIENT_ID,
            "Content-Type": "application/json", "Accept": "application/json"}


def _resolve_underlying(underlying: str) -> tuple[str | None, str | None]:
    """Front-month CRUDEOIL future — the option chain's underlying scrip.

    Reads the same compact scrip master the rest of the app uses (SEM_* columns);
    the detailed CSV has friendlier names but is a second large download for no
    gain.
    """
    try:
        rows = list(csv.DictReader(io.StringIO(_download_csv())))
    except Exception as e:  # noqa: BLE001
        log.warning("crude IV: scrip master unavailable (%s)", e)
        return None, None
    today = datetime.now()
    best = None
    for r in rows:
        if r.get("SEM_EXM_EXCH_ID") != "MCX" or r.get("SEM_INSTRUMENT_NAME") != "FUTCOM":
            continue
        if (r.get("SEM_TRADING_SYMBOL", "") or "").split("-", 1)[0] != underlying:
            continue
        exp = _parse_expiry(r.get("SEM_EXPIRY_DATE", ""))
        if not exp or exp < today:
            continue
        if best is None or exp < best[0]:
            best = (exp, str(r.get("SEM_SMST_SECURITY_ID")), r.get("SEM_TRADING_SYMBOL", ""))
    return (best[1], best[2]) if best else (None, None)


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


def _poll_once(sess: requests.Session, tok: str, key: str) -> None:
    st = _state[key]
    sid = st["underlying_id"]
    body = {"UnderlyingScrip": int(sid), "UnderlyingSeg": _SEGMENT}

    if not st["expiry"]:
        r = sess.post(f"{_BASE}/optionchain/expirylist", headers=_headers(tok),
                      data=json.dumps(body), timeout=20)
        r.raise_for_status()
        exps = (r.json() or {}).get("data") or []
        if not exps:
            raise RuntimeError("no expiries returned")
        st["expiries"] = exps
        st["expiry"] = exps[0]
        time.sleep(_GAP_SECONDS)            # respect the one-call-per-3s rule

    r = sess.post(f"{_BASE}/optionchain", headers=_headers(tok),
                  data=json.dumps({**body, "Expiry": st["expiry"]}), timeout=25)
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
    st.update({"future_price": spot, "rows": rows, "atm": atm,
               "ts": time.time(), "ok": True, "error": None})


def _loop() -> None:
    sess = requests.Session()
    last_resolve: dict[str, float] = {}
    while not _stop.is_set():
        for key, cfg in COMMODITIES.items():
            if _stop.is_set():
                break
            st = _state[key]
            try:
                if not st["underlying_id"] or (time.time() - last_resolve.get(key, 0)) > 12 * 3600:
                    sid, name = _resolve_underlying(cfg["underlying"])
                    if sid:
                        if sid != st["underlying_id"]:
                            st["expiry"] = None          # contract rolled → re-read expiries
                        st["underlying_id"], st["underlying_name"] = sid, name
                        last_resolve[key] = time.time()
                        log.info("option IV: %s underlying %s (%s)", key, name, sid)
                    else:
                        raise RuntimeError(f"{cfg['underlying']} future not found in scrip master")

                tok = dhan_auth.get_token(settings.DHAN_CLIENT_ID, settings.DHAN_MPIN,
                                          settings.DHAN_TOTP_SECRET).access_token
                _poll_once(sess, tok, key)
            except Exception as e:  # noqa: BLE001 — a bad poll must never kill the thread
                st["ok"] = False
                st["error"] = str(e)[:160]
                log.warning("option IV poll failed (%s): %s", key, st["error"])
                # An expiry that has rolled off errors forever until re-read.
                if "Expiry" in str(e) or "400" in str(e):
                    st["expiry"] = None
            _stop.wait(_GAP_SECONDS)
        _stop.wait(max(0, _ROUND_SECONDS - _GAP_SECONDS * len(COMMODITIES)))


def get_chain(commodity: str = "crude", window: int = 10) -> dict:
    """ATM ±`window` strikes. Client's convention (same as the Commodity Options
    tab): CE above the money, PE below it, and BOTH sides on the ATM row."""
    cfg = COMMODITIES.get(commodity) or COMMODITIES["crude"]
    st = _state[commodity if commodity in _state else "crude"]
    rows, atm = st["rows"], st["atm"]
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
    age = round(time.time() - st["ts"], 1) if st["ts"] else None
    return {
        "exchange": "MCX",
        "commodity": commodity,
        "label": cfg["label"],
        "decimals": cfg["decimals"],
        "symbol": st["underlying_name"],
        "future_price": st["future_price"],
        "expiry": st["expiry"],
        "expiries": st["expiries"],
        "atm": atm,
        "iv_unit": "percent",
        "age": age,
        "ok": st["ok"],
        "error": st["error"],
        "rows": out,
    }


def start_in_background() -> None:
    if not settings.CRUDE_IV_ENABLED:
        log.info("option IV service disabled")
        return
    threading.Thread(target=_loop, daemon=True, name="crude-iv").start()
    log.info("option IV service starting (Dhan MCX chains: %s, ~%ss round, in-memory)",
             ", ".join(COMMODITIES), _ROUND_SECONDS)
