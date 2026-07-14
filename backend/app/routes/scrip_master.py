"""Scrip Master API for the new modern admin panel.

Each scrip = a product whose Buy/Sell rate is computed LIVE from a reference
(a market feed, or another scrip) plus a buy/sell parity. Reuses the existing
live feeds via premium_feed.get_inputs() — no new market connections.
"""
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.database import SessionLocal
from app.models import Scrip
from app.security import get_current_user
from app.services import premium_feed

router = APIRouter(prefix="/api/scrips", tags=["scrip-master"])

# Read cache: the panel polls every 2s per open browser — collapse ALL of that
# into ≤1 tiny SQLite read per second (rates come from in-memory feeds anyway).
# Mutations invalidate immediately, so edits still show up on the next poll.
_cache: dict = {}          # template -> (ts, payload)
_CACHE_TTL = 1.0


def _invalidate_cache() -> None:
    _cache.clear()

# Reference feeds offered to the dealer (label shown in the UI + how to read buy/sell).
REFERENCES = [
    {"key": "gold_spot", "label": "Gold Spot ($)"},
    {"key": "silver_spot", "label": "Silver Spot ($)"},
    {"key": "usdinr", "label": "USD / INR"},
    {"key": "mcx_gold", "label": "MCX Gold (fut)"},
    {"key": "mcx_silver", "label": "MCX Silver (fut)"},
]


def _feed_pairs() -> dict:
    """{feed_key: (buy, sell)} from the live feeds. Spot/INR have no depth →
    buy == sell; MCX futures give real bid/ask."""
    d = premium_feed.get_inputs() or {}
    mg = d.get("mcx_gold") or {}
    ms = d.get("mcx_silver") or {}
    xau, xag, inr = d.get("xauusd"), d.get("xagusd"), d.get("usdinr")
    return {
        "gold_spot": (xau, xau),
        "silver_spot": (xag, xag),
        "usdinr": (inr, inr),
        "mcx_gold": (mg.get("bid") or mg.get("ltp"), mg.get("ask") or mg.get("ltp")),
        "mcx_silver": (ms.get("bid") or ms.get("ltp"), ms.get("ask") or ms.get("ltp")),
    }


def _compute(scrips: list[Scrip]) -> list[dict]:
    """Resolve each scrip's live Buy/Sell (feed/scrip ref + parity, or manual)."""
    feeds = _feed_pairs()
    by_id = {s.id: s for s in scrips}
    cache: dict[int, tuple] = {}

    def resolve(s: Scrip, depth: int = 0):
        if s.id in cache:
            return cache[s.id]
        cache[s.id] = (None, None)  # cycle guard
        if s.ref_type == "manual":
            base = (None, None)
        elif s.ref_type == "scrip":
            ref = by_id.get(int(s.ref_key)) if (s.ref_key and str(s.ref_key).isdigit()) else None
            base = resolve(ref, depth + 1) if (ref and depth < 6) else (None, None)
        else:
            base = feeds.get(s.ref_key, (None, None))
        bb, bs = base
        buy = s.buy_manual if s.buy_manual is not None else (
            round(bb + (s.buy_parity or 0), 4) if bb is not None else None)
        sell = s.sell_manual if s.sell_manual is not None else (
            round(bs + (s.sell_parity or 0), 4) if bs is not None else None)
        cache[s.id] = (buy, sell)
        return cache[s.id]

    out = []
    for s in scrips:
        buy, sell = resolve(s)
        out.append({
            "id": s.id, "name": s.name, "code": s.code,
            "ref_type": s.ref_type, "ref_key": s.ref_key,
            "buy_parity": s.buy_parity, "sell_parity": s.sell_parity,
            "buy_manual": s.buy_manual, "sell_manual": s.sell_manual,
            "buy_rate": buy, "sell_rate": sell,
            "visible": s.visible, "allow_trade": s.allow_trade, "position": s.position,
        })
    return out


class ScripIn(BaseModel):
    name: str
    code: str | None = None
    ref_type: str = "feed"
    ref_key: str | None = None
    buy_parity: float | None = 0.0
    sell_parity: float | None = 0.0
    buy_manual: float | None = None
    sell_manual: float | None = None
    visible: bool = True
    allow_trade: bool = False
    template: str = "gurukrupa"


class OrderIn(BaseModel):
    order: list[int]  # scrip ids in the desired display order


@router.get("")
def list_scrips(template: str = "gurukrupa", user: str = Depends(get_current_user)):
    now = time.time()
    hit = _cache.get(template)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]
    db = SessionLocal()
    try:
        rows = (db.query(Scrip).filter(Scrip.template == template)
                .order_by(Scrip.position, Scrip.id).all())
        tpls = [t[0] for t in db.query(Scrip.template).distinct().order_by(Scrip.template).all()]
        if template not in tpls:
            tpls.append(template)
        payload = {
            "template": template,
            "templates": tpls,
            "references": REFERENCES,
            "scrips": _compute(rows),
            "scrip_refs": [{"id": s.id, "name": s.name} for s in rows],  # for "my scrip" chaining
        }
        _cache[template] = (now, payload)
        return payload
    finally:
        db.close()


@router.post("")
def create_scrip(body: ScripIn, user: str = Depends(get_current_user)):
    db = SessionLocal()
    try:
        pos = (db.query(Scrip).filter(Scrip.template == body.template).count())
        s = Scrip(position=pos, **body.model_dump())
        db.add(s)
        db.commit()
        _invalidate_cache()
        return {"id": s.id}
    finally:
        db.close()


