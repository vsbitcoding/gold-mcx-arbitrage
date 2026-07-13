"""Fire-once mean-reversion SIGNAL engine with historical probability + accuracy
tracking (watch-only — no trade firing).

Design (kept fully off the live-feed hot path) — client's chosen mode:
**4H % band + warehouse-stock filter** (backtested: 4H band 97.8%/10 mo;
with the stock filter 100%, 0 losses, on the stock-data window):
  • DAILY batch (background): pull each front-month cross pair's 60-min history
    (~10 months, Dhan's intraday depth) → 4H bars → % spread series
    (spread ÷ small-leg value × 100) → (a) the current band (20-bar mean ± 1.5σ,
    in %) and (b) a per-pair PROBABILITY table — walk-forward, bucketed by z.
    A light band-only refresh rolls the 20-bar band forward every 4 hours.
  • STOCK FILTER at fire time: the latest MCXCCL warehouse-stock move, read via
    the pair's stock↔spread correlation sign, must point the same way as the
    signal — otherwise no fire (see _stock_allows).
  • TICK (background, ~3s, the single writer): compare each pair's live mid-spread
    to its band. On a confirmed extreme it FIRES ONE frozen Signal (direction,
    entry, target, probability%) → persisted to DB. It then tracks the open
    signal to resolution: HIT (reached target) or EXPIRED (didn't, in time).
  • READ paths (snapshot chip / API) are memory-only and never write.

Direction: mid ≥ upper → "narrow" (high, expected to fall); mid ≤ lower →
"widen" (low, expected to rise). Target = the mean.
"""
from __future__ import annotations

import logging
import statistics
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from app.config import MULTIPLIERS
from app.database import SessionLocal
from app.models import Signal
from app.services import pair_registry

log = logging.getLogger("signal_service")

WINDOW = 20                       # rolling days for mean / sd (the band)
ENTRY_K = 1.5                     # fire threshold in σ
STOP_MULT = 3.0                   # stop sits 3× the entry→target distance the other way (R:R 1:3; backtested ~98% hit-rate, 2024-26)
# Signals only fire / resolve inside this IST window, Mon–Fri (client's tradeable window).
SIGNAL_WINDOW_OPEN = 9 * 60 + 10    # 09:10 AM
SIGNAL_WINDOW_CLOSE = 22 * 60 + 30  # 10:30 PM
ROLL_DAYS = 7                     # within this many days of expiry → roll signals to the NEXT month (near-expiry = illiquid, untradeable)
MAXHOLD_BARS = 36                 # 4H bars to reach target = "right" (≈10 trading days; ~3.6 bars/day)
INTRADAY_DAYS = 320               # 60-min history to request (Dhan keeps ~10 months)
DEBOUNCE_SECONDS = 300            # mid must HOLD beyond band 5 min before firing (kills fast spikes)
MAX_AGE_SECONDS = 14 * 24 * 3600  # live signal expires (=wrong) if target not hit in ~10 trading days
MIN_HOLD_SECONDS = 60 * 60        # a signal that hits target faster than this = noise → discarded
LIQ_K = 1.0                       # skip firing if the spread's bid/ask width > LIQ_K × σ (illiquid)
GAP_MAX_FRAC = 0.25               # skip firing if buy/sell gap > 25% of the expected reversion (mid not tradeable)
TICK_SECONDS = 3
MIN_BUCKET_N = 5                  # min samples to trust a z-bucket's probability
Z_BUCKETS = [(1.5, 2.0), (2.0, 2.5), (2.5, 99.0)]

# Strategy search grid for "short + accurate + frequent". Each combo:
#   k = entry threshold (σ) · t = target distance from entry (σ) · s = stop distance (σ)
#   mean=True → target is the rolling mean (full reversion), stop 1:1 = the CURRENT live strategy
# SAME strategy (fire at 1.5σ → target = the rolling mean) at different R:R.
# stop_mult = how far the stop sits, as a multiple of the entry→mean distance.
#   1.0 = 1:1 (current) · 2.0 = 1:2 · etc.
STRAT_GRID = [
    {"name": "CURRENT · 1:1 (stop = 1.0× reversion)", "k": 1.5, "mean": True, "sm": 1.0},
    {"name": "mean revert · 1:1.5 (stop = 1.5×)", "k": 1.5, "mean": True, "sm": 1.5},
    {"name": "mean revert · 1:2 (stop = 2.0×)",   "k": 1.5, "mean": True, "sm": 2.0},
    {"name": "mean revert · 1:2.5 (stop = 2.5×)", "k": 1.5, "mean": True, "sm": 2.5},
    {"name": "mean revert · 1:3 (stop = 3.0×)",   "k": 1.5, "mean": True, "sm": 3.0},
    {"name": "mean revert · 1:4 (stop = 4.0×)",   "k": 1.5, "mean": True, "sm": 4.0},
]

