"""Webhook-driven DUMMY trades, monitored against the live MCX feed (client, 20-Aug).

The client's TradingView strategy fires a webhook - buy or sell, a symbol, lots,
a timeframe and whatever price his alert happened to carry. This turns each one
into a paper trade for monitoring only. **No real order is ever placed.**

The rules, exactly as agreed:

* One position per SYMBOL + TIMEFRAME pair, each pair its own ledger (client,
  21-Aug: his 5m and 15m strategies run side by side). GOLDM-5m long and
  GOLDM-15m short at the same time is normal; a second GOLDM-5m buy is a
  duplicate and is ignored, logged with the reason. No timeframe in the alert
  is its own bucket, so mixed setups still work.
* Signals FLIP: buy closes a short and opens a long in the same breath; sell
  does the reverse. First signal of either side opens from flat.
* Entry and exit are the exchange LTP **at the moment the webhook arrived**,
  read from the socket's in-memory store - never fetched. (`temp_price` was
  briefly stored for comparison and retired on 20-Aug; alerts still sending it
  are not errors, the field is simply ignored.)
* Symbols are DYNAMIC. Nothing is hard-coded: the first webhook naming a symbol
  resolves it against the Dhan scrip master (active front month + lot units)
  and puts it on the live feed. Gold and silver are pre-seeded so their first
  signal is instant. An unknown name rejects with "symbol not found", logged.

Load: everything the webhook path touches is memory plus two or three small
inserts on the WAL database - a few milliseconds, so the response is instant.
The only slow work, resolving a brand-new symbol and re-subscribing the feed,
happens at most once per symbol ever, and the resubscribe runs in the
background.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime

import requests

from app.config import settings
from app.database import SessionLocal
from app.models import PaperSignal, PaperState, PaperSymbol, PaperTrade
from app.services import dhan_auth
from app.services.extra_instruments import _resolve_front_month
from app.services.market_data import quote_store

log = logging.getLogger("paper_trades")

# Pre-seeded so the client's stated instruments trade instantly from webhook one.
# Anything else arrives dynamically; this list is a warm-up, not a whitelist.
PRESEED = ("GOLD", "GOLDM", "GOLDTEN", "GOLDGUINEA", "SILVER", "SILVERM", "SILVERMIC")

# A quote older than this is a dead feed, not a price. Same bar the comparison
# screens use.
_FRESH_SECONDS = 120.0

# Rupees of P/L per one-point move, per lot - the exchange's contract spec.
# The scrip master's SEM_LOT_UNITS reads 1 for every MCX future (checked live:
# GOLD, GOLDM, GOLDTEN all came back 1.0), so trusting it would understate
# GOLD's P/L by a factor of a hundred. These are exchange facts, stable for
# years, and they do NOT make symbols any less dynamic: an unlisted symbol
# still trades, its P/L is just quoted per point (multiplier 1) until its spec
# is added here.
_MULTIPLIERS = {
    "GOLD": 100, "GOLDM": 10, "GOLDTEN": 1, "GOLDGUINEA": 1, "GOLDPETAL": 1,
    "SILVER": 30, "SILVERM": 5, "SILVERMIC": 1,
    "CRUDEOIL": 100, "CRUDEOILM": 10, "NATURALGAS": 1250, "NATGASMINI": 250,
    "COPPER": 2500, "ZINC": 5000, "ZINCMINI": 1000, "LEAD": 5000,
    "LEADMINI": 1000, "ALUMINIUM": 5000, "ALUMINI": 1000, "NICKEL": 1500,
}


def _lot_units(symbol: str, master_value) -> float:
    """The master's figure when it is believable, the exchange spec otherwise."""
    try:
        mv = float(master_value or 0)
    except (TypeError, ValueError):
        mv = 0.0
    if mv > 1:
        return mv
    return float(_MULTIPLIERS.get(symbol, mv or 1))

_BASE = "https://api.dhan.co/v2"

# --------------------------------------------------------------------------- #
# Start / Stop (client, 21-Aug)
# --------------------------------------------------------------------------- #
_enabled_cache: bool | None = None


def is_enabled() -> bool:
    global _enabled_cache
    if _enabled_cache is None:
        db = SessionLocal()
        try:
            row = db.get(PaperState, 1)
            _enabled_cache = bool(row.enabled) if row else True
        except Exception:  # noqa: BLE001 - never let a DB blip halt trading state
            _enabled_cache = True
        finally:
            db.close()
    return _enabled_cache


