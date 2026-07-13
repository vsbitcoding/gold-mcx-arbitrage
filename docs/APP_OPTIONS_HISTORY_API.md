# App API — Nifty/Sensex Board History (weekday compare)

The server auto-captures the full Nifty/Sensex PE options board twice every
trading day — at **10:00** and **15:00 IST** (replacing the client's manual
screenshots). This endpoint returns those stored boards so the app can show
"the last 7 Mondays at 10am" style comparisons.

## Endpoint

```
GET /api/v1/options-history
Header: X-API-Key: <key>      (same key as all /api/v1 endpoints)
```

| Param | Values | Default | Meaning |
|---|---|---|---|
| `weekday` | `mon..sun` or `0..6` (0=Mon) | — | compare the same weekday across weeks; omit → latest snapshot days |
| `slot` | `10:00` \| `15:00` \| `both` | `both` | which capture time |
| `side` | `below` \| `above` \| `squareoff` | `below` | same meaning as `/api/v1/options-spread` |
| `weeks` | 1–52 | `7` | how many most-recent matching days |
| `date` | `YYYY-MM-DD` | — | one specific day's snapshot(s) instead of a weekday series |

**Do not poll.** History is static once written — fetch when the user opens
the screen or changes a filter.

## Example

```
GET /api/v1/options-history?weekday=mon&slot=10:00&side=below&weeks=7
```

```jsonc
{
  "server_time": "2026-07-13T05:31:00+00:00",
  "market_open": true,
  "weekday": "mon",            // echo of the filter (null if not given)
  "slot": "10:00",
  "side": "below",
  "weeks_requested": 7,
  "date": null,
  "count": 5,                  // can be < weeks_requested (holidays: no snapshot)
  "dates": ["2026-07-13", "2026-07-06", "..."],
  "snapshots": [               // newest first; one per date+slot
    {
      "snap_date": "2026-07-13",
      "weekday": "mon",
      "slot": "10:00",
      "captured_at": "2026-07-13T10:00:07",   // IST
      "nifty_spot": 24812.5,
      "sensex_spot": 81340.2,
      "india_vix": 11.4,
      "nifty_atm": 24800,
      "sensex_atm": 81300,
      "side": "below",
      "weeks": [               // SAME shape as /api/v1/options-spread → reuse the same renderer
        {
          "week_index": 0,
          "nifty_expiry": "2026-07-14T14:30:00",
          "sensex_expiry": "2026-07-16T14:30:00",
          "rows": [
            {
              "nifty_strike": 24800, "sensex_strike": 81300,
              "nifty_pe": 92.3, "sensex_pe": 305.8,          // LTP (info)
              "nifty_bid": 92.1, "nifty_ask": 92.6,
              "sensex_bid": 305.0, "sensex_ask": 306.5,
              "nifty_leg": 92.1, "sensex_leg": 306.5,        // leg used for THIS side
              "nifty_value": 29932.5, "sensex_value": 30650.0,
              "spread": -717.5
            }
            // ... more strikes ...
          ]
        }
        // week_index 1, 2
      ]
    }
    // ... older Mondays ...
  ]
}
```

## Rules for the app

1. **Render `count`, don't assume N** — market holidays have no snapshot, so
   "last 7 Mondays" can return fewer items.
2. **Row shape = live board** (`/api/v1/options-spread`): reuse the existing
   table renderer; `spread ≥ 0` green, `< 0` red, `null` → em-dash.
3. Strikes differ per date (ATM moves). For a compare grid, align rows by
   POSITION (row 0 = that day's ATM, row 1 = ATM±1 step, ...), not by
   absolute strike.
4. Suggested screen: weekday chips (Mon–Fri) + 10:00/3:00 toggle + the same
   below/above/squareoff sides + "last 4/7/12" selector → columns = dates,
   rows = strike position, cell = spread (strikes in small text).
5. `?date=YYYY-MM-DD` + `slot=both` → both boards of one specific day
   (for a "that day" detail view).

The web dashboard's Nifty/Sensex → **History** view is the reference
implementation.