_model: dict[str, dict] = {}      # pair_name -> {mean,sd,upper,lower,target,n, buckets, overall}
_active: dict[str, dict] = {}     # pair_name -> open frozen signal (mirrors DB open row)
_pending: dict[str, dict] = {}    # pair_name -> {direction, since}  (debounce buffer)
_state: dict = {"last_refresh": None, "models": 0}
_bt_grid: list | None = None      # backtest of every STRAT_GRID combo over ~1yr history


# ───────────────────────── Dhan history (4H bars) ─────────────────────────
# 60-min candles → 4H %-spread bars, shared with the research backtester.
# Uses the live feed's in-process token (never mints its own).
from app.services.research_backtest import _bars_4h, _intraday_60  # noqa: E402


def _pair_series_4h(p: dict, closes_cache: dict, token: str) -> list:
    """[(date_str, pct)] 4H %-spread bars for a pair (cached per contract)."""
    def closes(sid):
        sid = str(sid)
        if sid not in closes_cache:
            closes_cache[sid] = _intraday_60(sid, token, INTRADAY_DAYS)
        return closes_cache[sid]
    big = closes(p["big_security_id"])
    small = closes(p["small_security_id"])
    if not big or not small:
        return []
    return _bars_4h(big, small, MULTIPLIERS.get(p["big"], 1.0), MULTIPLIERS.get(p["small"], 1.0))


def _clean(vals: list) -> list:
    if len(vals) < 10:
        return vals
    vals = vals[3:]
    med = statistics.median(vals)
    mad = statistics.median([abs(v - med) for v in vals]) or 1.0
    return [v for v in vals if abs(v - med) <= 12 * mad]


# ───────────────────────── probability model ─────────────────────────
def _backtest(vals: list) -> list[tuple]:
    """Walk-forward (no lookahead). Returns [(abs_z, hit_bool, days)] for every
    ±ENTRY_K σ event, hit = reverted to the rolling mean within MAXHOLD_BARS."""
    res = []
    i = WINDOW
    n = len(vals)
    while i < n - 1:
        win = vals[i - WINDOW:i]
        m = statistics.mean(win)
        sd = statistics.pstdev(win)
        if sd <= 0:
            i += 1
            continue
        z = (vals[i] - m) / sd
        if abs(z) >= ENTRY_K:
            target = m
            short = z > 0
            hit, j = False, 0
            for j in range(1, MAXHOLD_BARS + 1):
                if i + j >= n:
                    break
                px = vals[i + j]
                if (short and px <= target) or (not short and px >= target):
                    hit = True
                    break
            res.append((abs(z), hit, j or 1))
            i += (j or 1) + 1
        else:
            i += 1
    return res


def _aggregate(res: list[tuple]):
    buckets = []
    for zmin, zmax in Z_BUCKETS:
        sel = [r for r in res if zmin <= r[0] < zmax]
        if sel:
            buckets.append({"zmin": zmin, "zmax": zmax,
                            "rate": round(sum(1 for r in sel if r[1]) / len(sel) * 100, 1),
                            "n": len(sel),
                            # r[2] is 4H BARS → convert to days (~3.6 bars/trading day)
                            "avg_days": round(statistics.mean([r[2] for r in sel]) / 3.6, 1)})
        else:
            buckets.append({"zmin": zmin, "zmax": zmax, "rate": None, "n": 0, "avg_days": None})
    overall = None
    if res:
        overall = {"rate": round(sum(1 for r in res if r[1]) / len(res) * 100, 1),
                   "n": len(res), "avg_days": round(statistics.mean([r[2] for r in res]) / 3.6, 1)}
    return buckets, overall


