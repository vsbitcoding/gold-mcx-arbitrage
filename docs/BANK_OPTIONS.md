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

## API and verification

All endpoints require dashboard authentication and page access:

- `GET /api/bank-options/live`
- `GET /api/bank-options/positions`
- `POST /api/bank-options/positions`
- `POST /api/bank-options/positions/{id}/close`

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
