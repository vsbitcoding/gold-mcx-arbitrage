"""One-off research backtest (client question): 4-hour timeframe accuracy —
(A) % spread band alone vs (B) % band + warehouse-stock direction filter.

READ-ONLY research: touches nothing live — no model changes, no signals, no
schema. Pulls 60-min candles per leg via Dhan intraday REST (in-process live
token, chunked + paced), builds 4H %-spread bars, walk-forward backtests the
SAME strategy as production (20-period mean ± 1.5σ entry, target = mean,
stop = 3× reversion → 1:3), then re-scores the same trades with the stock
filter: take a trade only when the warehouse-stock move agrees with the
direction implied by that pair's stock↔spread correlation sign.

Results live in an in-memory dict served by GET /api/signals/backtest-4h.
"""
from __future__ import annotations

import logging
import statistics
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta

import requests

from app.config import MULTIPLIERS, settings
from app.database import SessionLocal
from app.models import BullionStock

log = logging.getLogger("research_bt")

_lock = threading.Lock()
_result: dict = {"running": False, "msg": "never run", "at": None}

_INTRA_URL = "https://api.dhan.co/v2/charts/intraday"

WINDOW = 20        # 20 × 4H bars (same count as the daily strategy)
ENTRY_K = 1.5
STOP_MULT = 3.0
MAXHOLD_BARS = 36  # ≈ 10 trading days of 4H bars


def status() -> dict:
    return dict(_result)


def _intraday_60(sid: str, token: str, days: int) -> dict[int, float]:
    """epoch → 60-min close, chunked (Dhan caps ~90 days/request)."""
    out: dict[int, float] = {}
    to = datetime.now().date()
    cur = to - timedelta(days=days)
    while cur < to:
        end = min(cur + timedelta(days=74), to)
        try:
            r = requests.post(
                _INTRA_URL,
                headers={"access-token": token, "client-id": settings.DHAN_CLIENT_ID,
                         "Content-Type": "application/json"},
                json={"securityId": str(sid), "exchangeSegment": "MCX_COMM",
                      "instrument": "FUTCOM", "interval": "60",
                      "fromDate": cur.isoformat(), "toDate": end.isoformat()},
                timeout=45,
            )
            if r.status_code == 200:
                d = r.json()
                for ts, close in zip(d.get("timestamp") or [], d.get("close") or []):
                    try:
                        if close:
                            out[int(ts)] = float(close)
                    except (TypeError, ValueError):
                        continue
        except Exception as e:  # noqa: BLE001
            log.warning("intraday pull %s %s→%s failed: %s", sid, cur, end, e)
        cur = end + timedelta(days=1)
        time.sleep(0.4)
    return out