def _combo_bt(vals: list, k: float, t: float | None = None, s: float | None = None,
              target_mean: bool = False, stop_mult: float = 1.0) -> tuple:
    """Walk-forward backtest of one strategy combo (no lookahead).

    Fire when |z| ≥ k. Then:
      target_mean=True → target = rolling mean (full reversion); stop sits
                         `stop_mult`× the entry→mean distance the other way
                         (stop_mult=1.0 → 1:1, 2.0 → 1:2, …).
      else             → target = entry moved `t`·σ toward the mean;
                         stop   = entry moved `s`·σ away from the mean.
    Win = target reached before stop within MAXHOLD_BARS.
    Returns (wins, losses, timeouts, [days_to_win]).
    """
    win = loss = timeout = 0
    days: list[int] = []
    i, n = WINDOW, len(vals)
    while i < n - 1:
        w = vals[i - WINDOW:i]
        m = statistics.mean(w)
        sd = statistics.pstdev(w)
        if sd <= 0:
            i += 1
            continue
        z = (vals[i] - m) / sd
        if abs(z) >= k:
            entry = vals[i]
            short = z > 0                                  # spread high → target below
            if target_mean:
                target = m
                d = abs(entry - m)                         # the reversion distance
                stop = entry + stop_mult * d if short else entry - stop_mult * d
            else:
                target = entry - t * sd if short else entry + t * sd
                stop = entry + s * sd if short else entry - s * sd
            outcome, j = None, 0
            for j in range(1, MAXHOLD_BARS + 1):
                if i + j >= n:
                    break
                px = vals[i + j]
                if short:
                    if px <= target: outcome = "win"; break
                    if px >= stop:   outcome = "loss"; break
                else:
                    if px >= target: outcome = "win"; break
                    if px <= stop:   outcome = "loss"; break
            if outcome == "win":
                win += 1; days.append(j)
            elif outcome == "loss":
                loss += 1
            else:
                timeout += 1
            i += (j or 1) + 1
        else:
            i += 1
    return win, loss, timeout, days


def _yearly_bt(vals: list, dates: list, stop_mult: float) -> dict:
    """Current strategy (1.5σ entry → target = mean) at the given stop multiple,
    bucketed by the YEAR of each entry. Returns {year: [win, loss, timeout]}."""
    by_year: dict[str, list] = {}
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
            short = z > 0
            target = m
            d = abs(entry - m)
            stop = entry + stop_mult * d if short else entry - stop_mult * d
            outcome, j = None, 0
            for j in range(1, MAXHOLD_BARS + 1):
                if i + j >= n:
                    break
                px = vals[i + j]
                if short:
                    if px <= target: outcome = "win"; break
                    if px >= stop:   outcome = "loss"; break
                else:
                    if px >= target: outcome = "win"; break
                    if px <= stop:   outcome = "loss"; break
            yr = (dates[i] or "????")[:4]
            b = by_year.setdefault(yr, [0, 0, 0])
            if outcome == "win":    b[0] += 1
            elif outcome == "loss": b[1] += 1
            else:                   b[2] += 1
            i += (j or 1) + 1
        else:
            i += 1
    return by_year


def _summarize_bt(win: int, loss: int, timeout: int, days: list) -> dict:
    decisive = win + loss
    total = win + loss + timeout
    return {
        "trades": total, "win": win, "loss": loss, "timeout": timeout,
        "win_rate": round(win / decisive * 100, 1) if decisive else None,
        "timeout_pct": round(timeout / total * 100, 1) if total else None,
        # `days` holds 4H BARS → convert (~3.6 bars/trading day)
        "avg_days": round(statistics.mean(days) / 3.6, 1) if days else None,
    }


def _prob_for(model: dict, z: float):
    az = abs(z)
    for b in model.get("buckets", []):
        if b["zmin"] <= az < b["zmax"]:
            if b["n"] >= MIN_BUCKET_N and b["rate"] is not None:
                return b["rate"], b["avg_days"]
            break
    ov = model.get("overall")
    if ov and ov.get("rate") is not None:
        return ov["rate"], ov["avg_days"]
    return None, None


def _pair_expiry(p: dict) -> datetime:
    try:
        return datetime.fromisoformat(p.get("big_expiry") or "")
    except Exception:
        return datetime.max


def _pick_front(ps: list[dict]):
    """Front contract for a pair = nearest expiry that's still more than ROLL_DAYS
    away. Contracts within ROLL_DAYS of expiry are illiquid (wide, untradeable
    spreads) so signals roll forward to the next month (client rule)."""
    if not ps:
        return None
    cutoff = datetime.now() + timedelta(days=ROLL_DAYS)
    fresh = sorted((p for p in ps if _pair_expiry(p) > cutoff), key=_pair_expiry)
    return fresh[0] if fresh else min(ps, key=_pair_expiry)


