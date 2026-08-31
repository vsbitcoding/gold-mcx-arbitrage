"""Other-commodity calendar-spread service (watch-only) — powers the 'Other
Commodity' tab. Same logic as metals_service but for energy/power contracts and
WITHOUT the % column (per client).

For each family, for each ADJACENT month pair (near, far):
    far_price  = far month  Buy Price  (best bid)
    near_price = near month Sell Price (best ask)
    difference = far_price − near_price

Watch-only: NO firing, NO ladders. Legs ride the same Dhan MCX-Full feed.
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime

from app.services.instrument_resolver import _download_csv, _parse_expiry
from app.services.market_data import clean_sides, quote_store

log = logging.getLogger("othercomm_service")

# Dhan MCX trading-symbol prefix → display name (client-requested order)
FAMILIES: dict[str, str] = {
    "CRUDEOIL": "Crude Oil",
    "CRUDEOILM": "Crude Oil Mini",
    "NATURALGAS": "Natural Gas",
    "NATGASMINI": "Natural Gas Mini",
    "ELECDMBL": "Electricity",
}

MAX_MONTHS = 6

_state: dict = {"pairs": []}


def _resolve_contracts(csv_text: str) -> dict[str, list[dict]]:
    today = datetime.now()
    out: dict[str, list[dict]] = {sym: [] for sym in FAMILIES}
    for row in csv.DictReader(io.StringIO(csv_text)):
        if row.get("SEM_EXM_EXCH_ID") != "MCX":
            continue
        if row.get("SEM_INSTRUMENT_NAME") != "FUTCOM":
            continue
        ts = row.get("SEM_TRADING_SYMBOL", "")
        sym = ts.split("-", 1)[0]
        if sym not in out:
            continue
        expiry = _parse_expiry(row.get("SEM_EXPIRY_DATE", ""))
        if not expiry or expiry < today:
            continue
        out[sym].append({
            "security_id": str(row.get("SEM_SMST_SECURITY_ID")),
            "trading_symbol": ts,
            "expiry": expiry,
        })
    for sym in out:
        out[sym].sort(key=lambda r: r["expiry"])
        out[sym] = out[sym][:MAX_MONTHS]
    return out


def refresh() -> None:
    contracts = _resolve_contracts(_download_csv())
    pairs: list[dict] = []
    for sym, disp in FAMILIES.items():
        cs = contracts.get(sym, [])
        for i in range(len(cs) - 1):
            near, far = cs[i], cs[i + 1]
            pairs.append({
                "metal": disp,
                "symbol": sym,
                "near_expiry": near["expiry"],
                "far_expiry": far["expiry"],
                "near_security_id": near["security_id"],
                "far_security_id": far["security_id"],
                "near_trading_symbol": near["trading_symbol"],
                "far_trading_symbol": far["trading_symbol"],
            })
    _state["pairs"] = pairs
    log.info("OtherComm: %d calendar pairs across %d families", len(pairs), len(FAMILIES))


def get_subscription_meta() -> dict[str, dict]:
    meta: dict[str, dict] = {}
    for p in _state["pairs"]:
        for role, sid, tsym in (
            ("near", p["near_security_id"], p["near_trading_symbol"]),
            ("far", p["far_security_id"], p["far_trading_symbol"]),
        ):
            meta[sid] = {
                "short": f"oc_{p['symbol'].lower()}_{role}",
                "trading_symbol": tsym,
                "kind": "othercomm",
            }
    return meta


def _bid(q):
    # Dead book (no bid, no ask) -> dash; LTP only fills a one-sided book's gap.
    b, a = clean_sides(q)
    if not b and not a:
        return None
    return b or q.ltp


def _ask(q):
    return q.ask or q.ltp


def get_table() -> dict:
    """Calendar-spread table (no % column — client said not required)."""
    rows = []
    for p in _state["pairs"]:
        far_q = quote_store.get(p["far_security_id"])
        near_q = quote_store.get(p["near_security_id"])
        far_price = _bid(far_q)
        near_price = _ask(near_q)
        difference = None
        if far_price and near_price:
            difference = round(far_price - near_price, 2)
        rows.append({
            "metal": p["metal"],
            "symbol": p["symbol"],
            "month": f'{p["near_expiry"].strftime("%b")}–{p["far_expiry"].strftime("%b")}',
            "near_month": p["near_expiry"].strftime("%d %b %Y"),
            "far_month": p["far_expiry"].strftime("%d %b %Y"),
            "far_price": far_price,
            "near_price": near_price,
            "difference": difference,
        })
    return {"rows": rows, "count": len(rows)}


def status() -> dict:
    return {"othercomm_pairs": len(_state.get("pairs", []))}
