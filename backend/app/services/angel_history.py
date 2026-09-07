"""Hourly candles from Angel One, for the signals engine.

The 4H %-spread model was built on Dhan's 60-minute candles. Angel serves the
same bars (checked 07-Sep-2026: 320 days of ONE_HOUR for GOLDPETAL in one
call, 3,200 rows, 0.1 s) with the SAME closes, so the model, its backtest and
its rolling band come out identical. Angel allows a few calls a second on
this endpoint; one every 0.4 s is well inside that and the daily model needs
about twenty.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta

import requests

from app.services import angel_feed

log = logging.getLogger("angel_history")

_URL = "https://apiconnect.angelone.in/rest/secure/angelbroking/historical/v1/getCandleData"
_MAX_DAYS = {"ONE_HOUR": 400, "ONE_DAY": 2000, "ONE_MINUTE": 30, "FIVE_MINUTE": 100}
_lock = threading.Lock()
_last_call = [0.0]


def _pace(gap: float = 1.0) -> None:
    with _lock:
        wait = _last_call[0] + gap - time.time()
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.time()


def candles(token: str, days: int, interval: str = "ONE_HOUR", exchange: str = "MCX") -> list:
    """[[iso_ts, o, h, l, c, v], ...] oldest first, chunked to Angel's window."""
    out: list = []
    to = datetime.now()
    cur = to - timedelta(days=days)
    chunk = _MAX_DAYS.get(interval, 100) - 1
    jwt, _feed, creds = angel_feed.get_session()
    sess = requests.Session()
    while cur < to:
        end = min(cur + timedelta(days=chunk), to)
        got = None
        for attempt in range(4):
            _pace()
            try:
                r = sess.post(_URL, headers=angel_feed._headers(creds, jwt), json={
                    "exchange": exchange, "symboltoken": str(token), "interval": interval,
                    "fromdate": cur.strftime("%Y-%m-%d %H:%M"), "todate": end.strftime("%Y-%m-%d %H:%M")},
                    timeout=45)
                # The NSE poll shares this client's rate budget; a burst answers
                # 403 "exceeding access rate" as plain text. Back off and retry.
                if r.status_code == 403 or "rate" in r.text[:120].lower():
                    time.sleep(1.5 * (attempt + 1))
                    continue
                d = r.json()
                if r.status_code == 401 or (not d.get("status") and angel_feed._is_auth_error(d)):
                    jwt, _feed, creds = angel_feed.get_session(force=True)
                    continue
                if not d.get("status"):
                    log.warning("candles %s %s..%s: %s", token, cur.date(), end.date(), d.get("message"))
                got = d.get("data") or [] if d.get("status") else []
                break
            except Exception as e:  # noqa: BLE001
                log.warning("candles %s %s..%s attempt %d failed: %s", token, cur.date(), end.date(), attempt + 1, e)
                time.sleep(1.0)
        if got is None:
            log.warning("candles %s %s..%s: gave up after retries", token, cur.date(), end.date())
        else:
            out.extend(got)
        cur = end + timedelta(minutes=1)
    return out


def intraday_60(token: str, days: int) -> dict[int, float]:
    """epoch -> hourly close, the shape research_backtest._bars_4h consumes."""
    out: dict[int, float] = {}
    for row in candles(token, days, "ONE_HOUR"):
        try:
            ts = int(datetime.fromisoformat(row[0]).timestamp())
            close = float(row[4])
            if close:
                out[ts] = close
        except (TypeError, ValueError, IndexError):
            continue
    return out
