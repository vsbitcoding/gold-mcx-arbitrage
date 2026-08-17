"""Public read-only API for the spread-monitoring app.

Auth: API key via `X-API-Key` header OR `?api_key=` query param.
Versioned at /api/v1/* — read-only, mobile-friendly, lean.
No write endpoints. No internal fields exposed.
"""
import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel

from app.security import require_api_key, verify_api_key_value
from app.services import crude_iv_service, extra_instruments, fcm_service, goldopt_service, ibkr_feed, mcxccl_service, metals_service, nse_mcx_history, options_history_service, options_service, othercomm_service, premium_feed, price_service, signal_service
from app.services.dhan_feed import is_market_open
from app.services.market_data import quote_store
from app.services.spread_engine import compute_all

log = logging.getLogger("public_v1")

router = APIRouter(prefix="/api/v1", tags=["public-v1"])


def _spread_dict(s: dict) -> dict:
    """Lean shape — only what a spread-monitoring app actually needs."""
    return {
        "id": s["name"],
        "pair": s["label"],                                  # "PETAL / GUINEA" or "PETAL 30JUN26-29MAY26"
        "group": s.get("group_label") or s["label"],         # for grouping rows in UI
        "type": s["type"],                                   # "cross" | "calendar"
        "expiry": s.get("expiry_label", ""),                 # "29 May 2026" / "Far ... − Near ..."
        "decrease": s["decrease_spread"],                    # null if no live quote
        "increase": s["increase_spread"],                    # null if no live quote
        "decrease_pct": s.get("decrease_pct"),               # decrease ÷ near price × 100 (shown on Calendar)
        "increase_pct": s.get("increase_pct"),
    }


def _grouped(snaps: list[dict]) -> list[dict]:
    """Group by `group` and sort each group front-month first."""
    groups: dict[str, list[dict]] = {}
    for s in snaps:
        gl = s.get("group_label") or s["label"]
        groups.setdefault(gl, []).append(s)

    out = []
    for label, rows in groups.items():
        rows_sorted = sorted(rows, key=lambda r: r.get("big_expiry") or "")
        items = [_spread_dict(r) for r in rows_sorted]
        out.append({
            "group": label,
            "type": rows[0]["type"],
            "count": len(items),
            "front": items[0] if items else None,    # collapsed-default row
            "expiries": items,                        # full list (front is items[0])
        })
    out.sort(key=lambda g: g["group"])
    return out


def _filter(snaps: list[dict], type_: str | None) -> list[dict]:
    if type_ and type_ != "all":
        return [s for s in snaps if s["type"] == type_]
    return snaps


# ────────────────────────────────────────────────────────────────────────
# Endpoints
# ────────────────────────────────────────────────────────────────────────

@router.get("/health")
def health():
    """Public uptime / market-status check. No auth required."""
    return {
        "status": "ok",
        "server_time": datetime.now(timezone.utc).isoformat(),
        "market_open": is_market_open(),
    }


@router.get("/spreads")
def list_spreads(
    type: str | None = Query(None, description="cross | calendar | all (default)"),
    _key: str = Depends(require_api_key),
):
    """Flat list of all pairs with current decrease & increase spread values."""
    snaps = _filter(compute_all(), type)
    items = [_spread_dict(s) for s in snaps]
    return {
        "server_time": datetime.now(timezone.utc).isoformat(),
        "market_open": is_market_open(),
        "count": len(items),
        "spreads": items,
    }


@router.get("/spread-groups")
def list_spread_groups(
    type: str | None = Query(None, description="cross | calendar | all (default)"),
    _key: str = Depends(require_api_key),
):
    """Grouped + tabbed view (recommended for UI).

    Shape mirrors the dashboard:
    - Two tabs: cross / calendar
    - Each group shows `front` row collapsed by default
    - On expand, render `expiries[]` (front is included as `expiries[0]`)
    """
    all_snaps = compute_all()
    cross_count = sum(1 for s in all_snaps if s["type"] == "cross")
    calendar_count = sum(1 for s in all_snaps if s["type"] == "calendar")

    snaps = _filter(all_snaps, type)
    return {
        "server_time": datetime.now(timezone.utc).isoformat(),
        "market_open": is_market_open(),
        "tabs": {"cross": cross_count, "calendar": calendar_count},
        "groups": _grouped(snaps),
    }


