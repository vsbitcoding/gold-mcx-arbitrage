"""Public read-only API for external apps (e.g. mobile dashboard).

Auth: API key via X-API-Key header or ?api_key= query param.
Versioned at /api/v1/* — write endpoints (ladders, positions, control)
are NOT exposed here. Safe for third-party app developers.
"""
import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status

from app.security import require_api_key, verify_api_key_value
from app.services import pair_registry
from app.services.dhan_feed import is_market_open
from app.services.spread_engine import compute_all, compute_pair

router = APIRouter(prefix="/api/v1", tags=["public-v1"])


def _public_pair_dict(s: dict) -> dict:
    """Trim internal fields for the public API. Mobile-friendly shape."""
    return {
        "id": s["name"],
        "type": s["type"],
        "label": s["label"],
        "expiry": s.get("expiry_label", ""),
        "expiry_short": s.get("expiry_short", ""),
        "decrease_spread": s["decrease_spread"],
        "increase_spread": s["increase_spread"],
        "big": {
            "instrument": s["big"],
            "trading_symbol": s.get("big_trading_symbol", ""),
            "lots": s["big_lots"],
            "bid": s["big_bid"],
            "ask": s["big_ask"],
        },
        "small": {
            "instrument": s["small"],
            "trading_symbol": s.get("small_trading_symbol", ""),
            "lots": s["small_lots"],
            "bid": s["small_bid"],
            "ask": s["small_ask"],
        },
    }


@router.get("/health")
def health():
    """Public uptime check — no auth required."""
    return {
        "status": "ok",
        "server_time": datetime.now(timezone.utc).isoformat(),
        "market_open": is_market_open(),
    }


@router.get("/pairs")
def list_pairs(
    type: str | None = Query(None, description="Filter: cross | calendar | all"),
    search: str | None = Query(None, description="Filter by pair label/expiry text"),
    _key: str = Depends(require_api_key),
):
    """Returns all active pairs with current decrease/increase spreads.
    Supports filters: ?type=cross|calendar, ?search=petal"""
    snaps = compute_all()
    if type and type != "all":
        snaps = [s for s in snaps if s["type"] == type]
    if search:
        term = search.lower()
        snaps = [
            s for s in snaps
            if term in s["name"].lower()
            or term in s["label"].lower()
            or term in s.get("expiry_label", "").lower()
        ]
    out = [_public_pair_dict(s) for s in snaps]
    return {
        "total": len(out),
        "server_time": datetime.now(timezone.utc).isoformat(),
        "market_open": is_market_open(),
        "pairs": out,
    }


@router.get("/pairs/{pair_id}")
def get_pair(pair_id: str, _key: str = Depends(require_api_key)):
    """Single-pair detail with current spread."""
    pair = pair_registry.get_pair(pair_id)
    if not pair:
        raise HTTPException(404, "Pair not found")
    snap = compute_pair(pair)
    return _public_pair_dict(snap)


@router.websocket("/stream")
async def public_stream(
    websocket: WebSocket,
    key: str | None = Query(None),
    interval: float = Query(1.0, ge=0.5, le=5.0, description="Push interval in seconds (0.5-5)"),
):
    """Live WebSocket stream of pair snapshots.

    Connect with: wss://host/api/v1/stream?key=<api_key>&interval=1
    Pushes a full snapshot every `interval` seconds.
    Client may send "ping", server replies "pong".
    """
    if not verify_api_key_value(key):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()

    async def receiver():
        try:
            while True:
                msg = await websocket.receive_text()
                if msg == "ping":
                    await websocket.send_text("pong")
        except WebSocketDisconnect:
            return

    async def pusher():
        try:
            while True:
                snaps = compute_all()
                await websocket.send_json({
                    "type": "snapshot",
                    "pairs": [_public_pair_dict(s) for s in snaps],
                    "server_time": datetime.now(timezone.utc).isoformat(),
                    "market_open": is_market_open(),
                })
                await asyncio.sleep(interval)
        except WebSocketDisconnect:
            return
        except Exception:
            return

    try:
        await asyncio.gather(receiver(), pusher())
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
