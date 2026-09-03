"""Base-metal calendar-spread service (watch-only) — powers the 'Metal' tab.

For each metal family, for each ADJACENT month pair (near, far):
    far_price  = far month  Buy Price  (best bid)     e.g. Copper Jul 1392.15
    near_price = near month Sell Price (best ask)     e.g. Copper Jun 1376.30
    difference = far_price − near_price                = 15.85
    pct        = difference ÷ near_price × 100          = 1.15 %

Watch-only: NO firing, NO ladders. Legs are subscribed through the same Dhan
feed as plain MCX FUTCOM (Full mode, so bid/ask depth is available).
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime

from app.services.instrument_resolver import _download_csv, _parse_expiry
from app.services.market_data import clean_sides, quote_store

log = logging.getLogger("metals_service")

# Dhan MCX trading-symbol prefix → display name (all base metals + their minis)
METALS: dict[str, str] = {
    "COPPER": "Copper",
    "ALUMINIUM": "Aluminium",
    "ALUMINI": "Aluminium Mini",
    "ZINC": "Zinc",
    "ZINCMINI": "Zinc Mini",
    "NICKEL": "Nickel",
    "LEAD": "Lead",
    "LEADMINI": "Lead Mini",
}

MAX_MONTHS = 6  # expiries per metal to consider (gives up to 5 adjacent pairs)

_state: dict = {"pairs": []}  # list of pair dicts (see refresh())


def _resolve_metal_contracts(csv_text: str) -> dict[str, list[dict]]:
    """{symbol: [future contracts sorted by expiry ascending]} for metal families."""
    today = datetime.now()
    out: dict[str, list[dict]] = {sym: [] for sym in METALS}
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
    """Resolve metal contracts and build all adjacent-month calendar pairs."""
    contracts = _resolve_metal_contracts(_download_csv())
    pairs: list[dict] = []
    for sym, disp in METALS.items():
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
    log.info("Metals: %d calendar pairs across %d families", len(pairs), len(METALS))


def get_subscription_meta() -> dict[str, dict]:
    """{security_id: meta} for every metal leg — merged into the MCX feed subs
    so the default MCX-Full subscription path picks them up."""
    meta: dict[str, dict] = {}
    for p in _state["pairs"]:
        for role, sid, tsym in (
            ("near", p["near_security_id"], p["near_trading_symbol"]),
            ("far", p["far_security_id"], p["far_trading_symbol"]),
        ):
            meta[sid] = {
                "short": f"metal_{p['symbol'].lower()}_{role}",
                "trading_symbol": tsym,
                "kind": "metal",
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
    """Compute the 4-column metal calendar-spread table from live quotes."""
    rows = []
    for p in _state["pairs"]:
        far_q = quote_store.get(p["far_security_id"])
        near_q = quote_store.get(p["near_security_id"])
        far_price = _bid(far_q)    # far month Buy Price (bid)
        near_price = _ask(near_q)  # near month Sell Price (ask)
        difference = pct = None
        if far_price and near_price:
            difference = round(far_price - near_price, 2)
            pct = round(difference / near_price * 100, 2)
        rows.append({
            "metal": p["metal"],
            "symbol": p["symbol"],
            "month": f'{p["near_expiry"].strftime("%b")}–{p["far_expiry"].strftime("%b")}',
            "near_month": p["near_expiry"].strftime("%d %b %Y"),
            "far_month": p["far_expiry"].strftime("%d %b %Y"),
            # ISO legs for the row's History button (bhavcopy month-wise view)
            "near_expiry": p["near_expiry"].strftime("%Y-%m-%d"),
            "far_expiry": p["far_expiry"].strftime("%Y-%m-%d"),
            "far_price": far_price,      # 1392.15
            "near_price": near_price,    # 1376.30
            "difference": difference,    # 15.85
            "pct": pct,                  # 1.15
        })
    return {"rows": rows, "count": len(rows)}


def status() -> dict:
    return {"metal_pairs": len(_state.get("pairs", []))}