def _build_groups_payload(type_: str | None) -> tuple[dict, str]:
    """Compute the spread-groups payload and a digest of the spread values.

    Digest covers only the *data* (groups), not server_time, so successive
    snapshots with identical spreads can be skipped from being re-pushed.
    """
    all_snaps = compute_all()
    cross_count = sum(1 for s in all_snaps if s["type"] == "cross")
    calendar_count = sum(1 for s in all_snaps if s["type"] == "calendar")
    snaps = _filter(all_snaps, type_)
    groups = _grouped(snaps)

    digest_input = json.dumps(
        [
            (g["group"], [(p["id"], p["decrease"], p["increase"]) for p in g["expiries"]])
            for g in groups
        ],
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.md5(digest_input.encode("utf-8")).hexdigest()

    payload = {
        "type": "snapshot",
        "server_time": datetime.now(timezone.utc).isoformat(),
        "market_open": is_market_open(),
        "tabs": {"cross": cross_count, "calendar": calendar_count},
        "groups": groups,
    }
    return payload, digest


def _quote_ltp(security_id: str | None):
    if not security_id:
        return None
    q = quote_store.get(security_id)
    return q.ltp or None


def _build_metal_block(etf_symbol: str, etf_id: str, mcx_rec: dict | None, defaults: dict) -> dict:
    return {
        "etf": {
            "symbol": etf_symbol,
            "security_id": etf_id,
            "ltp": _quote_ltp(etf_id),
        },
        "mcx_full": {
            "symbol": mcx_rec["trading_symbol"] if mcx_rec else None,
            "security_id": mcx_rec["security_id"] if mcx_rec else None,
            "expiry": mcx_rec["expiry"].isoformat() if mcx_rec else None,
            "ltp": _quote_ltp(mcx_rec["security_id"] if mcx_rec else None),
        },
        "defaults": defaults,
        "formula": "(etf_ltp × multiplier + manual) ÷ divisor",
        "diff_definition": "calculator − mcx_full.ltp",
    }


@router.get("/calculator")
def public_calculator(_key: str = Depends(require_api_key)):
    """Live data for the Spot-vs-MCX Calculator (both metals).

    Returns raw LTPs + the per-metal default formula constants.
    The app does the math client-side:

        value  = (etf_ltp × multiplier + manual) / divisor
        diff   = value − mcx_full.ltp

    Multiplier, manual_value, and divisor are user-editable. Defaults shown
    are the ones the web dashboard ships with (Gold: ×120000 ÷103,
    Silver: ×31000 ÷30.9). Compare result vs `mcx_full.ltp` to surface the
    arbitrage gap.
    """
    return {
        "server_time": datetime.now(timezone.utc).isoformat(),
        "market_open": is_market_open(),
        "gold": _build_metal_block(
            etf_symbol=extra_instruments.GOLDBEES_TRADING_SYMBOL,
            etf_id=extra_instruments.GOLDBEES_NSE_SECURITY_ID,
            mcx_rec=extra_instruments.get_full_gold(),
            defaults={"multiplier": 120000, "manual": 0, "divisor": 103},
        ),
        "silver": _build_metal_block(
            etf_symbol=extra_instruments.SILVERBEES_TRADING_SYMBOL,
            etf_id=extra_instruments.SILVERBEES_NSE_SECURITY_ID,
            mcx_rec=extra_instruments.get_full_silver(),
            defaults={"multiplier": 31000, "manual": 0, "divisor": 30.9},
        ),
    }


@router.get("/options-spread")
def public_options_spread(
    side: str = Query("below", description="below = ATM+9 (10 rows) | above = ATM+14 (15 rows) | squareoff = ITM exit legs (Nifty ask / Sensex bid, 15 rows)"),
    _key: str = Depends(require_api_key),
):
    """Live Nifty / Sensex PE-options spread table (3 weeks × 10 strikes).

    Math (per row):
        nifty_value  = nifty_pe_ltp  × 325
        sensex_value = sensex_pe_ltp × 100
        spread       = nifty_value − sensex_value

    Sensex strike pairing (distance-preserving, per client):
        ITM_value     = nifty_spot − nifty_strike
        sensex_strike = round_to_100(sensex_spot − ITM_value × 3.2)
    ATM follows live Nifty spot; first row of each week is the ATM, next 9 are
    OTM puts (strikes below ATM).
    """
    return {
        "server_time": datetime.now(timezone.utc).isoformat(),
        "market_open": is_market_open(),
        "formula": "(nifty_pe_bid × 325) − (sensex_pe_ask × 100)   [falls back to LTP if no depth]",
        "strike_pairing": "sensex_strike = round_to_100(sensex_spot − (nifty_spot − nifty_strike) × 3.2)",
        "status": options_service.status(),
        **options_service.get_spread_table(side if side in ("above", "squareoff") else "below"),
    }


@router.get("/board")
def public_board(
    template: str = Query("gurukrupa", description="gurukrupa (LIVE RATES) | gurukrupasilver (SILVER RATES) | gurukrupab2c"),
    _key: str = Depends(require_api_key),
):
    """Customer-facing live rate board (powers the app's LIVE RATES / SILVER
    RATES screens and the public website).

    Returns only VISIBLE scrips of the template, in display order, each with
    live buy/sell plus the day's low/high (IST day, tracked server-side).
    Poll every 2s while the screen is foregrounded; pause in background.
    """
    from app.routes import scrip_master  # shared cached builder (~1s TTL)

    b = scrip_master.build_board(template if template in ("gurukrupa", "gurukrupab2c", "gurukrupasilver") else "gurukrupa")
    return {
        "server_time": datetime.now(timezone.utc).isoformat(),
        "market_open": is_market_open(),
        "template": b["template"],
        "scrips": [
            {"name": s["name"], "code": s["code"], "buy": s["buy_rate"], "sell": s["sell_rate"],
             "low": s.get("low"), "high": s.get("high"), "trade": s["allow_trade"]}
            for s in b["scrips"] if s["visible"]
        ],
    }


def _board_payload(template: str) -> tuple[dict, str]:
    """The board snapshot plus a digest of just the rates, so the socket stays
    quiet while nothing moves."""
    from app.routes import scrip_master  # shared cached builder (~1s TTL)

    b = scrip_master.build_board(template)
    scrips = [
        {"name": s["name"], "code": s["code"], "buy": s["buy_rate"], "sell": s["sell_rate"],
         "low": s.get("low"), "high": s.get("high"), "trade": s["allow_trade"]}
        for s in b["scrips"] if s["visible"]
    ]
    digest = hashlib.md5(json.dumps(
        [[x["code"], x["buy"], x["sell"], x["low"], x["high"]] for x in scrips],
        separators=(",", ":")).encode("utf-8")).hexdigest()
    return {
        "type": "snapshot",
        "server_time": datetime.now(timezone.utc).isoformat(),
        "market_open": is_market_open(),
        "template": b["template"],
        "scrips": scrips,
    }, digest


@router.websocket("/board/stream")
async def public_board_stream(
    websocket: WebSocket,
    api_key: str | None = Query(None, alias="api_key"),
    key: str | None = Query(None),
    template: str = Query("gurukrupa", description="gurukrupa | gurukrupasilver | gurukrupab2c"),
    interval: float = Query(1.0, ge=0.5, le=5.0),
    keepalive: int = Query(15, ge=5, le=60),
):
    """Live rate board as a push feed - the same rows and day low/high as
    GET /api/v1/board, sent the moment a rate changes instead of on a timer.

    Connect: wss://host/api/v1/board/stream?api_key=<KEY>&template=gurukrupa
    A {"type":"heartbeat"} frame goes out every `keepalive` seconds while the
    market is quiet. Send "ping" -> "pong".
    """
    if not verify_api_key_value(api_key or key):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    if template not in ("gurukrupa", "gurukrupab2c", "gurukrupasilver"):
        template = "gurukrupa"
    await websocket.accept()

    stop = asyncio.Event()

    async def receiver():
        try:
            while not stop.is_set():
                msg = await websocket.receive_text()
                if msg.strip().lower() == "ping":
                    await websocket.send_text("pong")
        except WebSocketDisconnect:
            pass
        except Exception as e:  # noqa: BLE001
            log.debug("board WS receiver ended: %s", e)
        finally:
            stop.set()

    async def pusher():
        last_digest, last_send_at = None, 0.0
        try:
            payload, digest = _board_payload(template)
            await websocket.send_json(payload)
            last_digest = digest
            last_send_at = asyncio.get_event_loop().time()
            while not stop.is_set():
                try:
                    await asyncio.wait_for(stop.wait(), timeout=interval)
                except asyncio.TimeoutError:
                    pass
                if stop.is_set():
                    break
                payload, digest = _board_payload(template)
                now = asyncio.get_event_loop().time()
                if digest != last_digest:
                    await websocket.send_json(payload)
                    last_digest, last_send_at = digest, now
                elif (now - last_send_at) >= keepalive:
                    await websocket.send_json({
                        "type": "heartbeat",
                        "server_time": payload["server_time"],
                        "market_open": payload["market_open"],
                    })
                    last_send_at = now
        except WebSocketDisconnect:
            pass
        except Exception as e:  # noqa: BLE001
            log.exception("board WS pusher error: %s", e)
        finally:
            stop.set()

    recv_task = asyncio.create_task(receiver())
    push_task = asyncio.create_task(pusher())
    try:
        await asyncio.wait({recv_task, push_task}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        stop.set()
        for t in (recv_task, push_task):
            t.cancel()
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass


@router.get("/options-history")
def public_options_history(
    weekday: str | None = Query(None, description="mon..sun or 0..6 (0=Mon) → last N same-weekday boards; omit = latest snapshot days"),
    slot: str = Query("both", description="10:00 | 15:00 | 15:15 | 15:35 | both (15:25 = boards from before 13-Aug-2026)"),
    side: str = Query("below", description="below | above | squareoff — same row shapes as /options-spread"),
    weeks: int = Query(7, ge=1, le=52, description="how many most-recent matching days (default 7)"),
    date: str | None = Query(None, description="YYYY-MM-DD → that day's snapshot(s) instead of a weekday series"),
    _key: str = Depends(require_api_key),
):
    """History of the Nifty/Sensex PE board, auto-captured at 10:00, 15:00, 15:15 & 15:35 IST
    each trading day (replaces manual screenshots).

    Example: /api/v1/options-history?weekday=mon&slot=10:00&weeks=7
       → the last 7 Mondays' 10am boards, newest first.
    Each snapshot's weeks[].rows[] has exactly the /options-spread row shape,
    so the same renderer works. `count` can be < weeks (holidays have no
    snapshot) — render what is returned. Data is static once written: fetch on
    demand, no polling needed.
    """
    return {
        "server_time": datetime.now(timezone.utc).isoformat(),
        "market_open": is_market_open(),
        **options_history_service.get_history(weekday=weekday, slot=slot, side=side, weeks=weeks, date=date),
    }


@router.get("/metals-spread")
def public_metals_spread(_key: str = Depends(require_api_key)):
    """Live base-metal calendar-spread table (watch-only).

    Per row (adjacent month pair):
        far_price  = far month  Buy Price  (bid)
        near_price = near month Sell Price (ask)
        difference = far_price − near_price
        pct        = difference ÷ near_price × 100
    """
    return {
        "server_time": datetime.now(timezone.utc).isoformat(),
        "market_open": is_market_open(),
        "formula": "difference = far.buy − near.sell ; pct = difference ÷ near.sell × 100",
        "status": metals_service.status(),
        **metals_service.get_table(),
    }


@router.get("/othercomm-spread")
def public_othercomm_spread(_key: str = Depends(require_api_key)):
    """Live other-commodity calendar-spread table (Crude / NatGas / Electricity).

    Per row (adjacent month pair):
        far_price  = far month  Buy Price  (bid)
        near_price = near month Sell Price (ask)
        difference = far_price − near_price
    """
    return {
        "server_time": datetime.now(timezone.utc).isoformat(),
        "market_open": is_market_open(),
        "formula": "difference = far.buy − near.sell",
        "status": othercomm_service.status(),
        **othercomm_service.get_table(),
    }


@router.get("/gold-options-spread")
def public_gold_options_spread(commodity: str = "gold", _key: str = Depends(require_api_key)):
    """Live commodity BIG-vs-MINI option-spread table (watch-only), current + next month.

    `commodity` = gold | silver | crude | natgas (see `commodities` in the response).
    Per strike (PE below the future price, CE above), 1:1, both directions:
        spread1 = lower-future.Bid - higher-future.Ask
        spread2 = higher-future.Bid - lower-future.Ask
    (The higher/lower future is decided live.)
    """
    return {
        "server_time": datetime.now(timezone.utc).isoformat(),
        "market_open": is_market_open(),
        "status": goldopt_service.status(),
        **goldopt_service.get_spread_table(commodity),
    }


@router.get("/bullion-stock")
def public_bullion_stock(_key: str = Depends(require_api_key)):
    """MCXCCL daily bullion warehouse stock (Eligible Units) + history + stock-vs-spread
    correlation. Data changes ~once/day — poll at most every 60s."""
    return {
        "server_time": datetime.now(timezone.utc).isoformat(),
        "status": mcxccl_service.status(),
        **mcxccl_service.report(),
    }


@router.get("/bullion-stock/pdf")
def public_bullion_pdf(download: bool = Query(False), _key: str = Depends(require_api_key)):
    """The latest MCXCCL stock PDF (served from our server). Accepts the key as a
    query param (`?api_key=...`) so the app can open/download it directly."""
    pdf = mcxccl_service.get_latest_pdf()
    if not pdf:
        raise HTTPException(status_code=404, detail="No bullion PDF available yet")
    content, name, _src = pdf
    disposition = "attachment" if download else "inline"
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disposition}; filename="{name}"'},
    )