def set_enabled(on: bool, username: str) -> dict:
    """Start or stop the whole system.

    Stop first books EVERY open trade at that moment's price - the client's
    words: close, calculate, store, then stop. Each closes with
    exit_reason='stop' so History says which endings were his hand and which
    were the strategy's. While stopped, webhooks are logged but fire nothing.
    """
    global _enabled_cache
    closed = []
    with _lock:
        db = SessionLocal()
        try:
            if not on:
                now = datetime.now()
                for tr in (db.query(PaperTrade)
                           .filter(PaperTrade.status == "open").all()):
                    rec = _symbols.get(tr.symbol) or {}
                    ltp, _age = _ltp(rec) if rec else (None, None)
                    # The books must balance even on a dead feed: no price at
                    # all closes flat at entry rather than not closing, because
                    # "stop" means stop.
                    _close(tr, ltp or tr.entry_ltp, now, reason="stop")
                    closed.append({"id": tr.id, "symbol": tr.symbol,
                                   "timeframe": tr.timeframe, "pnl": tr.pnl})
            row = db.get(PaperState, 1)
            if not row:
                row = PaperState(id=1)
                db.add(row)
            row.enabled = bool(on)
            row.changed_at = datetime.now()
            row.changed_by = username
            db.add(PaperSignal(
                received_at=datetime.now(), action="started" if on else "stopped",
                reason=(f"by {username}" if on else
                        f"by {username} - closed {len(closed)} open trade(s)")))
            db.commit()
            _enabled_cache = bool(on)
        except Exception:  # noqa: BLE001
            db.rollback()
            raise
        finally:
            db.close()
    log.info("paper: system %s by %s (%d closed)",
             "started" if on else "STOPPED", username, len(closed))
    return {"enabled": bool(on), "closed": closed}


def close_trade(trade_id: int, username: str) -> dict:
    """Close ONE open trade by hand, at this moment's price (client, 24-Aug).

    Same booking as a webhook flip, but exit_reason='manual' so History shows
    whose decision the exit was. Confirmed twice in the UI before this is ever
    called; here we only verify the trade is real and still open.
    """
    with _lock:
        db = SessionLocal()
        try:
            tr = db.get(PaperTrade, int(trade_id))
            if not tr:
                return {"ok": False, "reason": "trade not found"}
            if tr.status != "open":
                return {"ok": False, "reason": f"trade #{trade_id} is already closed"}
            if not _loaded:
                _load_symbols()
            rec = _symbols.get(tr.symbol) or {}
            ltp, _age = _ltp(rec) if rec else (None, None)
            # Same rule as Stop: the book must balance even on a dead feed -
            # no price at all books flat at entry rather than refusing.
            _close(tr, ltp or tr.entry_ltp, datetime.now(), reason="manual")
            db.add(PaperSignal(
                received_at=datetime.now(), symbol=tr.symbol, side=None,
                timeframe=tr.timeframe, action="closed",
                reason=f"manual close by {username}", ltp=tr.exit_ltp,
                trade_id=tr.id))
            db.commit()
            out = {"ok": True, "id": tr.id, "symbol": tr.symbol,
                   "exit_ltp": tr.exit_ltp, "points": tr.points, "pnl": tr.pnl}
        except Exception as e:  # noqa: BLE001
            db.rollback()
            log.exception("paper: manual close failed")
            out = {"ok": False, "reason": str(e)}
        finally:
            db.close()
    if out.get("ok"):
        log.info("paper: trade #%s closed manually by %s (pnl %s)",
                 out["id"], username, out["pnl"])
    return out


def state() -> dict:
    db = SessionLocal()
    try:
        row = db.get(PaperState, 1)
        return {"enabled": bool(row.enabled) if row else True,
                "changed_at": (row.changed_at.isoformat(sep=" ", timespec="seconds")
                               if row and row.changed_at else None),
                "changed_by": row.changed_by if row else None}
    finally:
        db.close()


# One lock for the whole state machine. Webhooks arrive one at a time from one
# client; correctness beats concurrency here, and the hold time is milliseconds.
_lock = threading.Lock()
# symbol -> {security_id, trading_symbol, lot_units, expiry}; mirror of the
# paper_symbols table, loaded once and kept warm.
_symbols: dict[str, dict] = {}
_loaded = False