def refresh_model() -> int:
    global _model, _bt_grid
    cross = [p for p in pair_registry.get_pairs() if p.get("type") == "cross"]
    if not cross:
        return 0
    groups: dict = defaultdict(list)
    for p in cross:
        groups[p.get("label")].append(p)
    pairs = [pf for ps in groups.values() if (pf := _pick_front(ps))]
    log.info("Signal fronts (roll within %dd → next month): %s", ROLL_DAYS,
             ", ".join(f"{p.get('label')}={p.get('expiry_short')}" for p in pairs))
    from app.services import dhan_feed
    token = dhan_feed.get_live_token()
    if not token:
        log.info("signal model: feed token not ready yet — will retry")
        return 0

    cache: dict[str, dict] = {}

    new: dict[str, dict] = {}
    grid_acc = [[0, 0, 0, []] for _ in STRAT_GRID]   # per-combo (win, loss, timeout, days)
    year_acc: dict[str, dict[str, list]] = {"1:1": {}, "1:3": {}}
    bars: list[int] = []
    dmin, dmax = None, None
    for p in pairs:
        # 4H %-spread bars (client logic: spread ÷ small-leg value × 100; % bands
        # stay comparable as prices move; converted back to value at fire time).
        ser = _pair_series_4h(p, cache, token)
        days = [d for d, _ in ser]
        # cleaned series WITH dates (mirror of _clean: trim 3 + drop 12-MAD outliers)
        if len(ser) >= 10:
            ser = ser[3:]
            _med = statistics.median([v for _, v in ser])
            _mad = statistics.median([abs(v - _med) for _, v in ser]) or 1.0
            ser = [(d, v) for d, v in ser if abs(v - _med) <= 12 * _mad]
        cdates = [d for d, _ in ser]
        vals = [v for _, v in ser]
        if len(vals) < WINDOW + 5:
            continue
        win = vals[-WINDOW:]
        mean = statistics.mean(win)
        sd = statistics.pstdev(win)
        if sd <= 0:
            continue
        buckets, overall = _aggregate(_backtest(vals))
        new[p["name"]] = {
            "label": p.get("label"),
            # contract refs for the 4-hourly band-only refresh + stock filter
            "big_sid": p["big_security_id"], "small_sid": p["small_security_id"],
            "big_key": p["big"], "small_key": p["small"],
            # all band fields are in % of the small-leg value (4dp — % values are small)
            "mean": round(mean, 4), "sd": round(sd, 4),
            "upper": round(mean + ENTRY_K * sd, 4), "lower": round(mean - ENTRY_K * sd, 4),
            "target": round(mean, 4), "n": len(vals),
            "buckets": buckets, "overall": overall,
        }
        bars.append(len(vals))
        if days:
            dmin = days[0] if dmin is None else min(dmin, days[0])
            dmax = days[-1] if dmax is None else max(dmax, days[-1])
        # backtest each R:R variant (CPU only on the already-fetched vals — no extra Dhan calls)
        for gi, g in enumerate(STRAT_GRID):
            w, l, t, d = _combo_bt(vals, g["k"], g.get("t"), g.get("s"),
                                   g.get("mean", False), g.get("sm", 1.0))
            a = grid_acc[gi]
            a[0] += w; a[1] += l; a[2] += t; a[3].extend(d)
        # per-year robustness for the current strategy at 1:1 and 1:3
        for lbl, smult in (("1:1", 1.0), ("1:3", 3.0)):
            for yr, (w, l, t) in _yearly_bt(vals, cdates, smult).items():
                b = year_acc[lbl].setdefault(yr, [0, 0, 0])
                b[0] += w; b[1] += l; b[2] += t
    _model = new   # atomic reference swap — readers never see a half-built map

    results = []
    for gi, g in enumerate(STRAT_GRID):
        r = _summarize_bt(*grid_acc[gi])
        r["name"] = g["name"]
        wr = (r["win_rate"] or 0) / 100.0
        if g.get("mean"):
            sm = g.get("sm", 1.0)
            r["rr"] = f"1:{sm:g}"
            # expectancy in "reversion units" (1 win = +1 reversion, 1 loss = −stop_mult)
            r["expectancy"] = round(wr * 1.0 - (1 - wr) * sm, 3)
        else:
            r.update(rr=f"{g['t']}:{g['s']}", expectancy=round(wr * g["t"] - (1 - wr) * g["s"], 3))
        results.append(r)
    def _year_rows(acc: dict) -> list:
        rows = []
        for yr in sorted(acc):
            w, l, t = acc[yr]
            dec = w + l
            rows.append({"year": yr, "win": w, "loss": l, "timeout": t,
                         "trades": w + l + t,
                         "win_rate": round(w / dec * 100, 1) if dec else None})
        return rows
    _bt_grid = {
        "tested": len(STRAT_GRID),
        "data": {"pairs": len(bars), "total_bars": sum(bars),
                 "min_bars": min(bars) if bars else 0, "max_bars": max(bars) if bars else 0,
                 "from": dmin, "to": dmax},
        "combos": results,
        "yearly": {lbl: _year_rows(acc) for lbl, acc in year_acc.items()},
    }
    _state["last_refresh"] = datetime.now().isoformat(timespec="seconds")
    _state["models"] = len(new)
    log.info("Signal model refreshed: %d pairs. Grid sweep %d combos over %d pairs (%d–%d bars, %s→%s).",
             len(new), len(STRAT_GRID), len(bars), min(bars) if bars else 0, max(bars) if bars else 0, dmin, dmax)
    c13 = next((c for c in results if c.get("rr") == "1:3"), {})
    yr13 = (_bt_grid.get("yearly") or {}).get("1:3", [])
    log.info("Backtest (current rolled contracts) 1:3 → win_rate=%s%% over %s trades · yearly: %s",
             c13.get("win_rate"), c13.get("trades"),
             ", ".join(f"{y['year']}={y['win_rate']}%" for y in yr13))
    return len(new)