@router.get("/signals")
def public_signals(_key: str = Depends(require_api_key)):
    """Currently-open fire-once mean-reversion signals (cross pairs).

    Each signal is FROZEN at fire: {label, expiry_label, direction, entry, target,
    probability (% chance to reach target, from history), expected_days, current,
    progress_pct, z_at_entry, age_min}.
    direction: 'narrow' = spread high, expected to fall to target (the mean);
               'widen'  = spread low,  expected to rise. Not financial advice.
    """
    return {
        "server_time": datetime.now(timezone.utc).isoformat(),
        "market_open": is_market_open(),
        "status": signal_service.status(),
        "signals": signal_service.get_active_signals(),
    }


@router.get("/signals-history")
def public_signals_history(limit: int = Query(100, ge=1, le=500), _key: str = Depends(require_api_key)):
    """Resolved signals, each marked outcome 'right' (hit target) or 'wrong'."""
    return {"server_time": datetime.now(timezone.utc).isoformat(),
            "history": signal_service.get_history(limit)}


@router.get("/signals-accuracy")
def public_signals_accuracy(_key: str = Depends(require_api_key)):
    """Overall + per-pair signal accuracy (the verifiable track record)."""
    return {"server_time": datetime.now(timezone.utc).isoformat(),
            **signal_service.get_accuracy()}


