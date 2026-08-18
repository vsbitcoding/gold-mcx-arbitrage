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
_GAP_SECONDS = 5.0     # raised from 4.0: the extra comparison chain tipped us into 429s
_ROUND_SECONDS = 10

COMMODITIES: dict[str, dict] = {
    "crude":  {"underlying": "CRUDEOIL",   "label": "MCX CRUDE OIL",   "decimals": 1},
    "natgas": {"underlying": "NATURALGAS", "label": "MCX NATURAL GAS", "decimals": 2},
}


def _blank() -> dict:
    return {"underlying_id": None, "underlying_name": None, "future_price": None,
            # The month after, so the NSE-vs-MCX screen can put next month's
            # futures side by side too. Only the FRONT one underlies the option
            # chain request; this pair is quoted purely to be displayed.
            "next_id": None, "next_name": None, "next_price": None,
            # bid/ask on both futures, so the comparison screen can show the
            # MCX card the way it shows the NSE one instead of a contract name
            # that wraps onto two lines and repeats the expiry above it.
            "future_bid": None, "future_ask": None,
            "next_bid": None, "next_ask": None,
            "expiry": None, "expiries": [], "atm": None, "rows": [],
            # Caller-chosen expiries. The NSE-vs-MCX screen needs MCX's
            # SEPTEMBER chain to sit beside NSE's 10-Sep; pairing NSE against
            # MCX's own front month (17-Aug) puts 24 days between them and the
            # premium "difference" comes out at +230%. With two months on that
            # screen there can be several at once, so they are held as a dict
            # keyed by expiry and refreshed one per round - the far months are
            # thin and barely move, and a chain call every 5 s is the budget.
            "want": [], "chains": {}, "want_turn": 0,
            "ts": 0.0, "ok": False, "error": None}


_state: dict[str, dict] = {k: _blank() for k in COMMODITIES}
_LIVE_UNDERLYING: dict[str, float] = {}      # commodity -> live futures mid
_stop = threading.Event()


def _headers(tok: str) -> dict:
    return {"access-token": tok, "client-id": settings.DHAN_CLIENT_ID,
            "Content-Type": "application/json", "Accept": "application/json"}


def _resolve_underlying(underlying: str) -> list[tuple[str, str]]:
    """The next two MCX futures for `underlying`, nearest first.

    The first is the option chain's underlying scrip; the second exists so the
    comparison screen can show next month's futures beside next month's chain.

    Reads the same compact scrip master the rest of the app uses (SEM_* columns);
    the detailed CSV has friendlier names but is a second large download for no
    gain.
    """
    try:
        rows = list(csv.DictReader(io.StringIO(_download_csv())))
    except Exception as e:  # noqa: BLE001
        log.warning("crude IV: scrip master unavailable (%s)", e)
        return []          # a list, like every other return - a bare (None, None)
                           # is truthy and unpacking months[0] off it would raise
    today = datetime.now()
    found = []
    for r in rows:
        if r.get("SEM_EXM_EXCH_ID") != "MCX" or r.get("SEM_INSTRUMENT_NAME") != "FUTCOM":
            continue
        if (r.get("SEM_TRADING_SYMBOL", "") or "").split("-", 1)[0] != underlying:
            continue
        exp = _parse_expiry(r.get("SEM_EXPIRY_DATE", ""))
        if not exp or exp < today:
            continue
        found.append((exp, str(r.get("SEM_SMST_SECURITY_ID")), r.get("SEM_TRADING_SYMBOL", "")))
    found.sort()
    return [(sid, name) for _e, sid, name in found[:2]]


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


def _underlying_prices(sess: requests.Session, tok: str) -> dict:
    """Live futures price per commodity, straight from the quote endpoint.

    The option chain also returns a `last_price` for the underlying, but it is
    STALE - on 13-Aug it read 7946 while the direct quote (and NSE, and IBKR
    converted to rupees) all said 7800. That 146-point error fed both the
    displayed future price and the ATM strike selection.
    """
    ids = [int(st[f]) for st in _state.values()
           for f in ("underlying_id", "next_id") if st.get(f)]
    if not ids:
        return {}
    r = sess.post(f"{_BASE}/marketfeed/quote", headers=_headers(tok),
                  data=json.dumps({"MCX_COMM": ids}), timeout=20)
    r.raise_for_status()
    got = ((r.json() or {}).get("data") or {}).get("MCX_COMM") or {}
    def px(sid):
        """(mid, bid, ask) - mid falls back to the last trade when one-sided."""
        q = got.get(str(sid or "")) or {}
        dep = q.get("depth") or {}
        bid = (dep.get("buy") or [{}])[0].get("price") or None
        ask = (dep.get("sell") or [{}])[0].get("price") or None
        mid = round((bid + ask) / 2, 2) if (bid and ask) else (q.get("last_price") or None)
        return mid, bid, ask

    out = {}
    for key, st in _state.items():
        out[key], st["future_bid"], st["future_ask"] = px(st.get("underlying_id"))
        st["next_price"], st["next_bid"], st["next_ask"] = px(st.get("next_id"))
    return out


