"""Implied volatility and greeks, computed here instead of taken from a vendor.

Why we compute it (18-Aug-2026)
------------------------------
Dhan ships an `implied_volatility` with its MCX chain and we were printing it.
It is wrong, and provably so: at crude 8100, both legs heavily traded, Dhan said
CE 46.36% and PE 56.12%. Put-call parity makes a 9.8 point gap at one strike
impossible. Solving each of Dhan's IVs back for the underlying it implies gives
8146 and 8145 - so Dhan's maths is fine and its INPUT is not. It is pricing a
September option off the August future. IBKR, which resolves the right month,
returns 48.71% for both legs of the US ATM - gap zero, which is what a correct
calculation looks like.

Nobody sells NSE IV at all (Angel gives bid/ask/ltp/OI and no greeks), so the
NSE side has to be computed regardless. Same code serves both.

The client specified the inputs himself, and they are right: underlying = the
FUTURE price, interest and dividend both zero. Black-Scholes with a futures
underlying and no carry is Black-76, which is the market convention for options
on futures. The calculator page keeps r and q as real fields so it reproduces
option-price.com exactly, which is the client's reference.

The one thing that must not be got wrong
----------------------------------------
WHICH future. This is the entire Dhan bug. A September option rides the
September future, not the front month - and on this app the front month is what
the screen shows. Measured 18-Aug in one simultaneous read of crude:

    NSE  parity forward 8099.2 | front future 8160.0 (off 60.8) | next 8100.0 (off 0.8)
    MCX  parity forward 8113.2 | front future 8163.0 (off 49.8) | next 8105.0 (off 8.2)

So `forward_from_parity` derives the underlying from the option prices
themselves - a median over every strike quoting two-way on both wings. That is
self-calibrating: CE and PE then agree by construction, which is the property
that proves the answer right. The matching-month future is kept as a cross-check
rather than as the input, because a future can be stale or thin while parity
across twenty strikes cannot be.
"""
from __future__ import annotations

import math
from datetime import date, datetime
from statistics import median

# Bisection bounds. 500% sounds absurd until a far wing quotes 0.05/16.85, and
# the low end has to admit a nearly worthless option without dividing by zero.
_V_LO, _V_HI = 1e-4, 5.0
_ITERS = 100          # 5.0 halved 100 times is far past double precision
DAYS_YEAR = 365.0     # calendar days, matching the client's reference calculator


def years_to(expiry: str | None, now: datetime | None = None) -> float | None:
    """Time to expiry in years, counting the PART of today already gone.

    The client asked for this in his own notation: `days to expire - 0.04166 x
    time`, where 0.04166 is one hour as a fraction of a day. Whole days are the
    convention his reference calculator uses and they are visibly coarse: at 29
    days and three in the afternoon, dropping the elapsed 15 hours moves the ATM
    IV from 45.80% to 46.30%. Half a point is not noise on a screen built to be
    compared against another exchange.

    Returns None once there is no time left, because an expired option has no
    implied volatility and a tiny positive T would report a huge one.
    """
    if not expiry:
        return None
    s = str(expiry)[:10].replace("/", "-")
    try:
        exp = date.fromisoformat(s) if "-" in s else date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except (ValueError, IndexError):
        return None
    now = now or datetime.now()          # server runs in IST
    days = (exp - now.date()).days - (now.hour + now.minute / 60.0) / 24.0
    return (days / DAYS_YEAR) if days > 0 else None


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def price(S: float, K: float, T: float, v: float, call: bool,
          r: float = 0.0, q: float = 0.0) -> float:
    """Black-Scholes with continuous carry. r=q=0 and S=future is Black-76.

    Verified against the client's reference calculator to six decimals on its
    own example (S 77.5, K 100, 87 days, 25% vol, 5% rate, 1% yield): it returns
    call 0.088000 / put 21.587799, this returns 0.087999 / 21.587797.
    """
    if T <= 0 or v <= 0 or S <= 0 or K <= 0:
        intrinsic = (S - K) if call else (K - S)
        return max(0.0, intrinsic)
    s = v * math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * v * v) * T) / s
    d2 = d1 - s
    dq, dr = math.exp(-q * T), math.exp(-r * T)
    if call:
        return S * dq * _norm_cdf(d1) - K * dr * _norm_cdf(d2)
    return K * dr * _norm_cdf(-d2) - S * dq * _norm_cdf(-d1)


