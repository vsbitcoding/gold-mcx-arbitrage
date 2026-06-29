# Gold MCX Arbitrage

Real-time spread-monitoring and **paper-trading** dashboard for MCX commodity
pair trading, with live Nifty/Sensex options spreads and base-metal calendar
spreads. Live at **https://arbitrage.bitcoding.ai**.

> Paper trading only — no real broker orders are ever placed. The Dhan
> connection is **market-data only**.

---

## Features

### Live spread monitor (Dashboard)
Three tabs in one "Live Spread Monitor":

| Tab | What it shows |
|-----|---------------|
| **Cross Pairs** | Two different instruments, same expiry month. Gold families (Petal / Guinea / Ten / Mini) + Mini→Full families (GOLDM×GOLD, SILVERM×SILVER, SILVERMIC×SILVERM) + SILVER100×SILVER MIC (10:1) and SILVER100×SILVER MINI (50:1). |
| **Calendar Spreads** | Same instrument, adjacent months (far vs near). Gold, Silver, Silver Mini/Mic, SILVER100. |
| **Metal** | **Watch-only** base-metal calendar spreads — Copper, Aluminium (+Mini), Zinc (+Mini), Nickel, Lead (+Mini). 4 columns: Metal · Month · Difference · % Spread. |

Each cross/calendar pair shows a **Decrease** and **Increase** spread:

```
Decrease Spread = (Big.bid × big_mult) − (Small.ask × small_mult)
Increase Spread = (Big.ask × big_mult) − (Small.bid × small_mult)
```

### Paper-trading engine
- **Multiple ladders per pair-side** — each ladder has its own entry / exit /
  lifetime weight-cap / armed state and fires independently.
- **Lifetime weight cap** (cap-only-increases) per ladder; the ladder locks when
  total fired grams reach the cap until the cap is raised.
- **Account margin cap** — pre-fire check against `balance × max_usage%`, using
  per-security SPAN margin where available (else instrument-% × LTP). Orphaned
  positions (whose ladder was cleared) are excluded so they can't dead-lock the cap.
- Auto entry trigger + auto exit; **manual square-off by weight (FIFO)**.
- Daily auto-clear of ladders at **23:35 IST** (open positions untouched);
  7-day history retention.

### Nifty / Sensex PE-options spread tab
- 3 weekly expiries × (ATM + 9 OTM puts), dynamic ATM that follows spot.
- Sensex strike paired to each Nifty strike by moneyness distance
  (`round_to_100(sensex_spot − (nifty_spot − nifty_strike) × 3.2)`).
- Columns: Strike (N/S) · ITM (N/S) · Variation · per-week (N bid · S ask · Spread).
- Spread = `(Nifty PE bid × 325) − (Sensex PE ask × 100)`.

### Calculator
Live GOLDBEES / SILVERBEES ETF vs MCX Gold/Silver fair-value comparison.

### Other
- **Activity** audit log (every fire / exit / cap change / block reason).
- **Settings** — account balance, max-usage %, per-pair margin.
- Persistent quotes in DB → dashboard never goes blank across restarts/holidays.
- Light/dark theme, density toggle, active-tab persistence, mobile-responsive.

### Public API (for mobile apps)
Read-only, API-key auth (`X-API-Key` header or `?api_key=`):

| Endpoint | Purpose |
|----------|---------|
| `GET /api/v1/health` | Uptime + market-open status (no auth) |
| `GET /api/v1/spreads` / `/spread-groups` | Cross + calendar spreads |
| `GET /api/v1/calculator` | ETF-vs-MCX raw data |
| `GET /api/v1/options-spread` | Nifty/Sensex PE options table |
| `GET /api/v1/metals-spread` | Base-metal calendar spreads |
| `WS  /api/v1/stream` | Live spread stream (change-only push + heartbeat) |

---

## Live feed & reliability

- Dhan WebSocket MarketFeed; access token auto-generated via **TOTP + MPIN**
  (refreshes daily, ~24h validity).
- Watchdog: token-expiry refresh, silent-feed reconnect, daily post-open
  re-subscription (~09:17 IST).
- **429 / rate-limit backoff** — on Dhan rate-limit the SDK is force-closed and
  a 15-min cool-down applied (avoids extending Dhan's ban by hammering it).
- One wide static strike-subscription window per day (no mid-session
  re-subscription churn).

> **Data API subscription required** — the live feed needs Dhan's *Data APIs*
> plan (separate from the trading subscription, auto-renews ~₹499+GST/month). If
> it lapses, the WS returns `806 Data APIs not Subscribed` and only the feed
> breaks (trading account stays fine).

---

## Stack

- **Backend:** FastAPI (Python 3.12), SQLAlchemy
- **Database:** SQLite (WAL mode, `busy_timeout`, batched quote persistence)
- **Frontend:** React + Vite
- **Live data:** Dhan HQ WebSocket MarketFeed + REST
- **Reverse proxy:** Nginx + Let's Encrypt SSL
- **Process:** systemd (`arbi-backend.service`), VPS at arbitrage.bitcoding.ai

---

## Project layout

```
backend/app/
  main.py                 FastAPI app + router registration
  config.py               multipliers, grams/lot, weight caps
  database.py             SQLite engine + WAL pragmas + auto-migrations
  models.py               SQLAlchemy models
  routes/                 auth, pairs, positions, history, ladders, activity,
                          calculator, options, metals, config, feed, ws, public_v1
  services/
    dhan_auth.py          TOTP token generation
    dhan_feed.py          WebSocket feed loop + watchdog + reconnect/backoff
    instrument_resolver.py  resolves MCX contracts from Dhan scrip master
    pair_generator.py     builds cross + calendar pair configs
    pair_registry.py      live pair registry
    spread_engine.py      per-pair decrease/increase spread math
    trade_engine.py       entry/exit evaluation + paper fills (2-pass, O(1)/tick)
    options_service.py    Nifty/Sensex PE-options spread
    metals_service.py     base-metal calendar spreads (watch-only)
    margin_service.py     SPAN-aware margin
    market_data.py        in-memory quote store + batched DB persistence
frontend/src/
  App.jsx                 top-level layout + page routing + WS/REST refresh
  components/             Header, StatCards, LiveSpreadTable, OptionsSpread,
                          MetalSpread, Calculator, Activity, Settings, ...
  api/                    REST client + live WebSocket
deploy/                   deploy.sh, nginx config, systemd unit
```

---

## Setup

Copy `.env.example` → `.env` and fill Dhan credentials
(`DHAN_CLIENT_ID`, `DHAN_MPIN`, `DHAN_TOTP_SECRET`, `PUBLIC_API_KEYS`, …).

```bash
# Backend
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium   # one-time: browser for the daily MCXCCL bullion-stock scrape (~300 MB)
uvicorn app.main:app --reload

# Frontend
cd frontend
npm install
npm run dev
```

> **Bullion Stock tab (MCXCCL):** a once-a-day job scrapes the warehouse
> "Eligible Units" PDF (isolated subprocess, runs at 18:00 IST) and snapshots the
> live spread, then shows stock-vs-spread correlation. It needs `playwright
> install chromium` in the backend venv. If the browser is missing the job logs a
> warning and the rest of the app is unaffected. Disable with `BULLION_STOCK_ENABLED=false`.

## Deploy

```bash
# on the server, after pushing to main:
cd /home/vs.bitcoding/gold-mcx-arbitrage
git fetch && git reset --hard origin/main
./deploy/deploy.sh   # rebuilds frontend; restarts backend only if backend changed
```
