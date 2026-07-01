"""GOLD vs GOLD MINI option-spread service (watch-only 'Gold Options' tab).

Pairs GOLD and GOLD MINI (GOLDM) MCX options (OPTFUT) at the SAME strike and the
SAME expiry-month, for the current + next monthly expiry. Per strike we use a PE
below the future price and a CE above it (client rule).

Spread rule (client): the leg whose FUTURE price is HIGHER quotes at its ASK; the
leg whose future is LOWER quotes at its BID. Both directions are shown (1:1, no
multiplier):

    spread1 (primary) = LOWER-future.Bid  − HIGHER-future.Ask
    spread2 (reverse) = HIGHER-future.Bid − LOWER-future.Ask

Currently GOLD future > GOLDM future, so spread1 = GOLDM.Bid − GOLD.Ask
(e.g. 1,80,000 CE: 55.50 − 68.50 = -13.00). It auto-flips if GOLDM ever trades above GOLD.

MCX options flow through the default MCX-Full feed path (get_subscription_meta()
is merged into the pair-registry subs, like metals/othercomm).
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime
from typing import Optional

from app.services.instrument_resolver import _download_csv, _parse_expiry, resolve_all_active
from app.services.market_data import quote_store

log = logging.getLogger("goldopt_service")

STRIKE_GAP = 5000      # client: 5,000 strike gap
MAX_PAIRS = 2          # current + next month

_state: dict = {
    # {(underlying, pair_index, strike, opt_type): {security_id, trading_symbol, expiry}}
    "options": {},
    "pairs": [],        # [(gold_expiry_iso, goldm_expiry_iso)] nearest → next
    "strikes": {},      # {pair_index: [sorted common 5000-gap strikes]}
    "gold_fut_id": None, "goldm_fut_id": None,
    "gold_fut_sym": None, "goldm_fut_sym": None,
}


def _parse_options(csv_text: str) -> dict:
    """{'GOLD'|'GOLDM': {expiry_dt: {(strike, 'CE'|'PE'): {security_id, trading_symbol}}}}."""
    out: dict = {"GOLD": {}, "GOLDM": {}}
    for row in csv.DictReader(io.StringIO(csv_text)):
        if row.get("SEM_EXM_EXCH_ID") != "MCX":
            continue
        if row.get("SEM_INSTRUMENT_NAME") != "OPTFUT":
            continue
        otype = row.get("SEM_OPTION_TYPE")
        if otype not in ("CE", "PE"):
            continue
        ts = row.get("SEM_TRADING_SYMBOL", "")
        sym = ts.split("-", 1)[0]
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
            "trading_symbol": ts,
        }
    return out


def refresh() -> None:
    """Resolve GOLD/GOLDM option chains for the next MAX_PAIRS common months.
    Called once at feed startup; stores everything in `_state`."""
    csv_text = _download_csv()
    opt = _parse_options(csv_text)
    today = datetime.now()
    gold_exps = sorted(e for e in opt["GOLD"] if e >= today)
    goldm_exps = sorted(e for e in opt["GOLDM"] if e >= today)

    # Pair by (year, month): GOLD's nearest expiries ↔ GOLDM's expiry in the same
    # month (their exact dates differ, e.g. GOLD 31-Aug vs GOLDM 28-Aug).
    pairs: list[tuple[datetime, datetime]] = []
    for ge in gold_exps:
        me = next((m for m in goldm_exps if (m.year, m.month) == (ge.year, ge.month)), None)
        if me:
            pairs.append((ge, me))
        if len(pairs) >= MAX_PAIRS:
            break

    if not pairs:
        log.warning("goldopt refresh: no common GOLD/GOLDM option months found")
        _state.update(options={}, pairs=[], strikes={})
        return

    options: dict = {}
    strikes_by_pair: dict = {}
    for i, (ge, me) in enumerate(pairs):
        g_strikes = {k[0] for k in opt["GOLD"][ge]}
        m_strikes = {k[0] for k in opt["GOLDM"][me]}
        common = sorted(s for s in (g_strikes & m_strikes) if s % STRIKE_GAP == 0)
        strikes_by_pair[i] = common
        for strike in common:
            for otype in ("CE", "PE"):  # subscribe both → robust to intraday PE/CE flip
                g = opt["GOLD"][ge].get((strike, otype))
                m = opt["GOLDM"][me].get((strike, otype))
                if g:
                    options[("GOLD", i, strike, otype)] = {**g, "expiry": ge.isoformat()}
                if m:
                    options[("GOLDM", i, strike, otype)] = {**m, "expiry": me.isoformat()}

    _state["options"] = options
    _state["pairs"] = [(ge.isoformat(), me.isoformat()) for ge, me in pairs]
    _state["strikes"] = strikes_by_pair

    # Near-month GOLD & GOLDM futures — used for the moneyness reference and the
    # higher/lower (ask/bid) decision. Already subscribed as pair legs.
    try:
        act = resolve_all_active(min_days_ahead=1)
        if act.get("gold"):
            _state["gold_fut_id"] = str(act["gold"][0]["security_id"])
            _state["gold_fut_sym"] = act["gold"][0]["trading_symbol"]
        if act.get("mini"):
            _state["goldm_fut_id"] = str(act["mini"][0]["security_id"])
            _state["goldm_fut_sym"] = act["mini"][0]["trading_symbol"]
    except Exception as e:  # noqa: BLE001
        log.warning("goldopt future resolve failed: %s", e)

    log.info("goldopt subscribed: %d option contracts, %d expiry-pairs, strikes/pair=%s",
             len(options), len(pairs), {i: len(s) for i, s in strikes_by_pair.items()})


def get_subscription_meta() -> dict:
    """{security_id: meta} for every option contract → merged into MCX-Full subs."""
    meta: dict = {}
    for (inst, pair_i, strike, otype), info in _state["options"].items():
        sid = info["security_id"]
        meta[sid] = {
            "short": f"{inst.lower()}_opt_{strike}{otype}_e{pair_i}",
            "trading_symbol": info["trading_symbol"],
            "kind": "gold_option",
            "underlying": inst,
            "strike": strike,
            "option_type": otype,
            "expiry_index": pair_i,
            "expiry": info["expiry"],
        }
    return meta


# ────────────────────────────────────────────────────────────────────────
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


def get_spread_table() -> dict:
    """Live GOLD↔GOLDM option-spread table (both directions) for each expiry."""
    gold_p = _fut_price(_state.get("gold_fut_id"))
    goldm_p = _fut_price(_state.get("goldm_fut_id"))

    # Moneyness reference (PE below / CE above). Fall back to strike median.
    ref = None
    if gold_p and goldm_p:
        ref = (gold_p + goldm_p) / 2
    elif gold_p or goldm_p:
        ref = gold_p or goldm_p
    strikes_by_pair = _state.get("strikes", {})
    if ref is None and strikes_by_pair.get(0):
        s0 = strikes_by_pair[0]
        ref = s0[len(s0) // 2] if s0 else None

    # Which future is higher → higher leg quotes at ASK, lower leg at BID.
    gold_higher = True if (gold_p is None or goldm_p is None) else (gold_p >= goldm_p)
    higher = "GOLD" if gold_higher else "GOLDM"
    lower = "GOLDM" if gold_higher else "GOLD"

    def px(v, ltp):
        return v if v else ltp

    expiries_out = []
    for i, (ge, me) in enumerate(_state.get("pairs", [])):
        rows = []
        for strike in strikes_by_pair.get(i, []):
            otype = "PE" if (ref is not None and strike < ref) else "CE"
            g = _state["options"].get(("GOLD", i, strike, otype))
            m = _state["options"].get(("GOLDM", i, strike, otype))
            g_bid, g_ask, g_ltp = _q(g["security_id"] if g else None)
            m_bid, m_ask, m_ltp = _q(m["security_id"] if m else None)

            if gold_higher:
                h_bid, h_ask, h_ltp = g_bid, g_ask, g_ltp
                l_bid, l_ask, l_ltp = m_bid, m_ask, m_ltp
            else:
                h_bid, h_ask, h_ltp = m_bid, m_ask, m_ltp
                l_bid, l_ask, l_ltp = g_bid, g_ask, g_ltp

            h_ask_p, l_bid_p = px(h_ask, h_ltp), px(l_bid, l_ltp)
            h_bid_p, l_ask_p = px(h_bid, h_ltp), px(l_ask, l_ltp)
            spread1 = (l_bid_p - h_ask_p) if (l_bid_p is not None and h_ask_p is not None) else None
            spread2 = (h_bid_p - l_ask_p) if (h_bid_p is not None and l_ask_p is not None) else None

            rows.append({
                "strike": strike,
                "type": otype,
                "gold_bid": g_bid, "gold_ask": g_ask, "gold_ltp": g_ltp,
                "goldm_bid": m_bid, "goldm_ask": m_ask, "goldm_ltp": m_ltp,
                "spread1": round(spread1, 2) if spread1 is not None else None,
                "spread2": round(spread2, 2) if spread2 is not None else None,
            })
        expiries_out.append({
            "expiry_index": i,
            "gold_expiry": ge,
            "goldm_expiry": me,
            "rows": rows,
        })

    return {
        "gold_price": gold_p,
        "goldm_price": goldm_p,
        "ref": ref,
        "higher": higher,
        "lower": lower,
        "spread1_label": f"{lower} Bid - {higher} Ask",
        "spread2_label": f"{higher} Bid - {lower} Ask",
        "expiries": expiries_out,
    }


def status() -> dict:
    return {
        "subscribed_options": len(_state.get("options", {})),
        "expiry_pairs": _state.get("pairs", []),
        "gold_fut": _state.get("gold_fut_sym"),
        "goldm_fut": _state.get("goldm_fut_sym"),
    }
