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

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel

from app.security import require_api_key, verify_api_key_value
from app.services import extra_instruments, fcm_service, goldopt_service, metals_service, options_service, othercomm_service, price_service, signal_service
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
def public_gold_options_spread(_key: str = Depends(require_api_key)):
    """Live GOLD vs GOLD MINI option-spread table (watch-only), current + next month.

    Per strike (PE below the future price, CE above), 1:1, both directions:
        spread1 = lower-future.Bid - higher-future.Ask
        spread2 = higher-future.Bid - lower-future.Ask
    (The higher/lower future is decided live; currently GOLD > GOLD MINI.)
    """
    return {
        "server_time": datetime.now(timezone.utc).isoformat(),
        "market_open": is_market_open(),
        "status": goldopt_service.status(),
        **goldopt_service.get_spread_table(),
    }


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
