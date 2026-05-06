"""Public read-only API for the spread-monitoring app.

Auth: API key via `X-API-Key` header OR `?api_key=` query param.
Versioned at /api/v1/* — read-only, mobile-friendly, lean.
No write endpoints. No internal fields exposed.
"""
import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect, status

from app.security import require_api_key, verify_api_key_value
from app.services.dhan_feed import is_market_open
from app.services.spread_engine import compute_all

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


@router.websocket("/stream")
async def public_stream(
    websocket: WebSocket,
    api_key: str | None = Query(None, alias="api_key"),
    key: str | None = Query(None),                  # legacy alias
    interval: float = Query(1.0, ge=0.5, le=5.0),
    type: str | None = Query(None),
):
    """Live spread stream.

    Connect: wss://host/api/v1/stream?api_key=<KEY>&interval=1
    Pushes the same shape as `/spread-groups` every `interval` seconds.
    Client may send "ping" → server replies "pong".
    """
    token = api_key or key
    if not verify_api_key_value(token):
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
                all_snaps = compute_all()
                cross_count = sum(1 for s in all_snaps if s["type"] == "cross")
                calendar_count = sum(1 for s in all_snaps if s["type"] == "calendar")
                snaps = _filter(all_snaps, type)
                await websocket.send_json({
                    "type": "snapshot",
                    "server_time": datetime.now(timezone.utc).isoformat(),
                    "market_open": is_market_open(),
                    "tabs": {"cross": cross_count, "calendar": calendar_count},
                    "groups": _grouped(snaps),
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