# --------------------------------------------------------------------------- #
# Symbol registry
# --------------------------------------------------------------------------- #
def _load_symbols() -> None:
    global _loaded
    db = SessionLocal()
    try:
        for r in db.query(PaperSymbol).all():
            _symbols[r.symbol] = {
                "security_id": r.security_id, "trading_symbol": r.trading_symbol,
                "lot_units": r.lot_units, "expiry": r.expiry,
            }
        _loaded = True
    finally:
        db.close()


def normalise_symbol(raw: str | None) -> str | None:
    """The official MCX name out of whatever TradingView sent.

    Alerts arrive as GOLDM, MCX:GOLDM, GOLDM1! or GOLDM2! depending on how the
    chart was set up. Strip the exchange prefix and the continuous-contract
    suffix; keep everything else exactly as given, uppercased - the scrip
    master is the judge of what exists, not us.
    """
    if not raw:
        return None
    s = str(raw).strip().upper()
    if ":" in s:
        s = s.split(":")[-1]
    if s.endswith("!") and len(s) > 2 and s[-2].isdigit():
        s = s[:-2]
    return s or None


def ensure_symbol(symbol: str) -> tuple[dict | None, bool, str | None]:
    """(record, is_new, error). Resolves and stores a first-time symbol."""
    if not _loaded:
        _load_symbols()
    rec = _symbols.get(symbol)
    if rec:
        return rec, False, None
    try:
        found = _resolve_front_month(symbol)
    except Exception as e:  # noqa: BLE001 - master download can fail; say so
        return None, False, f"scrip master unavailable: {e}"
    if not found:
        return None, False, "symbol not found on MCX"
    rec = {
        "security_id": str(found["security_id"]),
        "trading_symbol": found.get("trading_symbol"),
        "lot_units": _lot_units(symbol, found.get("lot_units")),
        "expiry": found["expiry"].strftime("%Y-%m-%d") if found.get("expiry") else None,
    }
    db = SessionLocal()
    try:
        db.add(PaperSymbol(symbol=symbol, security_id=rec["security_id"],
                           trading_symbol=rec["trading_symbol"],
                           lot_units=rec["lot_units"], expiry=rec["expiry"]))
        db.commit()
    except Exception:  # noqa: BLE001 - unique race: another thread won; use theirs
        db.rollback()
    finally:
        db.close()
    _symbols[symbol] = rec
    log.info("paper: new symbol %s -> %s (id %s, lot %s)",
             symbol, rec["trading_symbol"], rec["security_id"], rec["lot_units"])
    return rec, True, None


def refresh() -> None:
    """Called by the Dhan feed on every (re)connect: re-resolve each symbol so a
    rolled contract is replaced, exactly like every other subscription list."""
    if not _loaded:
        _load_symbols()
    for sym in list(_symbols) or []:
        try:
            found = _resolve_front_month(sym)
        except Exception as e:  # noqa: BLE001
            log.warning("paper: %s re-resolve failed: %s", sym, e)
            continue
        if not found:
            continue
        rec = {
            "security_id": str(found["security_id"]),
            "trading_symbol": found.get("trading_symbol"),
            "lot_units": _lot_units(sym, found.get("lot_units")),
            "expiry": found["expiry"].strftime("%Y-%m-%d") if found.get("expiry") else None,
        }
        if rec != _symbols.get(sym):
            _symbols[sym] = rec
            db = SessionLocal()
            try:
                row = db.query(PaperSymbol).filter(PaperSymbol.symbol == sym).first()
                if row:
                    row.security_id, row.trading_symbol = rec["security_id"], rec["trading_symbol"]
                    row.lot_units, row.expiry = rec["lot_units"], rec["expiry"]
                    row.resolved_at = datetime.utcnow()
                    db.commit()
            except Exception:  # noqa: BLE001
                db.rollback()
            finally:
                db.close()
    # Seed the client's stated set once, so the first real webhook is instant.
    for sym in PRESEED:
        if sym not in _symbols:
            ensure_symbol(sym)


def get_subscription_meta() -> dict[str, dict]:
    """security_id -> meta, merged into the Dhan feed's subscription list."""
    if not _loaded:
        _load_symbols()
    return {rec["security_id"]: {"short": f"paper_{sym.lower()}",
                                 "trading_symbol": rec["trading_symbol"],
                                 "kind": "paper"}
            for sym, rec in _symbols.items() if rec.get("security_id")}


