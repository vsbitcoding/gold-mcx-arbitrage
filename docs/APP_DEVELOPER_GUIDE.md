# Gurukrupa Bullion App: Complete Screen Guide

Version 2, 09-Oct-2026. Replaces version 1 of 08-Oct-2026.

This guide describes every page of the web dashboard (https://arbitrage.bitcoding.ai) so the mobile
app can show the same pages, in the same order, with the same sections, columns, labels, colours and
numbers. Screenshots of every page and every view, at phone width and desktop width, are in the
`screens/` folder next to this file.

**Instructions for the AI assistant reading this file**

1. Read the whole file and look at the screenshots of a screen before changing that screen.
2. The website is the reference. Match its order, sections, columns, labels and number formats.
   On a phone, follow the phone-width screenshot (`*_mobile.jpg`): it is how the website itself
   arranges the same content on a narrow screen.
3. The server computes every number (spreads, differences, IV, P&L, ATM, matched strikes, order of
   cards). Display what the API returns. Compute in the app only where this guide says
   "computed in the app".
4. `null` means "no data right now". Always show a dash for `null`. Never show `0` instead, and never
   hide the row.
5. The app is watch-only. It never places, closes or edits trades and never changes server settings.
6. Work through Part 4 screen by screen and tick the checklist in Part 6.

---

## Part 1. Connection rules

| Item | Value |
|---|---|
| Base URL | `https://arbitrage.bitcoding.ai/api/v1` |
| Auth | Header `X-API-Key: <app key>`, or `?api_key=<app key>` for links and WebSockets. Use the key the app already has. |
| Times | `server_time` is UTC ISO 8601. Dates (`date`, `snap_date`, `expiry`) are IST `YYYY-MM-DD`. Slots (`10:00`, `15:30`) are IST. |
| Errors | `401` wrong or missing key. `400` bad parameter or backtest rule (`detail` says why). `404` nothing stored yet. `429` a backtest is already running: wait 3 to 5 s and retry. `5xx`: retry after 2 s, 4 s, 8 s. |
| Market flag | Most live responses carry `market_open`. `/market-status` gives the reason (closed, holiday). |

**How often to call**

| Kind | Endpoints | Rule |
|---|---|---|
| Push streams | `stream` (Cross Pair and Calendar Spread), `international/stream` | WebSocket while the screen is open |
| Live boards | `metals-spread`, `othercomm-spread`, `price-table`, `premium-inputs`, `gold-options-spread`, `options-spread`, `making-price`, `bank-options` | Every 2 s while the screen is visible |
| Live, slower | `calculator` 1.5 s, `nse-mcx` 3 s, `crude-iv` 5 s, `nse-mcx/paper` 10 s, `signals` 15 s, `market-status` 60 s and on app resume | While visible |
| Static | history, daily closes, graphs, backtests, spread history, bullion stock | Only when the screen opens or a filter changes. Never on a timer. |

Stop every poll and close every socket when the screen is not visible.

Older detailed specs, still valid on the same server: `APP_NIFTY_SENSEX_API.md`,
`APP_OPTIONS_HISTORY_API.md`, `APP_GOLD_OPTIONS_API.md`, `APP_NSE_MCX_API.md`,
`APP_INTERNATIONAL_API.md`, `APP_BULLION_STOCK_API.md`, `APP_BRANDING.md` (logo and gold theme).

---

## Part 2. Status of each page in the app

Based on the server's request logs up to 09-Oct-2026 and the app screenshots the client sent.

| # | Web page (menu order) | App today | What to do |
|---|---|---|---|
| 1 | Cross Pair | Has it | Match the card layout and order exactly (4.1). Add the signal flash, Hist button and Spread History. |
| 2 | Calendar Spread | Has it | Match the card layout and order (4.2). Add the % column, bracketed plain difference, Hist, Spread History. |
| 3 | Metal Spread | Has it, wrong layout | Rebuild as Expiry / ▼ Dec / ▲ Inc / % cards (4.4). |
| 4 | Other Commodity Spread | Has it, wrong layout | Rebuild as Expiry / ▼ Dec / ▲ Inc cards (4.5). |
| 5 | Metal Price | Has it | Check against 4.6. |
| 6 | ETF vs MCX | Missing | New (4.7). |
| 7 | Premium | Has it | Small fixes (4.8): USD/INR with 4 decimals, "Ask" tag on the three calculators. |
| 8 | Commodity Option | Gold only | Add Silver, Crude Oil, Natural Gas and the expiry switch (4.9). |
| 9 | NSE vs MCX | Missing | New (4.10). |
| 10 | MCX vs NYMEX | Missing | New (4.11). |
| 11 | Making Price | Missing | New (4.12). |
| 12 | Bullion Stock | Missing | New (4.13). |
| 13 | COMEX + NYMEX | Missing | New (4.14). |
| 14 | IV Calculator | Missing | New (4.15). |
| 15 | Nifty / Sensex | Has Live (Below ATM) and History | Add Above ATM, Square off ITM, the Since 3:16 PM card, History filters, Calculator (4.16). |
| 16 | BANKEX / BANKNIFTY | Missing | New: Live and History (4.17). |
| 17 | Signals | Has it | Check against 4.18 (order, gauge, history). |
| 18 | Auto Trades | Not for this app | See Part 5. |
| - | Market badge | Partly (LIVE pill) | Use `/market-status` (4.19). |

**Server changes made for the app on 09-Oct-2026 (no app update needed to receive them):**
Cross Pair and Calendar Spread groups now arrive in the website's order; each row also carries
`expiry_display`, `big`, `small`, `expiry_date` / `near_expiry` / `far_expiry`, `decrease_raw`,
`increase_raw` and `signal`; groups carry `silver` and `has_signal`; `/signals` comes in the website's
order; `/international` has `competing_session`; Premium's USD/INR is now the live spot rate.

---

## Part 3. Shared look and number rules

- **Numbers:** Indian digit grouping (`1,50,851`). Decimals as each screen says.
- **Signs:** a signed value shows `+` or the minus sign before the number.
- **Colours:** positive green, negative red, zero or null neutral. Exception: the **▼ Dec** chip is
  always red and the **▲ Inc** chip is always green, whatever the sign (they are column colours).
- **Chips:** Dec and Inc values sit in small rounded chips with a light red / light green
  background, bold monospace digits, 2 decimals.
- **Front month:** the first row of each expiry card gets a ★ after the expiry text.
- **ATM:** the at-the-money row is highlighted and shows an `ATM` badge.
- **Cards:** gold-family cards use the gold theme, silver-family cards the silver theme
  (`APP_BRANDING.md`). Base metals use their own family colour (copper, aluminium, zinc, nickel, lead).
- **Live dot:** a small green dot after a live price.
- **Dash:** every `null` shows a dash.

---

## Part 4. Screens

### 4.1 Cross Pair

Screenshots: `01_cross_*`, signal flash and popup: see 4.18; Spread History: `01b_cross_spread_history_*`,
`01c_cross_row_history_*`.

**Data:** WebSocket `wss://arbitrage.bitcoding.ai/api/v1/stream?api_key=<key>&interval=1&type=cross`
(or `GET /spread-groups?type=cross`). Use `groups[]` in the order received: the server sends the
website's order:

`PETAL / GUINEA, PETAL / TEN, PETAL / MINI, GUINEA / TEN, GUINEA / MINI, TEN / MINI, MINI / GOLD,
SILVER 100 / SILVER MIC, SILVER 100 / SILVER MINI, SILVER MIC / SILVER MINI, SILVER MINI / SILVER`

**Layout, top to bottom:**
1. A **Spread History** button (opens 4.3 with nothing pre-selected).
2. One card per group:
   - Header: the group name (`group`) on the left, `<count> exp` on the right.
   - Silver theme when `silver` is true, gold theme otherwise. A card with `has_signal` gets a thin
     gold (accent) ring around it.
   - Column heads: **Expiry | ▼ Dec | ▲ Inc | (signal) | Hist.**
   - One row per item in `expiries[]` (already front month first):

| Column | Field | Format |
|---|---|---|
| Expiry | `expiry_display` (e.g. `30 Oct 2026`) | ★ after the first row's text |
| ▼ Dec | `decrease` | 2 decimals, red chip |
| ▲ Inc | `increase` | 2 decimals, green chip |
| signal | `signal` | When not null: a ⚡ button (red for `narrow`, green for `widen`) and the whole row tinted light red (`narrow`) or light green (`widen`); tap opens the signal popup (4.18). Empty otherwise. |
| Hist | - | A small chart icon; tap opens Spread History (4.3) pre-set to this pair and month: `kind=cross`, `big`, `small`, `mode=month`, `big_exp=expiry_date`. |

### 4.2 Calendar Spread

Screenshots: `02_calendar_*`, `02b_calendar_spread_history_*`, `02c_calendar_row_history_*`.

**Data:** the same stream or `GET /spread-groups?type=calendar`. Order (server-sorted):
`PETAL, GUINEA, TEN, MINI, GOLD, SILVER 100, SILVER MIC, SILVER MINI, SILVER`.

Same card as 4.1 with these differences:

| Column | Field | Format |
|---|---|---|
| Expiry | `expiry_display` (near month first: `30 Oct 2026 − 30 Nov 2026`) | ★ on the first row |
| ▼ Dec | `decrease`, then `decrease_raw` in small brackets when not null | `1270.00 (127.00)`: the bracket is the plain difference, only for Petal, Guinea and Silver 100 |
| ▲ Inc | `increase`, then `increase_raw` in brackets when not null | same |
| % | `decrease_pct` | signed, 2 decimals, `%`; green if positive, red if negative |
| Hist | - | Opens 4.3 with `kind=calendar`, `big=<big>`, `mode=month`, `big_exp=near_expiry` |

There is no signal column on Calendar.

### 4.3 Spread History (dialog, from Cross Pair and Calendar Spread)

Screenshots: `01b_*`, `01c_*`, `02b_*`, `02c_*`.

```
GET /spread-history/options                     (once per session)
GET /spread-history?kind=calendar&big=petal&mode=continuous&rank=0&start=2015-01-01
GET /spread-history?kind=calendar&big=petal&mode=month&big_exp=2026-10-30
GET /spread-history?kind=cross&big=petal&small=guinea&mode=continuous&start=2015-01-01
GET /spread-history?kind=cross&big=petal&small=guinea&mode=month&big_exp=2026-10-30
```

`/spread-history/options`: `symbols[]` (`key`, `label`, `expiries[]`), `cross[]` (`big`, `small`,
`label`), `coverage` (`from`, `to`). `/spread-history`: `label`, `count`, `rows[]` newest first,
plus `near_exp` / `far_exp` or `big_exp` / `small_exp` in month mode, and `std_unit` / `std_mult`
on calendar.

**Layout:**
1. Title row: "Spread history · Calendar" or "Spread history · Cross pair", close button. Subtitle:
   "One value per day from MCX closing prices · data <coverage.from> to <coverage.to> · far month
   minus near month" (calendar) or "· big leg minus small leg, board multipliers" (cross).
2. Toolbar: symbol select (calendar, labels from `symbols`) or pair select (cross, from `cross`);
   **View: Continuous | Month-wise**; **Year**: `All years (2015 to today)` or one year; in
   continuous calendar the **Months** chips `M1-M2 | M2-M3 | M3-M4` (`rank` 0, 1, 2); in month-wise
   a **Near month** select (calendar) or **Big leg month** select (cross) from the symbol's expiries.
3. One summary line in month-wise: `<label>: <near> (near) vs <far> (far)`, or for cross
   `<label>: <big_exp> vs <small_exp> - months matched the board's way`.
4. Four tiles: **Latest** (`diff` signed + its date + the two legs), **Average** (+ number of days),
   **Lowest** (date + legs), **Highest** (date + legs). Latest coloured by sign; Lowest red;
   Highest green.
5. A chart of `diff` by date with two lines: **daily difference** (gold line with a light filled
   area) and an **N-day average** (dark line), where `N = min(20, max(2, floor(number of rows / 8)))`
   and the legend reads `<N>-day average`. Touch shows: date, difference (and `pct` %), near and
   far (or big and small) with their months.
6. Table, newest first. Calendar: **Date | Near close | Far close | Difference | Diff per 10 gm**
   (only when `std_mult` is not 1, values `diff_std`; the unit text from `std_unit`) **| % |
   Contracts** (continuous mode only). Cross: **Date | Big (rate) | Small (rate) | Difference (per
   10 gm or per kg, by the big leg's family) | % | Contracts**. Difference and % coloured by sign.
   With "All years" the table pages by year: `‹ 2025 | 2026 · 243 days | 2027 ›`.

Static data: fetch on a control change only.

### 4.4 Metal Spread

Screenshots: `03_metal_spread_*`. The client's complaint of 09-Oct is about this screen and 4.5.

**Data:** `GET /metals-spread` every 2 s. `rows[]` is flat: group them into one card per `metal`,
keeping the API order: `Copper, Aluminium, Aluminium Mini, Zinc, Zinc Mini, Nickel, Lead, Lead Mini`.

**Card:** header = metal name, right side `<rows> exp`; header colour by family (copper,
aluminium, zinc, nickel, lead; minis use the parent's colour). Column heads
**Expiry | ▼ Dec | ▲ Inc | %**.

| Column | Field | Format |
|---|---|---|
| Expiry | `near_month` + ` − ` + `far_month` (`30 Oct 2026 − 30 Nov 2026`) | ★ on the first row |
| ▼ Dec | `difference` (far Buy − near Sell) | 2 decimals, red chip |
| ▲ Inc | `increase` (far Sell − near Buy) | 2 decimals, green chip |
| % | `pct` | signed, 2 decimals, `%`, green / red by sign |

No Hist button on this screen (client's rule).

### 4.5 Other Commodity Spread

Screenshots: `04_other_commodity_*`.

**Data:** `GET /othercomm-spread` every 2 s. Cards in API order:
`Crude Oil, Crude Oil Mini, Natural Gas, Natural Gas Mini, Electricity`. Exactly the 4.4 card
without the % column (**Expiry | ▼ Dec | ▲ Inc**). Header colours: crude, natural gas, electricity.

### 4.6 Metal Price

Screenshots: `05_metal_price_*`.

**Data:** `GET /price-table` every 2 s. One card per item in `groups[]` with at least one contract,
in API order (Gold, Silver, Gold Mini, Silver Mini, Gold Ten, Gold Guinea, Gold Petal, Silver Mic,
Silver 100, then the base metals). Header = `instrument`; silver theme for Silver, Silver Mini,
Silver Mic, Silver 100; gold theme otherwise. Columns **Expiry | Buyer | Seller**: `contract`,
`buyer`, `seller`, 2 decimals.

### 4.7 ETF vs MCX (computed in the app)

Screenshots: `06_etf_vs_mcx_*`.

**Data:** `GET /calculator` every 1.5 s: per `gold` / `silver`: `etf.ltp`, `etf.symbol`,
`mcx_full.ltp`, `mcx_full.symbol`, `mcx_full.expiry`, `defaults`.

Two cards, **GOLD** (`GOLDBEES → Full Gold MCX`) and **SILVER** (`SILVERBEES → Full Silver MCX`):

1. Header: metal name and the subtitle; a button **✎ Manual price** / **↻ Use live** that switches
   the ETF price between live and a typed value.
2. Rows: **<ETF> Price** (live `₹ <ltp>` with a live dot, or the typed price), **Multiplier**,
   **Manual Value**, **Divisor** (all editable, saved on the phone).
3. Formula text: `(price × <multiplier> + <manual>) ÷ <divisor>`.
4. Results:
   - **Calculated Value** `₹ <value>` where `value = (price × multiplier + manual) ÷ divisor`
   - **Full Gold MCX (<symbol>) · <expiry dd Mon yy>** `₹ <mcx_full.ltp>`
   - **Difference** = value − MCX: `▲ +x.xx` green or `▼ x.xx` red
   - Hint: positive "Calculator higher → opportunity to sell ETF, buy MCX"; negative "Calculator lower
     → opportunity to buy ETF, sell MCX"; zero "Aligned - no edge right now".
5. Defaults: Gold × 120000, manual 0, ÷ 103. Silver × 31000, manual 0, ÷ 30.9. A divisor of 0 or
   blank shows "Enter a finite divisor greater than zero." and no result.

### 4.8 Premium

Screenshots: `07_premium_*`.

**Data:** `GET /premium-inputs` every 2 s: `xauusd`, `xagusd`, `usdinr` (live spot USD/INR since
09-Oct-2026), `mcx_gold` / `mcx_silver` (`bid`, `ask`, `ltp`, `expiry`).

Gold and Silver (side by side on wide screens; a Gold | Silver switch on the phone is fine). Each has
a parameter table and three calculators. All inputs are editable and saved per metal on the phone.

| Row | Value | Format |
|---|---|---|
| Spot XAU/USD (Silver: XAG/USD) | `xauusd` / `xagusd` + live dot | 2 decimals |
| Cost (USD) | input, gold default 5 | |
| C. Duty | input, gold default 1854062 | |
| USD/INR (+<spread>) | `usdinr + spread` | **4 decimals** |
| Conversion - 999 | input, gold default 32.12 | |
| Conversion - 995 | input, gold default 31.99 | |
| USD/INR + spread | input, default 0.01 | |
| MCX Gold Bid (Silver: MCX Silver) | `mcx_gold.bid` (else `ltp`) + live dot | 0 decimals |
| Premium - 999 | `((spot + cost) × conv999 × (usdinr + spread) + duty) / 100 − mcx bid` | 2 decimals, green / red |
| Premium - 995 | same with conv995 | 2 decimals, green / red |

Silver inputs start blank, so its premiums show a dash until filled.

Calculators (three cards, each header shows `Ask <mcx ask, 0 decimals>` on the right):

| Card | Input | Output |
|---|---|---|
| Only Premium | Premium | Price = `(ask + premium) × 1.03` |
| Premium with GST | Premium GST | Rate = `ask + premium GST`; Premium = `rate / 1.03 − ask` (green / red) |
| Premium from Rate | Rate (highlighted input) | Premium = `rate / 1.03 − ask` (green / red) |

Outputs 0 decimals.

### 4.9 Commodity Option

Screenshots: `08a_commodity_option_gold_*`, `08b_*silver*`, `08c_*crude*`, `08d_*natgas*`.

**Data:** `GET /gold-options-spread?commodity=gold|silver|crude|natgas` every 2 s.

1. Commodity switch: **Gold | Silver | Crude Oil | Natural Gas** (names from `commodities`).
2. Title `<label> Options`, subtitle `<big_name> / <mini_name> · watch only · ATM ref <ref>`.
3. Expiry switch: one button per item in `expiries[]`: `<big_expiry dd Mon>` and, when different,
   `/ <mini_expiry>`.
4. Four cards: **<BIG> Future** (`big_price`, 0 decimals, live dot, "Full contract"); **<MINI> Future**
   (`mini_price`, "Mini contract"); **Pricing Side** (`<higher> → Ask`, `<lower> → Bid`); **Expiry**
   (big expiry, and `<MINI> <mini expiry>`).
5. Table for the selected expiry: two lines per strike.

| Column | Content |
|---|---|
| Strike | `strike` (spans both lines); `ATM` badge on the strike nearest `ref` |
| Type | `CE` / `PE` (spans both lines) |
| Contract | line 1 `<mini_name>`, line 2 `<big_name>` |
| Bid / Ask | line 1 `mini_bid` / `mini_ask`, line 2 `big_bid` / `big_ask`, 2 decimals |
| `spread1_label` | `spread1`, signed, 2 decimals, green / red, spans both lines |
| `spread2_label` | `spread2`, same |

On a phone the website shows one card per strike: strike + ATM badge + type, the two spreads big,
then `MINI Bid · Ask` and `BIG Bid · Ask` lines (`08*_mobile.jpg`). Details:
`APP_GOLD_OPTIONS_API.md`.

### 4.10 NSE vs MCX

Screenshots: `09a_*` to `09i_*`.

Header controls: commodity **Crude Oil | Natural Gas | Electricity**; month **<this month> | <next
month>** (`month=0|1`, names from the expiry, e.g. Oct / Nov); an **IV** toggle (crude and gas);
view **Live | History | Graph | Backtest | Paper** (Electricity: **Live | 1 Hr History** only).

**Live** (`GET /nse-mcx?commodity=crude|natgas&month=0|1&window=10`, every 3 s): exactly as
`APP_NSE_MCX_API.md` section 1: NSE FUTURE and MCX FUTURE chips (mid, expiry, bid / ask), the
option chain mirrored around the strike (CALL: NSE | MCX | Diff, STRIKE, PUT: Diff | MCX | NSE),
big number = `mid`, small line = `bid / ask`, Diff in rupees with % under it, green / red, amber
with "?" when `wide`. Never use `ltp`. With **IV** on, an IV column sits beside each exchange's
price column (after it on the call side, before it on the put side, so the table stays mirrored):
the leg's `iv` with 1 decimal and `%` (touch shows `iv`, `iv_bid`, `iv_ask`). Under the
futures, one line from `iv_basis`: the forward each exchange's options imply (`forward`, `strikes`,
`days`).

**History**: a switch **Saved boards | Daily since Apr 2024**.
- Saved boards: `GET /nse-mcx/history?commodity=&month=&slot=all|10:00|12:00|15:00&days=7`.
  Time chips **All | 10:00 AM | 12:00 PM | 3:00 PM**, days **Last 3 | 7 | 14 | 30**. Boards stacked
  newest first, each drawn like Live, with a date and time header.
- Daily: `GET /nse-mcx/daily/expiries?commodity=` then `GET /nse-mcx/daily?commodity=&expiry=<nse>`.
  Controls: **NSE expiry** (only expiries with `nse_traded_days > 0`), **MCX expiry**, **Period**
  (`Whole contract | Last 30 days | Last 7 days`), **From**, **Show** (Call and Put / Call / Put
  = `type`), **Strike** (`All strikes` or one), **Rows** (`ATM only | Traded only | All strikes`),
  **Reset**. A summary line, a chart "Premium difference over time", and the table:
  **Date | Future (close): NSE, MCX, Diff | Strike | Call: NSE, MCX, Diff, Diff % | Put: NSE, MCX,
  Diff, Diff %**. ATM only = one row per day, the strike nearest that day's future close. A whole
  expiry can be 1.5 MB: send `type` and `strike` once chosen.

**Graph** (`GET /nse-mcx/graph?commodity=&month=&side=ce|pe&strike=<strike or future>&days=30`):
Call | Put switch (hidden for the future); **CONTRACT** picker from `strike_options` ("Future" first,
each with its number of readings); a "hide unusable" toggle when some readings are wide; legend
"MCX bid − NSE ask" (solid) and "MCX mid − NSE mid" (dashed); tiles **LATEST DEAL** (with date and
time), **AVERAGE**, **BEST**, **WORST**, **READINGS**; the chart (null = gap); a table
**Date | Time | NSE ask | MCX bid | Mid | Future | Diff**.

**Backtest** (`POST /nse-mcx/backtest`): rule fields in this order with these labels: From, To, NSE
expiry (All expiries in range), Side (Call + Put / Call only / Put only), Mode (Hold to expiry (a) / Adjust: new strike, old closed (b1) / Adjust: new strike, old kept (b2) = `hold` / `roll` / `add`),
Move trigger (pts), Diff same expiry, Diff different expiry, OTM from (pts), OTM to (pts), Strike step,
₹ per point, Pick (Widest difference / Nearest to ATM), Entry window (days), Take profit (pts),
Square off (days before), Shift (days before), Shift legs (NSE and MCX / NSE only / MCX only),
Max shifts; buttons **Defaults** and **Run backtest**. Results: tiles **Net P&L, Trades, Win rate,
Average trade, Best / worst, Max drawdown, Avg days held**; the cumulative P&L chart (`equity`);
**By expiry** table (NSE expiry, MCX expiry, Gap, Diff rule, Days, NSE traded, Trades, Won, Shifts,
Best diff seen, P&L); **Trades** table (entry, side, strike, Buy on, Sell on, prices, Why, exit,
Exit prices, P&L pts, P&L ₹). Tapping a trade opens "Trade day by day": tiles **Result, First day
in profit, Best day, Worst day** and a table **Date | NSE price | MCX price | P&L pts | P&L ₹ | Note**
from the trade's `daily[]`. Body rules, defaults and meanings: see 4.10.1.

**Paper** (`GET /nse-mcx/paper?commodity=`, every 10 s, read-only): Running / Stopped (`enabled`),
the rules in force (`params`, shown read-only), tiles **Open lots, Open P&L, Closed trades, Closed
P&L, Total**, "Engine sees now" (`preview`), **Open lots** table (Entered, Side, Strike, Why, Buy on,
Sell on, Diff, Now buy / sell, Expiry NSE / MCX, Shifts, P&L pts, P&L ₹), **Closed trades** table
(the same plus Exit and Exit prices), and **What the engine did** (`events`). The website's Close,
Close all, Clear history and rule editing stay on the website.

**Electricity**: Live (`GET /nse-mcx?commodity=electricity&month=0|1`, every 3 s): the NSE and MCX
future prices and **Difference (MCX − NSE)**. **1 Hr History**
(`GET /nse-mcx/elec-hourly?month=0|1&days=30`): table **Hour | NSE | MCX | Difference | %**.

#### 4.10.1 NSE vs MCX backtest body

Send only what the user changed; missing rules take the defaults, which come back in `params`.
Show "Running..." while waiting; on `429` retry after 3 s. Crude starting values:

```json
{"commodity": "crude", "start": "2024-04-01", "end": null, "expiry": null, "sides": "both",
 "threshold_same": 25, "threshold_gap": 60, "otm_min": 300, "otm_max": 800, "strike_step": 100,
 "mode": "hold", "move_points": 500, "point_value": 100, "multi": false, "pick": "max",
 "entry_days": 30, "exit_days": 10, "loss_roll": true, "roll_days": 1, "roll_legs": "both",
 "max_rolls": 0, "take_profit": 0, "add_step": 0, "max_lots": 0}
```

Natural gas starts with `threshold_same 0.75`, `threshold_gap 1.25`, `otm_min 20`, `otm_max 60`,
`strike_step 5`, `move_points 40`, `point_value 1250`. Strike step choices: crude 100 or 500, gas 5
or 10. `max_rolls 0` = never shift. `take_profit 0` and `add_step 0` = off.

### 4.11 MCX vs NYMEX

Screenshots: `10a_*` to `10e_*`.

Top switch **INR vs Dollar | INR vs INR** (`currency=usd|inr`). Then commodity **Crude Oil | Natural
Gas**, month (two buttons named from `mcx.expiries[0]` and `[1]`), view **Live | History | Backtest**.

**Live** (`GET /crude-iv?commodity=&currency=&month=`, every 5 s):
1. Status pill from `us.connected` / `us.delayed`: **Live real-time**, **Delayed**, **Disconnected**.
2. Summary tiles: **MCX ATM IV** (+ MCX expiry), **US ATM IV** (+ US expiry), **Difference MCX − US**
   (green / red), **MCX forward** (`mcx.forward`, with `fwd_strikes`), **US future**
   (`us.future_price`), **USD / INR** (`usdinr.price`, 3 decimals, with `usdinr.source`).
   ATM IV is computed in the app: the average of `ce.iv` and `pe.iv` on the row with `atm: true`
   (ignore null or 0; one value alone is used as is).
3. Two chains, MCX and US (US titled "in ₹" when `currency=inr`): columns
   **Type | Strike | Bid | Ask | IV | Delta | OI** (OI on MCX only). Rows: 10 calls above the money,
   the ATM row (PE shown above CE), 10 puts below. IV is a percent. A leg with `wide: true` greyed.

**History** (`GET /crude-iv/history?commodity=&month=&slot=all|09:00..23:30&days=3`): boards every half
hour, newest first, drawn with the Live chain layout. Rows are arrays named by `board.cols_mcx` /
`board.cols_us`:

```
cols_mcx: strike, atm, ce_bid, ce_ask, ce_iv, ce_delta, ce_wide, ce_oi, pe_bid, pe_ask, pe_iv, pe_delta, pe_wide, pe_oi
cols_us : strike, atm, ce_bid, ce_ask, ce_iv, ce_delta, ce_wide, pe_bid, pe_ask, pe_iv, pe_delta, pe_wide
```

**Backtest** (`POST /crude-iv/backtest`): fields From, To, Entry IV gap (pts), Exit IV gap (pts),
Direction (Both / MCX IV higher only / NYMEX IV higher only), Side (Call + Put / Call only / Put
only), Price rule (Mid price / Buy at Bid, sell at Ask / Buy at Ask, sell at Bid), **MCX strikes**
(crude: Liquid 500 multiples / 1000 multiples / All strikes; gas: All / 10 / 20 / 50 multiples),
Strike from ATM min / max, Square off (days before expiry), Stop loss (pts), Lot size (bbl),
Max open trades, Skip wide quotes; **Defaults**, **Run backtest**. Crude defaults:

```json
{"commodity": "crude", "month": 0, "entry_diff": 5, "exit_diff": 3, "direction": "both",
 "sides": "both", "strike_step": 500, "otm_min": 0, "otm_max": 0, "exit_days": 5, "stop_loss": 0,
 "price_rule": "mid", "lot_size": 100, "max_positions": 0, "exclude_wide": true}
```

Natural gas: `strike_step 0`, `lot_size 1250`. `exit_diff` must be smaller than `entry_diff`
(else `400`). Results: tiles Net P&L, Trades, Win rate (with exit reasons), Average trade,
Best / worst, Max drawdown, Data (days, boards, range, avg hold); the cumulative chart; trades
table (Entry, Side, MCX strike, NYMEX strike, USD/INR, Sell on, Buy on, prices, MCX IV, NYMEX IV,
IV gap, Exit, Exit reason, Gap at exit, Exit prices, P&L pts, P&L ₹, Hours). Trades come without the
board-by-board path; fetch `?include_paths=true` only when the user opens a trade (large response).

### 4.12 Making Price

Screenshots: `11_making_price_*`.

**Data:** `GET /making-price?factor=&petal=&guinea=&ten=&silvermicro=` every 2 s. Keep the user's
factor and charges on the phone and send them; missing values use the defaults in `defaults`.

1. Title **Making Price** and one editable **Gold factor** field (default 0.00402) with the note
   "Gold Mini Bid × factor - used for Petal / Guinea / Ten".
2. Four cards from `rows[]`: **Mini → Petal**, **Mini → Guinea**, **Mini → Ten**, **Silver → Micro**.
   Gold cards: header label + `base_contract`; row **Gold Mini Bid × <factor>** = `base_bid` (live
   dot); row **Making charge × <multiplier>** (editable input); result **Value** = `value`,
   2 decimals. Silver card: only the editable charge and **Value**. `value` null shows a dash.

### 4.13 Bullion Stock

Screenshots: `12a_bullion_stock_*`, `12b_bullion_correlation_*`. Field details:
`APP_BULLION_STOCK_API.md`.

**Data:** `GET /bullion-stock` when the screen opens (data changes once a day); PDF at
`/bullion-stock/pdf?api_key=<key>` (`&download=1` to download).

1. Header "Bullion Warehouse Stock · MCXCCL", then "As on <as_on_date>" with a chip
   `<stale_days>d old` (green below 3 days, red from 3) and "exchange deliverable stock, updated
   daily". From 3 days old also a red note: "Data may be stale. Last updated <date> (<n> days ago)."
   **View PDF** and **Download** buttons when `pdf_available`. (The website's Refresh / Fetch now
   buttons are admin tools: leave them out.)
2. Switch **Bullion Warehouse Stock | Spread Correlation**.
3. Stock view: **Eligible Units** table **Commodity | Unit | Eligible Units | Δ 1 day** (Δ = last two
   `stock_history` values, ▲ green / ▼ red); **Daily History**: commodity chips, a trend chart of the
   chosen commodity, and a date × commodity table (paged).
4. Correlation view: links sorted by strength (|r| largest first); each row: commodity, pair and
   contract expiry, "Stock ↑ → Spread ↓" (r < 0) or "↑" (r > 0), strength (`Strong` |r| ≥ 0.7,
   `Moderate` ≥ 0.4, `Weak` ≥ 0.2, else `No clear link`) with `n` days, a bar from −1 to +1, `r`
   (2 decimals), "Chart + data". Colour: red when r < 0, green when r > 0, grey when |r| < 0.3.
   Links with |r| < 0.4 are hidden behind "Show N weaker links". Empty: "Building automatically -
   appears after a few days of history once the warehouse stock has changed."
5. Tapping a link opens a popup: title `<commodity> · <pair>`, "Contract expiry <date>"; tiles
   **Link** (r + strength), **Reads as**, **Latest stock** (+ unit, date), **Latest spread**; a
   chart; a table **Date | Stock (<unit>) | Stock change | Spread (pts) | Change | Spread % | Change**
   built by joining `spread_history[pair_name]` with the latest `stock_history[commodity]` on or
   before each date.

### 4.14 COMEX + NYMEX

Screenshots: `13_comex_nymex_*`. Field details: `APP_INTERNATIONAL_API.md`.

**Data:** WebSocket `/international/stream?api_key=<key>&interval=1` (or `GET /international` every 2 s).

1. Title **COMEX + NYMEX**, subtitle "5 live items · Interactive Brokers", status pill:
   **Blocked - logged in elsewhere** when `competing_session`, else **Live real-time** / **Delayed
   data** (`delayed`) / **Disconnected** (`connected` false). When `competing_session` is true also
   show the banner: "Prices are paused because this IBKR account is logged in somewhere else. Log out
   of the IBKR website and mobile app; the feed re-subscribes on its own within about three minutes."
2. Five cards, from `items[0..4]` (the 6th, natural gas, is not on the website): **1 GOLD SPOT**
   (XAU/USD · $/oz), **2 SILVER SPOT** (XAG/USD, 3 decimals), **3 GOLD FUTURE** (COMEX · contract),
   **4 SILVER FUTURE** (3 decimals), **5 CRUDE FUTURE** (NYMEX WTI · contract). Each: big `mid` with
   the unit, `Bid` and `Ask`, and `spread`.
3. Four tiles from `summary`: **Gold basis** (future − spot, signed), **Silver basis** (signed,
   3 decimals), **Gold / Silver** spot ratio, **Gold / Silver** future ratio.

### 4.15 IV Calculator

Screenshots: `14_iv_calculator_*`.

**Data:** `GET /iv-calculator?underlying=&strike=&days=&side=ce|pe&market=` (find IV) or `&vol=`
(find price), plus optional `rate`, `dividend`. Call it when an input changes (wait 300 ms after the
last keystroke), never on a timer.

1. Title **Option Calculator**; chips **Find IV | Find price** and **Call | Put**.
2. Inputs: **Underlying** (future price; hint "the future of the option's OWN month, not the front
   month"), **Strike**, **Days to expiry**, **Market price** (Find IV) or **Volatility %** (Find price,
   default 25), **Interest rate %** (0), **Dividend yield %** (0).
3. "Fill from the live board": chips **Crude Oil | Natural Gas** and buttons **NSE ATM | MCX ATM**.
   They read `GET /nse-mcx?commodity=<crude|natgas>&month=0` once and fill: underlying =
   `iv_basis.<nse|mcx>.forward`, days = `iv_basis.<ex>.days`, strike = the ATM row's strike, market
   price = that row's `<ce|pe>.<nse|mcx>.mid`; rate and dividend 0; mode Find IV. Disabled until the
   board has a forward.
4. Result: big **IMPLIED VOLATILITY** (`implied_vol`, 2 decimals, `%`) or **CALL / PUT PRICE**
   (`price`); `note` when present; **Call**, **Put**, **Intrinsic**, **Time value**; greeks table
   **Delta** (4), **Gamma** (6), **Vega** per 1% vol (4), **Theta** per day (4), **Rho** per 1% rate
   (4); and the parity line "strike + call − put = <x>, and the underlying you entered is <y>.
   These must agree." Before inputs are complete: "Fill the inputs".

### 4.16 Nifty / Sensex

Screenshots: `15a_*below*`, `15b_*above*`, `15c_*squareoff*`, `15d_*history*`, `15e_*calculator*`.
Field details: `APP_NIFTY_SENSEX_API.md`, `APP_OPTIONS_HISTORY_API.md`.

Header controls: **● Live | ◷ History**, **⌸ Calculator**, and the side tabs
**▼ Below ATM (10) | ▲ Above ATM (15) | ⤢ Square off ITM (15)** (`side=below|above|squareoff`).
The app today only calls `side=below`.

**Live** (`GET /options-spread?side=`, every 2 s; clear the board when the side changes):
1. Cards: **NIFTY spot** (`nifty_spot`, ATM `nifty_atm`); **DAY CHANGE** (big **Divergence**
   `day_divergence`, **Nifty** `nifty_day_change` and **Sensex** `sensex_day_change` stacked,
   **Expected** `sensex_expected_change`); **SINCE 3:16 PM** (the same four numbers from
   `ref_divergence`; title `SINCE <ref_slot as 3:16 PM>` and `YESTERDAY` when `ref_date` is the
   previous day, else the date; hide when `ref_divergence.divergence` is null); **SENSEX spot**
   (ATM `sensex_atm`); **INDIA VIX**. Values 1 decimal, signed, green / red.
2. The matrix: **Strike** (Nifty / Sensex, `ATM` badge on row 0), **ITM** (`N / S (strike − spot)`,
   2 decimals, neutral when |v| < 25, otherwise coloured), **Variation** (`S − N×3.2`), then for each
   of the three weeks (header `Week n`, `N <nifty expiry> · S <sensex expiry>`) the columns
   **N bid | S ask | Spread** (Square off ITM: **N ask | S bid | Spread**). Leg prices 2 decimals,
   Spread 0 decimals signed in a green / red cell.

**History** (`GET /options-history?weekday=&slot=&side=&weeks=`): chips **Mon to Fri**, time
**All | 10:00 AM | 3:00 PM | 3:16 PM | 3:35 PM | 3:15 PM | 3:25 PM** (`slot=both|10:00|15:00|15:16|15:35|15:15|15:25`),
**Last 4 | 7 | 12**; the side tabs apply too. Each board: header "Wednesday, 30 Sept 2026 ·
3:16 PM" and the full Live layout, including DAY CHANGE and SINCE 3:16 PM (for "YESTERDAY" compare
`ref_date` with the board's `snap_date`). Boards before 18-Aug-2026 have no SINCE card. With
`All`, draw a day divider when `snap_date` changes. When fewer days than asked come back: "3 of last
7 Wednesdays found (holidays have no snapshot)."

**Calculator** (popup, computed in the app): title "Premium Calculator"; rows **Nifty PUT** price
× **325** = value and **Sensex PUT** price × **100** = value; **Premium (Nifty − Sensex)** = Nifty
value − Sensex value, signed, green / red. Both price boxes start empty every time it opens.

### 4.17 BANKEX / BANKNIFTY

Screenshots: `16a_bankex_live_*`, `16b_bankex_history_saved_*`, `16c_bankex_history_daily_*`.

Views **Live | History** (the website's third view, paper Positions, stays on the website).

**Live** (`GET /bank-options?side=both|CE|PE&metric=points|rupees&bankex_lots=1&banknifty_lots=1`,
every 2 s):
1. Two index cards: name, action badge (`sell_index` = **SELL · BID**, `buy_index` = **BUY · ASK**),
   big `spot`, big monthly `expiry`, `ATM`, `Lot size`, last update age.
2. Controls: **Option side** (CE + PE / CE / PE), **Calculation** (Difference in points / Net premium
   in ₹), **BANKEX lots**, **BANKNIFTY lots**. Rule text: "Earlier expiry Sell at Bid → Later expiry Buy
   at Ask".
3. `status.message` as a small note above the table when not null.
4. Table, 15 rows (BANKEX ATM ± 7 × 500); `rows[]` has one record per strike per side: group by
   `offset_points`. CE block left, strikes middle, PE block right:
   - Middle: **BANKEX** strike + its points from spot (`strike − indices.BANKEX.spot`, rounded,
     signed, e.g. `64,000 +105`), **ATM distance** (`offset_points`; 0 = `ATM` badge), **BANKNIFTY**
     strike + points from its spot.
   - Per side: **Buy Ask** (`buy_price`, sub-label buy index), **Sell Bid** (`sell_price`), and the
     value (`display_value`: points, or rupees with `metric=rupees`), green / red; a green dot after
     a price when that leg is `fresh`, grey otherwise.
5. Footnote: "BANKEX ATM follows the nearest 500-point strike. BANKNIFTY strike = BANKNIFTY spot +
   (BANKEX strike − BANKEX spot), rounded to 100. Earlier expiry sold at Bid, later expiry bought at Ask."

**History** (`GET /bank-options/history?...`, on filter change):

| Source chip | Call | Notes |
|---|---|---|
| 10:00 / 3:30 boards | `source=snapshot&slot=both\|10:00\|15:30&weekday=&days=7` | Saved automatically at 10:00 AM and 3:30 PM IST (since 23-Sep-2026). A `•` after a price whose leg was older than a minute (`stale` row). |
| Daily close | `source=daily&weekday=&days=7..120` | One board per trading day since Jan 2024, closing prices; `s` after a leg priced at settlement (`settled` / `traded: false`); `listed: false` shows a dash. Headers read **Buy Close / Sell Close**. |

Filters: source, time (snapshot only: All / 10:00 AM / 3:30 PM), weekday (All days, Mon to Fri),
Last N days. Each board: "Wednesday, 07 Oct 2026 · 3:30 PM" (or "Daily close"), the two index cards
and the 15-row table, both strike columns with points from spot.

### 4.18 Signals

Screenshots: `17a_signals_*`, `17b_signals_history_*`.

**Data:** `GET /signals` (open, every 15 s, already in the Signals order), `GET /signals-history?limit=100`
(when History is open, every 15 s), `GET /signals-accuracy` (every 15 s). Push notifications as today.

1. Bar: **Open (<n>) | History** and the accuracy text `<accuracy_pct>% accurate` with
   `<right> hit · <wrong> stopped · <timeout> timed-out · <open> open`.
2. Open card per signal: pair (`label`) and direction badge (**▼ NARROW** / **▲ WIDEN**), `expiry_label`,
   trade legs (**BUY <x>**, **SELL <y>**: for `BIG / SMALL`, widen = buy BIG sell SMALL; narrow =
   buy SMALL sell BIG), **NOW** `current` with progress %, the gauge (stop → entry → target), the
   ends "✗ stop <stop>" and "target <target> ✓", footer "⚡ fired @ <entry>", `fired_at`,
   "running <age>". Values rounded to whole numbers.
   Gauge: `f(v) = clamp((v − stop) / (target − stop), 0, 1)`; entry mark at `f(entry)`; dot at
   `f(current)`; progress % = towards target `(f(cur) − f(entry)) / (1 − f(entry)) × 100`, towards
   stop `−(f(entry) − f(cur)) / f(entry) × 100`, rounded; green towards target, red towards stop.
3. Empty: "No open signals right now. A signal fires automatically when a cross-spread holds at an
   extreme (±1.5σ on the 4H % band) and the warehouse-stock direction confirms it."
4. History card: pair and outcome (**✓ RIGHT** / **✗ STOPPED** / **⏱ TIMED-OUT**), `expiry_label` ·
   direction, `entry → exit`, "⚡ fired <fired_at>", "🏁 closed <resolved_at>" (IST), "ran <duration>".
5. The same signal popup opens from a Cross Pair row's ⚡: pair, expiry, direction sentence
   ("▼ NARROW - spread likely to fall" / "▲ WIDEN - spread likely to rise"), "How to trade" (BUY / SELL
   legs; Enter now at the ▼ DEC (sell) or ▲ INC (buy) price; Exit: watch the ▲ INC (narrow) or ▼ DEC
   (widen) column, target = book profit, stop = stop loss), NOW + gauge, and **Entry (fired at),
   Target (profit), Stop (loss), Risk : Reward** (`rr`), **Fired**, **Running**, **Status**
   ("Open · usually hits in ~<expected_days>d").

### 4.19 Market badge (every screen)

`GET /market-status` every 60 s and on app resume. `now.mcx` / `now.nse`: `state` `open` | `closed` |
`holiday`, `label`, `reason`, `next_open`. Green **LIVE** when open; grey **MARKET CLOSED**;
**HOLIDAY** with `reason`. Use `nse` on Nifty / Sensex and BANKEX / BANKNIFTY, `mcx` elsewhere. An MCX
holiday can close only the morning or the evening session. `upcoming_holidays` lists the next 90 days.

---

## Part 5. Not in the app (by design)

| Website feature | Why |
|---|---|
| Auto Trades | A separate client's TradingView system, not part of the Gurukrupa app. |
| BANKEX / BANKNIFTY paper Positions; NSE vs MCX paper Close / Close all / Clear / rule editing | Write actions stay on the website. The app shows paper results read-only. |
| Bullion Stock Refresh / Fetch now, Manage Users, Market Holidays editing | Admin tools. |

---

## Part 6. Done checklist

- [ ] Cross Pair: server order, card header with `N exp`, Expiry / ▼ Dec / ▲ Inc chips, ★, ⚡ signal + popup, Hist, Spread History button.
- [ ] Calendar Spread: near − far expiry text, bracketed plain difference for Petal / Guinea / Silver 100, % column, Hist.
- [ ] Spread History dialog: toolbar, tiles, chart, table, year pages.
- [ ] Metal Spread: Expiry / ▼ Dec / ▲ Inc / % cards, full dates, ★, family colours.
- [ ] Other Commodity Spread: same cards without %.
- [ ] Metal Price checked against 4.6.
- [ ] ETF vs MCX screen.
- [ ] Premium: USD/INR 4 decimals, Ask tags on the calculators, formulas as 4.8.
- [ ] Commodity Option: four commodities, expiry switch, four cards, two-line rows.
- [ ] NSE vs MCX: Crude / Gas / Electricity, month, IV, Live, History (saved + daily), Graph, Backtest, Paper, 1 Hr History.
- [ ] MCX vs NYMEX: INR vs Dollar / INR vs INR, Crude / Gas, month, Live, History, Backtest.
- [ ] Making Price screen.
- [ ] Bullion Stock: stock and correlation views, popup, PDF.
- [ ] COMEX + NYMEX: five cards, four tiles, status pill and competing-session banner.
- [ ] IV Calculator with prefill.
- [ ] Nifty / Sensex: three sides, DAY CHANGE and SINCE 3:16 PM, history filters, Calculator.
- [ ] BANKEX / BANKNIFTY: Live and History.
- [ ] Signals: order, gauge, history, popup.
- [ ] Market badge from `/market-status`.
- [ ] Every null shows a dash; polling stops when hidden; static data fetched on user action; `429` retried.
