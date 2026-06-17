"""Fire-once mean-reversion SIGNAL engine with historical probability + accuracy
tracking (watch-only — no trade firing).

Design (kept fully off the live-feed hot path):
  • DAILY batch (background): pull each front-month cross pair's full available
    daily history (~1+ yr) → compute (a) the current band (20-day mean ± 1.5σ)
    and (b) a per-pair PROBABILITY table — walk-forward, bucketed by how
    stretched the spread was (z), what % reached target within MAXHOLD days.
    Heavy, but runs once/day and only stores a tiny summary in memory.
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
from datetime import datetime, timedelta

from app.config import MULTIPLIERS, settings
from app.database import SessionLocal
from app.models import Signal
from app.services import dhan_auth, pair_registry

log = logging.getLogger("signal_service")

WINDOW = 20                       # rolling days for mean / sd (the band)
ENTRY_K = 1.5                     # fire threshold in σ
LOOKBACK_DAYS = 800               # request long; API returns the contract's full life
MAXHOLD_DAYS = 10                 # trading days to reach target = "right" (for probability)
DEBOUNCE_SECONDS = 300            # mid must HOLD beyond band 5 min before firing (kills fast spikes)
MAX_AGE_SECONDS = 14 * 24 * 3600  # live signal expires (=wrong) if target not hit in ~10 trading days
MIN_HOLD_SECONDS = 60 * 60        # a signal that hits target faster than this = noise → discarded
LIQ_K = 1.0                       # skip firing if the spread's bid/ask width > LIQ_K × σ (illiquid)
TICK_SECONDS = 3
MIN_BUCKET_N = 5                  # min samples to trust a z-bucket's probability
Z_BUCKETS = [(1.5, 2.0), (2.0, 2.5), (2.5, 99.0)]

# Strategy search grid for "short + accurate + frequent". Each combo:
#   k = entry threshold (σ) · t = target distance from entry (σ) · s = stop distance (σ)
#   mean=True → target is the rolling mean (full reversion), stop 1:1 = the CURRENT live strategy
STRAT_GRID = [
    {"name": "CURRENT (1.5σ in · full revert · 1:1)", "k": 1.5, "mean": True},
    {"name": "prev best: 1.25σ in · 1.0σ tgt · 2.0σ stop", "k": 1.25, "t": 1.0, "s": 2.0},
    {"name": "1.5σ in · 0.5σ tgt · 2.5σ stop",  "k": 1.5,  "t": 0.5,  "s": 2.5},
    {"name": "1.5σ in · 0.75σ tgt · 2.5σ stop", "k": 1.5,  "t": 0.75, "s": 2.5},
    {"name": "1.5σ in · 1.0σ tgt · 2.5σ stop",  "k": 1.5,  "t": 1.0,  "s": 2.5},
    {"name": "1.5σ in · 1.0σ tgt · 3.0σ stop",  "k": 1.5,  "t": 1.0,  "s": 3.0},
    {"name": "1.25σ in · 0.5σ tgt · 2.5σ stop", "k": 1.25, "t": 0.5,  "s": 2.5},
    {"name": "1.25σ in · 0.75σ tgt · 2.5σ stop","k": 1.25, "t": 0.75, "s": 2.5},
    {"name": "1.25σ in · 1.0σ tgt · 2.5σ stop", "k": 1.25, "t": 1.0,  "s": 2.5},
    {"name": "1.75σ in · 1.0σ tgt · 2.0σ stop", "k": 1.75, "t": 1.0,  "s": 2.0},
    {"name": "1.75σ in · 1.0σ tgt · 2.5σ stop", "k": 1.75, "t": 1.0,  "s": 2.5},
]

_model: dict[str, dict] = {}      # pair_name -> {mean,sd,upper,lower,target,n, buckets, overall}
_active: dict[str, dict] = {}     # pair_name -> open frozen signal (mirrors DB open row)
_pending: dict[str, dict] = {}    # pair_name -> {direction, since}  (debounce buffer)
_state: dict = {"last_refresh": None, "models": 0}
_bt_grid: list | None = None      # backtest of every STRAT_GRID combo over ~1yr history


# ───────────────────────── Dhan history ─────────────────────────
def _dhan():
    from dhanhq import dhanhq
    from dhanhq.dhan_context import DhanContext
    tok = dhan_auth.get_token(settings.DHAN_CLIENT_ID, settings.DHAN_MPIN, settings.DHAN_TOTP_SECRET)
    return dhanhq(DhanContext(tok.client_id, tok.access_token))


def _daily_closes(dhan, sid: str) -> dict:
    to = datetime.now().strftime("%Y-%m-%d")
    frm = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    res = dhan.historical_daily_data(security_id=str(sid), exchange_segment="MCX_COMM",
                                     instrument_type="FUTCOM", from_date=frm, to_date=to)
    data = res.get("data", res) if isinstance(res, dict) else res
    closes = data.get("close") if isinstance(data, dict) else None
    ts = (data.get("timestamp") or data.get("start_Time")) if isinstance(data, dict) else None
    out = {}
    for t, c in zip(ts or [], closes or []):
        try:
            out[datetime.fromtimestamp(float(t)).strftime("%Y-%m-%d")] = c
        except Exception:
            pass
    return out


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
    ±ENTRY_K σ event, hit = reverted to the rolling mean within MAXHOLD_DAYS."""
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
            for j in range(1, MAXHOLD_DAYS + 1):
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
                            "n": len(sel), "avg_days": round(statistics.mean([r[2] for r in sel]), 1)})
        else:
            buckets.append({"zmin": zmin, "zmax": zmax, "rate": None, "n": 0, "avg_days": None})
    overall = None
    if res:
        overall = {"rate": round(sum(1 for r in res if r[1]) / len(res) * 100, 1),
                   "n": len(res), "avg_days": round(statistics.mean([r[2] for r in res]), 1)}
    return buckets, overall


