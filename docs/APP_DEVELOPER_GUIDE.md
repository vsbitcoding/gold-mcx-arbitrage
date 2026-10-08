# Gurukrupa Bullion App: Complete Feature Guide (08-Oct-2026)

This guide lists every page of the web dashboard (https://arbitrage.bitcoding.ai), which ones the
mobile app already shows, and exactly how to build the rest. It is written so that you, or the AI
coding assistant you work with, can implement all remaining screens from this file alone.

**Instructions for the AI assistant reading this file**

1. Read the whole file before writing code. Then implement Part 3 (fixes to existing screens) and
   Part 4 (new screens) in the order given.
2. The server already computes every number (spreads, differences, IV, P&L, ATM, matched strikes).
   Display what the API returns. Do not recompute it in the app, except where a section says
   "computed in the app".
3. `null` means "no data right now" (no buyer or seller, market closed, contract not listed). Always
   show `-` for `null`. Never show `0` in its place, and never hide the row.
4. Keep each screen's layout the same as the website: same sections, same columns, same order,
   same labels. Reuse the app's existing renderers where a section says the shape is shared.
5. All endpoints are read-only `GET`, except the two backtests and device registration, which are
   `POST`. The app is watch-only: it never places or edits trades.

---

## Part 1. Connection rules (all endpoints)

| Item | Value |
|---|---|
| Base URL | `https://arbitrage.bitcoding.ai/api/v1` |
| Auth | Header `X-API-Key: <app key>` (or `?api_key=<app key>` for links and WebSockets). Use the key the app already has. |
| Times | `server_time` is UTC ISO 8601. Dates (`date`, `snap_date`, `expiry`) are IST `YYYY-MM-DD`. Slots (`10:00`, `15:30`) are IST. |
| Errors | `401` wrong or missing key. `400` bad parameter or backtest rule (`detail` says why). `404` nothing stored yet. `429` a backtest is already running: wait 3 to 5 s and retry. `5xx`: retry with backoff (2 s, 4 s, 8 s). |
| Market flag | Most live responses carry `market_open` (true/false). Use `/market-status` for the reason (closed, holiday). |

**How often to call** (this keeps the server light; please follow it)

| Kind | Endpoints | Rule |
|---|---|---|
| Live boards | `options-spread`, `gold-options-spread`, `calculator`, `making-price`, `bank-options`, `price-table`, `metals-spread`, `othercomm-spread`, `premium-inputs` | Every 2 s while the screen is visible. Stop when it is not. |
| Live, slower | `nse-mcx` 3 s, `crude-iv` 5 s, `nse-mcx/paper` 10 s, `market-status` 60 s and on app resume | While visible |
| Push streams | `stream` (cross / calendar), `international/stream` | WebSocket, see the existing docs |
| History, backtest, daily, spread history, bullion stock | everything else | Only when the user opens the screen or changes a filter. Never on a timer. |

Existing detailed specs (still valid, same server): `APP_NIFTY_SENSEX_API.md`,
`APP_OPTIONS_HISTORY_API.md`, `APP_GOLD_OPTIONS_API.md`, `APP_NSE_MCX_API.md`,
`APP_INTERNATIONAL_API.md`, `APP_BULLION_STOCK_API.md`, `APP_BRANDING.md` (colours and logo).

---

## Part 2. Status: web pages vs the app

Based on the server's request logs from 24-Sep to 08-Oct-2026.

| # | Web page | In the app today | To do |
|---|---|---|---|
| 1 | Cross Pair | Yes (card view + stream) | Add Spread History (4.9) |
| 2 | Calendar Spread | Yes | Add Spread History (4.9) |
| 3 | Metal Spread | Yes | - |
| 4 | Other Commodity Spread | Yes | - |
| 5 | Metal Price | Yes | - |
| 6 | ETF vs MCX | No | New screen (4.1) |
| 7 | Premium | Yes | - |
| 8 | Commodity Option | Gold only | Add Silver, Crude Oil, Natural Gas (3.1) |
| 9 | NSE vs MCX | No | New screen (4.3) |
| 10 | MCX vs NYMEX | No | New screen (4.4) |
| 11 | Making Price | No | New screen (4.2) |
| 12 | Bullion Stock | No | New screen (4.5) |
| 13 | COMEX + NYMEX | No | New screen (4.6) |
| 14 | IV Calculator | No | New screen (4.7) |
| 15 | Nifty / Sensex | Yes (live + history) | Since 3:16 PM card, history filters (3.2) |
| 16 | BANKEX / BANKNIFTY | No | New screen (4.8) |
| 17 | Signals | Yes (with push) | - |
| 18 | Auto Trades | No | Not for this app (Part 5) |
| - | Market badge (LIVE / CLOSED / HOLIDAY) | No | Add (3.3) |

---

## Part 3. Fixes to screens the app already has

### 3.1 Commodity Option: all four commodities

The app requests only `commodity=gold`. The same endpoint serves four commodities with the same
response shape, so the existing renderer works unchanged.

```
GET /gold-options-spread?commodity=gold | silver | crude | natgas
```

Add a selector at the top of the screen: **Gold | Silver | Crude Oil | Natural Gas** (the
response's `commodities` list names them). Keep the user's last choice on the phone.

### 3.2 Nifty / Sensex: the "Since 3:16 PM" card, and History filters

**Live screen.** `/options-spread` already returns two summary blocks. The website shows both as
cards, side by side:

1. **DAY CHANGE** (already in the app): `day_divergence`, `nifty_day_change`, `sensex_day_change`,
   `sensex_expected_change`.
2. **SINCE 3:16 PM** (missing): the same four numbers measured from the previous trading day's
   3:16 PM reading, in `ref_divergence`:

```json
"ref_divergence": {
  "ref_date": "2026-09-29", "ref_slot": "15:16",
  "nifty_ref": 22683.75, "sensex_ref": 72480.07,
  "nifty_change": -67.15, "sensex_change": -39.28,
  "sensex_expected_change": -214.88, "divergence": 175.6
}
```

Card layout, same as DAY CHANGE: big **Divergence** value, then **Nifty** and **Sensex** changes
stacked, then **Expected**. Title: `SINCE 3:16 PM` plus the reference day: write `YESTERDAY` when
`ref_date` is the previous calendar day, otherwise the date (`25 SEPT` on a Monday). Build the time
text from `ref_slot` (`15:16` is `3:16 PM`). Green for positive, red for negative. If
`ref_divergence.divergence` is `null`, hide this card.

**History screen.** `/options-history` returns the same `ref_divergence` block on every stored
board (boards from before 18-Aug-2026 have `null`, so show only DAY CHANGE there). Render both
cards on each board, exactly as on the live screen. For the "YESTERDAY" test on a history board,
compare `ref_date` with the board's own `snap_date`, not with today.

The app currently always asks for `weekday=mon&slot=15:00&side=below&weeks=7`. Add the website's
filters:

| Filter | Values | Parameter |
|---|---|---|
| Weekday | Mon, Tue, Wed, Thu, Fri | `weekday=mon..fri` |
| Time | All, 10:00 AM, 3:00 PM, 3:16 PM, 3:35 PM (3:15 PM and 3:25 PM are old labels, keep them as extra choices) | `slot=both`, `10:00`, `15:00`, `15:16`, `15:35`, `15:15`, `15:25` |
| How many | Last 4, Last 7, Last 12 | `weeks=4`, `7`, `12` |
| Side | Below ATM, Above ATM, Square off ITM | `side=below`, `above`, `squareoff` (same tabs as the live screen) |

Boards come newest first; with `slot=both` several boards share a date, so draw a day divider when
`snap_date` changes. Details: `APP_OPTIONS_HISTORY_API.md`.

### 3.3 Market badge (all screens)

```
GET /market-status        (every 60 s and when the app comes back to the foreground)
```

Example, as it reads on the morning of 20-Oct-2026 (Dussehra: NSE shut all day, MCX shut only in
the morning):

```json
{
  "server_time": "2026-10-20T04:30:00+00:00",
  "now": {
    "mcx": {"state": "holiday", "open": false, "label": "Holiday", "reason": "Dussehra (morning session)", "holiday": "Dussehra", "next_open": "2026-10-20T17:00:00+05:30"},
    "nse": {"state": "holiday", "open": false, "label": "Holiday", "reason": "Dussehra", "holiday": "Dussehra", "next_open": "2026-10-21T09:15:00+05:30"}
  },
  "sessions": {"nse": "09:15-15:40 IST", "mcx": "09:00-23:30 IST"},
  "upcoming_holidays": [
    {"date": "2026-10-20", "weekday": "Tuesday", "exchange": "MCX", "name": "Dussehra", "morning_closed": true, "evening_closed": false}
  ]
}
```

`state` is `open`, `closed` or `holiday`. Show a small badge in the header like the website:
green **LIVE**, grey **MARKET CLOSED**, or **HOLIDAY** with `reason`. Use `mcx` for MCX screens
and `nse` for Nifty / Sensex and BANKEX / BANKNIFTY. An MCX holiday can close only the morning or
only the evening session (`morning_closed`, `evening_closed`). Optional: a "Holidays" list from
`upcoming_holidays` (next 90 days).

---

## Part 4. New screens

### 4.1 ETF vs MCX (computed in the app)

```
GET /calculator          (every 2 s)
```

Returns, for `gold` and `silver`: `etf.ltp` (GOLDBEES / SILVERBEES), `mcx_full.ltp` with
`mcx_full.symbol` and `expiry`, and `defaults` (`multiplier`, `manual`, `divisor`).

Per metal (two cards, Gold and Silver):

```
value = (etf.ltp x multiplier + manual) / divisor
diff  = value - mcx_full.ltp
```

Defaults: Gold x 120000, manual 0, / 103. Silver x 31000, manual 0, / 30.9. The user can edit
multiplier, manual and divisor, and can type an ETF price manually instead of the live one; save
these on the phone. Show: ETF LTP, MCX LTP (with contract), calculated value, and `diff` (green
positive, red negative).

### 4.2 Making Price

```
GET /making-price                                   (every 2 s)
GET /making-price?factor=0.00402&petal=325&guinea=1000&ten=1400&silvermicro=3500
```

All parameters are optional; missing ones use the defaults (also returned in `defaults`). Store the
user's own factor and charges on the phone and send them on every call.

```json
{
  "server_time": "...", "market_open": true,
  "rows": [
    {"key": "petal", "label": "Mini → Petal", "base": "Gold Mini", "base_contract": "05 Nov 2026",
     "base_bid": 150000.0, "factor": 0.00402, "making_charge": 325.0, "multiplier": 10.0, "value": 3853.0},
    {"key": "guinea", "label": "Mini → Guinea", "...": "..."},
    {"key": "ten", "label": "Mini → Ten", "...": "..."},
    {"key": "silvermicro", "label": "Silver → Micro", "base": null, "making_charge": 3500.0, "value": 3500.0}
  ],
  "defaults": {"factor": 0.00402, "charges": {"petal": 325, "guinea": 1000, "ten": 1400, "silvermicro": 3500}},
  "formula": {"gold": "Gold Mini Bid x factor + making charge x multiplier", "silver": "making charge (flat)"}
}
```

Layout as the website: one editable **Gold factor** field at the top, then four cards. Each gold
card shows `Gold Mini Bid` (with `x factor`), `Making charge` (editable, with `x multiplier`) and
the big **value**. The Silver card shows only the editable charge and its value. `value` is `null`
when Gold Mini has no bid: show `-`.

### 4.3 NSE vs MCX

One screen with a commodity switch **Crude Oil | Natural Gas | Electricity**, a month switch
(near / next: `month=0|1`), and views **Live | History | Graph | Backtest | Paper**. Electricity has
only **Live | 1 Hr History**.

| View | Endpoint | Notes |
|---|---|---|
| Live | `GET /nse-mcx?commodity=crude\|natgas&month=0\|1&window=10` (3 s) | Future + option chain, NSE and MCX side by side, difference in rupees and percent. Full spec: `APP_NSE_MCX_API.md` section 1. |
| History (snapshots) | `GET /nse-mcx/history?commodity=&month=&slot=all\|10:00\|12:00\|14:00\|15:00\|16:00\|18:00\|20:00\|22:00\|23:15&days=7` | Stored boards, newest first, each `board` in the Live shape. `APP_NSE_MCX_API.md` section 2. |
| History (daily closes) | `GET /nse-mcx/daily/expiries?commodity=` then `GET /nse-mcx/daily?commodity=&expiry=<nse>` | Close against close since April 2024, per strike per day (see below). |
| Graph | `GET /nse-mcx/graph?commodity=&month=&side=ce\|pe&strike=<strike or future>&days=30` | One strike's `diff` (MCX bid - NSE ask) and `mid_diff` over time. Call once without `strike` to get `strike_options` for the picker. Draw `null` as a gap. |
| Backtest | `POST /nse-mcx/backtest` | See below. |
| Paper | `GET /nse-mcx/paper?commodity=` (10 s) | See below. |
| Electricity Live | `GET /nse-mcx?commodity=electricity&month=0\|1` (3 s) | Futures only, NSE vs MCX. |
| Electricity 1 Hr History | `GET /nse-mcx/elec-hourly?month=0\|1&days=30` | `rows[]`: `hour`, `nse`, `mcx`, `diff`, `pct`, one per hour since 02-Sep-2026. |

**Daily closes.** `/nse-mcx/daily/expiries` returns `expiries[]` items
`{nse, mcx, nse_traded_days, gap_days}`; show only expiries with `nse_traded_days > 0` (NSE options
that never traded have nothing to compare). `/nse-mcx/daily?expiry=<nse>` returns `futures`,
`strikes[]` and `rows[]` (one per strike per day). Optional filters: `type=CE|PE`, `strike=`,
`start=`, `end=` (`YYYY-MM-DD`). A whole expiry can be about 1.5 MB (4,000+ rows), so on the phone
let the user pick CE or PE and a strike first (`strikes[]` gives the list), then request with those
filters.

**Backtest.** Body = any of the rules below; send only what the user changed (missing rules take
the defaults, which come back in `params`). Show a "Running..." state; on `429` retry after 3 s.
These are the website's starting values for crude:

```json
POST /nse-mcx/backtest
{"commodity": "crude", "start": "2024-04-01", "end": null, "expiry": null, "sides": "both",
 "threshold_same": 25, "threshold_gap": 60, "otm_min": 300, "otm_max": 800, "strike_step": 100,
 "mode": "hold", "move_points": 500, "point_value": 100, "multi": false, "pick": "max",
 "entry_days": 30, "exit_days": 10, "loss_roll": true, "roll_days": 1, "roll_legs": "both",
 "max_rolls": 0, "take_profit": 0, "add_step": 0, "max_lots": 0}
```

Natural gas starts with `threshold_same 0.75`, `threshold_gap 1.25`, `otm_min 20`, `otm_max 60`,
`strike_step 5`, `move_points 40`, `point_value 1250` (the server applies these when
`commodity` is `natgas` and the rule is not sent).

| Rule | Meaning |
|---|---|
| `start`, `end`, `expiry` | Date range (`YYYY-MM-DD`, `end` null = today); `expiry` = one NSE expiry only |
| `sides` | `both`, `CE`, `PE` |
| `threshold_same` / `threshold_gap` | Minimum difference to enter when both expiries fall on the same day / a week apart |
| `otm_min` / `otm_max` | Strike distance from ATM |
| `strike_step` | Crude `100` (every strike) or `500` (round strikes); natural gas `5` or `10` |
| `mode` | `hold`, `roll`, `add`; `move_points` = the move that triggers a roll |
| `point_value` | Rupees per point (crude 100, natural gas 1250) |
| `pick`, `multi` | `max` = widest difference, `near` = nearest to ATM; `multi` = several strikes at once |
| `entry_days` / `exit_days` | Enter only this many days before the first expiry (0 = any day); square off this many days before it |
| `loss_roll`, `roll_days`, `roll_legs`, `max_rolls` | A losing trade shifts its legs to the next expiry instead of squaring off; `max_rolls 0` = never shift |
| `take_profit` | Square off when open profit reaches this many points (0 = off) |
| `add_step`, `max_lots` | Add one lot each time the difference widens by `add_step` while OTM (0 = off); cap per strike (0 = no cap) |

Response: `summary` (`trades`, `wins`, `losses`, `win_rate`, `pnl_points`, `pnl_rs`, `avg_points`,
`best`, `worst`, `max_drawdown_points`, `max_drawdown_rs`, `avg_days`, `rolls`), `equity[]`
(`date`, `cum_points`, `cum_rs`) for the P&L line chart, `by_expiry[]` (one row per expiry,
including `best_seen` = the biggest difference seen), and `trades[]` (entry and exit date, side,
strike, buy / sell exchange and price, `diff`, `exit_reason`, `pnl_points`, `pnl_rs`, `days`, and
`daily[]` = the trade's day-by-day path for a detail sheet). Layout as the website: rule fields on
top, summary tiles, equity chart, expiry table, trades table (tap a trade for its daily path).

**Paper.** Read-only view of the live paper-trading engine (start / stop and rules stay on the
website). Show: `enabled` (Running / Stopped), `params` (rules in force), `summary` tiles
(`open_lots`, `closed`, `win_rate`, `open_rs`, `closed_rs`, `total_rs`), `open[]` lots with live
`mark` and `mark_rs`, `closed[]` trades (`entry_time`, `exit_time`, `side`, `strike`,
`buy_exch` / `sell_exch`, `buy_px` / `sell_px`, `exit_reason`, `pnl_points`, `pnl_rs`) and
`events[]` (the engine's log, newest last).

### 4.4 MCX vs NYMEX

One screen with: a currency switch **INR vs Dollar | INR vs INR** (`currency=usd|inr`), a commodity
switch **Crude Oil | Natural Gas**, a month switch (`month=0|1`, label it with
`mcx.expiries[month]`), and views **Live | History | Backtest**.

**Live** (`GET /crude-iv?commodity=crude|natgas&currency=usd|inr&month=0|1`, every 5 s)

- Summary strip: MCX ATM IV, US ATM IV, Difference (MCX - US), MCX forward (`mcx.forward`),
  US future (`us.future_price`), USD / INR (`usdinr.price`). ATM IV (computed in the app, as on
  the website) = the average of `ce.iv` and `pe.iv` on the row with `atm: true` (ignore a null or
  0 value; one value alone is used as is). Difference = MCX ATM IV - US ATM IV.
- Two chains side by side: `mcx.rows[]` and `us.rows[]`. Each row: `strike`, `side`, `atm`, and a
  `ce` and / or `pe` leg with `bid`, `ask`, `iv` (percent), `delta`, plus `oi` on MCX. Layout: 10
  calls above the money, the ATM row (PE shown above CE on that row), 10 puts below. Columns:
  Type, OI (MCX), IV, Delta, Bid, Ask, Strike.
- `currency=inr` restates the US strikes and prices in rupees; the IV does not change.
- A leg with `wide: true` has a very wide bid / ask: show it greyed.

**History** (`GET /crude-iv/history?commodity=&month=&slot=all|09:00..23:30&days=3`)

Boards saved every half hour from 09:00 to 23:30 IST, newest first. Each snapshot has summary
values (`mcx_future`, `us_future`, `usdinr`, `mcx_atm_iv`, `us_atm_iv`, `iv_diff`) and a compact
`board`: rows are plain arrays whose column names are in `board.cols_mcx` and `board.cols_us`:

```
cols_mcx: strike, atm, ce_bid, ce_ask, ce_iv, ce_delta, ce_wide, ce_oi, pe_bid, pe_ask, pe_iv, pe_delta, pe_wide, pe_oi
cols_us : strike, atm, ce_bid, ce_ask, ce_iv, ce_delta, ce_wide, pe_bid, pe_ask, pe_iv, pe_delta, pe_wide
```

Map each array by index, then render each board with the Live chain layout. Filters: time slot,
days (1 to 30), or one `date=YYYY-MM-DD`.

**Backtest** (`POST /crude-iv/backtest`)

Sells the option with the higher implied volatility, buys the same strike on the other exchange,
closes when the IV gap narrows. Runs on the stored half-hourly boards (since 19-Aug-2026).

```json
POST /crude-iv/backtest
{"commodity": "crude", "month": 0, "start": null, "end": null,
 "entry_diff": 5, "exit_diff": 3, "direction": "both", "sides": "both",
 "strike_step": 500, "otm_min": 0, "otm_max": 0, "exit_days": 5, "stop_loss": 0,
 "price_rule": "mid", "lot_size": 100, "max_positions": 0, "exclude_wide": true}
```

| Rule | Meaning |
|---|---|
| `entry_diff` / `exit_diff` | Enter when MCX IV and NYMEX IV differ by at least this many points; exit at or below `exit_diff` (must be smaller than `entry_diff`, else `400`). |
| `direction` | `both`, `mcx_high` (sell MCX, buy NYMEX), `us_high` (sell NYMEX, buy MCX) |
| `sides` | `both`, `CE`, `PE` |
| `strike_step` | MCX strikes allowed: crude `500` = liquid strikes 7500, 8000, 8500 (website default), `1000`, `0` = every strike. Natural gas: `0` (default), `10`, `20`, `50`. |
| `otm_min` / `otm_max` | Points from ATM, `0` = no limit |
| `exit_days` | Square off this many days before expiry |
| `stop_loss` | Points, `0` = off |
| `price_rule` | `mid` (default), `client` (buy at bid, sell at ask), `market` (buy at ask, sell at bid) |
| `lot_size` | Crude 100, natural gas 1250. P&L in rupees = points x lot size. |

Response: `params`, `coverage` (`boards`, `first`, `last`, `days`), `summary` (`trades`, `wins`,
`losses`, `win_rate`, `pnl_points`, `pnl_rs`, `avg_points`, `best`, `worst`,
`max_drawdown_points`, `max_drawdown_rs`, `avg_hours`, `exits`, `still_open`), `equity[]` and
`trades[]` (`entry_ts`, `side`, `mcx_strike`, `us_strike`, `sell_exch`, `buy_exch`, `sell_px`,
`buy_px`, `mcx_iv`, `us_iv`, `diff`, `exit_ts`, `exit_reason`, `exit_diff`, `pnl_points`,
`pnl_rs`, `hours`). Trades come without the board-by-board path; add `?include_paths=true` only
when the user opens a trade's detail sheet (that response is large, about 2 to 3 MB).

### 4.5 Bullion Stock

Already specified in `APP_BULLION_STOCK_API.md` (`GET /bullion-stock`, PDF at
`/bullion-stock/pdf`). Fetch when the screen opens; the data changes once a day.

### 4.6 COMEX + NYMEX

Already specified in `APP_INTERNATIONAL_API.md` (`GET /international` or the WebSocket
`/international/stream?api_key=<key>&interval=1`).

### 4.7 IV Calculator (Black-76)

```
GET /iv-calculator?underlying=8600&strike=8500&days=20&market=250&side=ce
GET /iv-calculator?underlying=8600&strike=8500&days=20&vol=45&side=pe
```

Inputs: `underlying` (the FUTURE price of the option's month), `strike`, `days` (calendar days to
expiry), `side` (`ce` / `pe`), optional `rate` and `dividend` (percent, 0 for futures options), and
either `market` (option price, solves the implied volatility) or `vol` (percent, prices the
option). Output: `implied_vol` (percent), `price`, `call_price`, `put_price`, `intrinsic`,
`time_value`, `greeks` (`delta`, `gamma`, `vega`, `theta`, `rho`). `implied_vol: null` with a
`note` means no volatility can produce that price (a stale quote): show the note. Call when an
input changes (debounce 300 ms), not on a timer.

### 4.8 BANKEX / BANKNIFTY

Views **Live | History**. (The website's third view, paper Positions, stays on the website.)

**Live** (`GET /bank-options?side=both|CE|PE&metric=points|rupees&bankex_lots=1&banknifty_lots=1`,
every 2 s)

- Two index cards: `indices.BANKEX` and `indices.BANKNIFTY` with `spot` (large), `expiry` (large,
  monthly), `atm`, `lot_size`, and the action badge: the index named in `sell_index` is
  **SELL · BID** (earlier expiry), the one in `buy_index` is **BUY · ASK** (later expiry).
- `status.message`: show it as a small note above the table when not null (market closed, waiting
  for quotes).
- Table: 15 BANKEX strikes (ATM +/- 7 x 500). `rows[]` holds one record per strike per side
  (`side` `CE` / `PE`, `offset_points` from -3500 to +3500). Group by `offset_points` into 15 rows:
  CE block on the left, strikes in the middle, PE block on the right.
  - Middle columns: BANKEX strike (`bankex.strike`), ATM distance (`offset_points`; `0` shows an
    **ATM** badge), BANKNIFTY strike (`banknifty.strike`). After each strike show its points from
    that index's spot: `strike - indices.X.spot`, rounded, with a sign (e.g. `64,000 +105`,
    `56,600 +58`).
  - Per side: **Buy Ask** (`buy_price`, under the buy index name), **Sell Bid** (`sell_price`),
    **Difference** (`display_value`: points, or rupees with `metric=rupees`). Positive green,
    negative red, `null` shows `-`.
  - A small dot after each price: green when that leg's `fresh` is true, grey when stale.
- Footnote: "BANKNIFTY strike = BANKNIFTY spot + (BANKEX strike - BANKEX spot), rounded to 100.
  Earlier expiry sold at Bid, later expiry bought at Ask."

**History** (`GET /bank-options/history?...`, fetch on filter change)

| Source | Call | What it is |
|---|---|---|
| 10:00 / 3:30 boards | `source=snapshot&slot=both\|10:00\|15:30&weekday=mon..fri&days=7` | The board saved automatically at 10:00 AM and 3:30 PM IST every trading day (since 23-Sep-2026). Prices are each leg's last bid / ask; `stale: true` on a row means a leg's quote was older than a minute (show a small `•`). |
| Daily close | `source=daily&weekday=&days=7..120` | One board per trading day since January 2024 from the exchanges' closing prices. Legs carry `price` (close, or the settlement price when the strike did not trade); `settled: true` / `traded: false` marks those (show a small `s`). Strikes nobody traded are not in the exchange files: `listed: false`, show `-`. |

Response: `boards[]`, newest first, each with `date`, `weekday`, `slot` (`10:00`, `15:30` or
`close`), `captured_at`, `indices` (same as Live), `buy_index`, `sell_index` and `rows[]` (same
grouping as Live, with `buy_price`, `sell_price`, `difference_points`). Render each board like the
Live screen (index cards + 15-row table), stacked, with a header "Wednesday, 07 Oct 2026 · 3:30 PM".
Filters: source, time (snapshot only), weekday chips (All, Mon to Fri), "Last N days".

### 4.9 Spread History (inside Cross Pair and Calendar Spread)

The website has a **Spread History** button on both screens: one close-based spread value per
trading day from MCX's daily closing prices (from 2015).

```
GET /spread-history/options        (once per session)
GET /spread-history?kind=calendar&big=petal&mode=continuous&rank=0&start=2021-01-01
GET /spread-history?kind=calendar&big=petal&mode=month&big_exp=2026-10-30&small_exp=2026-11-30
GET /spread-history?kind=cross&big=petal&small=guinea&mode=continuous&start=2026-01-01
```

`/spread-history/options` returns `symbols[]` (`key`, `label`, `expiries[]`), `cross[]` (the board's
cross pairs: `big`, `small`, `label`) and `coverage` (`from`, `to`). `/spread-history` returns
`label`, `count` and `rows[]` newest first. Calendar rows: `date`, `near`, `far`, `diff`,
`diff_std` (per 10 gm or per kg, see `std_unit`), `pct`, `near_exp`, `far_exp`. Cross rows: `date`,
`big`, `small`, `big_rate`, `small_rate`, `diff`, `pct`, `big_exp`, `small_exp`.

Layout as the website: a toolbar (symbol or pair, **Continuous | Month-wise**, year selector: All
years or one year, and for calendar continuous the **M1-M2 / M2-M3** choice = `rank`), four tiles
in this order: **Latest**, **Average** (with the number of days), **Lowest** and **Highest** (each
with its date), a line chart of `diff` over time, and a paged table (100 rows per page). From a row on the live board, open the dialog pre-filled
with that pair and month (`mode=month` with its expiries).

---

## Part 5. Not in the app (by design)

| Website feature | Why |
|---|---|
| BANKEX / BANKNIFTY paper Positions, NSE vs MCX paper start / stop / rules | Write actions and per-user data stay on the website. The app shows the paper results read-only (4.3). |
| Auto Trades | A separate client's TradingView system, not part of the Gurukrupa app. |
| Manage Users, Market Holidays editing | Admin pages. The app only reads holidays (3.3). |

---

## Part 6. Done checklist

- [ ] Commodity Option: Gold, Silver, Crude Oil, Natural Gas selector.
- [ ] Nifty / Sensex: SINCE 3:16 PM card on Live and on every History board; History filters
      (weekday, time, last N, side).
- [ ] Market badge on every screen from `/market-status`.
- [ ] ETF vs MCX screen (computed in the app, editable constants saved on the phone).
- [ ] Making Price screen (editable factor and charges sent as parameters).
- [ ] NSE vs MCX: Crude / Gas / Electricity, near / next month, Live, History (snapshots + daily
      closes), Graph, Backtest, Paper (read-only).
- [ ] MCX vs NYMEX: INR vs Dollar / INR vs INR, Crude / Gas, month, Live, History, Backtest.
- [ ] Bullion Stock screen with PDF view / download.
- [ ] COMEX + NYMEX screen (WebSocket preferred).
- [ ] IV Calculator screen.
- [ ] BANKEX / BANKNIFTY: Live (15 strikes, points from spot) and History (10:00 / 3:30 boards and
      daily closes).
- [ ] Spread History dialog on Cross Pair and Calendar Spread.
- [ ] Every `null` shows `-`; polling stops when a screen is hidden; history and backtests are
      fetched only on user action; `429` is retried after 3 s.
