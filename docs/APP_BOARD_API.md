# App API — Live Rate Board (LIVE RATES / SILVER RATES screens)

Powers the customer app's rate screens from the NEW admin panel (Scrip Master).
Whatever the dealer sets in the admin (parity, ±5 nudge, visible on/off, order)
reflects here within ~1 second.

## Endpoint

```
GET /api/v1/board?template=<template>
Header: X-API-Key: <same key as all /api/v1 endpoints>
```

| template | App screen |
|---|---|
| `gurukrupa` | **LIVE RATES** tab (default) |
| `gurukrupasilver` | **SILVER RATES** tab |
| `gurukrupab2c` | (reserved — B2C pricing board) |

**Polling:** every **2s** while the rate screen is visible; **stop when the app
is backgrounded**. Update values in place — no blink/flash animations.

## Response

```jsonc
{
  "server_time": "2026-07-14T09:20:11+00:00",
  "market_open": true,
  "template": "gurukrupa",
  "scrips": [                    // ONLY visible scrips, already in display order
    { "name": "GOLD($)",   "code": "8868", "buy": 4028.0,   "sell": 4028.0,
      "low": 4025.2, "high": 4061.8, "trade": false },
    { "name": "INR(₹)",    "code": "8870", "buy": 96.22,    "sell": 96.23,
      "low": 96.035, "high": 96.2,   "trade": false },
    { "name": "GOLD COST", "code": "8871", "buy": 141625.0, "sell": 141671.0,
      "low": 140740.0, "high": 141788.0, "trade": false },
    { "name": "GOLD 999 WITH GST IMP", "code": "8925", "buy": 141171.0,
      "sell": 146621.0, "low": 146339.0, "high": 148200.0, "trade": true }
  ]
}
```

Fields per scrip:
- `buy` / `sell` — live rates (null → show "—"; happens briefly after a server restart)
- `low` / `high` — that scrip's **day** low/high (IST day, tracked server-side; null early in the day)
- `trade` — `true` = orderable product (keep for the upcoming Order flow)
- `code` — scrip code (stable id for the app)

## Rendering rules (match the current app screen)

1. **Top cards** = the reference scrips: `GOLD($)`, `INR(₹)`, `GOLD COST`
   (on silver tab: `SILVER($)`, `INR(₹)`, `SILVER COST`). Big number = `sell`;
   below it `low | high`.
2. **PRODUCT / SELL table** = the remaining scrips (typically `trade: true`),
   big number = `sell`, with `L: low  H: high` underneath.
   Simple rule that works for both tabs: scrips whose `name` matches a top-card
   name → cards; everything else → product rows. (Order is already correct.)
3. Indian number formatting (1,41,625). 2 decimals for $/₹ values, 0 for rupees
   rates — follow the current app's formatting.
4. `market_open: false` → show the "market closed" state; keep last rates visible.
5. Values change SILENTLY in place — no row blink.

## Notes
- Rates originate from the new Scrip Master admin — scrips can be added/renamed/
  hidden by the dealer at any time. Render whatever the API returns (don't
  hard-code the product list); only the 3 card names above are special-cased.
- Marquee text ("Welcome to Gurukrupa Jewellers.") + news/ticker APIs come next
  (separate endpoint, will be documented the same way).
- Order placing ("trade": true products) is a later phase — API not live yet.
