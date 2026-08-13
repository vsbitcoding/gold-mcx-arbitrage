"""Angel One SmartAPI feed — NSE commodity (crude) + real-time USD/INR.

Dhan and IBKR both refuse NSE's commodity segment: Dhan's API has no such
exchange segment at all (their app shows it, the API cannot), and IBKR does not
list the contracts. Angel does, so this is the third and only source for the
NSE half of the NSE-vs-MCX comparison. It also carries USD/INR as a genuinely
liquid NSE currency future, replacing TwelveData's ~2-minute spot.

Design constraints (same rules as every other feed here):
  * ZERO database writes - one in-memory dict the routes read.
  * ONE request per poll. Angel accepts up to 50 tokens across segments in a
    single quote call, so the crude future, 21 strikes both sides and USD/INR
    all arrive together - no per-instrument fan-out.
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

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}

_state: dict = {
    "future": None,          # {symbol, expiry, bid, ask, ltp, volume, oi}
    "options": [],           # [{strike, ce:{...}, pe:{...}}]
    "atm": None,
    "opt_expiry": None,
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
        _SESSION_FILE.write_text(json.dumps({"jwt": tok["jwtToken"], "ts": time.time()}))
        os.chmod(_SESSION_FILE, 0o600)
    except Exception as e:  # noqa: BLE001
        log.debug("angel session not cached: %s", e)
    log.info("Angel: logged in as %s", c["ANGEL_CLIENT_CODE"])
    return tok["jwtToken"]


def _session_token(sess: requests.Session, c: dict, force: bool = False) -> str:
    if not force and _SESSION_FILE.exists():
        try:
            d = json.loads(_SESSION_FILE.read_text())
            if time.time() - d.get("ts", 0) < 8 * 3600:      # well inside Angel's 24 h
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


def _resolve() -> dict:
    """Nearest NSE crude future, its option chain, and the front USD/INR future."""
    data = _load_master()
    today = date.today()

    nco = [x for x in data if x.get("exch_seg") == "NCO" and x.get("name") == "CRUDEOIL"]
    futs = sorted([x for x in nco if x.get("instrumenttype", "").startswith("FUT")
                   and _expiry_date(x.get("expiry")) >= today],
                  key=lambda x: _expiry_date(x.get("expiry")))
    opts = [x for x in nco if x.get("instrumenttype") == "OPTFUT"
            and _expiry_date(x.get("expiry")) >= today]
    opt_exp = min((_expiry_date(x.get("expiry")) for x in opts), default=None)
    chain = [x for x in opts if _expiry_date(x.get("expiry")) == opt_exp]

    cds = sorted([x for x in data if x.get("exch_seg") == "CDS" and x.get("name") == "USDINR"
                  and x.get("instrumenttype", "").startswith("FUT")
                  and _expiry_date(x.get("expiry")) >= today],
                 key=lambda x: _expiry_date(x.get("expiry")))
    # skip the weekly stubs - the monthly is where the volume is
    usdinr = next((x for x in cds if "FUT" in x.get("symbol", "") and
                   not x.get("symbol", "").replace("USDINR", "")[:5].isdigit()), cds[0] if cds else None)

    return {
        "future": futs[0] if futs else None,
        "chain": chain,
        "opt_expiry": opt_exp,
        "usdinr": usdinr,
    }


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


def _poll(sess: requests.Session, c: dict, jwt: str, inst: dict) -> None:
    fut, chain, usd = inst["future"], inst["chain"], inst["usdinr"]
    if not fut:
        raise RuntimeError("no NSE crude future resolved")

    # 1) future + USD/INR first, so the ATM strike is known
    base_tokens = {"NCO": [fut["token"]]}
    if usd:
        base_tokens["CDS"] = [usd["token"]]
    r = sess.post(f"{_BASE}/rest/secure/angelbroking/market/v1/quote",
                  headers=_headers(c, jwt),
                  json={"mode": "FULL", "exchangeTokens": base_tokens}, timeout=25)
    if r.status_code == 401:
        raise PermissionError("angel session expired")
    d = r.json()
    if not d.get("status"):
        raise RuntimeError(f"quote failed: {d.get('message')}")
    fetched = {x["symbolToken"]: x for x in (d.get("data") or {}).get("fetched", [])}

    frow = _leg(fetched.get(fut["token"]))
    fmid = (frow or {}).get("mid") or (frow or {}).get("ltp")
    _state["future"] = {**(frow or {}), "symbol": fut["symbol"],
                        "expiry": _expiry_date(fut.get("expiry")).isoformat()}
    if usd and usd["token"] in fetched:
        u = _leg(fetched[usd["token"]])
        _state["usdinr"] = {**u, "symbol": usd["symbol"],
                            "expiry": _expiry_date(usd.get("expiry")).isoformat()}

    # 2) the 21 strikes around the money, both sides, in one more call
    if fmid and chain:
        def strike_of(x):
            return float(x.get("strike", 0)) / 100.0
        strikes = sorted({strike_of(x) for x in chain})
        atm = min(strikes, key=lambda s: abs(s - fmid))
        window = sorted(sorted(strikes, key=lambda s: abs(s - atm))[: _WINDOW * 2 + 1])
        by = {}
        for x in chain:
            k = strike_of(x)
            if k in window:
                by.setdefault(k, {})[x.get("symbol", "")[-2:]] = x
        tokens = [x["token"] for legs in by.values() for x in legs.values()][: _MAX_TOKENS]
        r2 = sess.post(f"{_BASE}/rest/secure/angelbroking/market/v1/quote",
                       headers=_headers(c, jwt),
                       json={"mode": "FULL", "exchangeTokens": {"NCO": tokens}}, timeout=25)
        d2 = r2.json()
        got = {x["symbolToken"]: x for x in (d2.get("data") or {}).get("fetched", [])} \
            if d2.get("status") else {}
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
        _state["options"], _state["atm"] = rows, atm
        _state["opt_expiry"] = inst["opt_expiry"].isoformat() if inst["opt_expiry"] else None

    _state.update({"ts": time.time(), "ok": True, "error": None})


def _loop() -> None:
    sess = requests.Session()
    c = _creds()
    if not all(c.get(k) for k in ("ANGEL_API_KEY", "ANGEL_CLIENT_CODE",
                                  "ANGEL_MPIN", "ANGEL_TOTP_SECRET")):
        log.warning("Angel feed: credentials missing (%s) - disabled", _SECRETS)
        return

    jwt, inst, resolved_at = None, None, 0.0
    while not _stop.is_set():
        try:
            if inst is None or (time.time() - resolved_at) > _MASTER_TTL:
                inst = _resolve()
                resolved_at = time.time()
                f = inst["future"]
                log.info("Angel: NSE crude %s (exp %s), chain exp %s, %d strikes; USD/INR %s",
                         f and f.get("symbol"), f and _expiry_date(f.get("expiry")),
                         inst["opt_expiry"], len({x.get("strike") for x in inst["chain"]}),
                         inst["usdinr"] and inst["usdinr"].get("symbol"))
            if jwt is None:
                jwt = _session_token(sess, c)
            _poll(sess, c, jwt, inst)
        except PermissionError:
            log.info("Angel: session expired, logging in again")
            jwt = None
            _stop.wait(2)
            continue
        except Exception as e:  # noqa: BLE001 - a bad poll must never kill the thread
            _state["ok"] = False
            _state["error"] = str(e)[:160]
            log.warning("Angel poll failed: %s", _state["error"])
            _stop.wait(15)
            continue
        _stop.wait(_POLL_SECONDS)


def get_data() -> dict:
    now = time.time()
    return {
        "source": "Angel One (NSE)",
        "future": _state["future"],
        "options": _state["options"],
        "atm": _state["atm"],
        "opt_expiry": _state["opt_expiry"],
        "usdinr": _state["usdinr"],
        "age": round(now - _state["ts"], 1) if _state["ts"] else None,
        "ok": _state["ok"],
        "error": _state["error"],
    }


def start_in_background() -> None:
    if not settings.ANGEL_ENABLED:
        log.info("Angel feed disabled")
        return
    threading.Thread(target=_loop, daemon=True, name="angel-feed").start()
    log.info("Angel feed starting (NSE crude + USD/INR, %ss poll, in-memory)", _POLL_SECONDS)