class DeviceRegister(BaseModel):
    token: str | None = None
    device_id: str | None = None
    platform: str | None = "android"        # "android" | "ios"


@router.post("/devices/register")
def register_device(payload: DeviceRegister, _key: str = Depends(require_api_key)):
    """Register a device for push notifications.

    Body: { "token": "<FCM token>", "device_id": "<id>", "platform": "android"|"ios" }
    Identity is `device_id` — sending again just updates that device's token.
    A BLANK token never overwrites a previously-saved token (kept by request).
    Returns { ok, saved } — saved=false when a blank token was ignored.
    """
    return fcm_service.register_device(payload.token, payload.device_id, payload.platform)


@router.get("/price-table")
def public_price_table(_key: str = Depends(require_api_key)):
    """Live Buyer (bid) / Seller (ask) price for every active contract of the
    gold & silver instruments, grouped per instrument in display sequence."""
    return {
        "server_time": datetime.now(timezone.utc).isoformat(),
        "market_open": is_market_open(),
        "status": price_service.status(),
        **price_service.get_table(),
    }


def _quote(o: dict | None, name: str, symbol: str, unit: str, decimals: int) -> dict:
    """One international instrument, with the mid already computed for the app."""
    o = o or {}
    # the IV blocks report a single future_price rather than a bid/ask pair
    if "future_price" in o and "bid" not in o:
        o = {"bid": o.get("future_price"), "ask": o.get("future_price"),
             "symbol": o.get("symbol"), "expiry": o.get("expiry"), "age": o.get("age")}
    bid, ask = o.get("bid"), o.get("ask")
    mid = (bid + ask) / 2 if (bid and ask) else (bid or ask or o.get("last"))
    return {
        "name": name, "symbol": symbol, "unit": unit, "decimals": decimals,
        "bid": bid, "ask": ask,
        "mid": round(mid, decimals) if mid else None,
        "spread": round(ask - bid, decimals) if (bid and ask) else None,
        "contract": o.get("symbol"),          # e.g. "GCV6" (futures only)
        "expiry": o.get("expiry"),            # e.g. "20261229" (futures only)
        "age": o.get("age"),                  # seconds since the last tick
    }


