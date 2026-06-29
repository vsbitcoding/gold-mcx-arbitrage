"""Daily MCXCCL bullion warehouse-stock feed + stock-vs-spread analytics.

Once a day (driven by the maintenance loop) `refresh()`:
  1. runs scripts/fetch_bullion_stock.py as an ISOLATED SUBPROCESS — a headless
     Chromium scrape of the MCXCCL 'Warehouse & Vault Wise Stock Position' PDF,
     parsing the bullion 'Eligible Units' summary. Keeping Chromium + pdfplumber
     in a short-lived subprocess means their memory never sits in the API process
     and a hang is bounded by a timeout.
  2. snapshots the live per-pair spread (from the in-memory quote_store, which a
     subprocess can't see) — building the spread history the correlation needs.

Both steps are independent and fully wrapped: a failure NEVER touches the live
Dhan feed or signals. Storage is idempotent (a PDF date already stored / today's
spread already snapped is skipped), so a restart after run-time is harmless.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.database import SessionLocal
from app.models import BullionPdf, BullionStock, DailySpread

log = logging.getLogger("mcxccl")

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "fetch_bullion_stock.py"

# MCXCCL PDF commodity label → internal pair-leg key (used for correlation).
_LABEL_TO_KEY = {
    "GOLD GUINEA": "guinea",
    "GOLD MINI": "mini",
    "GOLD TEN": "ten",
    "GOLD": "gold",
    "GOLDPETAL": "petal",
    "SILVER": "silver",
    "SILVERMIC": "silvermic",
}

_status = {
    "last_run_at": None,   # ISO UTC of the last refresh() attempt
    "ok": False,
    "msg": "not run yet",
    "as_on_date": None,    # date printed in the most recent scraped PDF
    "rows": 0,
}

# Tiny TTL cache for the dashboard payload — the data changes once/day, so there
# is no reason to re-query SQLite on every page load.
_report_cache: dict = {"at": 0.0, "data": None}
_REPORT_TTL = 60.0

# Serialises refresh() so the daily job and a manual "Fetch now" can't overlap
# (and double-clicks can't spawn two Chromium subprocesses).
_refresh_lock = threading.Lock()


def status() -> dict:
    return dict(_status)


# --------------------------------------------------------------------------- #
# Daily refresh
# --------------------------------------------------------------------------- #
def _scrape_and_store() -> tuple[str, bool, str | None, int]:
    """Run the subprocess scrape and store new rows. Returns (msg, ok, as_on, rows)."""
    env = {
        **os.environ,
        "MCXCCL_STOCK_PAGE_URL": settings.MCXCCL_STOCK_PAGE_URL,
    }
    if settings.MCXCCL_CHROME_CHANNEL:
        env["MCXCCL_CHROME_CHANNEL"] = settings.MCXCCL_CHROME_CHANNEL
    if settings.MCXCCL_CHROME_PATH:
        env["MCXCCL_CHROME_PATH"] = settings.MCXCCL_CHROME_PATH
    try:
        proc = subprocess.run(
            [sys.executable, str(_SCRIPT)],
            capture_output=True, text=True,
            timeout=settings.MCXCCL_SCRAPE_TIMEOUT,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return (f"scrape timed out after {settings.MCXCCL_SCRAPE_TIMEOUT}s", False, None, 0)
    except Exception as e:  # noqa: BLE001
        return (f"subprocess error: {e}", False, None, 0)

    out = (proc.stdout or "").strip()
    try:
        payload = json.loads(out.splitlines()[-1]) if out else {"ok": False, "error": "no output"}
    except (ValueError, IndexError):
        return (f"unparseable scraper output: {out[:120]!r}", False, None, 0)

    if not payload.get("ok"):
        log.warning("scrape failed: %s | stderr=%s", payload.get("error"), (proc.stderr or "")[:300])
        return (f"scrape failed: {payload.get('error')}", False, None, 0)

    as_on = payload.get("as_on_date")
    rows = payload.get("rows") or []
    if not as_on or not rows:
        return ("scrape returned no usable rows", False, as_on, 0)

    db = SessionLocal()
    try:
        already = db.query(BullionStock.id).filter(BullionStock.as_on_date == as_on).first()
        if not already:
            for r in rows:
                db.add(BullionStock(
                    as_on_date=as_on,
                    commodity=str(r.get("commodity", ""))[:40],
                    unit=str(r.get("unit", ""))[:8],
                    eligible_units=float(r.get("eligible_units", 0) or 0),
                ))
            db.commit()
        added = 0 if already else len(rows)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        return (f"stock store error: {e}", False, as_on, 0)
    finally:
        db.close()

    pdf_msg = _store_pdf(as_on, payload.get("source_url"), payload.get("pdf_name"), payload.get("pdf_b64"))
    detail = "already stored" if added == 0 else f"+{added} stock rows"
    return (f"as_on {as_on}: {detail}{pdf_msg}", True, as_on, added)


def _store_pdf(as_on: str, url, name, b64) -> str:
    """Persist the latest PDF (keep only the most recent row). Returns a status suffix."""
    if not b64:
        return ""
    db = SessionLocal()
    try:
        cur = db.query(BullionPdf).first()
        if cur and cur.as_on_date == as_on:
            return ""  # already have this date's PDF
        db.query(BullionPdf).delete()   # keep only the latest
        db.add(BullionPdf(as_on_date=as_on, filename=name, source_url=url,
                          content=base64.b64decode(b64)))
        db.commit()
        return "; PDF saved"
    except Exception as e:  # noqa: BLE001
        db.rollback()
        log.warning("PDF store error: %s", e)
        return "; PDF store failed"
    finally:
        db.close()


def get_latest_pdf():
    """Return (content_bytes, filename, source_url) for the stored PDF, or None."""
    db = SessionLocal()
    try:
        row = db.query(BullionPdf).order_by(BullionPdf.id.desc()).first()
        if not row:
            return None
        return (row.content, row.filename or f"mcxccl-bullion-{row.as_on_date}.pdf", row.source_url)
    finally:
        db.close()


def _snapshot_spread() -> str:
    """Store today's (IST) per-pair spread once. Runs even if the scrape failed."""
    from app.services.spread_engine import compute_all  # lazy: avoid import-order coupling

    today = datetime.now().date().isoformat()  # server runs in Asia/Kolkata → IST
    db = SessionLocal()
    try:
        if db.query(DailySpread.id).filter(DailySpread.snap_date == today).first():
            return "spread: already snapped today"
        n = 0
        for s in compute_all():
            dec, inc = s.get("decrease_spread"), s.get("increase_spread")
            if dec is None and inc is None:
                continue  # no live quote → don't store an empty point
            db.add(DailySpread(snap_date=today, pair_name=s["name"],
                               decrease_spread=dec, increase_spread=inc))
            n += 1
        db.commit()
        return f"spread: +{n} rows"
    except Exception as e:  # noqa: BLE001
        db.rollback()
        return f"spread snapshot error: {e}"
    finally:
        db.close()


