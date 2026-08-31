"""Dhan WebSocket live feed for ALL active MCX gold contracts (~24 instruments).

Auto-flow:
  1. Generate access_token via TOTP+MPIN (services.dhan_auth)
  2. Refresh pair_registry → resolves all active contracts and builds 56 pairs
  3. Subscribe to all unique security_ids in Full mode
  4. quote_store keyed by security_id → spread engine pulls per-pair
  5. Watchdog handles token refresh, silent-feed reconnect, daily refresh
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.config import settings
from app.database import SessionLocal
from app.services import dhan_auth, pair_registry
from app.services.broadcaster import broadcaster
from app.services.market_data import prev_close_store, quote_store
from app.services.snapshot import build_live_payload

log = logging.getLogger("dhan_feed")
IST = timezone(timedelta(hours=5, minutes=30))


def _ist_now() -> datetime:
    return datetime.now(IST)


def is_market_open() -> bool:
    n = _ist_now()
    if n.weekday() >= 5:
        return False
    open_t = n.replace(hour=9, minute=0, second=0, microsecond=0)
    close_t = n.replace(hour=23, minute=30, second=0, microsecond=0)
    return open_t <= n <= close_t


_state: dict = {
    "mode": "starting",
    "client_id": "",
    "client_name": "",
    "token_expiry_epoch": 0.0,
    "last_tick_epoch": 0.0,
    "last_token_refresh_epoch": 0.0,
    "instruments": {},  # security_id -> {short, trading_symbol, expiry}
    "ws_connected": False,
    "reconnect_count": 0,
    "last_error": "",
}
_state_lock = threading.Lock()
_active_feed = None


_live_token = {"value": ""}  # module-private; NEVER exposed via _state / get_status()


def get_live_token() -> str:
    """Current in-process Dhan access token ('' until the feed authenticates)."""
    return _live_token["value"]


def get_status() -> dict:
    with _state_lock:
        s = dict(_state)
    s["token_expires_in_seconds"] = max(0, int(s["token_expiry_epoch"] - time.time()))
    s["last_tick_age_seconds"] = (
        int(time.time() - s["last_tick_epoch"]) if s["last_tick_epoch"] else None
    )
    s["server_time"] = datetime.now(timezone.utc).isoformat()
    s["market_open"] = is_market_open()
    return s


def _set_state(**kwargs) -> None:
    with _state_lock:
        _state.update(kwargs)


def _eval_and_broadcast() -> None:
    # Watch-only: no trade evaluation — just broadcast the live spread snapshot.
    try:
        if broadcaster.client_count > 0:
            payload = build_live_payload()
            broadcaster.push_threadsafe({"type": "snapshot", "data": payload})
    except Exception as e:
        log.exception("broadcast failed: %s", e)


_last_reconnect_epoch: float = 0.0
RECONNECT_GRACE_SECONDS = 300


def _safe_close_active(timeout: float = 15.0) -> None:
    """close_connection() on a disposable thread. The SDK's close can hang
    forever on a half-dead socket — exactly that froze the watchdog thread
    from 16-Jul 09:17 until the 21-Jul restart, so no caller may ever invoke
    it directly."""
    feed = _active_feed
    if not feed:
        return

    def _closer() -> None:
        try:
            feed.close_connection()
        except Exception as e:  # noqa: BLE001
            log.warning("close_connection() failed: %s", e)

    t = threading.Thread(target=_closer, daemon=True, name="dhan-close")
    t.start()
    t.join(timeout)
    if t.is_alive():
        log.warning("close_connection() still hung after %.0fs — abandoning it.", timeout)


def _trigger_reconnect(reason: str) -> None:
    global _active_feed, _last_reconnect_epoch
    if time.time() - _last_reconnect_epoch < RECONNECT_GRACE_SECONDS:
        return
    # Don't double-tap: if the feed loop is already reconnecting (or rate-limited)
    # let it finish its cool-down. Watchdog jumping in here on top of an ongoing
    # SDK retry was the root cause of the 2026-05-29 Dhan 429 cascade.
    with _state_lock:
        cur_mode = _state["mode"]
    if cur_mode in ("reconnecting", "starting"):
        log.info("Skip watchdog reconnect (%s) — feed is already in %s mode.", reason, cur_mode)
        return
    _last_reconnect_epoch = time.time()
    log.warning("Watchdog forcing reconnect: %s", reason)
    dhan_auth.invalidate()
    _safe_close_active()


def has_expiring_today() -> bool:
    """True when any subscribed contract's expiry date is today - the day the
    23:00 expiry-roll in maintenance must fire (client rule, 31-Aug)."""
    today = datetime.now().date().isoformat()
    try:
        subs = _state.get("instruments") or {}
        return any(str((m or {}).get("expiry") or "")[:10] == today
                   for m in subs.values())
    except Exception:  # noqa: BLE001 - a state hiccup must not break the loop
        return False


def request_resubscribe(reason: str) -> str:
    """Rebuild the instrument list without touching the token.

    Contracts roll. An option expires, a future moves to the next month, and
    every security id resolved at the last connect is then pointing at
    something that no longer trades. The list is only ever built when the
    socket connects, so with a feed that stays up the app keeps serving
    yesterday's contract: on 18-Aug the Commodity Options tab showed the
    expired 17-Aug crude chain all night and only corrected at 09:17, when the
    feed happened to reconnect on its own. That was luck, not design.

    Deliberately NOT `_trigger_reconnect`: that invalidates the Dhan token,
    which is the right move for a dead feed and the wrong one here. The token
    is healthy - it is the instrument list that is stale - and minting a new
    one would kill the session this very feed is using.
    """
    with _state_lock:
        cur_mode = _state["mode"]
    if cur_mode in ("reconnecting", "starting"):
        return f"skipped, feed is {cur_mode}"
    log.info("Rebuilding subscriptions: %s", reason)
    _safe_close_active()          # the loop re-enters and re-resolves everything
    return "resubscribing"


def _watchdog() -> None:
    log.info("Watchdog thread started.")
    last_postmarket_open = None
    while True:
        time.sleep(60)
        # The whole iteration is armored: one unexpected exception must never
        # kill this thread (a dead watchdog = no token pre-refresh and no
        # silent-feed recovery until the next service restart).
        try:
            with _state_lock:
                expiry = _state["token_expiry_epoch"]
                mode = _state["mode"]
                last_tick = _state["last_tick_epoch"]

            if expiry and (expiry - time.time()) < 30 * 60:
                _trigger_reconnect("token expiring")
                continue
            if mode == "live" and is_market_open() and last_tick:
                age = time.time() - last_tick
                if age > 180:
                    _trigger_reconnect(f"no tick for {int(age)}s during market hours")
                    continue
            ist = _ist_now()
            today = ist.date()
            # Post-open fresh subscription — delayed to 09:17-09:25 IST.
            # Was 09:01-09:05 but Dhan's WS is at its worst exactly at market open;
            # waiting 15 minutes lets their side stabilise and avoids the 429 storm.
            if (
                ist.weekday() < 5
                and ist.hour == 9
                and 17 <= ist.minute <= 25
                and last_postmarket_open != today
            ):
                _trigger_reconnect("post-open fresh subscription")
                last_postmarket_open = today
        except Exception as e:  # noqa: BLE001
            log.exception("Watchdog iteration failed: %s — continuing.", e)


def _run_real_feed_thread() -> None:
    global _active_feed
    from dhanhq import marketfeed
    from dhanhq.dhan_context import DhanContext

    backoff = 5
    while True:
        try:
            _set_state(mode="reconnecting", ws_connected=False)
            token = dhan_auth.get_token(
                settings.DHAN_CLIENT_ID,
                settings.DHAN_MPIN,
                settings.DHAN_TOTP_SECRET,
            )
            _set_state(
                client_id=token.client_id,
                client_name=token.client_name,
                token_expiry_epoch=token.expiry_epoch,
                last_token_refresh_epoch=time.time(),
            )
            # Keep the raw token in a PRIVATE holder (never in _state — get_status()
            # dumps _state to the API). Lets in-process helpers (e.g. the one-time
            # spread backfill) call Dhan REST with the live token instead of
            # minting a new one (which would kill this feed).
            _live_token["value"] = token.access_token
            log.info(
                "Token OK: %s, expires %s (in %.1f hours)",
                token.client_name,
                datetime.fromtimestamp(token.expiry_epoch).strftime("%Y-%m-%d %H:%M"),
                token.expires_in() / 3600,
            )

            # Refresh pair registry → build all 56 pairs and gather subscription list
            n = pair_registry.refresh(min_days_ahead=1, max_per_instrument=6)
            if n == 0:
                raise RuntimeError("Pair registry empty — no active MCX gold contracts resolved.")

            subs = pair_registry.get_subscriptions()

            # Resolve + add extra calculator instruments (GOLDBEES + Full Gold).
            # Side-channel feed; lives in the same quote_store keyed by security_id.
            from app.services import extra_instruments, options_service
            extra_instruments.refresh()
            extra_tuples, extra_meta = extra_instruments.get_extra_subscriptions()
            for sid, m in extra_meta.items():
                subs[sid] = m

            # Resolve + add Nifty/Sensex weekly PE options (spot indices + 3 weeks × 21 strikes × 2 indices).
            try:
                options_service.refresh()
            except Exception as e:
                log.warning("options_service.refresh() failed: %s", e)
            options_tuples, options_meta = options_service.get_extra_subscriptions()
            for sid, m in options_meta.items():
                subs[sid] = m

            # Resolve + add base-metal calendar legs (Copper/Aluminium/Zinc/Nickel/Lead +
            # minis) — watch-only 'Metal' tab. These are MCX FUTCOM, so they flow through
            # the default MCX-Full path below (NOT added to non_mcx_meta).
            from app.services import (goldopt_service, mcx_opt_stream, metals_service,
                                      othercomm_service, price_service)
            try:
                metals_service.refresh()
            except Exception as e:
                log.warning("metals_service.refresh() failed: %s", e)
            for sid, m in metals_service.get_subscription_meta().items():
                subs[sid] = m

            # Other-commodity calendar legs (Crude/NatGas/Electricity) — watch-only
            # 'Other Commodity' tab. MCX FUTCOM → default MCX-Full path.
            try:
                othercomm_service.refresh()
            except Exception as e:
                log.warning("othercomm_service.refresh() failed: %s", e)
            for sid, m in othercomm_service.get_subscription_meta().items():
                subs[sid] = m

            # GOLD ↔ GOLD MINI option spreads (watch-only 'Gold Options' tab).
            # MCX OPTFUT → flows through the default MCX-Full path below.
            try:
                goldopt_service.refresh()
            except Exception as e:
                log.warning("goldopt_service.refresh() failed: %s", e)
            for sid, m in goldopt_service.get_subscription_meta().items():
                subs[sid] = m

            # NSE-vs-MCX comparison strikes. That screen compares bid against bid
            # and never touches IV, so it has no business waiting on the REST
            # option chain's one-call-per-3s. MCX OPTFUT → default MCX-Full path.
            try:
                mcx_opt_stream.refresh()
            except Exception as e:
                log.warning("mcx_opt_stream.refresh() failed: %s", e)
            for sid, m in mcx_opt_stream.get_subscription_meta().items():
                subs[sid] = m

            # Webhook paper-trade symbols (Auto Trades page). Dynamic: whatever
            # the client's webhooks have named, plus the pre-seeded bullion set.
            # MCX FUTCOM → the default MCX-Full path below, ticks land in
            # quote_store like everything else.
            try:
                from app.services import paper_trades
                paper_trades.refresh()
                for sid, m in paper_trades.get_subscription_meta().items():
                    subs.setdefault(sid, m)
            except Exception as e:
                log.warning("paper_trades.refresh() failed: %s", e)

            # 'Price' tab — gold/silver active contracts (already subscribed by the
            # pair feed, so just resolve them; no extra subscription needed).
            try:
                price_service.refresh()
            except Exception as e:
                log.warning("price_service.refresh() failed: %s", e)

            _set_state(instruments=subs)

            # Build instrument tuples: (exchange, security_id, request_code).
            # Default MCX for pair-registry contracts; extras + options bring their own exchange.
            non_mcx_meta = {**extra_meta, **options_meta}
            instruments = [
                (marketfeed.MarketFeed.MCX, str(sid), marketfeed.MarketFeed.Full)
                for sid in subs.keys() if sid not in non_mcx_meta
            ]
            instruments.extend(extra_tuples)
            instruments.extend(options_tuples)
            log.info(
                "Subscribing to %d unique contracts for %d pairs (+%d calculator +%d options/indices)",
                len(instruments), n, len(extra_tuples), len(options_tuples),
            )

            ctx = DhanContext(settings.DHAN_CLIENT_ID, token.access_token)
            last_eval = [0.0]
            tick_counts: dict[str, int] = {}

            def on_message(_instance, data):
                if not isinstance(data, dict):
                    return
                t = data.get("type")
                sec_id = str(data.get("security_id", ""))
                if not sec_id or sec_id not in subs:
                    return

                key = f"{sec_id}:{t}"
                tick_counts[key] = tick_counts.get(key, 0) + 1
                if tick_counts[key] == 1:
                    short = subs[sec_id].get("short", "?")
                    log.info("FIRST tick %s/%s: ltp=%s depth=%s",
                             short, key, data.get("LTP"), bool(data.get("depth")))

                # One-shot "Previous Close" packet (sent per instrument at
                # subscribe) → keep for day-change / index-divergence display.
                if t == "Previous Close":
                    try:
                        pc = float(data.get("prev_close") or 0)
                        if pc > 0:
                            prev_close_store[sec_id] = pc
                    except (TypeError, ValueError):
                        pass
                    return

                try:
                    ltp = float(data.get("LTP") or 0)
                except (TypeError, ValueError):
                    ltp = 0.0
                bid = ask = ltp
                if t in ("Full Data", "Market Depth"):
                    depth = data.get("depth") or []
                    if depth:
                        d0 = depth[0]
                        try:
                            b = float(d0.get("bid_price") or 0)
                            a = float(d0.get("ask_price") or 0)
                            bid = b if b > 0 else ltp
                            ask = a if a > 0 else ltp
                        except (TypeError, ValueError):
                            pass

                existing = quote_store.get(sec_id)
                bid = bid or existing.bid
                ask = ask or existing.ask
                ltp = ltp or existing.ltp
                if bid or ask or ltp:
                    quote_store.update(sec_id, bid=bid, ask=ask, ltp=ltp, ts=time.time())
                _set_state(last_tick_epoch=time.time(), ws_connected=True, mode="live")

                now = time.time()
                if now - last_eval[0] > 0.5:
                    _eval_and_broadcast()
                    last_eval[0] = now

            # Track error type so we can break out on Dhan rate-limit (429).
            rate_limited_flag = {"hit": False}
            err_window = {"count": 0, "since": time.time()}

            def _force_close():
                """Force close the SDK so feed.run() exits — without this the
                SDK retries internally every ~2s forever, extending Dhan's ban.
                Uses the hang-proof helper: a close that blocks must not freeze
                the SDK callback thread."""
                _safe_close_active()

            def on_error(_instance, err):
                msg = str(err)
                log.warning("MarketFeed error: %s", msg)
                _set_state(last_error=msg[:200])
                # Dhan rate-limits aggressive reconnects (HTTP 429).
                if "429" in msg or "rate" in msg.lower():
                    if not rate_limited_flag["hit"]:
                        rate_limited_flag["hit"] = True
                        log.warning("Dhan 429 detected — force-closing SDK to exit feed.run()")
                        _force_close()
                    return
                # Pre-emptive: if non-429 errors flood (e.g. "no close frame"
                # repeated every 2s), treat as effective rate-limit and back off
                # BEFORE Dhan actually 429s us. >= 5 errors in 30s → trip flag.
                now = time.time()
                if now - err_window["since"] > 30:
                    err_window["since"] = now
                    err_window["count"] = 0
                err_window["count"] += 1
                if err_window["count"] >= 5 and not rate_limited_flag["hit"]:
                    log.warning("MarketFeed error flood (%d in <30s) — treating as rate-limit.",
                                err_window["count"])
                    rate_limited_flag["hit"] = True
                    _force_close()

            def on_close(_instance):
                log.info("MarketFeed connection closed.")
                _set_state(ws_connected=False)

            feed = marketfeed.MarketFeed(
                ctx, instruments, version="v2",
                on_message=on_message, on_error=on_error, on_close=on_close,
            )
            _active_feed = feed
            _set_state(last_tick_epoch=time.time())
            log.info("Starting MarketFeed.run() — real ticks incoming.")
            feed.run()
            log.info("MarketFeed.run() exited normally.")
            # If we exited because of rate-limit, use long cool-down (5 min).
            # Otherwise reset to fast backoff for benign disconnects.
            if rate_limited_flag["hit"]:
                # An EXPIRED token produces the same error flood as a genuine
                # rate-limit (handshake rejected every ~2s). Cooling down 900s
                # for that ate the 09:00 market open on 20/21-Jul — instead,
                # re-auth immediately and only cool down on a real 429.
                rem = dhan_auth.current_expires_in()
                if rem is None or rem < dhan_auth.REFRESH_BEFORE_EXPIRY_SECONDS:
                    log.warning(
                        "Error flood but token is expired/expiring (%s) — "
                        "re-authing now instead of cooling down.",
                        "no token" if rem is None else f"{rem / 60:.0f} min left")
                    dhan_auth.invalidate(disk=True)
                    backoff = 5
                else:
                    cool = 900
                    log.warning("Rate-limited by Dhan — cooling down for %ds before reconnect.", cool)
                    _set_state(last_error=f"Dhan rate-limited; cooling down {cool}s")
                    time.sleep(cool)
                    backoff = 5
            else:
                backoff = 5
        except Exception as e:
            err_str = str(e)
            # Dhan rate-limit: cool down 5 min instead of fast retry
            if "429" in err_str or "rate" in err_str.lower():
                rem = dhan_auth.current_expires_in()
                if rem is None or rem < dhan_auth.REFRESH_BEFORE_EXPIRY_SECONDS:
                    log.warning("Rate-limit-looking error with expired/expiring token — re-authing now: %s",
                                err_str[:120])
                    dhan_auth.invalidate(disk=True)
                    time.sleep(5)
                else:
                    cool = 900
                    log.warning("Feed loop hit rate-limit — cooling down for %ds: %s", cool, err_str[:120])
                    _set_state(last_error=f"Dhan rate-limited; cooling down {cool}s")
                    time.sleep(cool)
                backoff = 5
            else:
                log.exception("Feed loop error: %s — retrying in %ds", e, backoff)
                _set_state(last_error=err_str[:200])
                # Auth-invalid (revoked/expired token) → also drop the DISK cache
                # so the retry mints fresh. Benign errors keep the disk token —
                # the retry reuses it (no new login → no 2-min limit, no cooldown).
                auth_bad = any(k in err_str.lower() for k in
                               ("invalid", "unauthor", "401", "dh-901", "authentication"))
                dhan_auth.invalidate(disk=auth_bad)
                time.sleep(backoff)
                backoff = min(backoff * 2, 120)
        finally:
            _active_feed = None
            with _state_lock:
                _state["reconnect_count"] += 1
                _state["ws_connected"] = False


def _run_simulated_thread() -> None:
    import random
    log.warning("SIMULATED feed (no Dhan credentials).")
    pair_registry.refresh(min_days_ahead=1, max_per_instrument=6)
    subs = pair_registry.get_subscriptions()
    _set_state(mode="simulated", instruments=subs)
    base_by_short = {"petal": 122.0, "guinea": 968.0, "ten": 1218.0, "mini": 12180.0}
    while True:
        for sid, info in subs.items():
            mid = base_by_short.get(info["short"], 100.0)
            jitter = random.uniform(-0.5, 0.5)
            quote_store.update(
                sid,
                bid=round(mid + jitter - 0.05, 2),
                ask=round(mid + jitter + 0.05, 2),
                ltp=round(mid + jitter, 2),
                ts=time.time(),
            )
        _eval_and_broadcast()
        _set_state(last_tick_epoch=time.time())
        time.sleep(1.0)


def start_feed_in_background(loop: asyncio.AbstractEventLoop):
    creds_ok = bool(settings.DHAN_CLIENT_ID and settings.DHAN_MPIN and settings.DHAN_TOTP_SECRET)
    target = _run_real_feed_thread if creds_ok else _run_simulated_thread
    feed_thread = threading.Thread(target=target, daemon=True, name="dhan-feed")
    feed_thread.start()
    if creds_ok:
        watch_thread = threading.Thread(target=_watchdog, daemon=True, name="dhan-watchdog")
        watch_thread.start()
    return feed_thread
