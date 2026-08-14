"""Angel One SmartAPI feed — NSE commodity (crude, natural gas) + real-time USD/INR.

Dhan and IBKR both refuse NSE's commodity segment: Dhan's API has no such
exchange segment at all (their app shows it, the API cannot), and IBKR does not
list the contracts. Angel does, so this is the third and only source for the
NSE half of the NSE-vs-MCX comparison. It also carries USD/INR as a genuinely
liquid NSE currency future, replacing TwelveData's ~2-minute spot.

Design constraints (same rules as every other feed here):
  * ZERO database writes - one in-memory dict the routes read.
  * TWO requests per poll, NO MATTER how many commodities are tracked. Angel
    accepts up to 50 tokens in a single quote call, so every future plus USD/INR
    ride in one request; the 42 option legs of ONE commodity fill the second.
    Chains therefore take turns - each refreshes every 6 s, which sits beside
    the MCX side's ~5 s. Firing a call per commodity instead would have tripled
    the request rate for no visible gain.
  * Session cached to disk so a redeploy reuses the token instead of logging in
    again (Angel throttles hard).
  * NEVER touches the historical endpoint. It allows roughly one call before
    blocking for 10+ minutes, and NSE commodity is not covered by it anyway.
  * Nothing here can disturb the Dhan or IBKR feeds - separate thread, separate
    credentials, separate upstream.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import struct
import threading
import time
import urllib.request
from datetime import date, datetime
from pathlib import Path

import requests

from app.config import settings

log = logging.getLogger("angel_feed")

_BASE = "https://apiconnect.angelone.in"
_MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
_SECRETS = Path(os.path.expanduser("~/.config/arbi-secrets/angelone.env"))
_SESSION_FILE = Path(__file__).resolve().parents[2] / ".angel_session.json"
_MASTER_CACHE = Path("/tmp/angel-scrip-master.json")
_MASTER_TTL = 12 * 3600

_POLL_SECONDS = 3
_WINDOW = 10                 # strikes each side of the money -> 21 rows
_MAX_TOKENS = 50             # Angel's per-request cap

# NSE lists bullion and base metals too, but they are dead: bid 0 / ask 0 all
# day against a months-old LTP (NSE gold printed 112578 while MCX traded
# 152000). Only these two carry real two-way markets, so only these two are
# worth comparing.
COMMODITIES: dict[str, dict] = {
    # Crude lists every 50 points, but the client reads it in round hundreds, so
    # only hundreds are subscribed. That is not just a display choice: a quote
    # call takes 50 tokens and 21 strikes both sides is 42, so subscribing every
    # 50 would cover only +-500 points. Filtering at the source buys the same 21
    # rows across +-1000 instead (client asked for 21 hundreds, 13-Aug).
    "crude":  {"name": "CRUDEOIL",   "label": "NSE CRUDE OIL", "strike_step": 100},
    "natgas": {"name": "NATURALGAS", "label": "NSE NATURAL GAS"},
}

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}


def _blank() -> dict:
    return {
        "future": None,      # {symbol, expiry, bid, ask, ltp, volume, oi}
        "options": [],       # [{strike, atm, ce:{...}, pe:{...}}]
        "atm": None,
        "opt_expiry": None,
        "chain_ts": 0.0,     # the chain's own clock - it updates every other tick
    }


_state: dict = {
    "c": {k: _blank() for k in COMMODITIES},
    "usdinr": None,          # {symbol, expiry, bid, ask, ltp, volume, oi}
    "ts": 0.0,
    "ok": False,
    "error": None,
}
_stop = threading.Event()


# ── credentials ──────────────────────────────────────────────────────────
def _creds() -> dict:
    """Read from the secrets file, falling back to the environment."""
    out = {}
    if _SECRETS.exists():
        for line in _SECRETS.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.strip().split("=", 1)
                out[k] = v
    for k in ("ANGEL_API_KEY", "ANGEL_CLIENT_CODE", "ANGEL_MPIN", "ANGEL_TOTP_SECRET"):
        out.setdefault(k, os.environ.get(k, ""))
    return out


def _totp(secret: str, period: int = 30, digits: int = 6) -> str:
    key = base64.b32decode(secret.upper() + "=" * ((8 - len(secret) % 8) % 8))
    msg = struct.pack(">Q", int(time.time()) // period)
    h = hmac.new(key, msg, hashlib.sha1).digest()
    o = h[-1] & 0x0F
    return str((struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % (10 ** digits)).zfill(digits)


def _headers(c: dict, jwt: str | None = None) -> dict:
    h = {
        "Content-Type": "application/json", "Accept": "application/json",
        "X-UserType": "USER", "X-SourceID": "WEB",
        "X-ClientLocalIP": settings.ANGEL_STATIC_IP,
        "X-ClientPublicIP": settings.ANGEL_STATIC_IP,
        "X-MACAddress": "00:00:00:00:00:00",
        "X-PrivateKey": c["ANGEL_API_KEY"],
    }
    if jwt:
        h["Authorization"] = "Bearer " + jwt
    return h


def _login(sess: requests.Session, c: dict) -> str:
    """Fresh login. Cached to disk because Angel throttles repeated logins."""
    r = sess.post(f"{_BASE}/rest/auth/angelbroking/user/v1/loginByPassword",
                  headers=_headers(c),
                  json={"clientcode": c["ANGEL_CLIENT_CODE"],
                        "password": c["ANGEL_MPIN"],
                        "totp": _totp(c["ANGEL_TOTP_SECRET"])}, timeout=25)
    d = r.json()
    if not d.get("status"):
        raise RuntimeError(f"Angel login failed: {d.get('message')} ({d.get('errorcode')})")
    tok = d["data"]
    try:
        _SESSION_FILE.write_text(json.dumps({"jwt": tok["jwtToken"], "ts": time.time(),
                                             "day": date.today().isoformat()}))
        os.chmod(_SESSION_FILE, 0o600)
    except Exception as e:  # noqa: BLE001
        log.debug("angel session not cached: %s", e)
    log.info("Angel: logged in as %s", c["ANGEL_CLIENT_CODE"])
    return tok["jwtToken"]


def _session_token(sess: requests.Session, c: dict, force: bool = False) -> str:
    if not force and _SESSION_FILE.exists():
        try:
            d = json.loads(_SESSION_FILE.read_text())
            # A token is only good for the day it was minted. Age alone was not
            # enough: one taken at 23:00 is dead an hour later at midnight, and
            # the old 8-hour rule would have handed it back as fresh.
            if (d.get("day") == date.today().isoformat()
                    and time.time() - d.get("ts", 0) < 8 * 3600):
                return d["jwt"]
        except Exception:  # noqa: BLE001
            pass
    return _login(sess, c)


# ── instrument master ────────────────────────────────────────────────────
def _expiry_date(s: str) -> date:
    """Angel writes DDMMMYYYY. A string sort puts DEC before SEP, which silently
    picks the wrong contract - always parse."""
    s = (s or "").strip()
    try:
        return date(int(s[5:9]), _MONTHS[s[2:5]], int(s[:2]))
    except Exception:  # noqa: BLE001
        return date(2099, 1, 1)


def _load_master() -> list:
    if _MASTER_CACHE.exists() and (time.time() - _MASTER_CACHE.stat().st_mtime) < _MASTER_TTL:
        try:
            return json.loads(_MASTER_CACHE.read_text())
        except Exception:  # noqa: BLE001
            pass
    log.info("Angel: downloading scrip master (~36 MB)")
    with urllib.request.urlopen(_MASTER_URL, timeout=300) as r:
        raw = r.read().decode("utf-8", "ignore")
    try:
        _MASTER_CACHE.write_text(raw)
    except Exception as e:  # noqa: BLE001
        log.debug("angel master not cached: %s", e)
    return json.loads(raw)


def _resolve_commodity(data: list, name: str, today: date) -> dict:
    """Nearest NSE future for `name` plus its nearest option chain."""
    nco = [x for x in data if x.get("exch_seg") == "NCO" and x.get("name") == name]
    futs = sorted([x for x in nco if x.get("instrumenttype", "").startswith("FUT")
                   and _expiry_date(x.get("expiry")) >= today],
                  key=lambda x: _expiry_date(x.get("expiry")))
    opts = [x for x in nco if x.get("instrumenttype") in ("OPTFUT", "OPTBLN")
            and _expiry_date(x.get("expiry")) >= today]
    opt_exp = min((_expiry_date(x.get("expiry")) for x in opts), default=None)
    chain = [x for x in opts if _expiry_date(x.get("expiry")) == opt_exp]
    return {"future": futs[0] if futs else None, "chain": chain, "opt_expiry": opt_exp}


def _resolve() -> dict:
    """Every tracked NSE commodity plus the front USD/INR future."""
    data = _load_master()
    today = date.today()

    out = {"c": {k: _resolve_commodity(data, cfg["name"], today)
                 for k, cfg in COMMODITIES.items()}}

    cds = sorted([x for x in data if x.get("exch_seg") == "CDS" and x.get("name") == "USDINR"
                  and x.get("instrumenttype", "").startswith("FUT")
                  and _expiry_date(x.get("expiry")) >= today],
                 key=lambda x: _expiry_date(x.get("expiry")))
    # skip the weekly stubs - the monthly is where the volume is
    out["usdinr"] = next((x for x in cds if "FUT" in x.get("symbol", "") and
                          not x.get("symbol", "").replace("USDINR", "")[:5].isdigit()),
                         cds[0] if cds else None)
    return out


# ── polling ──────────────────────────────────────────────────────────────
def _leg(row: dict | None) -> dict | None:
    if not row:
        return None
    dep = row.get("depth") or {}
    bid = (dep.get("buy") or [{}])[0].get("price")
    ask = (dep.get("sell") or [{}])[0].get("price")
    bid = bid if bid else None
    ask = ask if ask else None
    return {
        "bid": bid, "ask": ask,
        "mid": round((bid + ask) / 2, 2) if (bid and ask) else None,
        # LTP is kept but must NOT be used for comparison: a dead NSE contract
        # still prints a months-old last trade (gold showed 112578 against MCX's
        # 152000). Anything with no bid AND no ask is not a live market.
        "ltp": row.get("ltp"),
        "volume": row.get("tradeVolume"),
        "oi": row.get("opnInterest"),
    }


# Angel expires every session at midnight IST - on 14-Aug it happened at
# 00:00:00 to the second - and it reports that with **HTTP 200** and
# `status: false, "Invalid Token"` in the body, never a 401. Checking only the
# status code meant a dead session read as an ordinary poll failure, so the
# loop retried the same dead token every 15 s: 2,322 failures and nine hours of
# midnight prices on screen before anyone restarted the backend. Their whole
# AG80xx family is session trouble; the message check catches new siblings.
_AUTH_CODES = {"AG8001", "AG8002", "AG8003", "AB8050", "AB8051"}


def _is_auth_error(d: dict) -> bool:
    code = (d.get("errorcode") or "").strip().upper()
    msg = (d.get("message") or "").lower()
    return code in _AUTH_CODES or "token" in msg or "session" in msg


def _quote(sess: requests.Session, c: dict, jwt: str, tokens: dict) -> dict:
    r = sess.post(f"{_BASE}/rest/secure/angelbroking/market/v1/quote",
                  headers=_headers(c, jwt),
                  json={"mode": "FULL", "exchangeTokens": tokens}, timeout=25)
    if r.status_code == 401:
        raise PermissionError("angel session expired (401)")
    d = r.json()
    if not d.get("status"):
        if _is_auth_error(d):
            raise PermissionError("angel session rejected: %s (%s)"
                                  % (d.get("message"), d.get("errorcode")))
        raise RuntimeError(f"quote failed: {d.get('message')}")
    return {x["symbolToken"]: x for x in (d.get("data") or {}).get("fetched", [])}


def _poll(sess: requests.Session, c: dict, jwt: str, inst: dict, turn: str) -> None:
    """One round: every future and USD/INR, then ONE commodity's option chain."""
    # ── call 1: all futures + USD/INR, so every ATM is known ──────────────
    nco = [inst["c"][k]["future"]["token"] for k in COMMODITIES
           if inst["c"][k].get("future")]
    if not nco:
        raise RuntimeError("no NSE commodity future resolved")
    tokens = {"NCO": nco}
    usd = inst.get("usdinr")
    if usd:
        tokens["CDS"] = [usd["token"]]
    fetched = _quote(sess, c, jwt, tokens)

    mids: dict[str, float | None] = {}
    for key in COMMODITIES:
        fut = inst["c"][key].get("future")
        if not fut:
            continue
        frow = _leg(fetched.get(fut["token"]))
        mids[key] = (frow or {}).get("mid") or (frow or {}).get("ltp")
        _state["c"][key]["future"] = {**(frow or {}), "symbol": fut["symbol"],
                                      "expiry": _expiry_date(fut.get("expiry")).isoformat()}
    if usd and usd["token"] in fetched:
        u = _leg(fetched[usd["token"]])
        _state["usdinr"] = {**u, "symbol": usd["symbol"],
                            "expiry": _expiry_date(usd.get("expiry")).isoformat()}

    # ── call 2: the 21 strikes around the money for whichever chain's turn ─
    chain, fmid = inst["c"][turn].get("chain"), mids.get(turn)
    if fmid and chain:
        def strike_of(x):
            return float(x.get("strike", 0)) / 100.0

        strikes = sorted({strike_of(x) for x in chain})
        step = COMMODITIES[turn].get("strike_step")
        if step:
            keep = [s for s in strikes if s % step == 0]
            strikes = keep or strikes          # never blank the chain on a surprise ladder
        atm = min(strikes, key=lambda s: abs(s - fmid))
        window = sorted(sorted(strikes, key=lambda s: abs(s - atm))[: _WINDOW * 2 + 1])
        by: dict[float, dict] = {}
        for x in chain:
            k = strike_of(x)
            if k in window:
                by.setdefault(k, {})[x.get("symbol", "")[-2:]] = x
        toks = [x["token"] for legs in by.values() for x in legs.values()][: _MAX_TOKENS]
        got = _quote(sess, c, jwt, {"NCO": toks})
        rows = []
        for k in window:
            legs = by.get(k, {})
            ce, pe = legs.get("CE"), legs.get("PE")
            rows.append({
                "strike": k,
                "atm": k == atm,
                "ce": _leg(got.get(ce["token"])) if ce else None,
                "pe": _leg(got.get(pe["token"])) if pe else None,
            })
        st = _state["c"][turn]
        st["options"], st["atm"], st["chain_ts"] = rows, atm, time.time()
        exp = inst["c"][turn]["opt_expiry"]
        st["opt_expiry"] = exp.isoformat() if exp else None

    _state.update({"ts": time.time(), "ok": True, "error": None})


