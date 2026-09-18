# BANKEX / BANKNIFTY

The dashboard has a `BANKEX / BANKNIFTY` page with **Live** and **Position** views.
Access is controlled by the `bankoptions` page permission in Manage Users.

## Live comparison

- Each index uses its current monthly expiry from Angel's instrument master.
  Actual expiry dates and lot sizes are read from the master, including holiday changes.
- ATM follows the live spot index and rounds to the nearest listed strike; a
  halfway value rounds upwards. BANKEX determines the displayed strikes.
- A CE is paired at the same number of points above each ATM; a PE at the same
  number of points below. ATM is included. A missing exact counterpart is omitted.
- The earlier-expiring option is the **Buy** leg at **Ask**. The later-expiring
  option is the **Sell** leg at **Bid**. Equal expiries have no entry direction.
- The strike dropdown, CE/PE selector and 1,000/2,000/3,000-point range control
  the board. There is no combined straddle premium.

The calculation dropdown makes the previously unspecified “divide by 30”
instruction explicit and adjustable:

| Selection | Calculation |
|---|---|
| Difference in points | Sell Bid − Buy Ask |
| Difference ÷ divisor (default) | (Sell Bid − Buy Ask) ÷ 30, with an editable positive divisor |
| Net premium in ₹ | Sell Bid × sell quantity − Buy Ask × buy quantity |

Quantity is the contract's lot size multiplied by the entered whole number of
lots (default one per index). The display divisor never changes quantities or
P&L. These controls are implementation defaults chosen after the user delegated
the remaining decisions; a particular lot ratio was not specified by the client.

“Liquid strikes” defaults to BANKEX having fresh, uncrossed, two-sided quotes,
at least one unit of traded volume, and a Bid/Ask width no larger than 10% of
the midpoint. Volume and width thresholds are editable. This filter evaluates
quotes; a strike ending in 000 or 500 is not automatically treated as liquid.
“All monitored strikes” also displays contracts which fail that filter.

## Paper positions

Choose **Add position** on a matched pair and confirm the entry. Positions are
private to the signed-in user and persist in `bank_option_positions`. Strikes,
expiries, direction, lot sizes and quantities are fixed at entry.

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

Offline checks (no broker connection or live database):

```bash
cd backend
DATABASE_URL=sqlite:// python -m unittest discover -s tests -p 'test_bank_options*.py' -v
```

New tables are created by the existing `Base.metadata.create_all` startup path.
Backend and frontend changes must be deployed together for this page.
