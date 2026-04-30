"""WebSocket endpoint for live spread updates.

Auth via JWT in query string: wss://host/ws/live?token=<jwt>
On connect, sends current snapshot. Then receives pushes from broadcaster
as ticks arrive. Client should also handle ping/pong (FastAPI handles it).
"""
import logging

import jwt
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from app.config import settings
from app.database import SessionLocal
from app.security import ALGORITHM
from app.services.broadcaster import broadcaster
from app.services.snapshot import build_live_payload

log = logging.getLogger("ws")
router = APIRouter()


def _verify(token: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.APP_SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except jwt.PyJWTError:
        return None


@router.websocket("/ws/live")
async def ws_live(websocket: WebSocket, token: str = Query(...)):
    user = _verify(token)
    if not user:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await broadcaster.connect(websocket)
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