# --------------------------------------------------------------------------- #
# Prices
# --------------------------------------------------------------------------- #
def _ltp(rec: dict) -> tuple[float | None, float | None]:
    """(ltp, age_seconds) from the socket's in-memory store."""
    q = quote_store.get(rec["security_id"])
    ltp = q.ltp or q.bid or q.ask or None
    age = (time.time() - q.timestamp) if q.timestamp else None
    return (float(ltp) if ltp else None), age


def _rest_ltp(rec: dict) -> float | None:
    """One REST quote, for the one moment a symbol is too new for the socket.

    Reuses the cached token the live feed already holds - the same pattern as
    the option-chain poller. NEVER mints a token; that would kill the feed's.
    """
    try:
        tok = dhan_auth.get_token(settings.DHAN_CLIENT_ID, settings.DHAN_MPIN,
                                  settings.DHAN_TOTP_SECRET).access_token
        r = requests.post(f"{_BASE}/marketfeed/ltp",
                          headers={"access-token": tok,
                                   "client-id": settings.DHAN_CLIENT_ID,
                                   "Content-Type": "application/json"},
                          data=json.dumps({"MCX_COMM": [int(rec["security_id"])]}),
                          timeout=8)
        r.raise_for_status()
        got = ((r.json() or {}).get("data") or {}).get("MCX_COMM") or {}
        row = got.get(str(rec["security_id"])) or got.get(rec["security_id"]) or {}
        return float(row.get("last_price") or 0) or None
    except Exception as e:  # noqa: BLE001
        log.warning("paper: REST ltp failed for %s: %s", rec.get("trading_symbol"), e)
        return None


# --------------------------------------------------------------------------- #
# The state machine
# --------------------------------------------------------------------------- #
def _close(trade: PaperTrade, ltp: float, now: datetime,
           reason: str = "signal") -> None:
    """Fill in the exit half and every derived number. Pure arithmetic.

    The temp_* columns still exist in the table and stay empty: dropping a
    column in SQLite rebuilds the whole table, and the client has live open
    positions - dormant columns cost nothing, a rebuild risks everything.
    """
    trade.exit_time = now
    trade.exit_ltp = ltp
    sign = 1 if trade.side == "long" else -1
    trade.points = round(sign * (ltp - trade.entry_ltp), 4)
    if trade.lot_units:
        trade.pnl = round(trade.points * (trade.lots or 1) * trade.lot_units, 2)
    trade.duration_s = max(0, int((now - trade.entry_time).total_seconds()))
    trade.exit_reason = reason
    trade.status = "closed"