def refresh_band() -> int:
    """Light 4-hourly band update: re-pull ~12 days of 60-min data per contract
    and recompute just the rolling 20-bar % band (the probability model stays
    from the daily build). ~2 calls per pair → negligible load."""
    from app.services import dhan_feed
    token = dhan_feed.get_live_token()
    if not token or not _model:
        return 0
    updated = 0
    cache: dict = {}
    for name, m in list(_model.items()):
        try:
            big = cache.setdefault(str(m["big_sid"]), _intraday_60(m["big_sid"], token, 12))
            small = cache.setdefault(str(m["small_sid"]), _intraday_60(m["small_sid"], token, 12))
            series = _bars_4h(big, small, MULTIPLIERS.get(m["big_key"], 1.0), MULTIPLIERS.get(m["small_key"], 1.0))
            vals = [v for _, v in series]
            if len(vals) < WINDOW:
                continue
            win = vals[-WINDOW:]
            mean = statistics.mean(win)
            sd = statistics.pstdev(win)
            if sd <= 0:
                continue
            m.update(mean=round(mean, 4), sd=round(sd, 4),
                     upper=round(mean + ENTRY_K * sd, 4), lower=round(mean - ENTRY_K * sd, 4),
                     target=round(mean, 4))
            updated += 1
        except Exception as e:  # noqa: BLE001
            log.warning("band refresh %s failed: %s", name, e)
    if updated:
        _state["last_band_refresh"] = datetime.now().isoformat(timespec="seconds")
        log.info("Signal band refresh: %d pairs updated", updated)
    return updated


def _stock_allows(small_key: str, pair_name: str, direction: str) -> bool:
    """Client's stock filter: fire only when the latest warehouse-stock move,
    read through the pair's stock↔spread correlation sign, points the SAME way
    as the signal. No stock data / no correlation / flat stock → no fire
    (this strictness is exactly what produced the 0-loss backtest)."""
    try:
        from app.services import mcxccl_service
        rep = mcxccl_service.report()                       # 60s-cached, no extra load
        label = next((k for k, v in mcxccl_service._LABEL_TO_KEY.items() if v == small_key), None)
        if not label:
            return False
        r = None
        for c in rep.get("correlation") or []:
            if c["pair_name"] == pair_name and (r is None or abs(c["r"]) > abs(r)):
                r = c["r"]
        ser = (rep.get("stock_history") or {}).get(label) or []
        if r is None or len(ser) < 2:
            return False
        chg = ser[-1]["units"] - ser[-2]["units"]
        if chg == 0:
            return False
        expected_up = (chg > 0) == (r > 0)   # stock move × corr sign → expected spread direction
        return direction == ("widen" if expected_up else "narrow")
    except Exception:  # noqa: BLE001
        return False


# ───────────────────────── live state machine (single writer) ─────────────────────────
def _mid(snap):
    dec, inc = snap.get("decrease_spread"), snap.get("increase_spread")
    if dec is None or inc is None:
        return None
    return (dec + inc) / 2.0


def _small_value(snap) -> float | None:
    """Live small/near-leg value (price × multiplier) — the denominator that
    converts between spread VALUE (points) and the model's % space."""
    mult = MULTIPLIERS.get(snap.get("small"), 1.0)
    sb, sa = snap.get("small_bid"), snap.get("small_ask")
    px = (sb + sa) / 2.0 if (sb and sa) else (sb or sa)
    return px * mult if px else None