def greeks(S: float, K: float, T: float, v: float, call: bool,
           r: float = 0.0, q: float = 0.0) -> dict:
    """Per 1 unit of underlying; vega and theta per 1% and per day respectively.

    These carry the e^(-qT) factor, which is correct: delta is d(price)/d(S) and
    the price itself is discounted by it. The client's reference calculator
    omits it from its greeks while including it in its prices - remove the factor
    from ours and its numbers reappear to six decimals (delta 0.025635, vega
    0.022584 on its own example). We keep the consistent version. It makes no
    difference to this app in any case: with the dividend yield at zero, which is
    what the client specified and what a futures option requires, e^(-qT) is 1.
    """
    if T <= 0 or v <= 0 or S <= 0 or K <= 0:
        return {"delta": None, "gamma": None, "vega": None, "theta": None, "rho": None}
    s = v * math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * v * v) * T) / s
    d2 = d1 - s
    dq, dr = math.exp(-q * T), math.exp(-r * T)
    n1 = _norm_pdf(d1)
    delta = dq * _norm_cdf(d1) if call else -dq * _norm_cdf(-d1)
    theta_y = (-S * dq * n1 * v / (2 * math.sqrt(T))
               + (q * S * dq * _norm_cdf(d1) - r * K * dr * _norm_cdf(d2)) * (1 if call else 0)
               + (r * K * dr * _norm_cdf(-d2) - q * S * dq * _norm_cdf(-d1)) * (0 if call else 1))
    return {
        "delta": round(delta, 6),
        "gamma": round(dq * n1 / (S * s), 8),
        # per one percentage point of vol, which is how a person reads vega
        "vega": round(S * dq * n1 * math.sqrt(T) / 100.0, 6),
        "theta": round(theta_y / DAYS_YEAR, 6),
        "rho": round((K * T * dr * _norm_cdf(d2) if call
                      else -K * T * dr * _norm_cdf(-d2)) / 100.0, 6),
    }


def implied_vol(market: float, S: float, K: float, T: float, call: bool,
                r: float = 0.0, q: float = 0.0) -> float | None:
    """Volatility in PERCENT that reprices `market`, or None if there is none.

    None is the honest answer more often than people expect. A quote below
    intrinsic has no implied vol at any volatility - no amount of movement makes
    an option worth less than exercising it - and a stale wing quote on a thin
    NSE strike does exactly that. Returning a number there would be inventing
    one, and the whole point of this file is that a plausible wrong number is
    worse than a blank.
    """
    if market is None or market <= 0 or T <= 0 or S <= 0 or K <= 0:
        return None
    lo_px = price(S, K, T, _V_LO, call, r, q)      # the intrinsic floor
    hi_px = price(S, K, T, _V_HI, call, r, q)
    if market <= lo_px or market >= hi_px:
        return None
    lo, hi = _V_LO, _V_HI
    for _ in range(_ITERS):
        mid = 0.5 * (lo + hi)
        if price(S, K, T, mid, call, r, q) < market:
            lo = mid
        else:
            hi = mid
    return round(0.5 * (lo + hi) * 100.0, 2)


def coarse_strikes(strikes: list[float], atm: float | None, count: int,
                   every: int = 2) -> list[float]:
    """`count` strikes around the money, taking every `every`-th rung of the ladder.

    The next month gets half the lines the front one does, so the client asked
    for it to skip every other strike - "100 ni strike" on MCX crude, whose
    ladder steps 50. Same fifteen strikes, twice the price covered: crude's next
    month went from 7550-8250 to 7200-8600, which is the range the front month
    already shows.

    The rungs are chosen as multiples of `every x step` rather than by counting
    outward from the money, so they land on round numbers a person reads at a
    glance - 7200, 7300, 7400 - instead of wherever the ATM happens to sit.

    The ATM is always included even when it is not a round rung (gas can sit at
    275 on a 10-step ladder), and the farthest rung is dropped to pay for it, so
    `count` is exact. That matters upstream: each strike is two IBKR market-data
    lines and the account has seven to spare.
    """
    ks = sorted({s for s in strikes if s})
    if len(ks) < 3 or count <= 0:
        return ks[:count]
    step = min((round(b - a, 6) for a, b in zip(ks, ks[1:]) if b > a), default=0)
    coarse = step * every
    if not coarse:
        return ks[:count]
    rungs = [s for s in ks if abs(s / coarse - round(s / coarse)) < 1e-6]
    # A ladder with no round rung at this spacing falls back to every strike -
    # better a narrow chain than an empty one.
    if len(rungs) < count:
        rungs = ks
    if atm is None:
        atm = ks[len(ks) // 2]
    near = sorted(rungs, key=lambda s: abs(s - atm))[:count]
    if atm in ks and atm not in near:
        near = near[:-1] + [atm]          # buy the ATM's place from the farthest
    return sorted(near)


def forward_from_parity(pairs: list[tuple[float, float, float]]) -> float | None:
    """The underlying the option prices themselves imply: median of K + C - P.

    `pairs` is (strike, call_price, put_price) for strikes quoting two-way on
    BOTH wings. With r=0 put-call parity is exact, so every usable strike votes
    for the same forward and they agree closely when the chain is healthy - 11
    NSE strikes spanned 8127.9 to 8133.0 on 18-Aug, a five rupee spread across a
    thousand rupees of strikes.

    Median, not mean: one stale wing shifts a mean and cannot shift a median.
    """
    votes = [k + c - p for k, c, p in pairs if k and c and p]
    return round(median(votes), 2) if votes else None


def spread(votes: list[float]) -> float | None:
    """How far apart the parity votes are - the chain's own consistency check."""
    return round(max(votes) - min(votes), 2) if votes else None
