"""WebSocket broadcaster for live spread updates.

The Dhan feed thread calls `push_snapshot_async()` (via threadsafe wrapper)
after each tick batch. The broadcaster fans out the latest spread snapshot
to every connected browser WebSocket. Throttled to ~10 Hz to avoid flooding.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Set

from fastapi import WebSocket

log = logging.getLogger("broadcaster")

MAX_BROADCAST_HZ = 10  # cap pushes to ~10/sec even on busy markets
_min_interval = 1.0 / MAX_BROADCAST_HZ


class Broadcaster:
    def __init__(self) -> None:
        self._clients: Set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._last_push_ts: float = 0.0
        self._latest_payload: dict | None = None
        self._pending_task: asyncio.Task | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Called from main thread on startup so background threads can submit."""
        self._loop = loop

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)
        log.info("WS client connected (total=%d)", len(self._clients))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)
        log.info("WS client disconnected (total=%d)", len(self._clients))

    async def _broadcast_now(self, payload: dict) -> None:
        if not self._clients:
            return
        msg = json.dumps(payload, default=str)
        dead: list[WebSocket] = []
        async with self._lock:
            clients = list(self._clients)
        for ws in clients:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._clients.discard(ws)

    def push_threadsafe(self, payload: dict) -> None:
        """Called from the Dhan feed thread (sync). Schedules broadcast on the loop."""
        if not self._loop:
            return
        self._latest_payload = payload
        now = time.time()
        if now - self._last_push_ts < _min_interval:
            # Coalesce: keep latest, schedule one broadcast at end of window
            if self._pending_task is None or self._pending_task.done():
                delay = _min_interval - (now - self._last_push_ts)
                self._pending_task = asyncio.run_coroutine_threadsafe(
                    self._delayed_push(delay), self._loop
                )
            return
        self._last_push_ts = now
        asyncio.run_coroutine_threadsafe(self._broadcast_now(payload), self._loop)

    async def _delayed_push(self, delay: float) -> None:
        await asyncio.sleep(delay)
        if self._latest_payload is not None:
            self._last_push_ts = time.time()
            await self._broadcast_now(self._latest_payload)

    @property
    def client_count(self) -> int:
        return len(self._clients)


broadcaster = Broadcaster()