def _too_noisy(s, sd_pct, small_value):
    """Liquidity guard: True when the spread's bid/ask width (increase − decrease)
    is wide vs the band's σ → illiquid pair, the mid is unreliable, so any signal
    would be noise. σ is in % → convert to value via the small-leg denominator."""
    dec, inc = s.get("decrease_spread"), s.get("increase_spread")
    if dec is None or inc is None or not small_value:
        return True
    sd_val = sd_pct * small_value / 100.0 if sd_pct else 0
    return sd_val > 0 and (inc - dec) > LIQ_K * sd_val


def _load_open():
    db = SessionLocal()
    try:
        changed = False
        for r in db.query(Signal).filter(Signal.status == "open").all():
            if r.entry_spread is not None and r.target_spread is not None:
                new_stop = round(r.entry_spread + STOP_MULT * (r.entry_spread - r.target_spread), 1)
                if r.stop_spread != new_stop:                 # re-cap open signals to the current 1:STOP_MULT stop
                    r.stop_spread = new_stop
                    changed = True
            _active[r.pair_name] = {
                "id": r.id, "direction": r.direction, "entry": r.entry_spread,
                "target": r.target_spread, "stop": r.stop_spread, "probability": r.probability,
                "z_at_entry": r.z_at_entry, "expected_days": r.expected_days,
                "label": r.label, "expiry_label": r.expiry_label,
                # fired_at is stored naive-UTC (datetime.utcnow); tag it UTC so the epoch
                # (and the IST time shown on the card) is correct after a reload/restart.
                "started": r.fired_at.replace(tzinfo=timezone.utc).timestamp() if r.fired_at else time.time(),
            }
        if changed:
            db.commit()
    finally:
        db.close()


def _in_signal_window() -> bool:
    """True only inside the client's tradeable window: 09:10 AM – 10:30 PM IST, Mon–Fri."""
    n = datetime.utcnow() + timedelta(hours=5, minutes=30)   # IST
    if n.weekday() >= 5:
        return False
    mins = n.hour * 60 + n.minute
    return SIGNAL_WINDOW_OPEN <= mins <= SIGNAL_WINDOW_CLOSE


