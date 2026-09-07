"""Angel One SmartAPI WebSocket 2.0 live feed - the whole dashboard's ticks.

Behind the live_feed facade: state keys, status shape, resubscribe / expiry
hooks, the quote_store keyed by exchange token, the broadcast cadence. The
wire:

  * Angel caps a socket at 1000 tokens and a client at 3 sockets, so the
    ~1400 contracts are dealt across up to three connections, MCX first.
  * Prices arrive in paise (divided by 100 here); snap-quote mode (3) carries
    best-five depth, volume, OI and the previous close; the three spot
    indices are streamed in LTP mode (1), as Angel serves indices.
  * Each connection is supervised here, not by the SDK: a closed or silent
    socket is reopened with backoff, and a silent BOARD during market hours
    forces a full rebuild after 60 s (the old feed waited 180 s, which the
    client saw as "feed down" on 04-Sep).
  * Angel's session is a daily login (angel_feed keeps it on disk); every
    rebuild takes the current one, so the 08:40 contract roll also carries
    the day's fresh login.
"""
from __future__ import annotations

import base64
import json
import logging
import threading
import time
from datetime import datetime, timezone

from datetime import timedelta

from app.services import angel_feed, subscriptions
from app.services.broadcaster import broadcaster
from app.services.market_data import prev_close_store, quote_store
from app.services.snapshot import build_live_payload

log = logging.getLogger("angel_ws_feed")
IST = timezone(timedelta(hours=5, minutes=30))


def is_market_open() -> bool:
    """MCX hours, Mon-Fri 09:00-23:30 IST - the one clock every screen uses."""
    n = datetime.now(IST)
    if n.weekday() >= 5:
        return False
    open_t = n.replace(hour=9, minute=0, second=0, microsecond=0)
    close_t = n.replace(hour=23, minute=30, second=0, microsecond=0)
    return open_t <= n <= close_t


def _eval_and_broadcast() -> None:
    """Push the live board to every browser socket (watch-only, no trading)."""
    try:
        if broadcaster.client_count > 0:
            broadcaster.push_threadsafe({"type": "snapshot", "data": build_live_payload()})
    except Exception as e:  # noqa: BLE001
        log.exception("broadcast failed: %s", e)


def _run_simulated_thread() -> None:
    """No Angel credentials: jittered prices so the UI can be developed."""
    import random
    log.warning("SIMULATED feed (no Angel credentials).")
    subs, _n = subscriptions.build()
    _set_state(mode="simulated", instruments=subs)
    base_by_short = {"petal": 122.0, "guinea": 968.0, "ten": 1218.0, "mini": 12180.0}
    while True:
        for sid, info in subs.items():
            mid = base_by_short.get(info.get("short"), 100.0)
            j = random.uniform(-0.5, 0.5)
            quote_store.update(sid, bid=round(mid + j - 0.05, 2), ask=round(mid + j + 0.05, 2),
                               ltp=round(mid + j, 2), ts=time.time())
        _eval_and_broadcast()
        _set_state(last_tick_epoch=time.time())
        time.sleep(1.0)

MAX_TOKENS_PER_CONN = 1000
MAX_CONNS = 3
STALE_BOARD_SECONDS = 60        # no tick anywhere in market hours -> rebuild
STALE_CONN_SECONDS = 180        # one silent socket -> reopen just that one
REBUILD_GRACE_SECONDS = 120     # never two forced rebuilds closer than this
HEARTBEAT_SECONDS = 25          # Angel wants a text "ping" inside 30 s

_state: dict = {
    "mode": "starting",
    "client_id": "",
    "client_name": "",
    "token_expiry_epoch": 0.0,
    "last_tick_epoch": 0.0,
    "last_token_refresh_epoch": 0.0,
    "instruments": {},          # security_id -> meta
    "ws_connected": False,
    "reconnect_count": 0,
    "last_error": "",
    "connections": [],
}
_state_lock = threading.Lock()
_resub = threading.Event()
_resub_reason = [""]
_conns: list = []
_last_rebuild_epoch = [0.0]