def refresh() -> bool:
    """Run the daily scrape + spread snapshot. Always safe; never raises."""
    if not _refresh_lock.acquire(blocking=False):
        log.info("MCXCCL refresh skipped — already running")
        return False
    try:
        _status["last_run_at"] = datetime.now(timezone.utc).isoformat()
        if not settings.BULLION_STOCK_ENABLED:
            _status.update(ok=False, msg="disabled (BULLION_STOCK_ENABLED=false)")
            return False

        stock_msg, stock_ok, as_on, nrows = _scrape_and_store()
        spread_msg = _snapshot_spread()
        _report_cache["data"] = None  # invalidate the dashboard cache

        _status.update(ok=stock_ok, as_on_date=as_on or _status["as_on_date"],
                       rows=nrows, msg=f"{stock_msg}; {spread_msg}")
        log.info("MCXCCL refresh: %s", _status["msg"])
        return stock_ok
    finally:
        _refresh_lock.release()


# --------------------------------------------------------------------------- #
# Dashboard report (stock + spread history + correlation)
# --------------------------------------------------------------------------- #
def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = sum((x - mx) ** 2 for x in xs)
    sy = sum((y - my) ** 2 for y in ys)
    if sx == 0 or sy == 0:   # no variance (e.g. stock unchanged) → undefined
        return None
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return cov / (sx ** 0.5 * sy ** 0.5)


