# BANKEX / BANKNIFTY

The dashboard has a `BANKEX / BANKNIFTY` page with **Live** and **Position** views.
Access is controlled by the `bankoptions` page permission in Manage Users.

## Live comparison

- Each index uses its current monthly expiry from Angel's instrument master.
  Actual expiry dates and lot sizes are read from the master, including holiday changes.
- ATM follows the live spot index. BANKEX uses the nearest listed strike on a
  **500-point grid**; BANKNIFTY uses its own **100-point grid**. Halfway values
  round upwards.
- The board shows **fifteen BANKEX strike rows**: ATM, seven strikes below and
  seven above, from **ATM − 3,500** to **ATM + 3,500**, in **500-point steps**.
- By default, every row contains separate **CE and PE** comparisons. The option
  side selector can show calls or puts alone without changing the fifteen strikes.
  Each BANKNIFTY strike has the same signed distance from its own ATM as the
  BANKEX strike. Both
  option types appear above and below ATM; their premiums are not combined.
- Missing, stale or illiquid contracts keep their place in the fifteen-row
  window. Unlisted contracts have no invented token or price, and unavailable
  pairs cannot open paper positions. An adjacent strike is never substituted.
- The earlier-expiring option is the **Buy** leg at **Ask**. The later-expiring
  option is the **Sell** leg at **Bid**. Equal expiries have no entry direction.

The calculation dropdown controls the displayed value independently of the
fixed strike window:

| Selection | Calculation |
|---|---|
| Difference in points | Sell Bid − Buy Ask |
| Difference ÷ divisor (default) | (Sell Bid − Buy Ask) ÷ 30, with an editable positive divisor |
| Net premium in ₹ | Sell Bid × sell quantity − Buy Ask × buy quantity |

Quantity is the contract's lot size multiplied by the entered whole number of
lots (default one per index). The display divisor never changes quantities or
P&L.

Liquidity is a quote diagnostic, separate from the fixed 500-point strike grid.
The API's default thresholds require fresh, uncrossed, two-sided BANKEX quotes,
at least one unit of traded volume and a Bid/Ask width no larger than 10% of the
midpoint. These thresholds are editable under **Quote quality** and label
low-liquidity pairs without hiding any strike rows. A strike ending in 000 or
500 is not automatically treated as liquid.

## Paper positions

Choose **Add CE** or **Add PE** on a matched row and confirm the entry. Positions are
private to the signed-in user and persist in `bank_option_positions`. Strikes,
expiries, direction, lot sizes and quantities are fixed at entry.

New entries must match the current fifteen-strike window. Existing positions keep
their saved contracts, including BANKEX strikes outside this window or off the
new 500-point grid; they remain subscribed, marked and closable under the same
quote and expiry checks.

Entries use the latest validated Buy Ask / Sell Bid. Open positions are marked
and closed using **Buy-leg Bid / Sell-leg Ask**. P&L is the sum of each leg's
price change multiplied by its stored quantity and direction, before charges.
Duplicate retries use a request ID and cannot create a second copy of the same
entry. Closing a position is idempotent.

Both quotes must be at most 60 seconds old and the shared equity market calendar
must be open. Missing, crossed, stale or restored-only quotes cannot create a
fill. An expired position is marked **Expired**, with no invented settlement or
realised P&L. The view provides manual entry and square-off; it sends no broker
orders and has no automatic entry/exit strategy.

## Feed integration

The feature shares the existing Angel sockets and session. A startup spot quote
centres a ±6,000-point subscription buffer. Ordinary ATM changes use that buffer;
expiry rollover or a move beyond the buffer triggers a debounced rebuild through
the existing supervisor. Open position contracts remain subscribed.

Bank option storage keys include their exchange (`NFO:token`, `BFO:token`), while
the socket receives raw exchange tokens. Existing screens retain their subscription
capacity; bank indices and pinned positions have priority over optional bank
strikes within the remaining 3,000-token budget. Capacity limits appear in the page.
The app uses its existing shared NSE/BSE equity holiday calendar.

Public contract source: [Angel instrument master](https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json).

## History

The page's third tab (client, 23-Sep-2026) shows stored boards, newest first,
each in the Live view's shape (index cards + the fifteen matched strikes):

- **10:00 / 3:30 boards**: `bank_options_history.snapshot()` is called from the
  maintenance loop at 10:00 and 15:30 IST (`SLOTS`). It reads the in-memory
  quote store through `get_live(metric="points")`, refuses a holiday (the NSE
  calendar), a cold feed and a late run (45 min window at 10:00, 8 min at
  15:30 so nothing is filed after the 15:40 close), and stores one compact row
  per (date, slot) in `bank_options_snapshot`. A history row is priced from each
  leg's LAST two-way quote when it is under fifteen minutes old and carries a
  `stale` flag when a leg was older than the Live page's 60-second "fresh" bar.
- **Daily close**: `bank_daily_history` pulls the BSE and NSE UDiFF bhavcopy
  (`BhavCopy_<EXCH>_FO_0_0_0_YYYYMMDD_F_0000`) for every weekday since January
  2024 into `bank_opt_daily` (every option row within 6,000 points of the
  underlying, every expiry; the files only list contracts that saw activity).
  A board is built per date with the Live rules at that day's close: current
  contract per index = the nearest expiry still ahead of the day (the monthly
  since 2025, when only monthlies are listed; the front weekly in 2024), BANKEX
  ATM on 500s, BANKNIFTY strike the same points from its spot, earlier expiry
  sold. A leg is priced at its close when it traded and at the settlement price
  when it did not (`settled` flag). The store is refreshed at 07:15 IST with the
  last seven days; `POST /history/backfill` (admin) fetches everything missing
  in the background.

## API and verification

All endpoints require dashboard authentication and page access:

- `GET /api/bank-options/live`
- `GET /api/bank-options/positions`
- `POST /api/bank-options/positions`
- `POST /api/bank-options/positions/{id}/close`
- `GET /api/bank-options/history?source=snapshot|daily&slot=both|10:00|15:30&weekday=mon..fri&days=7&date=YYYY-MM-DD`
- `GET /api/bank-options/history/status`
- `POST /api/bank-options/history/backfill` (admin)

The create endpoint accepts the two contract IDs, side, lots and request ID;
entry prices always come from the server's quote store. There is no public
mobile API for this page yet.

`GET /live` defaults to `side=both` and `liquidity=all`. It returns thirty
separate CE/PE pair records for the fifteen strike slots when both ATMs are
available; the frontend groups them into fifteen rows. Its `window` metadata
reports the 500-point step, seven strikes on each side and fifteen total strikes.
An explicit `side=CE` or `side=PE` still selects one option type for API clients.
The legacy `range_points` query parameter is accepted but cannot resize the
window. The legacy `liquidity=liquid` API filter may hide failing pair records;
the fixed fifteen-row dashboard uses `liquidity=all`.

Offline checks (no broker connection or live database):

```bash
cd backend
DATABASE_URL=sqlite:// python -m unittest discover -s tests -p 'test_bank_options*.py' -v
```

New tables are created by the existing `Base.metadata.create_all` startup path.
Backend and frontend changes must be deployed together for this page.