def _international_payload() -> tuple[dict, str]:
    """The international snapshot + a digest of just the prices, so the
    WebSocket can skip pushing when nothing actually moved."""
    d = ibkr_feed.get_data()

    items = [
        _quote(d.get("gold_spot"), "GOLD SPOT", "XAU/USD", "$/oz", 2),
        _quote(d.get("silver_spot"), "SILVER SPOT", "XAG/USD", "$/oz", 3),
        _quote(d.get("gold_future"), "GOLD FUTURE", "COMEX GC", "$/oz", 2),
        _quote(d.get("silver_future"), "SILVER FUTURE", "COMEX SI", "$/oz", 3),
        _quote(d.get("crude_future"), "CRUDE FUTURE", "NYMEX WTI CL", "$/bbl", 2),
        _quote(d.get("natgas_iv"), "NATURAL GAS FUTURE", "NYMEX NG", "$/MMBtu", 3),
    ]
    by = {i["symbol"]: i["mid"] for i in items}
    xau, xag = by["XAU/USD"], by["XAG/USD"]
    gc, si = by["COMEX GC"], by["COMEX SI"]
    cl = by["NYMEX WTI CL"]

    def chain_block(src: dict | None, prefix: str, under: float | None) -> dict:
        """Full option chain: every strike with both legs, expiry repeated on each
        row and a ready trading symbol per leg. Used for crude and gas alike."""
        src = src or {}
        raw_ = src.get("rows") or []
        atm_ = min((r["strike"] for r in raw_), key=lambda k: abs(k - under)) \
            if (raw_ and under) else None
        e = src.get("expiry")
        e_date = e_disp = None
        dte_ = None
        if e and len(e) == 8:
            ed_ = datetime(int(e[:4]), int(e[4:6]), int(e[6:8]), tzinfo=timezone.utc)
            e_date = ed_.strftime("%Y-%m-%d")
            e_disp = ed_.strftime("%d-%b-%Y").upper()
            dte_ = (ed_.date() - datetime.now(timezone.utc).date()).days

        def m_(x):
            b, a = x.get("bid"), x.get("ask")
            return round((b + a) / 2, 4) if (b and a) else (b or a)

        out = []
        for r in raw_:
            c_, p_ = r.get("call") or {}, r.get("put") or {}
            k = r["strike"]
            out.append({
                "strike": k,
                "expiry": e, "expiry_date": e_date, "expiry_display": e_disp,
                "atm": (k == atm_),
                "itm": None if not under else ("call" if k < under else "put" if k > under else None),
                "call": {"symbol": f"{prefix}_OPT_{e_disp or e}_{k}_CE",
                         "bid": c_.get("bid"), "ask": c_.get("ask"), "mid": m_(c_),
                         "iv": c_.get("iv"), "delta": c_.get("delta")},
                "put": {"symbol": f"{prefix}_OPT_{e_disp or e}_{k}_PE",
                        "bid": p_.get("bid"), "ask": p_.get("ask"), "mid": m_(p_),
                        "iv": p_.get("iv"), "delta": p_.get("delta")},
            })
        return {
            "exchange": "NYMEX",
            "trading_class": src.get("trading_class"),
            "expiry": e, "expiry_date": e_date, "expiry_display": e_disp,
            "days_to_expiry": dte_,
            "underlying": under,
            "atm_strike": atm_,
            "age": src.get("age"),
            "rows": out,
        }

    opts = d.get("crude_options") or {}
    raw = opts.get("rows") or []
    atm = min((r["strike"] for r in raw), key=lambda k: abs(k - cl)) if (raw and cl) else None

    # Expiry on every leg, not only on the parent object. Consumers iterate the
    # rows and build their own symbols, so an expiry that lives one level up
    # simply never reaches the screen (client's terminal, 03-Aug).
    exp = opts.get("expiry")                      # "YYYYMMDD"
    exp_date = exp_display = None
    dte = None
    if exp and len(exp) == 8:
        ed = datetime(int(exp[:4]), int(exp[4:6]), int(exp[6:8]), tzinfo=timezone.utc)
        exp_date = ed.strftime("%Y-%m-%d")
        exp_display = ed.strftime("%d-%b-%Y").upper()          # 05-AUG-2026
        dte = (ed.date() - datetime.now(timezone.utc).date()).days

    def strike_txt(k):
        # 78.0 / 78.25 - matches how the client's terminal already prints strikes,
        # so `symbol` is a drop-in for the string his code builds itself.
        return str(k)

    rows = []
    for r in raw:
        c, p = r.get("call") or {}, r.get("put") or {}
        def m(x):
            b, a = x.get("bid"), x.get("ask")
            return round((b + a) / 2, 2) if (b and a) else (b or a)
        k = r["strike"]
        rows.append({
            "strike": k,
            "expiry": exp,                        # same on every row, but always present
            "expiry_date": exp_date,
            "expiry_display": exp_display,
            "atm": k == atm,
            "itm": None if not cl else ("call" if k < cl else "put" if k > cl else None),
            "call": {"symbol": f"CRUDE_OPT_{exp_display or exp}_{strike_txt(k)}_CE",
                     "bid": c.get("bid"), "ask": c.get("ask"), "mid": m(c)},
            "put": {"symbol": f"CRUDE_OPT_{exp_display or exp}_{strike_txt(k)}_PE",
                    "bid": p.get("bid"), "ask": p.get("ask"), "mid": m(p)},
        })
    atm_row = next((r for r in rows if r["atm"]), None)
    straddle = None
    if atm_row and atm_row["call"]["mid"] and atm_row["put"]["mid"]:
        straddle = round(atm_row["call"]["mid"] + atm_row["put"]["mid"], 2)

    def iv_block(src: dict | None, prefix: str, dec: int) -> dict:
        """The monthly chain with implied volatility: 10 calls above the money,
        the ATM row carrying both sides, 10 puts below (the client's layout)."""
        src = src or {}
        e = src.get("expiry")
        disp = None
        if e and len(e) == 8:
            disp = datetime(int(e[:4]), int(e[4:6]), int(e[6:8]),
                            tzinfo=timezone.utc).strftime("%d-%b-%Y").upper()
        out = []
        for r in src.get("rows") or []:
            k = r["strike"]

            def leg(side, tag, _r=r, _k=k):
                if not _r.get(side):
                    return None
                return {
                    "symbol": f"{prefix}_OPT_{disp or e}_{_k}_{tag}",
                    **{kk: _r[side].get(kk) for kk in
                       ("bid", "ask", "mid", "iv", "delta", "theta", "gamma", "vega")},
                }

            out.append({
                "strike": k, "side": r["side"], "atm": r["atm"],
                "expiry": e, "expiry_display": disp,
                "ce": leg("ce", "CE"), "pe": leg("pe", "PE"),
            })
        return {
            "exchange": "NYMEX",
            "symbol": src.get("symbol"),
            "trading_class": src.get("trading_class"),
            "future_price": src.get("future_price"),
            "expiry": e, "expiry_display": disp,
            "atm": src.get("atm"),
            "iv_unit": "percent",
            "decimals": dec,
            "age": src.get("age"),
            "rows": out,
        }

    payload = {
        "type": "snapshot",
        "server_time": datetime.now(timezone.utc).isoformat(),
        "source": "Interactive Brokers (COMEX + NYMEX)",
        "connected": d.get("connected", False),
        "delayed": d.get("delayed", False),
        "items": items,
        "crude_options": {
            "exchange": "NYMEX",
            "expiry": exp,                       # "YYYYMMDD"
            "expiry_date": exp_date,             # "2026-08-05"
            "expiry_display": exp_display,       # "05-AUG-2026"
            "days_to_expiry": dte,
            "underlying": cl,
            "atm_strike": atm,
            "age": opts.get("age"),
            "rows": rows,
        },
        # Monthly chains WITH implied volatility - crude and gas, same shape.
        "crude_iv": iv_block(d.get("crude_iv"), "CRUDE", 2),
        "natgas_iv": iv_block(d.get("natgas_iv"), "NATGAS", 3),
        # Full chain, both sides on every strike - the shape a terminal renders
        # directly. natgas_options is new; gas was showing half-empty rows
        # because only the IV block existed for it (client, 12-Aug).
        "natgas_options": chain_block(d.get("natgas_options"), "NATGAS",
                                      (d.get("natgas_iv") or {}).get("future_price")),
        # NEXT month, identical shape to the four above (client's developer,
        # 13-Aug). Separate keys rather than a month field inside the existing
        # ones, so an app already reading crude_options keeps working untouched.
        "crude_iv_next": iv_block(d.get("crude_iv_next"), "CRUDE", 2),
        "natgas_iv_next": iv_block(d.get("natgas_iv_next"), "NATGAS", 3),
        "crude_options_next": chain_block(d.get("crude_options_next"), "CRUDE",
                                          (d.get("crude_iv_next") or {}).get("future_price")),
        "natgas_options_next": chain_block(d.get("natgas_options_next"), "NATGAS",
                                           (d.get("natgas_iv_next") or {}).get("future_price")),
        "summary": {
            "gold_basis": round(gc - xau, 2) if (gc and xau) else None,
            "silver_basis": round(si - xag, 3) if (si and xag) else None,
            "gold_silver_ratio_spot": round(xau / xag, 2) if (xau and xag) else None,
            "gold_silver_ratio_future": round(gc / si, 2) if (gc and si) else None,
            "atm_straddle": straddle,
        },
    }
    # Every chain feeds the digest, next month included - otherwise the socket
    # would sit quiet while only a next-month strike moved.
    ivsrc = [r for k in ("crude_iv", "natgas_iv", "crude_iv_next", "natgas_iv_next")
             for r in (d.get(k) or {}).get("rows", [])]
    digest_input = json.dumps(
        [[i["bid"], i["ask"]] for i in items]
        + [[r["strike"], r["call"]["bid"], r["call"]["ask"], r["put"]["bid"], r["put"]["ask"]] for r in rows]
        + [[r["strike"], (r.get("ce") or {}).get("bid"), (r.get("ce") or {}).get("ask"),
            (r.get("pe") or {}).get("bid"), (r.get("pe") or {}).get("ask")] for r in ivsrc],
        separators=(",", ":"),
    )
    return payload, hashlib.md5(digest_input.encode("utf-8")).hexdigest()