def _stock_asof(series: list[dict], date_str: str) -> float | None:
    """Latest stock value with date <= date_str (forward-fill the lagging PDF)."""
    val = None
    for r in series:           # series is sorted ascending by date
        if r["date"] <= date_str:
            val = r["units"]
        else:
            break
    return val


def _correlate(stock_hist: dict, spread_hist: dict) -> list[dict]:
    """Pearson r between each pair's daily spread and each leg-commodity's stock."""
    from app.services.pair_registry import get_pairs

    key_to_label = {v: k for k, v in _LABEL_TO_KEY.items()}
    out = []
    for p in get_pairs():
        sh = spread_hist.get(p["name"])
        if not sh or len(sh) < 3:
            continue
        sdates = [r["date"] for r in sh]
        svals = [r["spread"] for r in sh]
        for leg in (p.get("big"), p.get("small")):
            label = key_to_label.get(leg)
            series = stock_hist.get(label) if label else None
            if not series:
                continue
            xs, ys = [], []
            for d, sv in zip(sdates, svals):
                stk = _stock_asof(series, d)
                if stk is not None:
                    xs.append(stk)
                    ys.append(sv)
            r = _pearson(xs, ys)
            if r is None:
                continue
            out.append({
                "pair": p.get("label", p["name"]),
                "pair_name": p["name"],
                "commodity": label,
                "n": len(xs),
                "r": round(r, 3),
            })
    out.sort(key=lambda x: abs(x["r"]), reverse=True)
    return out


def report() -> dict:
    """Dashboard payload: latest stock, history series, spread history, correlation."""
    now = time.time()
    cached = _report_cache["data"]
    if cached is not None and now - _report_cache["at"] < _REPORT_TTL:
        return cached

    db = SessionLocal()
    try:
        stock = db.query(BullionStock).order_by(BullionStock.as_on_date).all()
        spreads = db.query(DailySpread).order_by(DailySpread.snap_date).all()
        pdf = db.query(BullionPdf.filename, BullionPdf.source_url).order_by(BullionPdf.id.desc()).first()
    finally:
        db.close()

    latest_date = stock[-1].as_on_date if stock else None
    latest = [
        {"commodity": s.commodity, "unit": s.unit, "eligible_units": s.eligible_units}
        for s in stock if s.as_on_date == latest_date
    ] if latest_date else []

    stock_hist: dict[str, list] = {}
    for s in stock:
        stock_hist.setdefault(s.commodity, []).append({"date": s.as_on_date, "units": s.eligible_units})

    spread_hist: dict[str, list] = {}
    for sp in spreads:
        v = sp.decrease_spread if sp.decrease_spread is not None else sp.increase_spread
        if v is None:
            continue
        spread_hist.setdefault(sp.pair_name, []).append({"date": sp.snap_date, "spread": v})

    stale = None
    if latest_date:
        try:
            d = datetime.strptime(latest_date, "%Y-%m-%d").date()
            stale = (datetime.now().date() - d).days
        except ValueError:
            pass

    result = {
        "status": status(),
        "as_on_date": latest_date,
        "stale_days": stale,
        "pdf_available": pdf is not None,
        "pdf_name": pdf[0] if pdf else None,
        "source_url": pdf[1] if pdf else None,
        "latest": latest,
        "stock_history": stock_hist,
        "spread_history": spread_hist,
        "correlation": _correlate(stock_hist, spread_hist),
    }
    _report_cache.update(at=now, data=result)
    return result