def _bars_4h(big: dict[int, float], small: dict[int, float], bm: float, sm: float):
    """Merge hourly closes → 4H %-spread bars [(date_str, pct)] (last close per bucket)."""
    common = sorted(set(big) & set(small))
    buckets: dict = {}
    for ts in common:
        dt = datetime.fromtimestamp(ts)
        key = (dt.date(), dt.hour // 4)
        sv = small[ts] * sm
        if not sv:
            continue
        buckets[key] = (dt.date().isoformat(), round((big[ts] * bm - sv) / sv * 100, 4))
    return [buckets[k] for k in sorted(buckets)]


def _walk(series, target_frac: float = 1.0, maxhold: int = MAXHOLD_BARS) -> list[dict]:
    """Walk-forward trades on 4H % bars.

    target_frac: how much of the entry→mean reversion to take (1.0 = full mean,
    0.75 = exit at 75% of the way — hits sooner → fewer timeouts, smaller move).
    Stop stays 3× the TAKEN distance (constant 1:3 risk:reward per variant)."""
    vals = [v for _, v in series]
    dates = [d for d, _ in series]
    trades = []
    i, n = WINDOW, len(vals)
    while i < n - 1:
        w = vals[i - WINDOW:i]
        m = statistics.mean(w)
        sd = statistics.pstdev(w)
        if sd <= 0:
            i += 1
            continue
        z = (vals[i] - m) / sd
        if abs(z) >= ENTRY_K:
            entry = vals[i]
            short = z > 0                      # spread high → expect narrow
            dist = abs(entry - m) * target_frac
            target = entry - dist if short else entry + dist
            stop = entry + STOP_MULT * dist if short else entry - STOP_MULT * dist
            outcome, j = "timeout", 0
            for j in range(1, maxhold + 1):
                if i + j >= n:
                    break
                px = vals[i + j]
                if short:
                    if px <= target: outcome = "win"; break
                    if px >= stop:   outcome = "loss"; break
                else:
                    if px >= target: outcome = "win"; break
                    if px <= stop:   outcome = "loss"; break
            trades.append({"date": dates[i], "direction": "narrow" if short else "widen",
                           "outcome": outcome, "bars": j or 1})
            i += (j or 1) + 1
        else:
            i += 1
    return trades


def _summ(trades: list[dict]) -> dict:
    win = sum(1 for t in trades if t["outcome"] == "win")
    loss = sum(1 for t in trades if t["outcome"] == "loss")
    timeout = sum(1 for t in trades if t["outcome"] == "timeout")
    dec = win + loss
    win_bars = [t["bars"] for t in trades if t["outcome"] == "win" and t.get("bars")]
    return {"trades": len(trades), "win": win, "loss": loss, "timeout": timeout,
            "win_rate": round(win / dec * 100, 1) if dec else None,
            "timeout_pct": round(timeout / len(trades) * 100, 1) if trades else None,
            # ~3.6 four-hour bars per MCX trading day (09:00–23:30)
            "avg_days_to_win": round(statistics.mean(win_bars) / 3.6, 1) if win_bars else None}


def run(days: int = 185) -> None:
    from app.services import dhan_feed, mcxccl_service, pair_registry
    from app.services.signal_service import _pick_front  # same front-contract rule

    if not _lock.acquire(blocking=False):
        return
    _result.update(running=True, msg="running...", at=datetime.now().isoformat(timespec="seconds"))
    try:
        token = dhan_feed.get_live_token()
        if not token:
            _result.update(running=False, msg="no live token (feed not authenticated)")
            return

        # fronts — identical selection to the live signal engine
        groups = defaultdict(list)
        for p in pair_registry.get_pairs():
            if p.get("type") == "cross":
                groups[p.get("label")].append(p)
        pairs = [pf for ps in groups.values() if (pf := _pick_front(ps))]

        # stock series per commodity label + per-pair correlation sign (live report)
        db = SessionLocal()
        try:
            stock_rows = db.query(BullionStock).order_by(BullionStock.as_on_date).all()
        finally:
            db.close()
        stock: dict[str, list] = defaultdict(list)
        for s in stock_rows:
            stock[s.commodity].append((s.as_on_date, s.eligible_units))
        first_stock = min((r.as_on_date for r in stock_rows), default=None)
        key_to_label = {v: k for k, v in mcxccl_service._LABEL_TO_KEY.items()}
        corr = {}
        for c in (mcxccl_service.report().get("correlation") or []):
            cur = corr.get(c["pair_name"])
            if cur is None or abs(c["r"]) > abs(cur):
                corr[c["pair_name"]] = c["r"]

        def stock_change(label: str, d: str):
            ser = stock.get(label) or []
            prev = [v for dt, v in ser if dt <= d]
            return prev[-1] - prev[-2] if len(prev) >= 2 else None

        all_trades: list[tuple[dict, dict]] = []   # (trade, pair) — baseline variant
        series_by_pair: dict[str, dict] = {}
        used, bars_total, span_from, span_to = 0, 0, None, None
        for p in pairs:
            big = _intraday_60(p["big_security_id"], token, days)
            small = _intraday_60(p["small_security_id"], token, days)
            if not big or not small:
                continue
            series = _bars_4h(big, small, MULTIPLIERS.get(p["big"], 1.0), MULTIPLIERS.get(p["small"], 1.0))
            if len(series) < WINDOW + 10:
                continue
            used += 1
            bars_total += len(series)
            span_from = min(span_from or series[0][0], series[0][0])
            span_to = max(span_to or series[-1][0], series[-1][0])
            series_by_pair[p["name"]] = {"label": p.get("label"), "small": p.get("small"), "series": series}
            for t in _walk(series):
                all_trades.append((t, p))

        # Persist the built 4H series → future sweeps run standalone (no Dhan,
        # no token, no deploy): /tmp/research_4h_series.json
        try:
            import json as _json
            with open("/tmp/research_4h_series.json", "w") as f:
                _json.dump({"built_at": datetime.now().isoformat(timespec="seconds"),
                            "days": days, "pairs": series_by_pair}, f)
        except Exception as e:  # noqa: BLE001
            log.warning("series dump failed: %s", e)

        # Timeout-reduction sweep: target fraction × max-hold (only-% strategy)
        sweep = []
        for frac in (1.0, 0.75, 0.5):
            for hold in (36, 18):
                trades_v = []
                for info in series_by_pair.values():
                    trades_v.extend(_walk(info["series"], target_frac=frac, maxhold=hold))
                sweep.append({"target": f"{int(frac * 100)}% reversion", "maxhold_bars": hold,
                              "maxhold_days": round(hold / 3.6, 1), **_summ(trades_v)})

        # (A) % band alone — full window
        a_full = _summ([t for t, _ in all_trades])

        # overlap = trades where the stock filter is even possible
        overlap, b_take, b_skip = [], [], 0
        for t, p in all_trades:
            label = key_to_label.get(p.get("small"))
            r = corr.get(p["name"])
            if not label or r is None or first_stock is None or t["date"] < first_stock:
                continue
            chg = stock_change(label, t["date"])
            if chg is None:
                continue
            overlap.append(t)
            expected_up = (chg > 0) == (r > 0)     # stock move × corr sign → spread direction
            if chg != 0 and ((t["direction"] == "widen") == expected_up):
                b_take.append(t)
            else:
                b_skip += 1

        _result.update(
            running=False,
            msg="done",
            params={"timeframe": "4H", "window_bars": WINDOW, "entry_sigma": ENTRY_K,
                    "rr": f"1:{STOP_MULT:g}", "maxhold_bars": MAXHOLD_BARS},
            data={"pairs_used": used, "bars_total": bars_total,
                  "from": span_from, "to": span_to, "stock_from": first_stock},
            only_pct_full=a_full,
            only_pct_overlap=_summ(overlap),
            pct_plus_stock={**_summ(b_take), "filtered_out": b_skip},
            sweep=sweep,
        )
        log.info("4H research backtest: %s", _result["msg"])
    except Exception as e:  # noqa: BLE001
        _result.update(running=False, msg=f"error: {e}")
        log.exception("4H research backtest failed")
    finally:
        _lock.release()


def start(days: int = 185) -> bool:
    if _result["running"]:
        return False
    threading.Thread(target=run, args=(days,), daemon=True, name="research-bt").start()
    return True