def _chain_rows(payload: dict) -> tuple[list, float | None]:
    data = (payload or {}).get("data") or {}
    oc = data.get("oc") or {}
    rows = []
    for k, legs in oc.items():
        try:
            strike = float(k)
        except (TypeError, ValueError):
            continue
        ce, pe = _leg(legs.get("ce")), _leg(legs.get("pe"))
        if not ce and not pe:
            continue
        rows.append({"strike": strike, "ce": ce, "pe": pe})
    rows.sort(key=lambda x: x["strike"])
    return rows, data.get("last_price")


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
    # prefer the live quote; the chain's own last_price lags badly
    spot = _LIVE_UNDERLYING.get(key) or data.get("last_price")

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

    # Extra chains for whichever expiries a caller asked for, ONE per round.
    # Fetching every one each round would put five chain calls between two
    # refreshes of the front month, which is the screen everybody watches.
    listed = st.get("expiries") or []
    wanted = [e for e in st.get("want") or [] if e and e != st["expiry"] and e in listed]
    # Drop anything nobody asks for any more, so a rolled-past chain can never
    # be served as live - that bug had the September chain frozen on screen.
    st["chains"] = {e: v for e, v in st["chains"].items() if e in wanted}
    if wanted:
        st["want_turn"] = (st.get("want_turn", 0) + 1) % len(wanted)
        pick = wanted[st["want_turn"]]
        time.sleep(_GAP_SECONDS)
        r2 = sess.post(f"{_BASE}/optionchain", headers=_headers(tok),
                       data=json.dumps({**body, "Expiry": pick}), timeout=25)
        r2.raise_for_status()
        rows2, _ = _chain_rows(r2.json())
        if rows2:
            st["chains"][pick] = {"rows": rows2, "ts": time.time()}


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
                    months = _resolve_underlying(cfg["underlying"])
                    sid, name = months[0] if months else (None, None)
                    st["next_id"], st["next_name"] = months[1] if len(months) > 1 else (None, None)
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
                # one quote call covers every underlying, so this costs a single
                # request per round no matter how many commodities are tracked
                if key == next(iter(COMMODITIES)):
                    try:
                        _LIVE_UNDERLYING.update(_underlying_prices(sess, tok))
                    except Exception as e:  # noqa: BLE001
                        log.debug("underlying quote failed: %s", e)
                    _stop.wait(2.0)
                _poll_once(sess, tok, key)
            except Exception as e:  # noqa: BLE001 — a bad poll must never kill the thread
                st["ok"] = False
                st["error"] = str(e)[:160]
                log.warning("option IV poll failed (%s): %s", key, st["error"])
                msg = str(e)
                # A dead token 401s forever unless someone asks for a new one.
                # The WebSocket feed keeps running on its established connection,
                # so nothing looks broken while every REST call quietly fails -
                # that is exactly how the MCX chain sat empty on 13-Aug.
                if "401" in msg or "Unauthorized" in msg:
                    log.warning("option IV: Dhan token rejected - forcing re-auth")
                    try:
                        dhan_auth.invalidate(disk=True)
                    except Exception:  # noqa: BLE001
                        pass
                    _stop.wait(5)
                # An expiry that has rolled off errors forever until re-read.
                elif "Expiry" in msg or "400" in msg:
                    st["expiry"] = None
            _stop.wait(_GAP_SECONDS)
        _stop.wait(max(0, _ROUND_SECONDS - _GAP_SECONDS * len(COMMODITIES)))


def set_want_expiry(commodity: str, iso_date: str | None) -> str | None:
    """Ask the poller to keep a chain near `iso_date`, and say which it picked.

    Callers hand over the date they want to sit beside - the NSE screen passes
    NSE's own expiry - and get back the listed MCX expiry nearest to it, so they
    can read exactly the chain they asked for out of `get_full_chain`.
    """
    st = _state.get(commodity)
    if not st or not iso_date:
        return None
    listed = st.get("expiries") or []
    if not listed:
        return None
    pick = min(listed, key=lambda e: abs(
        (datetime.strptime(e, "%Y-%m-%d") - datetime.strptime(iso_date, "%Y-%m-%d")).days))
    if pick not in st["want"]:
        st["want"].append(pick)
    return pick


def get_full_chain(commodity: str = "crude", expiry: str | None = None,
                   month: int = 0) -> dict:
    """Every strike with BOTH legs - no calls-above/puts-below trimming.

    `expiry` names which chain is wanted (what set_want_expiry handed back).
    Omit it for the front month. An expiry that has been asked for but not
    fetched yet comes back empty rather than silently falling back to a
    different month - a chain labelled September showing August prices is the
    worst thing this screen could do.
    """
    st = _state.get(commodity) or _state["crude"]
    if expiry and expiry != st["expiry"]:
        got = (st.get("chains") or {}).get(expiry) or {}
        rows, ts = got.get("rows", []), got.get("ts", 0.0)
    else:
        expiry, rows, ts = st["expiry"], st["rows"], st["ts"]
    # month 1 shows the NEXT future beside the next chain; the front one would
    # be a different contract wearing the right chain's label.
    nxt = month == 1 and st.get("next_name")
    return {
        "expiry": expiry,
        "expiries": st.get("expiries") or [],
        "future_price": st["next_price"] if nxt else st["future_price"],
        "future_bid": st["next_bid"] if nxt else st["future_bid"],
        "future_ask": st["next_ask"] if nxt else st["future_ask"],
        "symbol": st["next_name"] if nxt else st["underlying_name"],
        "rows": rows,
        "age": round(time.time() - ts, 1) if ts else None,
        "ok": st["ok"], "error": st["error"],
    }


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