def process_signal(payload: dict, raw_body: str) -> dict:
    """One webhook in, one decision out. Instant: memory reads + tiny inserts.

    Returns the dict the webhook answers with; every path also writes a
    PaperSignal row so the Log tab can show exactly what happened and why.
    """
    t0 = time.perf_counter()
    now = datetime.now()                      # server runs IST

    side_raw = str(payload.get("type") or payload.get("side") or "").strip().lower()
    side = {"buy": "buy", "long": "buy", "sell": "sell", "short": "sell"}.get(side_raw)
    symbol_raw = payload.get("symbol")
    symbol = normalise_symbol(symbol_raw)
    try:
        lots = float(payload.get("lot") or payload.get("lots")
                     or payload.get("lot_size") or 1) or 1
    except (TypeError, ValueError):
        lots = 1.0
    timeframe = (str(payload.get("timeframe") or payload.get("tf") or "")
                 .strip().lower() or None)
    # temp_price retired (client, 20-Aug): alerts may still send it - it is
    # simply ignored, never an error. It survives only inside raw_json.

    def _log(action: str, reason: str | None = None, ltp: float | None = None,
             trade_id: int | None = None) -> dict:
        db = SessionLocal()
        try:
            db.add(PaperSignal(
                received_at=now, symbol_raw=str(symbol_raw or "")[:64] or None,
                symbol=symbol, side=side or side_raw or None, lots=lots,
                timeframe=timeframe, action=action,
                reason=reason, ltp=ltp, trade_id=trade_id,
                latency_ms=int((time.perf_counter() - t0) * 1000),
                raw_json=raw_body[:2000] if raw_body else None))
            db.commit()
        except Exception:  # noqa: BLE001 - a full disk must not break the answer
            db.rollback()
        finally:
            db.close()
        out = {"status": action, "symbol": symbol, "side": side, "ltp": ltp}
        if reason:
            out["reason"] = reason
        if trade_id:
            out["trade_id"] = trade_id
        return out

    if side is None:
        return _log("rejected", f"type must be buy or sell, got {side_raw!r}")
    if not symbol:
        return _log("rejected", "symbol missing")
    # The Stop button outranks everything: the signal is still LOGGED - missed
    # entries must stay visible - but nothing fires until Start.
    if not is_enabled():
        return _log("rejected", "system stopped - press Start on the dashboard to resume")

    from app.services import dhan_feed
    if not dhan_feed.is_market_open():
        return _log("rejected", "MCX closed")

    with _lock:
        rec, is_new, err = ensure_symbol(symbol)
        if err:
            return _log("rejected", err)

        ltp, age = _ltp(rec)
        if is_new and not ltp:
            # Once per symbol's lifetime: the socket has never carried it, so
            # this one entry price comes from REST while the feed picks it up.
            ltp, age = _rest_ltp(rec), 0.0
        if not ltp:
            return _log("rejected", "no live price - feed has nothing for this contract")
        if age is not None and age > _FRESH_SECONDS:
            return _log("rejected", f"price is {int(age)}s old - feed stale, refusing to trade on it")

        db = SessionLocal()
        try:
            # The ledger key is symbol + timeframe (client, 21-Aug): his 5m and
            # 15m strategies trade the same symbol independently, so only an
            # exact repeat - same symbol, same timeframe, same side - is a
            # duplicate. `== None` compiles to IS NULL, so alerts without a
            # timeframe form their own bucket rather than colliding.
            open_trade = (db.query(PaperTrade)
                          .filter(PaperTrade.symbol == symbol,
                                  PaperTrade.timeframe == timeframe,
                                  PaperTrade.status == "open")
                          .first())
            want = "long" if side == "buy" else "short"

            if open_trade and open_trade.side == want:
                res = _log("ignored", f"already {want} {symbol}"
                                      f"{' ' + timeframe if timeframe else ''} "
                                      f"(trade #{open_trade.id}) - duplicate {side}")
            else:
                closed_id = None
                if open_trade:
                    _close(open_trade, ltp, now)
                    closed_id = open_trade.id
                new = PaperTrade(symbol=symbol, side=want, lots=lots,
                                 lot_units=rec.get("lot_units"), timeframe=timeframe,
                                 entry_time=now, entry_ltp=ltp, status="open")
                db.add(new)
                db.commit()
                res = _log("flipped" if closed_id else "opened",
                           (f"closed #{closed_id}, opened {want}" if closed_id
                            else f"opened {want}"),
                           ltp=ltp, trade_id=new.id)
        except Exception as e:  # noqa: BLE001
            db.rollback()
            log.exception("paper: signal store failed")
            res = _log("rejected", f"store error: {e}")
        finally:
            db.close()

    if is_new:
        # The feed learns the new contract in the background; the trade above
        # already has its price, so nothing waits on this.
        threading.Thread(target=lambda: dhan_feed.request_resubscribe(
            f"paper symbol {symbol} added"), daemon=True).start()
    return res


# --------------------------------------------------------------------------- #
# Reads for the page
# --------------------------------------------------------------------------- #
def positions() -> list[dict]:
    """Open trades with the live LTP and running P/L - all from memory."""
    if not _loaded:
        _load_symbols()
    db = SessionLocal()
    try:
        rows = (db.query(PaperTrade).filter(PaperTrade.status == "open")
                .order_by(PaperTrade.entry_time.desc()).all())
        out = []
        for r in rows:
            rec = _symbols.get(r.symbol) or {}
            ltp, age = _ltp(rec) if rec else (None, None)
            sign = 1 if r.side == "long" else -1
            pts = round(sign * (ltp - r.entry_ltp), 4) if ltp else None
            out.append({
                "id": r.id, "symbol": r.symbol, "side": r.side, "lots": r.lots,
                "timeframe": r.timeframe, "lot_units": r.lot_units,
                "entry_time": r.entry_time.isoformat(sep=" ", timespec="seconds"),
                "entry_ltp": r.entry_ltp,
                "ltp": ltp, "ltp_age": round(age, 1) if age is not None else None,
                "points": pts,
                "pnl": (round(pts * (r.lots or 1) * r.lot_units, 2)
                        if (pts is not None and r.lot_units) else None),
                "contract": rec.get("trading_symbol"),
            })
        return out
    finally:
        db.close()


