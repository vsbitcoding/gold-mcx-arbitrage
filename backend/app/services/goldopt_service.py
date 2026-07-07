"""Commodity option-spread service — GOLD, SILVER, CRUDE OIL, NATURAL GAS
(each: BIG contract vs its MINI), powering the watch-only "Options" tab.

Per commodity, pairs the BIG and MINI MCX options (OPTFUT) at the same strike and
the same expiry-month (current + next month), using PE below the future price and
CE above it. Spread rule (client): the leg whose FUTURE is HIGHER quotes at its
ASK; the lower at its BID. Both directions shown (1:1):

    spread1 = lower-future.Bid  - higher-future.Ask
    spread2 = higher-future.Bid - lower-future.Ask

MCX options flow through the default MCX-Full feed path (get_subscription_meta()
is merged into the pair-registry subs).
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime
from typing import Optional

from app.services.instrument_resolver import _download_csv, _parse_expiry
from app.services.market_data import quote_store

log = logging.getLogger("optspread_service")

# key → config. gap = client-chosen strike step; names are display labels.
COMMODITIES: dict[str, dict] = {
    "gold":   {"label": "Gold",        "big": "GOLD",       "mini": "GOLDM",      "gap": 5000,  "big_name": "GOLD",      "mini_name": "GOLD MINI"},
    "silver": {"label": "Silver",      "big": "SILVER",     "mini": "SILVERM",    "gap": 10000, "big_name": "SILVER",    "mini_name": "SILVER MINI"},
    "crude":  {"label": "Crude Oil",   "big": "CRUDEOIL",   "mini": "CRUDEOILM",  "gap": 500,   "big_name": "CRUDE OIL", "mini_name": "CRUDE OIL MINI"},
    "natgas": {"label": "Natural Gas", "big": "NATURALGAS", "mini": "NATGASMINI", "gap": 10,    "big_name": "NAT GAS",   "mini_name": "NATGAS MINI"},
}
MAX_PAIRS = 2       # current + next month
STRIKE_WINDOW = 12  # keep strikes within ATM ± WINDOW*gap (caps very fine chains)

# All underlying symbols we parse options / futures for.
_ALL_SYMBOLS = {c[side] for c in COMMODITIES.values() for side in ("big", "mini")}

# _state[commodity] = {options, pairs, strikes, big_fut_id, mini_fut_id, big_fut_sym, mini_fut_sym}
_state: dict[str, dict] = {}


def _parse_all(csv_text: str) -> dict:
    """{underlying: {expiry_dt: {(strike, 'CE'|'PE'): {security_id, trading_symbol}}}}."""
    out: dict = {s: {} for s in _ALL_SYMBOLS}
    for row in csv.DictReader(io.StringIO(csv_text)):
        if row.get("SEM_EXM_EXCH_ID") != "MCX" or row.get("SEM_INSTRUMENT_NAME") != "OPTFUT":
            continue
        otype = row.get("SEM_OPTION_TYPE")
        if otype not in ("CE", "PE"):
            continue
        sym = (row.get("SEM_TRADING_SYMBOL", "") or "").split("-", 1)[0]
        if sym not in out:
            continue
        expiry = _parse_expiry(row.get("SEM_EXPIRY_DATE", ""))
        if not expiry:
            continue
        try:
            strike = int(float(row.get("SEM_STRIKE_PRICE", "0")))
        except (TypeError, ValueError):
            continue
        out[sym].setdefault(expiry, {})[(strike, otype)] = {
            "security_id": str(row.get("SEM_SMST_SECURITY_ID")),
            "trading_symbol": row.get("SEM_TRADING_SYMBOL", ""),
        }
    return out


def _resolve_futures(csv_text: str) -> dict:
    """{underlying: {security_id, trading_symbol}} for the nearest FUTCOM contract."""
    today = datetime.now()
    best: dict = {}  # sym -> (expiry, sid, ts)
    for row in csv.DictReader(io.StringIO(csv_text)):
        if row.get("SEM_EXM_EXCH_ID") != "MCX" or row.get("SEM_INSTRUMENT_NAME") != "FUTCOM":
            continue
        sym = (row.get("SEM_TRADING_SYMBOL", "") or "").split("-", 1)[0]
        if sym not in _ALL_SYMBOLS:
            continue
        expiry = _parse_expiry(row.get("SEM_EXPIRY_DATE", ""))
        if not expiry or expiry < today:
            continue
        cur = best.get(sym)
        if cur is None or expiry < cur[0]:
            best[sym] = (expiry, str(row.get("SEM_SMST_SECURITY_ID")), row.get("SEM_TRADING_SYMBOL", ""))
    return {s: {"security_id": v[1], "trading_symbol": v[2]} for s, v in best.items()}


def _q(sid: Optional[str]):
    if not sid:
        return (None, None, None)
    q = quote_store.get(sid)
    return (q.bid or None, q.ask or None, q.ltp or None)


def _fut_price(sid: Optional[str]) -> Optional[float]:
    if not sid:
        return None
    q = quote_store.get(sid)
    if q.ltp:
        return q.ltp
    if q.bid and q.ask:
        return (q.bid + q.ask) / 2
    return None


def refresh() -> None:
    """Resolve every commodity's option chain + futures. Called once at feed startup."""
    csv_text = _download_csv()
    opt = _parse_all(csv_text)
    futs = _resolve_futures(csv_text)
    today = datetime.now()

    for key, cfg in COMMODITIES.items():
        big, mini, gap = cfg["big"], cfg["mini"], cfg["gap"]
        gmap, mmap = opt.get(big, {}), opt.get(mini, {})
        st = {
            "options": {}, "pairs": [], "strikes": {},
            "big_fut_id": None, "mini_fut_id": None, "big_fut_sym": None, "mini_fut_sym": None,
        }
        bf, mf = futs.get(big), futs.get(mini)
        if bf:
            st["big_fut_id"], st["big_fut_sym"] = bf["security_id"], bf["trading_symbol"]
        if mf:
            st["mini_fut_id"], st["mini_fut_sym"] = mf["security_id"], mf["trading_symbol"]

        # Pair BIG expiries with the MINI expiry in the same (year, month).
        gexps = sorted(e for e in gmap if e >= today)
        mexps = sorted(e for e in mmap if e >= today)
        pairs: list = []
        for ge in gexps:
            me = next((m for m in mexps if (m.year, m.month) == (ge.year, ge.month)), None)
            if me:
                pairs.append((ge, me))
            if len(pairs) >= MAX_PAIRS:
                break
        if not pairs:
            _state[key] = st
            log.warning("optspread %s: no common BIG/MINI option months", key)
            continue

        # Window centre = BIG future price (restored from DB even before live ticks).
        center = _fut_price(st["big_fut_id"]) or _fut_price(st["mini_fut_id"])
        options: dict = {}
        strikes_by_pair: dict = {}
        for i, (ge, me) in enumerate(pairs):
            common = sorted(s for s in ({k[0] for k in gmap[ge]} & {k[0] for k in mmap[me]}) if s % gap == 0)
            c = center if center else (common[len(common) // 2] if common else None)
            if c is not None:
                common = [s for s in common if abs(s - c) <= STRIKE_WINDOW * gap]
            strikes_by_pair[i] = common
            for strike in common:
                for otype in ("CE", "PE"):
                    g = gmap[ge].get((strike, otype))
                    m = mmap[me].get((strike, otype))
                    if g:
                        options[(big, i, strike, otype)] = {**g, "expiry": ge.isoformat()}
                    if m:
                        options[(mini, i, strike, otype)] = {**m, "expiry": me.isoformat()}
        st["options"] = options
        st["pairs"] = [(ge.isoformat(), me.isoformat()) for ge, me in pairs]
        st["strikes"] = strikes_by_pair
        _state[key] = st
        log.info("optspread %s: %d contracts, %d expiry-pairs, strikes/pair=%s",
                 key, len(options), len(pairs), {i: len(s) for i, s in strikes_by_pair.items()})


def get_subscription_meta() -> dict:
    """{security_id: meta} for all commodities' option contracts + their futures."""
    meta: dict = {}
    for key, st in _state.items():
        for (sym, pair_i, strike, otype), info in st.get("options", {}).items():
            sid = info["security_id"]
            meta[sid] = {
                "short": f"{key}_opt_{strike}{otype}_e{pair_i}",
                "trading_symbol": info["trading_symbol"],
                "kind": "comm_option", "commodity": key, "underlying": sym,
                "strike": strike, "option_type": otype, "expiry_index": pair_i, "expiry": info["expiry"],
            }
        for fid, fsym in ((st.get("big_fut_id"), st.get("big_fut_sym")), (st.get("mini_fut_id"), st.get("mini_fut_sym"))):
            if fid:
                meta.setdefault(fid, {"short": f"{key}_fut", "trading_symbol": fsym or "", "kind": "comm_option_fut", "commodity": key})
    return meta


def list_commodities() -> list[dict]:
    return [{"key": k, "label": c["label"]} for k, c in COMMODITIES.items()]


def get_spread_table(commodity: str = "gold") -> dict:
    """Live option-spread table (both directions) for one commodity."""
    if commodity not in COMMODITIES:
        commodity = "gold"
    cfg = COMMODITIES[commodity]
    big, mini = cfg["big"], cfg["mini"]
    st = _state.get(commodity, {})

    big_p = _fut_price(st.get("big_fut_id"))
    mini_p = _fut_price(st.get("mini_fut_id"))
    ref = None
    if big_p and mini_p:
        ref = (big_p + mini_p) / 2
    elif big_p or mini_p:
        ref = big_p or mini_p
    strikes_by_pair = st.get("strikes", {})
    if ref is None and strikes_by_pair.get(0):
        s0 = strikes_by_pair[0]
        ref = s0[len(s0) // 2] if s0 else None

    big_higher = True if (big_p is None or mini_p is None) else (big_p >= mini_p)
    higher_name = cfg["big_name"] if big_higher else cfg["mini_name"]
    lower_name = cfg["mini_name"] if big_higher else cfg["big_name"]

    def px(v, ltp):
        return v if v else ltp

    def build_row(i, strike, otype):
        g = st["options"].get((big, i, strike, otype))
        m = st["options"].get((mini, i, strike, otype))
        g_bid, g_ask, g_ltp = _q(g["security_id"] if g else None)   # BIG
        m_bid, m_ask, m_ltp = _q(m["security_id"] if m else None)   # MINI
        if big_higher:
            h_bid, h_ask, h_ltp = g_bid, g_ask, g_ltp
            l_bid, l_ask, l_ltp = m_bid, m_ask, m_ltp
        else:
            h_bid, h_ask, h_ltp = m_bid, m_ask, m_ltp
            l_bid, l_ask, l_ltp = g_bid, g_ask, g_ltp
        h_ask_p, l_bid_p = px(h_ask, h_ltp), px(l_bid, l_ltp)
        h_bid_p, l_ask_p = px(h_bid, h_ltp), px(l_ask, l_ltp)
        spread1 = (l_bid_p - h_ask_p) if (l_bid_p is not None and h_ask_p is not None) else None
        spread2 = (h_bid_p - l_ask_p) if (h_bid_p is not None and l_ask_p is not None) else None
        return {
            "strike": strike, "type": otype,
            "big_bid": g_bid, "big_ask": g_ask,
            "mini_bid": m_bid, "mini_ask": m_ask,
            "spread1": round(spread1, 2) if spread1 is not None else None,
            "spread2": round(spread2, 2) if spread2 is not None else None,
        }

    expiries_out = []
    for i, (ge, me) in enumerate(st.get("pairs", [])):
        strikes = strikes_by_pair.get(i, [])
        # ATM strike = nearest to ref; per client it shows BOTH CE and PE (other strikes: one type by moneyness).
        atm = min(strikes, key=lambda s: abs(s - ref)) if (strikes and ref is not None) else None
        rows = []
        for strike in strikes:
            primary = "PE" if (ref is not None and strike < ref) else "CE"
            rows.append(build_row(i, strike, primary))
            if strike == atm:
                rows.append(build_row(i, strike, "CE" if primary == "PE" else "PE"))
        expiries_out.append({"expiry_index": i, "big_expiry": ge, "mini_expiry": me, "rows": rows})

    return {
        "commodity": commodity, "label": cfg["label"],
        "big_name": cfg["big_name"], "mini_name": cfg["mini_name"],
        "big_price": big_p, "mini_price": mini_p, "ref": ref,
        "higher": higher_name, "lower": lower_name,
        "spread1_label": f"{lower_name} Bid - {higher_name} Ask",
        "spread2_label": f"{higher_name} Bid - {lower_name} Ask",
        "commodities": list_commodities(),
        "expiries": expiries_out,
    }


def status() -> dict:
    return {
        "commodities": {
            k: {
                "subscribed_options": len(st.get("options", {})),
                "expiry_pairs": st.get("pairs", []),
                "big_fut": st.get("big_fut_sym"),
                "mini_fut": st.get("mini_fut_sym"),
            }
            for k, st in _state.items()
        }
    }
