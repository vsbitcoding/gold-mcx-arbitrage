"""Live mean-reversion SIGNAL engine (watch-only — no trade firing).

Validated by backtest on gold cross pairs: when a cross-spread reaches an
extreme (±1.5σ of its 20-day average), it reverts toward the average ~82% of
the time (avg +400 pts over ~6 days).

Daily  : pull recent daily closes from Dhan → build each cross pair's band
         (mean ± 1.5σ over the last 20 clean daily closes; target = mean).
Live   : compare each pair's current mid-spread to its band → auto-fire a
         signal (direction + entry + target). Display / alert only.

Direction:
  mid ≥ upper band  → "narrow"  (spread is high → expected to fall to mean)
  mid ≤ lower band  → "widen"   (spread is low  → expected to rise to mean)
"""
from __future__ import annotations

import logging
import statistics
import threading
import time
from datetime import datetime, timedelta

from app.config import MULTIPLIERS, settings
from app.services import dhan_auth, pair_registry

log = logging.getLogger("signal_service")

WINDOW = 20            # rolling days for mean / sd
ENTRY_K = 1.5          # entry threshold in σ (validated)
LOOKBACK_DAYS = 120    # daily history to pull

_bands: dict[str, dict] = {}    # pair_name -> {mean, sd, upper, lower, target, n}
_active: dict[str, dict] = {}   # pair_name -> {direction, entry, target, started}
_state: dict = {"last_refresh": None, "bands": 0}


def _dhan():
    from dhanhq import dhanhq
    from dhanhq.dhan_context import DhanContext
    # Re-uses the feed's in-process cached token (no extra Dhan login).
    tok = dhan_auth.get_token(settings.DHAN_CLIENT_ID, settings.DHAN_MPIN, settings.DHAN_TOTP_SECRET)
    return dhanhq(DhanContext(tok.client_id, tok.access_token))


def _daily_closes(dhan, sid: str) -> dict:
    to = datetime.now().strftime("%Y-%m-%d")
    frm = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    res = dhan.historical_daily_data(
        security_id=str(sid), exchange_segment="MCX_COMM",
        instrument_type="FUTCOM", from_date=frm, to_date=to,
    )
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
    """Drop obvious data-glitch spikes (robust median / MAD) + listing edge."""
    if len(vals) < 10:
        return vals
    vals = vals[3:]                    # trim early listing-illiquidity days
    med = statistics.median(vals)
    mad = statistics.median([abs(v - med) for v in vals]) or 1.0
    return [v for v in vals if abs(v - med) <= 12 * mad]


def refresh_bands() -> int:
    pairs = [p for p in pair_registry.get_pairs() if p.get("type") == "cross"]
    if not pairs:
        return 0
    try:
        dhan = _dhan()
    except Exception as e:
        log.warning("signal refresh: dhan/token failed: %s", e)
        return 0

    cache: dict[str, dict] = {}
    def closes(sid):
        sid = str(sid)
        if sid not in cache:
            try:
                cache[sid] = _daily_closes(dhan, sid)
            except Exception as e:
                log.warning("hist pull failed sid=%s: %s", sid, e)
                cache[sid] = {}
        return cache[sid]

    new: dict[str, dict] = {}
    for p in pairs:
        big = closes(p["big_security_id"])
        small = closes(p["small_security_id"])
        if not big or not small:
            continue
        bm = MULTIPLIERS.get(p["big"], 1.0)
        sm = MULTIPLIERS.get(p["small"], 1.0)
        days = sorted(set(big) & set(small))
        vals = _clean([round(big[d] * bm - small[d] * sm, 2) for d in days])
        if len(vals) < WINDOW:
            continue
        win = vals[-WINDOW:]
        mean = statistics.mean(win)
        sd = statistics.pstdev(win)
        if sd <= 0:
            continue
        new[p["name"]] = {
            "mean": round(mean, 1), "sd": round(sd, 1),
            "upper": round(mean + ENTRY_K * sd, 1),
            "lower": round(mean - ENTRY_K * sd, 1),
            "target": round(mean, 1), "n": len(win),
        }
    _bands.clear()
    _bands.update(new)
    _state["last_refresh"] = datetime.now().isoformat(timespec="seconds")
    _state["bands"] = len(new)
    log.info("Signal bands refreshed: %d cross pairs", len(new))
    return len(new)


def _mid(snap):
    dec, inc = snap.get("decrease_spread"), snap.get("increase_spread")
    if dec is None or inc is None:
        return None
    return (dec + inc) / 2.0


def evaluate_all(snaps: list[dict]) -> dict:
    """Update active-signal state from live snaps; return {pair_name: signal}."""
    out: dict[str, dict] = {}
    now = time.time()
    seen = set()
    for s in snaps:
        if s.get("type") != "cross":
            continue
        name = s.get("name")
        band = _bands.get(name)
        if not band:
            continue
        mid = _mid(s)
        if mid is None:
            continue
        sd = band["sd"] or 1.0
        z = (mid - band["mean"]) / sd
        direction = None
        if mid >= band["upper"]:
            direction = "narrow"
        elif mid <= band["lower"]:
            direction = "widen"
        if direction is None:
            _active.pop(name, None)
            continue
        seen.add(name)
        prev = _active.get(name)
        if not prev or prev["direction"] != direction:
            prev = {"direction": direction, "entry": round(mid, 1),
                    "target": band["target"], "started": now}
            _active[name] = prev
        out[name] = {
            "name": name, "label": s.get("label"), "expiry_label": s.get("expiry_label"),
            "direction": direction, "entry": prev["entry"], "target": band["target"],
            "current": round(mid, 1), "z": round(z, 2),
            "age_min": int((now - prev["started"]) / 60),
            "mean": band["mean"], "upper": band["upper"], "lower": band["lower"],
        }
    for name in list(_active):
        if name not in seen:
            _active.pop(name, None)
    return out


def get_active_signals() -> list[dict]:
    from app.services.spread_engine import compute_all
    sigs = evaluate_all(compute_all())
    return sorted(sigs.values(), key=lambda x: -abs(x["z"]))


def status() -> dict:
    return {"bands": _state["bands"], "last_refresh": _state["last_refresh"],
            "active": len(_active), "window": WINDOW, "entry_sigma": ENTRY_K}


def _loop() -> None:
    # Wait until the feed has resolved pairs (token also becomes available).
    for _ in range(60):
        if pair_registry.get_pairs():
            break
        time.sleep(5)
    time.sleep(5)
    last_date = None
    while True:
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            if today != last_date and _bands_ready_or_retry():
                last_date = today
        except Exception as e:
            log.exception("signal loop: %s", e)
        time.sleep(300)


def _bands_ready_or_retry() -> bool:
    """Refresh bands; return True only if at least one band was built (so a
    failed/empty pull retries on the next tick instead of waiting a full day)."""
    return refresh_bands() > 0


def start_in_background() -> threading.Thread:
    t = threading.Thread(target=_loop, daemon=True, name="signal_service")
    t.start()
    return t