def known_timeframes() -> list[str]:
    """Every timeframe that has actually appeared, for the dropdown."""
    db = SessionLocal()
    try:
        seen = {r[0] for r in db.query(PaperTrade.timeframe).distinct()}
        seen |= {r[0] for r in db.query(PaperSignal.timeframe).distinct()}
        return sorted(s for s in seen if s)
    finally:
        db.close()


def trades(symbol: str | None = None, side: str | None = None,
           timeframe: str | None = None,
           page: int = 1, page_size: int = 20) -> dict:
    """Closed trades, newest first, with an all-pages summary for the tiles."""
    from sqlalchemy import func
    page, page_size = max(1, int(page)), min(100, max(5, int(page_size)))
    db = SessionLocal()
    try:
        q = db.query(PaperTrade).filter(PaperTrade.status == "closed")
        if symbol:
            q = q.filter(PaperTrade.symbol == symbol.upper())
        if side in ("long", "short"):
            q = q.filter(PaperTrade.side == side)
        if timeframe:
            q = q.filter(PaperTrade.timeframe == timeframe.lower())
        total = q.count()
        agg = (db.query(func.sum(PaperTrade.pnl),
                        func.sum(func.iif(PaperTrade.pnl > 0, 1, 0)),
                        func.sum(func.iif(PaperTrade.pnl < 0, 1, 0)))
               .filter(PaperTrade.status == "closed"))
        if symbol:
            agg = agg.filter(PaperTrade.symbol == symbol.upper())
        if side in ("long", "short"):
            agg = agg.filter(PaperTrade.side == side)
        if timeframe:
            agg = agg.filter(PaperTrade.timeframe == timeframe.lower())
        pnl_sum, wins, losses = agg.first() or (None, 0, 0)
        rows = (q.order_by(PaperTrade.exit_time.desc())
                .offset((page - 1) * page_size).limit(page_size).all())
        return {
            "rows": [{
                "id": r.id, "symbol": r.symbol, "side": r.side, "lots": r.lots,
                "timeframe": r.timeframe, "lot_units": r.lot_units,
                "entry_time": r.entry_time.isoformat(sep=" ", timespec="seconds"),
                "entry_ltp": r.entry_ltp,
                "exit_time": (r.exit_time.isoformat(sep=" ", timespec="seconds")
                              if r.exit_time else None),
                "exit_ltp": r.exit_ltp,
                "points": r.points, "pnl": r.pnl,
                # 'signal' = the opposite webhook; 'stop' = the Stop button.
                "exit_reason": r.exit_reason or "signal",
                "duration_s": r.duration_s,
            } for r in rows],
            "total": total, "page": page, "page_size": page_size,
            "pages": max(1, -(-total // page_size)),
            "summary": {
                "trades": total,
                "pnl": round(pnl_sum, 2) if pnl_sum is not None else 0,
                "wins": int(wins or 0), "losses": int(losses or 0),
                "win_rate": round(100 * (wins or 0) / total, 1) if total else None,
            },
        }
    finally:
        db.close()


def signals(symbol: str | None = None, side: str | None = None,
            timeframe: str | None = None,
            page: int = 1, page_size: int = 20) -> dict:
    page, page_size = max(1, int(page)), min(100, max(5, int(page_size)))
    db = SessionLocal()
    try:
        q = db.query(PaperSignal)
        if symbol:
            q = q.filter(PaperSignal.symbol == symbol.upper())
        if side in ("buy", "sell"):
            q = q.filter(PaperSignal.side == side)
        if timeframe:
            q = q.filter(PaperSignal.timeframe == timeframe.lower())
        total = q.count()
        rows = (q.order_by(PaperSignal.received_at.desc(), PaperSignal.id.desc())
                .offset((page - 1) * page_size).limit(page_size).all())
        return {
            "rows": [{
                "id": r.id,
                "received_at": r.received_at.isoformat(sep=" ", timespec="seconds"),
                "symbol": r.symbol or r.symbol_raw, "side": r.side, "lots": r.lots,
                "timeframe": r.timeframe,
                "action": r.action, "reason": r.reason, "ltp": r.ltp,
                "trade_id": r.trade_id, "latency_ms": r.latency_ms,
            } for r in rows],
            "total": total, "page": page, "page_size": page_size,
            "pages": max(1, -(-total // page_size)),
        }
    finally:
        db.close()


def known_symbols() -> list[str]:
    """For the dropdowns: only what has actually been used or pre-seeded."""
    if not _loaded:
        _load_symbols()
    return sorted(_symbols)