def _tick():
    """Single-threaded writer: fire new signals + resolve open ones. ~3s cadence.

    Only fires/resolves inside the client's tradeable window (09:10 AM – 10:30 PM
    IST) so every entry & exit is at a price you can actually trade. Outside it
    holds (no fire, no resolve) — avoids un-tradeable after-hours/pre-open fills."""
    from app.services.spread_engine import compute_all
    if not _in_signal_window():
        _pending.clear()                       # reset debounce; resume cleanly at next open
        return
    snaps = {s["name"]: s for s in compute_all() if s.get("type") == "cross"}
    now = time.time()
    db = None
    try:
        # ── 1) RESOLVE every open signal — including ones whose contract has rolled
        #        out of the model, so a near-expiry open still hits target / stop. ──
        for name in list(_active):
            a = _active[name]
            s = snaps.get(name)
            mid = _mid(s) if s else None
            hit = mid is not None and (
                (a["direction"] == "narrow" and mid <= a["target"]) or
                (a["direction"] == "widen" and mid >= a["target"]))
            stop = a.get("stop")
            stopped = mid is not None and stop is not None and (
                (a["direction"] == "narrow" and mid >= stop) or
                (a["direction"] == "widen" and mid <= stop))
            expired = (now - a["started"]) > MAX_AGE_SECONDS
            if hit or stopped or expired:
                db = db or SessionLocal()
                row = db.get(Signal, a["id"])
                dur = now - a["started"]
                if row and row.status == "open":
                    if (hit or stopped) and dur < MIN_HOLD_SECONDS:
                        db.delete(row)       # resolved too fast → noise, discard (not counted)
                    else:
                        row.status = "hit" if hit else ("stopped" if stopped else "expired")
                        row.exit_spread = round(mid, 1) if mid is not None else None
                        row.resolved_at = datetime.utcnow()
                        row.days_held = round(dur / 86400.0, 2)
                    db.commit()              # persist BEFORE dropping from memory
                _active.pop(name, None)

        # ── 2) FIRE new signals on the current (rolled) front contracts ──
        open_labels = {a.get("label") for a in _active.values()}
        for name, model in _model.items():
            if name in _active:
                continue
            s = snaps.get(name)
            mid = _mid(s) if s else None
            small_value = _small_value(s) if s else None
            if mid is None or not small_value:
                _pending.pop(name, None)
                continue
            # Compare in % space (model bands are %), fire/store in VALUE (points).
            mid_pct = mid / small_value * 100.0
            direction = "narrow" if mid_pct >= model["upper"] else "widen" if mid_pct <= model["lower"] else None
            if direction is None or _too_noisy(s, model["sd"], small_value):
                _pending.pop(name, None)        # no extreme, or pair too illiquid → don't fire
                continue
            if not _stock_allows(s.get("small"), name, direction):
                _pending.pop(name, None)        # warehouse-stock direction doesn't confirm → skip
                continue
            if model.get("label") in open_labels:
                _pending.pop(name, None)        # one open signal per pair at a time (across rolled expiries)
                continue
            p = _pending.get(name)
            if p and p["direction"] == direction:
                if now - p["since"] >= DEBOUNCE_SECONDS:
                    sd = model["sd"] or 1.0
                    z = (mid_pct - model["mean"]) / sd
                    prob, exp_days = _prob_for(model, z)
                    entry = round(mid, 1)
                    # % band target → concrete spread VALUE at today's price (client:
                    # "convert % band to spread value")
                    target = round(model["target"] * small_value / 100.0, 1)
                    # Tradeability: skip if the live buy/sell gap is wide vs the expected
                    # profit — on a wide gap you fill at bid/ask, far from the mid, so the
                    # signal isn't realistically tradeable (esp. near-expiry illiquid contracts).
                    gap = abs((s.get("increase_spread") or 0) - (s.get("decrease_spread") or 0))
                    reversion = abs(entry - target)
                    if reversion <= 0 or gap > GAP_MAX_FRAC * reversion:
                        log.info("signal SKIP %s — buy/sell gap %.0f is %.0f%% of reversion %.0f (not tradeable)",
                                 name, gap, (gap / reversion * 100) if reversion else 0, reversion)
                        _pending.pop(name, None)
                        continue
                    stop = round(entry + STOP_MULT * (entry - target), 1)   # 1:STOP_MULT (3× the distance the other way)
                    db = db or SessionLocal()
                    row = Signal(
                        pair_name=name, label=s.get("label"), expiry_label=s.get("expiry_label"),
                        direction=direction, entry_spread=entry, target_spread=target, stop_spread=stop,
                        probability=prob, z_at_entry=round(z, 2), expected_days=exp_days, status="open")
                    db.add(row)
                    db.flush()
                    rid = row.id
                    db.commit()              # persist BEFORE adding to memory
                    _active[name] = {
                        "id": rid, "direction": direction, "entry": entry,
                        "target": target, "stop": stop, "probability": prob, "z_at_entry": round(z, 2),
                        "expected_days": exp_days, "label": s.get("label"),
                        "expiry_label": s.get("expiry_label"), "started": now}
                    open_labels.add(s.get("label"))
                    _pending.pop(name, None)
                    try:                                   # fire a push to all registered devices (non-blocking)
                        from app.services import fcm_service
                        fcm_service.notify_new_signal({
                            "label": s.get("label"), "direction": direction,
                            "entry": entry, "target": target, "stop": stop,
                            "expiry_label": s.get("expiry_label")})
                    except Exception as e:
                        log.warning("signal push dispatch failed: %s", e)
            else:
                _pending[name] = {"direction": direction, "since": now}
    except Exception:
        if db:
            db.rollback()
        raise
    finally:
        if db:
            db.close()


# ───────────────────────── read-only display ─────────────────────────
def _disp(name, s, a, cur, z):
    entry, target = a["entry"], a["target"]
    span = (entry - target) or 1
    progress = max(0, min(100, round((entry - cur) / span * 100))) if cur is not None else 0
    return {
        "id": a.get("id"), "name": name, "label": a.get("label") or s.get("label"),
        "expiry_label": a.get("expiry_label") or s.get("expiry_label"),
        "direction": a["direction"], "entry": entry, "target": target,
        "stop": a.get("stop"), "rr": f"1:{STOP_MULT:g}",
        "probability": a.get("probability"), "expected_days": a.get("expected_days"),
        "current": cur if cur is not None else entry, "z": z,
        "z_at_entry": a.get("z_at_entry"),
        "fired_at": datetime.fromtimestamp(a["started"]).strftime("%d %b %Y, %I:%M %p"),
        "age_min": int((time.time() - a["started"]) / 60), "progress_pct": progress,
        "time_left_min": max(0, int((MAX_AGE_SECONDS - (time.time() - a["started"])) / 60)),
        "limit_days": round(MAX_AGE_SECONDS / 86400),
    }


