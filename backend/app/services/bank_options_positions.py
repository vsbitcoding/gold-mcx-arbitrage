"""Persistent manual paper positions for the bank-index comparison board.

Only executable, fresh two-way quotes can open/close a paper position. This
module never submits orders and never estimates a missing fill from the LTP.
"""
from __future__ import annotations

import json
import math
import threading
from datetime import date, datetime, time, timezone
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models import BankOptionPosition, User


_lock = threading.RLock()
_IST = ZoneInfo("Asia/Kolkata")
_INDICES = ("BANKEX", "BANKNIFTY")
_MAX_QUOTE_AGE = 60
_EXPIRED_REASON = "A leg has expired. No paper settlement or post-expiry fill has been assumed."


def _live():
    # The live service reads our pinned subscription metadata, so import lazily.
    from app.services import bank_options_service
    return bank_options_service


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _money(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _quote_problem(quote: dict) -> str | None:
    bid, ask, age = quote.get("bid"), quote.get("ask"), quote.get("age_seconds")
    if not _number(bid) or not _number(ask) or bid <= 0 or ask <= 0:
        return "A positive bid and ask are required."
    if bid > ask:
        return "Crossed bid/ask quotes cannot be used."
    if quote.get("fresh") is not True or not _number(age) or not 0 <= age <= _MAX_QUOTE_AGE:
        return "Quotes are missing or older than 60 seconds."
    return None


def _expiry(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError("A valid contract expiry is required.") from None


def _has_expired(data: dict, now: datetime) -> bool:
    for index in _INDICES:
        expiry = _expiry(data[index.lower()]["expiry"])
        cutoff = datetime.combine(expiry, time(15, 30), tzinfo=_IST)
        if now >= cutoff:
            return True
    return False


def _expire_if_needed(db, row: BankOptionPosition, now: datetime) -> None:
    if row.status != "open":
        return
    data = json.loads(row.data)
    if not _has_expired(data, now):
        return
    data["reason"] = _EXPIRED_REASON
    # Conditional updates protect a close committed by another worker.
    db.query(BankOptionPosition).filter(
        BankOptionPosition.id == row.id,
        BankOptionPosition.status == "open",
    ).update({"status": "expired", "data": json.dumps(data)}, synchronize_session=False)
    db.commit()
    db.refresh(row)


def _mark(data: dict, now: datetime) -> dict:
    prices = {index: None for index in _INDICES}
    if _has_expired(data, now):
        return {"prices": prices, "fresh": False, "pnl": None, "reason": _EXPIRED_REASON}
    live = _live()
    market_open = live.market_is_open()
    problems = []
    pnl = Decimal("0")
    for index in _INDICES:
        leg = data[index.lower()]
        quote = live.quote_leg(leg)
        problem = _quote_problem(quote)
        if problem:
            problems.append(f"{index}: {problem}")
            continue
        # Liquidation of a bought leg sells at bid; a sold leg buys at ask.
        current = quote["bid"] if leg["action"] == "BUY" else quote["ask"]
        prices[index] = current
        direction = 1 if leg["action"] == "BUY" else -1
        pnl += (Decimal(str(current)) - Decimal(str(leg["entry_price"]))) * leg["quantity"] * direction
    if not market_open:
        problems.insert(0, "Both index markets must be open for a live mark or paper close.")
    return {
        "prices": prices,
        "fresh": not problems,
        "pnl": _money(pnl) if not problems else None,
        "reason": " ".join(problems) if problems else None,
    }


def _serialize(row: BankOptionPosition, *, mark: dict | None = None) -> dict:
    data = json.loads(row.data)
    if row.status == "open":
        mark = mark if mark is not None else _mark(data, _now())
    else:
        mark = {
            "prices": {index: data[index.lower()].get("exit_price") for index in _INDICES},
            "fresh": False,
            "pnl": row.realised_pnl_rupees if row.status == "closed" else None,
            "reason": data.get("reason"),
        }
    result = {
        "id": row.id,
        "status": row.status,
        "side": row.side,
        "created_at": _iso(row.created_at),
        "closed_at": _iso(row.closed_at),
        "buy_index": data["buy_index"],
        "sell_index": data["sell_index"],
        "entry_credit_rupees": data["entry_credit_rupees"],
        "pnl_rupees": mark["pnl"],
        "mark_fresh": mark["fresh"],
        "can_close": row.status == "open" and mark["fresh"],
        "reason": mark["reason"],
    }
    for index in _INDICES:
        key = index.lower()
        result[key] = {**data[key], "current_price": mark["prices"][index]}
    return result


def _validate_request(username: str, side: str, bankex_lots: int, banknifty_lots: int,
                      request_id: str) -> None:
    if not isinstance(username, str) or not username.strip() or len(username) > 64:
        raise ValueError("A valid user is required.")
    if side not in {"CE", "PE"}:
        raise ValueError("Option side must be CE or PE.")
    for lots in (bankex_lots, banknifty_lots):
        if isinstance(lots, bool) or not isinstance(lots, int) or not 1 <= lots <= 100:
            raise ValueError("Lots must be a whole number from 1 to 100 for each leg.")
    if not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 80:
        raise ValueError("A request ID of 1 to 80 characters is required.")


def _check_duplicate(row: BankOptionPosition, request: dict) -> None:
    if json.loads(row.data).get("request") != request:
        raise ValueError("This request ID has already been used for a different position.")


def _owner_key(username: str, db) -> str:
    uid = getattr(username, "auth_uid", None)
    if not uid:
        # Internal callers/tests may use a name; never persist it as identity.
        row = db.query(User.auth_uid).filter(User.username == str(username)).first()
        uid = row[0] if row else None
    if not uid:
        raise ValueError("An existing user is required for paper positions.")
    return "uid:" + uid


def create_position(username: str, bankex_security_id: str, banknifty_security_id: str,
                    side: str, bankex_lots: int, banknifty_lots: int, request_id: str) -> dict:
    """Open a paper pair once, pinned to validated contracts and actual lot sizes."""
    _validate_request(username, side, bankex_lots, banknifty_lots, request_id)
    if not all(isinstance(sid, str) and sid.strip() for sid in (bankex_security_id, banknifty_security_id)):
        raise ValueError("Both contract IDs are required.")
    request = {
        "bankex_security_id": bankex_security_id, "banknifty_security_id": banknifty_security_id,
        "side": side, "bankex_lots": bankex_lots, "banknifty_lots": banknifty_lots,
    }
    with _lock, SessionLocal() as db:
        owner = _owner_key(username, db)
        existing = db.query(BankOptionPosition).filter_by(owner_uid=owner, request_id=request_id).first()
        if existing:
            _check_duplicate(existing, request)
            _expire_if_needed(db, existing, _now())
            return _serialize(existing)

        live = _live()
        pair = live.get_entry_pair(bankex_security_id, banknifty_security_id, side)
        if pair.get("market_open") is not True or not live.market_is_open():
            raise ValueError("Both index markets must be open to add a paper position.")
        if pair.get("tradable") is not True:
            raise ValueError(pair.get("reason") or "This pair is not currently tradable.")
        expiries = {index: _expiry(pair[index.lower()].get("expiry")) for index in _INDICES}
        if expiries["BANKEX"] == expiries["BANKNIFTY"]:
            raise ValueError("Equal expiries have no earlier-buy/later-sell direction.")
        buy_index = min(expiries, key=expiries.get)
        sell_index = "BANKNIFTY" if buy_index == "BANKEX" else "BANKEX"
        data = {"request": request, "buy_index": buy_index, "sell_index": sell_index}
        credit = Decimal("0")
        for index, sid, lots in (("BANKEX", bankex_security_id, bankex_lots),
                                 ("BANKNIFTY", banknifty_security_id, banknifty_lots)):
            quote = pair[index.lower()]
            if quote.get("security_id") != sid:
                raise ValueError("The requested contract does not match the live pair.")
            if quote.get("exchange") != ("BFO" if index == "BANKEX" else "NFO"):
                raise ValueError("The option contract has an unexpected exchange.")
            problem = _quote_problem(quote)
            if problem:
                raise ValueError(f"{index}: {problem}")
            lot_size = quote.get("lot_size")
            if not _number(lot_size) or int(lot_size) != lot_size or not 1 <= lot_size <= 100000:
                raise ValueError(f"{index}: Contract lot size is unavailable.")
            if not _number(quote.get("strike")) or quote["strike"] <= 0:
                raise ValueError(f"{index}: Contract strike is unavailable.")
            action = "BUY" if index == buy_index else "SELL"
            price = quote["ask"] if action == "BUY" else quote["bid"]
            quantity = lots * int(lot_size)
            data[index.lower()] = {
                "security_id": sid, "exchange": quote["exchange"],
                "trading_symbol": quote.get("trading_symbol") or sid,
                "strike": quote["strike"], "expiry": expiries[index].isoformat(),
                "lot_size": int(lot_size), "lots": lots, "quantity": quantity,
                "entry_price": price, "exit_price": None, "action": action, "side": side,
            }
            credit += Decimal(str(price)) * quantity * (-1 if action == "BUY" else 1)
        now = _now()
        if _has_expired(data, now):
            raise ValueError("Expired contracts cannot open a paper position.")
        if not live.market_is_open():
            raise ValueError("The market session ended before the paper entry.")
        data["entry_credit_rupees"] = _money(credit)
        row = BankOptionPosition(owner_uid=owner, owner_name=str(username), request_id=request_id, side=side,
                                 created_at=now.replace(tzinfo=None), status="open", data=json.dumps(data))
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            # Also safe if two server workers race on the same request ID.
            db.rollback()
            row = db.query(BankOptionPosition).filter_by(owner_uid=owner, request_id=request_id).first()
            if row is None:
                raise
            _check_duplicate(row, request)
        db.refresh(row)
        return _serialize(row)


def list_positions(username: str) -> dict:
    with _lock, SessionLocal() as db:
        owner = _owner_key(username, db)
        rows = db.query(BankOptionPosition).filter_by(owner_uid=owner).order_by(
            BankOptionPosition.created_at.desc(), BankOptionPosition.id.desc()).all()
        now = _now()
        positions = []
        for row in rows:
            _expire_if_needed(db, row, now)
            positions.append(_serialize(row))
    opened = [p for p in positions if p["status"] == "open"]
    closed = [p for p in positions if p["status"] == "closed"]
    # An incomplete total must never look like zero (or a partial positive P&L).
    open_pnl = None if any(p["pnl_rupees"] is None for p in opened) else _money(
        sum((Decimal(str(p["pnl_rupees"])) for p in opened), Decimal("0")))
    return {"positions": positions, "summary": {
        "open": len(opened), "closed": len(closed),
        "expired": sum(p["status"] == "expired" for p in positions),
        "open_pnl_rupees": open_pnl,
        "realised_pnl_rupees": _money(sum((Decimal(str(p["pnl_rupees"])) for p in closed), Decimal("0"))),
    }}


def close_position(username: str, position_id: int) -> dict:
    """Book a manual paper close once, with the current opposite-side quotes."""
    with _lock, SessionLocal() as db:
        owner = _owner_key(username, db)
        row = db.query(BankOptionPosition).filter_by(id=position_id, owner_uid=owner).first()
        if row is None:
            raise LookupError("Paper position not found.")
        _expire_if_needed(db, row, _now())
        if row.status == "closed":
            return _serialize(row)
        if row.status != "open":
            raise ValueError(_EXPIRED_REASON)
        data = json.loads(row.data)
        mark = _mark(data, _now())
        if not mark["fresh"]:
            raise ValueError(mark["reason"])
        # Recheck the expiry and session at the moment the fill is committed.
        now = _now()
        if _has_expired(data, now) or not _live().market_is_open():
            _expire_if_needed(db, row, now)
            raise ValueError("The market session ended or a leg expired before the paper close.")
        for index in _INDICES:
            data[index.lower()]["exit_price"] = mark["prices"][index]
        data["reason"] = None
        changed = db.query(BankOptionPosition).filter_by(
            id=row.id, owner_uid=owner, status="open",
        ).update({"status": "closed", "closed_at": now.replace(tzinfo=None),
                  "realised_pnl_rupees": mark["pnl"], "data": json.dumps(data)}, synchronize_session=False)
        db.commit()
        db.refresh(row)
        if not changed and row.status != "closed":
            raise ValueError("This position is no longer open.")
        return _serialize(row)


def get_subscription_meta() -> dict[str, dict]:
    """Keep saved contracts subscribed even after live ATM/expiry selection moves."""
    with _lock, SessionLocal() as db:
        rows = db.query(BankOptionPosition).filter_by(status="open").all()
        now = _now()
        result = {}
        for row in rows:
            data = json.loads(row.data)
            if _has_expired(data, now):
                continue
            for index in _INDICES:
                leg = data[index.lower()]
                result[leg["security_id"]] = {
                    "security_id": leg["security_id"], "exch": leg["exchange"],
                    "exchange": leg["exchange"], "kind": "bank_option", "index": index,
                    "trading_symbol": leg["trading_symbol"], "strike": leg["strike"],
                    "expiry": leg["expiry"], "lot_size": leg["lot_size"], "side": row.side,
                }
        return result