@router.put("/{scrip_id}")
def update_scrip(scrip_id: int, body: ScripIn, user: str = Depends(get_current_user)):
    db = SessionLocal()
    try:
        s = db.get(Scrip, scrip_id)
        if not s:
            raise HTTPException(404, "Scrip not found")
        for k, v in body.model_dump().items():
            setattr(s, k, v)
        db.commit()
        _invalidate_cache()
        return {"ok": True}
    finally:
        db.close()


@router.delete("/{scrip_id}")
def delete_scrip(scrip_id: int, user: str = Depends(get_current_user)):
    db = SessionLocal()
    try:
        s = db.get(Scrip, scrip_id)
        if s:
            db.delete(s)
            db.commit()
        _invalidate_cache()
        return {"ok": True}
    finally:
        db.close()


@router.post("/reorder")
def reorder(body: OrderIn, user: str = Depends(get_current_user)):
    db = SessionLocal()
    try:
        for pos, sid in enumerate(body.order):
            s = db.get(Scrip, sid)
            if s:
                s.position = pos
        db.commit()
        _invalidate_cache()
        return {"ok": True}
    finally:
        db.close()


# Client's real products, copied from the old panel's two templates
# (gurukrupa = B2B pricing, gurukrupab2c = B2C pricing — same scrips, own
# parities/codes). ref "COST" = chained to the GOLD COST scrip of the template.
_SEED = {
    "gurukrupa": [
        # name, code, ref_type, ref_key, buy_parity, sell_parity, visible, allow_trade
        ("GOLD($)", "8868", "feed", "gold_spot", 0, 0, True, False),
        ("SILVER($)", "8869", "feed", "silver_spot", 0, 0, False, False),
        ("INR(₹)", "8870", "feed", "usdinr", 0, 0.01, True, False),
        ("GOLD COST", "8871", "feed", "mcx_gold", 0, 0, True, False),
        ("SILVER FUTURE", "8872", "feed", "mcx_silver", 0, 0, False, False),
        ("GOLD 995 (1kg) IND-BIS T+0", "8873", "feed", "mcx_gold", -100, 100, False, False),
        ("GOLD 995 (500gm) T+0", "8874", "feed", "mcx_gold", -100, 100, False, False),
        ("GOLD 995 (1KG) IND-BIS 24th FEB", "8922", "feed", "mcx_gold", -150, 150, False, False),
        ("GOLD 995 (500gm) 24th FEB", "8923", "feed", "mcx_gold", -200, 200, False, False),
        ("GOLD 995 WITH GST IMP", "8924", "feed", "mcx_gold", 5000, 3900, False, False),
        ("GOLD 999 WITH GST IMP", "8925", "scrip", "COST", -500, 4950, True, True),
        ("GOLD 999 100 Grams", "8968", "feed", "mcx_gold", -1000, 1000, False, True),
    ],
    "gurukrupab2c": [
        ("GOLD($)", "8957", "feed", "gold_spot", 0, 0, True, False),
        ("SILVER($)", "8958", "feed", "silver_spot", 0, 0, False, False),
        ("INR(₹)", "8959", "feed", "usdinr", 0, 0.01, True, False),
        ("GOLD COST", "8960", "feed", "mcx_gold", 0, 0, True, False),
        ("SILVER FUTURE", "8961", "feed", "mcx_silver", 0, 0, False, False),
        ("GOLD 995 (1kg) IND-BIS T+0", "8962", "feed", "mcx_gold", -100, 100, False, False),
        ("GOLD 995 (500gm) T+0", "8963", "feed", "mcx_gold", -100, 100, False, False),
        ("GOLD 995 (1KG) IND-BIS 24th FEB", "8964", "feed", "mcx_gold", -150, 150, False, False),
        ("GOLD 995 (500gm) 24th FEB", "8965", "feed", "mcx_gold", -200, 200, False, False),
        ("GOLD 995 WITH GST IMP", "8966", "feed", "mcx_gold", 5000, 3150, False, False),
        ("GOLD 999 WITH GST IMP", "8967", "feed", "mcx_gold", -500, 2450, True, True),
    ],
}


@router.post("/seed")
def seed(user: str = Depends(get_current_user)):
    """Seed the client's real products for BOTH templates (values copied from
    the old panel). Idempotent per template — skips a template that has rows."""
    db = SessionLocal()
    seeded = {}
    try:
        for tpl, rows in _SEED.items():
            if db.query(Scrip.id).filter(Scrip.template == tpl).first():
                seeded[tpl] = 0
                continue
            objs = []
            for i, (name, code, rt, rk, bp, sp, vis, at) in enumerate(rows):
                objs.append(Scrip(template=tpl, name=name, code=code, ref_type=rt,
                                  ref_key=None if rk == "COST" else rk,
                                  buy_parity=bp, sell_parity=sp, visible=vis,
                                  allow_trade=at, position=i))
            db.add_all(objs)
            db.flush()
            cost = next((o for o in objs if o.name == "GOLD COST"), None)
            for o, (name, code, rt, rk, *_rest) in zip(objs, rows):
                if rk == "COST" and cost:
                    o.ref_key = str(cost.id)
            seeded[tpl] = len(objs)
        db.commit()
        _invalidate_cache()
        return {"seeded": seeded}
    finally:
        db.close()