def evaluate_all(snaps: list[dict]) -> dict:
    """Read-only: decorate live snaps with the frozen open signal (if any)."""
    out = {}
    for s in snaps:
        if s.get("type") != "cross":
            continue
        name = s.get("name")
        a = _active.get(name)
        if not a:
            continue
        model = _model.get(name) or {}
        mid = _mid(s)
        small_value = _small_value(s)
        if mid is not None and model.get("sd") and small_value:
            mid_pct = mid / small_value * 100.0
            cur, z = round(mid, 1), round((mid_pct - model["mean"]) / model["sd"], 2)
        else:
            cur, z = a["entry"], a.get("z_at_entry")
        out[name] = _disp(name, s, a, cur, z)
    return out


def get_active_signals() -> list[dict]:
    from app.services.spread_engine import compute_all
    sigs = evaluate_all(compute_all())
    return sorted(sigs.values(), key=lambda x: -(x["probability"] or 0))


def get_history(limit: int = 100) -> list[dict]:
    db = SessionLocal()
    try:
        rows = (db.query(Signal).filter(Signal.status != "open")
                .order_by(Signal.resolved_at.desc()).limit(limit).all())
        return [{
            "id": r.id, "label": r.label, "expiry_label": r.expiry_label, "direction": r.direction,
            "entry": r.entry_spread, "target": r.target_spread, "stop": r.stop_spread, "exit": r.exit_spread,
            "probability": r.probability, "z_at_entry": r.z_at_entry,
            "outcome": "right" if r.status == "hit" else ("timeout" if r.status == "expired" else "wrong"),
            "days_held": r.days_held,
            "fired_at": r.fired_at.isoformat() if r.fired_at else None,
            "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
        } for r in rows]
    finally:
        db.close()


def get_accuracy() -> dict:
    db = SessionLocal()
    try:
        resolved = db.query(Signal).filter(Signal.status != "open").all()
        hits = sum(1 for r in resolved if r.status == "hit")
        stopped = sum(1 for r in resolved if r.status == "stopped")
        timeout = sum(1 for r in resolved if r.status == "expired")
        decisive = hits + stopped                      # target-or-stop trades (1:1 win-rate)
        by = defaultdict(lambda: [0, 0])               # label -> [decisive, hits]
        for r in resolved:
            if r.status in ("hit", "stopped"):
                by[r.label][0] += 1
                if r.status == "hit":
                    by[r.label][1] += 1
        by_pair = [{"label": k, "total": v[0], "right": v[1],
                    "accuracy_pct": round(v[1] / v[0] * 100, 1) if v[0] else None}
                   for k, v in sorted(by.items())]
        return {
            "total": len(resolved), "right": hits, "wrong": stopped, "timeout": timeout,
            "accuracy_pct": round(hits / decisive * 100, 1) if decisive else None,
            "open": len(_active), "by_pair": by_pair,
        }
    finally:
        db.close()


def status() -> dict:
    return {"models": _state["models"], "last_refresh": _state["last_refresh"],
            "timeframe": "4H", "stock_filter": True,
            "last_band_refresh": _state.get("last_band_refresh"),
            "open": len(_active), "window": WINDOW, "entry_sigma": ENTRY_K,
            "maxhold_days": round(MAXHOLD_BARS / 3.6),
            "pairs": sorted({m.get("label") for m in _model.values() if m.get("label")}),
            "rr": f"1:{STOP_MULT:g}"}          # live risk:reward


# ───────────────────────── background loop ─────────────────────────
def _loop() -> None:
    for _ in range(60):
        if pair_registry.get_pairs():
            break
        time.sleep(5)
    time.sleep(5)
    try:
        _load_open()
    except Exception as e:
        log.warning("load open signals failed: %s", e)
    last_model_date = None
    last_band_at = 0.0
    while True:
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            if today != last_model_date:
                if refresh_model() > 0:
                    last_model_date = today
                    last_band_at = time.time()
            elif time.time() - last_band_at >= 4 * 3600:   # roll the 4H band forward
                refresh_band()
                last_band_at = time.time()
            if _model:
                _tick()
        except Exception as e:
            log.exception("signal loop: %s", e)
        time.sleep(TICK_SECONDS)


def start_in_background() -> threading.Thread:
    t = threading.Thread(target=_loop, daemon=True, name="signal_service")
    t.start()
    return t