def _combo_bt(vals: list, k: float, t: float | None = None,
              s: float | None = None, target_mean: bool = False) -> tuple:
    """Walk-forward backtest of one strategy combo (no lookahead).

    Fire when |z| ≥ k. Then:
      target_mean=True → target = rolling mean (full reversion), stop 1:1 (2*entry−mean).
      else             → target = entry moved `t`·σ toward the mean;
                         stop   = entry moved `s`·σ away from the mean.
    Win = target reached before stop within MAXHOLD_DAYS.
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
                stop = 2 * entry - m
            else:
                target = entry - t * sd if short else entry + t * sd
                stop = entry + s * sd if short else entry - s * sd
            outcome, j = None, 0
            for j in range(1, MAXHOLD_DAYS + 1):
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


def _summarize_bt(win: int, loss: int, timeout: int, days: list) -> dict:
    decisive = win + loss
    total = win + loss + timeout
    return {
        "trades": total, "win": win, "loss": loss, "timeout": timeout,
        "win_rate": round(win / decisive * 100, 1) if decisive else None,
        "timeout_pct": round(timeout / total * 100, 1) if total else None,
        "avg_days": round(statistics.mean(days), 1) if days else None,
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


def refresh_model() -> int:
    global _model, _bt_grid
    cross = [p for p in pair_registry.get_pairs() if p.get("type") == "cross"]
    if not cross:
        return 0
    groups: dict = defaultdict(list)
    for p in cross:
        groups[p.get("label")].append(p)
    pairs = [min(ps, key=lambda x: x.get("name", "")) for ps in groups.values()]
    try:
        dhan = _dhan()
    except Exception as e:
        log.warning("signal model: dhan/token failed: %s", e)
        return 0

    cache: dict[str, dict] = {}
    def closes(sid):
        sid = str(sid)
        if sid in cache:
            return cache[sid]
        c = {}
        for attempt in range(3):
            try:
                c = _daily_closes(dhan, sid)
            except Exception as e:
                log.warning("hist pull failed sid=%s: %s", sid, e)
                c = {}
            if c:
                break
            time.sleep(1.0 + attempt)
        cache[sid] = c
        time.sleep(0.45)
        return cache[sid]

    new: dict[str, dict] = {}
    grid_acc = [[0, 0, 0, []] for _ in STRAT_GRID]   # per-combo (win, loss, timeout, days)
    for p in pairs:
        big = closes(p["big_security_id"])
        small = closes(p["small_security_id"])
        if not big or not small:
            continue
        bm = MULTIPLIERS.get(p["big"], 1.0)
        sm = MULTIPLIERS.get(p["small"], 1.0)
        days = sorted(set(big) & set(small))
        vals = _clean([round(big[d] * bm - small[d] * sm, 2) for d in days])
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
            "mean": round(mean, 1), "sd": round(sd, 1),
            "upper": round(mean + ENTRY_K * sd, 1), "lower": round(mean - ENTRY_K * sd, 1),
            "target": round(mean, 1), "n": len(vals),
            "buckets": buckets, "overall": overall,
        }
        # strategy-grid backtest (CPU only on the already-fetched vals — no extra Dhan calls)
        for gi, g in enumerate(STRAT_GRID):
            w, l, t, d = _combo_bt(vals, g["k"], g.get("t"), g.get("s"), g.get("mean", False))
            a = grid_acc[gi]
            a[0] += w; a[1] += l; a[2] += t; a[3].extend(d)
    _model = new   # atomic reference swap — readers never see a half-built map
    grid_out = []
    for gi, g in enumerate(STRAT_GRID):
        sm = _summarize_bt(*grid_acc[gi])
        sm["name"] = g["name"]
        if not g.get("mean") and g.get("t") and g.get("s"):
            wr = (sm["win_rate"] or 0) / 100.0
            sm["rr"] = f"{g['t']}:{g['s']}"
            sm["expectancy_sigma"] = round(wr * g["t"] - (1 - wr) * g["s"], 3)  # avg σ gained per trade
        grid_out.append(sm)
    _bt_grid = grid_out
    _state["last_refresh"] = datetime.now().isoformat(timespec="seconds")
    _state["models"] = len(new)
    log.info("Signal model refreshed: %d pairs. Strategy grid backtested (%d combos).", len(new), len(STRAT_GRID))
    return len(new)


# ───────────────────────── live state machine (single writer) ─────────────────────────
def _mid(snap):
    dec, inc = snap.get("decrease_spread"), snap.get("increase_spread")
    if dec is None or inc is None:
        return None
    return (dec + inc) / 2.0


def _too_noisy(s, sd):
    """Liquidity guard: True when the spread's bid/ask width (increase − decrease)
    is wide vs the band's σ → illiquid pair, the mid is unreliable, so any signal
    would be noise. Keeps the fast junk signals (e.g. Silver Mic/Mini) from firing."""
    dec, inc = s.get("decrease_spread"), s.get("increase_spread")
    if dec is None or inc is None:
        return True
    return bool(sd) and sd > 0 and (inc - dec) > LIQ_K * sd


def _load_open():
    db = SessionLocal()
    try:
        changed = False
        for r in db.query(Signal).filter(Signal.status == "open").all():
            if r.stop_spread is None and r.entry_spread is not None and r.target_spread is not None:
                r.stop_spread = round(2 * r.entry_spread - r.target_spread, 1)   # backfill 1:1 stop
                changed = True
            _active[r.pair_name] = {
                "id": r.id, "direction": r.direction, "entry": r.entry_spread,
                "target": r.target_spread, "stop": r.stop_spread, "probability": r.probability,
                "z_at_entry": r.z_at_entry, "expected_days": r.expected_days,
                "label": r.label, "expiry_label": r.expiry_label,
                "started": r.fired_at.timestamp() if r.fired_at else time.time(),
            }
        if changed:
            db.commit()
    finally:
        db.close()


def _tick():
    """Single-threaded writer: fire new signals + resolve open ones. ~3s cadence."""
    from app.services.spread_engine import compute_all
    snaps = {s["name"]: s for s in compute_all() if s.get("type") == "cross"}
    now = time.time()
    db = None
    try:
        for name, model in _model.items():
            s = snaps.get(name)
            mid = _mid(s) if s else None
            a = _active.get(name)

            if a:  # track open signal → resolve (target = win, stop = loss, timeout)
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
                continue

            # no open signal → debounce + fire
            if mid is None:
                _pending.pop(name, None)
                continue
            direction = "narrow" if mid >= model["upper"] else "widen" if mid <= model["lower"] else None
            if direction is None or _too_noisy(s, model["sd"]):
                _pending.pop(name, None)        # no extreme, or pair too illiquid → don't fire
                continue
            p = _pending.get(name)
            if p and p["direction"] == direction:
                if now - p["since"] >= DEBOUNCE_SECONDS:
                    sd = model["sd"] or 1.0
                    z = (mid - model["mean"]) / sd
                    prob, exp_days = _prob_for(model, z)
                    entry = round(mid, 1)
                    target = model["target"]
                    stop = round(2 * entry - target, 1)   # 1:1 — stop as far past entry as target is before it
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

        # expire orphan open signals whose pair is gone (rolled expiry)
        for name in list(_active):
            if name not in _model and (now - _active[name]["started"]) > MAX_AGE_SECONDS:
                db = db or SessionLocal()
                row = db.get(Signal, _active[name]["id"])
                if row and row.status == "open":
                    row.status = "expired"
                    row.resolved_at = datetime.utcnow()
                    row.days_held = round((now - _active[name]["started"]) / 86400.0, 2)
                    db.commit()
                _active.pop(name, None)
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
        "stop": a.get("stop"), "rr": "1:1",
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
        if mid is not None and model.get("sd"):
            cur, z = round(mid, 1), round((mid - model["mean"]) / model["sd"], 2)
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
            "open": len(_active), "window": WINDOW, "entry_sigma": ENTRY_K,
            "maxhold_days": MAXHOLD_DAYS,
            "pairs": sorted({m.get("label") for m in _model.values() if m.get("label")}),
            "backtest_grid": _bt_grid}        # strategy search: each combo's win-rate / avg-days / trades


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
    while True:
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            if today != last_model_date:
                if refresh_model() > 0:
                    last_model_date = today
            if _model:
                _tick()
        except Exception as e:
            log.exception("signal loop: %s", e)
        time.sleep(TICK_SECONDS)


def start_in_background() -> threading.Thread:
    t = threading.Thread(target=_loop, daemon=True, name="signal_service")
    t.start()
    return t