def _loop() -> None:
    sess = requests.Session()
    c = _creds()
    if not all(c.get(k) for k in ("ANGEL_API_KEY", "ANGEL_CLIENT_CODE",
                                  "ANGEL_MPIN", "ANGEL_TOTP_SECRET")):
        log.warning("Angel feed: credentials missing (%s) - disabled", _SECRETS)
        return

    order = list(COMMODITIES)
    jwt, inst, resolved_at, turn = None, None, 0.0, 0
    force_login, login_fails = False, 0
    while not _stop.is_set():
        try:
            if inst is None or (time.time() - resolved_at) > _MASTER_TTL:
                inst = _resolve()
                resolved_at = time.time()
                for k in COMMODITIES:
                    r = inst["c"][k]
                    f = r.get("future")
                    log.info("Angel: NSE %s %s (exp %s), chain exp %s, %d strikes",
                             k, f and f.get("symbol"),
                             f and _expiry_date(f.get("expiry")), r["opt_expiry"],
                             len({x.get("strike") for x in r["chain"]}))
                log.info("Angel: USD/INR %s",
                         inst["usdinr"] and inst["usdinr"].get("symbol"))
            if jwt is None:
                jwt = _session_token(sess, c, force=force_login)
                force_login, login_fails = False, 0
            _poll(sess, c, jwt, inst, order[turn % len(order)])
            turn += 1
        except PermissionError as e:
            # force=True matters: the cached token IS the rejected one, so
            # reading it back would loop for ever on a dead session.
            log.info("Angel: %s - forcing a fresh login", e)
            jwt, force_login = None, True
            _stop.wait(2)
            continue
        except Exception as e:  # noqa: BLE001 - a bad poll must never kill the thread
            _state["ok"] = False
            _state["error"] = str(e)[:160]
            if force_login:
                # The login itself is failing. Angel throttles logins hard, so
                # backing off is the only way through - hammering it keeps the
                # feed down longer than waiting does.
                login_fails += 1
                wait = min(30 * login_fails, 300)
            else:
                wait = 15
            log.warning("Angel poll failed: %s (retry in %ss)", _state["error"], wait)
            _stop.wait(wait)
            continue
        _stop.wait(_POLL_SECONDS)


def get_data(commodity: str = "crude") -> dict:
    now = time.time()
    key = commodity if commodity in _state["c"] else "crude"
    st = _state["c"][key]
    return {
        "source": "Angel One (NSE)",
        "commodity": key,
        "label": COMMODITIES[key]["label"],
        "future": st["future"],
        "options": st["options"],
        "atm": st["atm"],
        "opt_expiry": st["opt_expiry"],
        "usdinr": _state["usdinr"],
        # `age` is the futures clock (every 3 s); the chain takes turns, so it
        # gets its own - a screen that showed one number for both would call a
        # stale chain fresh.
        "age": round(now - _state["ts"], 1) if _state["ts"] else None,
        "chain_age": round(now - st["chain_ts"], 1) if st["chain_ts"] else None,
        "ok": _state["ok"],
        "error": _state["error"],
    }


def start_in_background() -> None:
    if not settings.ANGEL_ENABLED:
        log.info("Angel feed disabled")
        return
    threading.Thread(target=_loop, daemon=True, name="angel-feed").start()
    log.info("Angel feed starting (NSE %s + USD/INR, %ss poll, in-memory)",
             "/".join(COMMODITIES), _POLL_SECONDS)