def _set_state(**kw) -> None:
    with _state_lock:
        _state.update(kw)


def get_status() -> dict:
    with _state_lock:
        s = dict(_state)
    s["token_expires_in_seconds"] = max(0, int(s["token_expiry_epoch"] - time.time()))
    s["last_tick_age_seconds"] = int(time.time() - s["last_tick_epoch"]) if s["last_tick_epoch"] else None
    s["server_time"] = datetime.now(timezone.utc).isoformat()
    s["market_open"] = is_market_open()
    s["connections"] = [c.describe() for c in list(_conns)]
    return s


def has_expiring_today() -> bool:
    today = datetime.now().date().isoformat()
    try:
        subs = _state.get("instruments") or {}
        return any(str((m or {}).get("expiry") or "")[:10] == today for m in subs.values())
    except Exception:  # noqa: BLE001
        return False


def request_resubscribe(reason: str) -> str:
    """Rebuild the instrument list (contract rolls, a new paper symbol). The
    sockets are closed and reopened on the fresh list; ~5 s without ticks."""
    with _state_lock:
        cur = _state["mode"]
    if cur in ("reconnecting", "starting"):
        return f"skipped, feed is {cur}"
    _resub_reason[0] = reason
    _resub.set()
    log.info("Rebuilding subscriptions: %s", reason)
    return "resubscribing"


def _jwt_expiry(jwt: str) -> float:
    try:
        payload = jwt.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return float(json.loads(base64.urlsafe_b64decode(payload)).get("exp") or 0)
    except Exception:  # noqa: BLE001
        return 0.0


