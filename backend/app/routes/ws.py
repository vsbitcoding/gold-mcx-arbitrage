"""WebSocket endpoint for live spread updates.

Auth via JWT in query string: wss://host/ws/live?token=<jwt>
On connect, sends current snapshot. Then receives pushes from broadcaster
as ticks arrive. Client should also handle ping/pong (FastAPI handles it).
"""
import logging

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect, status

from app.database import SessionLocal
from app.security import authenticate, may_board
from app.services.broadcaster import broadcaster
from app.services.snapshot import build_live_payload

log = logging.getLogger("ws")
router = APIRouter()


def _verify(token: str):
    """The same session check as every REST call: a UUID-backed token whose
    login is still active and whose password has not been reset since."""
    try:
        return authenticate(token)
    except HTTPException:
        return None


@router.websocket("/ws/live")
async def ws_live(websocket: WebSocket, token: str = Query(...)):
    user = _verify(token)
    # The socket streams the whole arbitrage board - only a login that may
    # see one of the board pages (Cross / Calendar / Signals) gets it.
    if user and not may_board(user):
        user = None
    if not user:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # The broadcaster keeps the identity: a login disabled, renamed away, or
    # whose password was reset is dropped on the next push, not at the next
    # reconnect (review 18-Sep, finding 12).
    await broadcaster.connect(websocket, user)
    try:
        # Initial snapshot
        db = SessionLocal()
        try:
            await websocket.send_json({"type": "snapshot", "data": build_live_payload(db)})
        finally:
            db.close()

        # Keep connection alive — the broadcaster pushes from another task.
        # We just handle disconnects + occasional client pings.
        while True:
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.warning("WS error: %s", e)
    finally:
        await broadcaster.disconnect(websocket)