@router.get("/international")
def public_international(_key: str = Depends(require_api_key)):
    """The six international items from IBKR (COMEX + NYMEX real-time):
    gold & silver spot, gold & silver COMEX futures, NYMEX crude future and the
    crude option chain around the money. All mids/derived values are computed
    here so the client only renders. Poll every 2-5 s, or use the WebSocket at
    /api/v1/international/stream to be pushed only on change."""
    payload, _ = _international_payload()
    payload.pop("type", None)
    return payload


@router.websocket("/international/stream")
async def public_international_stream(
    websocket: WebSocket,
    api_key: str | None = Query(None, alias="api_key"),
    key: str | None = Query(None),                  # same alias as /stream
    interval: float = Query(1.0, ge=0.5, le=5.0),
    keepalive: int = Query(15, ge=5, le=60, description="Heartbeat interval (s) when nothing moves"),
):
    """Live international stream (the six IBKR items + crude option chain).

    Connect: wss://host/api/v1/international/stream?api_key=<KEY>&interval=1
    Sends one snapshot immediately, then a new one every `interval` seconds
    **only when a price actually changed**. A {"type":"heartbeat"} frame goes out
    every `keepalive` seconds while the market is quiet.

    Client may send "ping" -> server replies "pong".
    """
    token = api_key or key
    if not verify_api_key_value(token):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await websocket.accept()

    stop = asyncio.Event()

    async def receiver():
        try:
            while not stop.is_set():
                msg = await websocket.receive_text()
                if msg.strip().lower() == "ping":
                    await websocket.send_text("pong")
        except WebSocketDisconnect:
            pass
        except Exception as e:  # noqa: BLE001
            log.debug("intl WS receiver ended: %s", e)
        finally:
            stop.set()

    async def pusher():
        last_digest, last_send_at = None, 0.0
        try:
            payload, digest = _international_payload()
            await websocket.send_json(payload)
            last_digest = digest
            last_send_at = asyncio.get_event_loop().time()

            while not stop.is_set():
                try:
                    await asyncio.wait_for(stop.wait(), timeout=interval)
                except asyncio.TimeoutError:
                    pass
                if stop.is_set():
                    break

                payload, digest = _international_payload()
                now = asyncio.get_event_loop().time()
                if digest != last_digest:
                    await websocket.send_json(payload)
                    last_digest, last_send_at = digest, now
                elif (now - last_send_at) >= keepalive:
                    await websocket.send_json({
                        "type": "heartbeat",
                        "server_time": payload["server_time"],
                        "connected": payload["connected"],
                    })
                    last_send_at = now
        except WebSocketDisconnect:
            pass
        except Exception as e:  # noqa: BLE001
            log.exception("intl WS pusher error: %s", e)
            try:
                await websocket.send_json({"type": "error", "detail": "stream error, please reconnect"})
            except Exception:  # noqa: BLE001
                pass
        finally:
            stop.set()

    recv_task = asyncio.create_task(receiver())
    push_task = asyncio.create_task(pusher())
    try:
        await asyncio.wait({recv_task, push_task}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        stop.set()
        for t in (recv_task, push_task):
            t.cancel()
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass


@router.get("/crude-iv")
def public_crude_iv(
    commodity: str = Query("crude", description="crude | natgas"),
    window: int = Query(10, ge=1, le=25, description="strikes each side of ATM (default 10 => 21 rows)"),
    _key: str = Depends(require_api_key),
):
    """MCX and US option chains side by side (crude oil or natural gas), with
    implied volatility and greeks on both. Layout is 10 calls above the money, the ATM row, 10 puts
    below. IV is a PERCENT on both sides (64.89 = 64.89%).

    MCX refreshes every ~5 s (Dhan permits one option-chain call per 3 s); the
    US side is live. Poll every 3-5 s - faster gains nothing.
    """
    from app.routes.crude_iv import _payload
    return _payload(window, commodity)


@router.get("/nse-mcx")
def public_nse_mcx(
    commodity: str = Query("crude", pattern="^(crude|natgas)$", description="crude | natgas"),
    month: int = Query(0, ge=0, le=1, description="0 = near month, 1 = the one after"),
    window: int = Query(10, ge=1, le=25, description="strikes each side of ATM (default 10 => 21 rows)"),
    _key: str = Depends(require_api_key),
):
    """NSE vs MCX - future and option chain side by side, with the difference in
    rupees and percent on every leg. Crude oil and natural gas; those are the
    only NSE commodities with a real two-way market.

    Futures share an expiry on both, so that difference is clean. Option
    expiries do NOT match (crude MCX 17-Sep vs NSE 10-Sep, gas MCX 24-Aug vs NSE
    20-Aug), so both dates are returned and part of any premium gap is time
    value. `traded` is false where a leg has no bid and no ask - ignore its LTP,
    dead contracts still print stale prices.
    """
    from app.routes.nse_mcx import payload
    return payload(commodity, window, month)


@router.get("/nse-mcx-crude")
def public_nse_mcx_crude(
    commodity: str = Query("crude", pattern="^(crude|natgas)$"),
    window: int = Query(10, ge=1, le=25),
    _key: str = Depends(require_api_key),
):
    """Kept working because the app already calls this path. Same response as
    /nse-mcx - prefer that one for new work."""
    from app.routes.nse_mcx import payload
    return payload(commodity, window)


@router.get("/nse-mcx/history")
def public_nse_mcx_history(
    commodity: str = Query("crude", pattern="^(crude|natgas)$"),
    slot: str = Query("all", pattern="^(all|10:00|12:00|15:00)$"),
    days: int = Query(7, ge=1, le=60, description="how many snapshot days back"),
    date: str | None = Query(None, description="YYYY-MM-DD => that day only"),
    month: int = Query(0, ge=0, le=1, description="0 = near month, 1 = the one after"),
    _key: str = Depends(require_api_key),
):
    """Stored 10:00 / 12:00 / 15:00 IST boards, newest first.

    Each snapshot's `board` has exactly the /nse-mcx shape, so the same renderer
    works for both. Data is static once written - fetch on demand, do not poll.
    No exchange sells NSE-commodity history, so nothing before our first capture
    exists and never will.
    """
    return nse_mcx_history.get_history(commodity=commodity, slot=slot, days=days, date=date, month=month)


@router.get("/premium-inputs")
def public_premium_inputs(_key: str = Depends(require_api_key)):
    """Live premium-calc inputs: XAU/USD (Deriv), USD/INR (TwelveData spot), MCX gold (Dhan)."""
    return premium_feed.get_inputs()


@router.websocket("/stream")
async def public_stream(
    websocket: WebSocket,
    api_key: str | None = Query(None, alias="api_key"),
    key: str | None = Query(None),                  # legacy alias
    interval: float = Query(1.0, ge=0.5, le=5.0),
    type: str | None = Query(None),
    keepalive: int = Query(15, ge=5, le=60, description="Heartbeat interval (s) when no data change"),
):
    """Live spread stream.

    Connect: wss://host/api/v1/stream?api_key=<KEY>&interval=1
    Pushes a snapshot every `interval` seconds **only when spread values change**.
    A heartbeat frame {"type":"heartbeat"} is sent every `keepalive` seconds
    so idle clients can confirm the connection is alive.

    Client may send "ping" → server replies "pong".
    """
    token = api_key or key
    if not verify_api_key_value(token):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()

    stop = asyncio.Event()

    async def receiver():
        try:
            while not stop.is_set():
                msg = await websocket.receive_text()
                if msg == "ping":
                    await websocket.send_text("pong")
        except WebSocketDisconnect:
            pass
        except Exception as e:
            log.exception("WS receiver error: %s", e)
        finally:
            stop.set()

    async def pusher():
        last_digest = None
        last_send_at = 0.0
        try:
            # Always send the first snapshot so the client has initial state.
            payload, digest = _build_groups_payload(type)
            await websocket.send_json(payload)
            last_digest = digest
            last_send_at = asyncio.get_event_loop().time()

            while not stop.is_set():
                # Yield to receiver / cancellation between ticks.
                try:
                    await asyncio.wait_for(stop.wait(), timeout=interval)
                except asyncio.TimeoutError:
                    pass
                if stop.is_set():
                    break

                payload, digest = _build_groups_payload(type)
                now = asyncio.get_event_loop().time()
                changed = digest != last_digest
                stale_keepalive = (now - last_send_at) >= keepalive

                if changed:
                    await websocket.send_json(payload)
                    last_digest = digest
                    last_send_at = now
                elif stale_keepalive:
                    # Idle heartbeat — no data change, but tell the client we're alive.
                    await websocket.send_json({
                        "type": "heartbeat",
                        "server_time": payload["server_time"],
                        "market_open": payload["market_open"],
                    })
                    last_send_at = now
        except WebSocketDisconnect:
            pass
        except Exception as e:
            log.exception("WS pusher error: %s", e)
            try:
                await websocket.send_json({"type": "error", "detail": "stream error, please reconnect"})
            except Exception:
                pass
        finally:
            stop.set()

    recv_task = asyncio.create_task(receiver())
    push_task = asyncio.create_task(pusher())
    try:
        await stop.wait()
    finally:
        for t in (recv_task, push_task):
            if not t.done():
                t.cancel()
        # Drain any cancellations cleanly.
        await asyncio.gather(recv_task, push_task, return_exceptions=True)
        try:
            await websocket.close()
        except Exception:
            pass