# --------------------------------------------------------------------------- #
# one socket
# --------------------------------------------------------------------------- #
class _Conn:
    def __init__(self, idx: int, groups: dict[int, list[str]], index_tokens: dict[int, list[str]],
                 auth: tuple[str, str, dict], subs: dict[str, dict]):
        self.idx = idx
        self.groups = groups                # exchangeType -> tokens (snap quote)
        self.index_tokens = index_tokens    # exchangeType -> index tokens (LTP)
        self.jwt, self.feed_token, self.creds = auth
        self.subs = subs
        self.ws = None
        self.thread = None
        self.connected = False
        self.opened_at = 0.0
        self.last_msg = 0.0
        self.msgs = 0
        self.stopping = False
        self.attempt = 0
        self.last_attempt = 0.0
        self.first_seen: set = set()

    @property
    def n_tokens(self) -> int:
        return sum(len(v) for v in self.groups.values()) + sum(len(v) for v in self.index_tokens.values())

    def describe(self) -> dict:
        return {"idx": self.idx, "tokens": self.n_tokens,
                "exchanges": sorted(set(self.groups) | set(self.index_tokens)),
                "connected": self.connected, "messages": self.msgs,
                "last_msg_age": round(time.time() - self.last_msg, 1) if self.last_msg else None}

    # ---- SDK callbacks -------------------------------------------------- #
    def _on_open(self, _wsapp) -> None:
        self.connected = True
        self.opened_at = time.time()
        self.last_msg = time.time()
        self.attempt = 0
        try:
            if self.groups:
                self.ws.subscribe(f"arbi-{self.idx}", 3,
                                  [{"exchangeType": ex, "tokens": toks} for ex, toks in self.groups.items()])
            if self.index_tokens:
                self.ws.subscribe(f"arbi-idx-{self.idx}", 1,
                                  [{"exchangeType": ex, "tokens": toks} for ex, toks in self.index_tokens.items()])
            log.info("socket %d open: %d tokens on %s", self.idx, self.n_tokens,
                     sorted(set(self.groups) | set(self.index_tokens)))
        except Exception as e:  # noqa: BLE001
            log.warning("socket %d subscribe failed: %s", self.idx, e)
            _set_state(last_error=f"subscribe: {e}"[:200])

    def _on_data(self, _wsapp, msg) -> None:
        self.msgs += 1
        now = time.time()
        self.last_msg = now
        try:
            tok = str(msg.get("token") or "")
            meta = self.subs.get(tok)
            if not meta:
                return
            ltp = float(msg.get("last_traded_price") or 0) / 100.0
            mode = msg.get("subscription_mode")
            bid = ask = ltp
            volume = oi = None
            if mode == 3:
                b = a = 0.0
                for lvl in (msg.get("best_5_buy_data") or []) + (msg.get("best_5_sell_data") or []):
                    try:
                        px = float(lvl.get("price") or 0) / 100.0
                    except (TypeError, ValueError):
                        continue
                    if px <= 0:
                        continue
                    if lvl.get("flag") == 1:
                        b = px if not b else max(b, px)      # best buy = highest
                    else:
                        a = px if not a else min(a, px)      # best sell = lowest
                # No depth = no buyer / no seller = dash (client rule, 31-Aug).
                # Angel keeps sending a dead far month's last trade from days
                # ago; falling back to it would resurrect exactly the ghosts
                # the rule removed. Same for the LTP itself: it counts only
                # once the contract has traded today.
                bid, ask = b, a
                volume = float(msg.get("volume_trade_for_the_day") or 0)
                oi = float(msg.get("open_interest") or 0)
                if volume <= 0:
                    ltp = 0.0
                pc = float(msg.get("closed_price") or 0) / 100.0
                if pc > 0:
                    prev_close_store[tok] = pc
            if tok not in self.first_seen:
                self.first_seen.add(tok)
                log.info("FIRST tick %s/%s: ltp=%s bid=%s ask=%s", meta.get("short", "?"), tok, ltp, bid, ask)
            # Every packet is the whole truth of the book right now - a side that
            # emptied is written as empty, never kept from an earlier packet.
            quote_store.update(tok, bid=bid, ask=ask, ltp=ltp, ts=now, volume=volume, oi=oi)
            _set_state(last_tick_epoch=now, ws_connected=True, mode="live")
            if now - _last_eval[0] > 0.5:
                _last_eval[0] = now
                _eval_and_broadcast()
        except Exception as e:  # noqa: BLE001 - one bad packet must not kill the socket
            log.debug("tick parse failed: %s", e)

    def _on_error(self, _wsapp, err) -> None:
        log.warning("socket %d error: %s", self.idx, str(err)[:160])
        _set_state(last_error=str(err)[:200])

    def _on_close(self, _wsapp, *_a) -> None:
        if self.connected:
            log.info("socket %d closed after %.0fs, %d messages", self.idx,
                     time.time() - self.opened_at, self.msgs)
        self.connected = False

    # ---- lifecycle ------------------------------------------------------ #
    def start(self) -> None:
        from SmartApi.smartWebSocketV2 import SmartWebSocketV2
        self.stopping = False
        ws = SmartWebSocketV2(self.jwt, self.creds["ANGEL_API_KEY"], self.creds["ANGEL_CLIENT_CODE"],
                              self.feed_token, max_retry_attempt=0)
        ws.on_open, ws.on_data, ws.on_error, ws.on_close = (
            self._on_open, self._on_data, self._on_error, self._on_close)
        # websocket-client hands close three arguments; the SDK's own handler
        # takes one and raises inside the callback (logged as an ERROR every
        # close). Ours accepts any, so it goes straight on the socket.
        ws._on_close = self._on_close
        self.ws = ws
        self.attempt += 1
        self.last_attempt = time.time()

        def _run():
            try:
                ws.connect()
            except Exception as e:  # noqa: BLE001
                log.warning("socket %d connect raised: %s", self.idx, str(e)[:160])
            finally:
                self.connected = False
        self.thread = threading.Thread(target=_run, daemon=True, name=f"angel-ws-{self.idx}")
        self.thread.start()

    def heartbeat(self) -> None:
        try:
            if self.connected and self.ws and self.ws.wsapp:
                self.ws.wsapp.send("ping")
        except Exception:  # noqa: BLE001
            pass

    def close(self, timeout: float = 10.0) -> None:
        self.stopping = True
        ws = self.ws
        if not ws:
            return

        def _closer():
            try:
                ws.close_connection()
            except Exception as e:  # noqa: BLE001
                log.debug("socket %d close: %s", self.idx, e)
        t = threading.Thread(target=_closer, daemon=True, name=f"angel-close-{self.idx}")
        t.start()
        t.join(timeout)
        self.connected = False


_last_eval = [0.0]


# --------------------------------------------------------------------------- #
# dealing tokens across sockets
# --------------------------------------------------------------------------- #
def _plan(subs: dict[str, dict]) -> list[tuple[dict[int, list[str]], dict[int, list[str]]]]:
    """Up to three (groups, index_tokens) plans of <= 1000 tokens each."""
    from app.services.angel_master import WS_EXCHANGE_TYPE
    by_ex: dict[int, list[str]] = {}
    idx_by_ex: dict[int, list[str]] = {}
    for sid, meta in subs.items():
        ex = WS_EXCHANGE_TYPE.get(subscriptions.exchange_of(sid, meta), 5)
        (idx_by_ex if meta.get("kind") == "index" else by_ex).setdefault(ex, []).append(str(sid))
    # MCX first so the board's socket is the first to open, then the rest
    order = sorted(by_ex, key=lambda e: (0 if e == 5 else 1, -len(by_ex[e])))
    plans: list = []
    cur_groups: dict[int, list[str]] = {}
    cur_n = 0
    for ex in order:
        for tok in by_ex[ex]:
            if cur_n >= MAX_TOKENS_PER_CONN:
                plans.append((cur_groups, {}))
                cur_groups, cur_n = {}, 0
            cur_groups.setdefault(ex, []).append(tok)
            cur_n += 1
    if cur_groups:
        plans.append((cur_groups, {}))
    # the handful of index tokens ride the last socket
    if idx_by_ex:
        if plans and sum(len(v) for v in plans[-1][0].values()) + sum(len(v) for v in idx_by_ex.values()) <= MAX_TOKENS_PER_CONN:
            plans[-1] = (plans[-1][0], idx_by_ex)
        else:
            plans.append(({}, idx_by_ex))
    if len(plans) > MAX_CONNS:
        dropped = sum(sum(len(v) for v in g.values()) for g, _i in plans[MAX_CONNS:])
        log.error("Angel allows %d sockets; %d tokens beyond that are NOT subscribed", MAX_CONNS, dropped)
        plans = plans[:MAX_CONNS]
    return plans


def _close_all() -> None:
    global _conns
    for c in list(_conns):
        c.close()
    _conns = []
    _set_state(ws_connected=False)


# --------------------------------------------------------------------------- #
# the feed loop
# --------------------------------------------------------------------------- #
def _run_feed_thread() -> None:
    global _conns
    backoff = 5
    while True:
        try:
            _set_state(mode="reconnecting", ws_connected=False)
            jwt, feed_token, creds = angel_feed.get_session()
            _set_state(client_id=creds.get("ANGEL_CLIENT_CODE", ""), client_name="Angel One",
                       token_expiry_epoch=_jwt_expiry(jwt), last_token_refresh_epoch=time.time())
            subs, n_pairs = subscriptions.build()
            _set_state(instruments=subs)
            plans = _plan(subs)
            log.info("Subscribing to %d unique contracts for %d pairs across %d Angel socket(s): %s",
                     len(subs), n_pairs, len(plans),
                     [sum(len(v) for v in g.values()) + sum(len(v) for v in i.values()) for g, i in plans])
            _conns = [_Conn(i, g, idx, (jwt, feed_token, creds), subs) for i, (g, idx) in enumerate(plans)]
            for c in _conns:
                c.start()
                time.sleep(1.0)
            _resub.clear()
            _last_rebuild_epoch[0] = time.time()
            backoff = 5
            # supervise until something asks for a rebuild
            last_beat = time.time()
            while not _resub.is_set():
                time.sleep(1.0)
                now = time.time()
                if now - last_beat >= HEARTBEAT_SECONDS:
                    last_beat = now
                    for c in _conns:
                        c.heartbeat()
                any_up = False
                for c in _conns:
                    alive = c.thread is not None and c.thread.is_alive() and c.connected
                    if alive:
                        any_up = True
                        if is_market_open() and c.last_msg and now - c.last_msg > STALE_CONN_SECONDS:
                            log.warning("socket %d silent for %.0fs - reopening it", c.idx, now - c.last_msg)
                            c.close()
                            c.start()
                    elif not c.stopping and (c.thread is None or not c.thread.is_alive()):
                        # Backoff from the last ATTEMPT, doubling to a minute.
                        # Angel answers a fourth socket with 429 "Connection
                        # Limit Exceeded"; retrying that every second would only
                        # earn a ban, so a socket that never opened waits too.
                        wait = min(5 * (2 ** max(0, c.attempt - 1)), 60)
                        if now - c.last_attempt >= wait:
                            log.warning("socket %d down - reconnecting (attempt %d, next wait %ds)",
                                        c.idx, c.attempt + 1, min(wait * 2, 60))
                            with _state_lock:
                                _state["reconnect_count"] += 1
                            c.start()
                if not any_up:
                    _set_state(ws_connected=False)
                    if _state["mode"] == "live":
                        _set_state(mode="reconnecting")
            reason = _resub_reason[0] or "rebuild"
            log.info("Closing %d socket(s) to rebuild: %s", len(_conns), reason)
            _close_all()
            time.sleep(1.0)
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            log.exception("Angel feed loop error: %s - retrying in %ds", msg[:160], backoff)
            _set_state(last_error=msg[:200])
            _close_all()
            if "session" in msg.lower() or "token" in msg.lower() or "login" in msg.lower():
                try:
                    angel_feed.get_session(force=True)
                except Exception as e2:  # noqa: BLE001
                    log.warning("Angel re-login failed: %s", e2)
            time.sleep(backoff)
            backoff = min(backoff * 2, 120)


def _watchdog() -> None:
    log.info("Angel watchdog started.")
    while True:
        time.sleep(15)
        try:
            with _state_lock:
                mode, last_tick = _state["mode"], _state["last_tick_epoch"]
            if mode == "live" and is_market_open() and last_tick:
                age = time.time() - last_tick
                if age > STALE_BOARD_SECONDS and time.time() - _last_rebuild_epoch[0] > REBUILD_GRACE_SECONDS:
                    log.warning("Watchdog: no tick for %.0fs during market hours - rebuilding feed", age)
                    _set_state(mode="stale")
                    request_resubscribe_force(f"no tick for {int(age)}s")
        except Exception as e:  # noqa: BLE001
            log.exception("Angel watchdog iteration failed: %s", e)


def request_resubscribe_force(reason: str) -> None:
    _resub_reason[0] = reason
    _resub.set()


def start_feed_in_background(loop):
    try:
        c = angel_feed._creds()
        creds_ok = bool(c.get("ANGEL_API_KEY") and c.get("ANGEL_CLIENT_CODE")
                        and c.get("ANGEL_MPIN") and c.get("ANGEL_TOTP_SECRET"))
    except Exception:  # noqa: BLE001
        creds_ok = False
    target = _run_feed_thread if creds_ok else _run_simulated_thread
    t = threading.Thread(target=target, daemon=True, name="angel-feed")
    t.start()
    if creds_ok:
        threading.Thread(target=_watchdog, daemon=True, name="angel-watchdog").start()
    else:
        log.warning("Angel credentials missing - SIMULATED feed.")
    return t
