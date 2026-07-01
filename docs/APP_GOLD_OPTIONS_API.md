# GOLD / GOLD MINI — Options Spread (App API)

Live GOLD vs GOLD MINI (GOLDM) option-spread table (watch-only), for the
**current + next monthly expiry**. Everything is computed server-side — the app
just displays it.

## Endpoint
```
GET  https://arbitrage.bitcoding.ai/api/v1/gold-options-spread
Header:  X-API-Key: <your key>
```
- **Poll every 1–2 s** while the screen is open (no WebSocket for options).
- No query params. The response contains **both expiry months**; make an in-app
  toggle (see `expiries[]`), don't call twice.
- Row count per expiry varies (15 / 13 / …) — read `expiries[i].rows.length`,
  don't hard-code.

## Response
```jsonc
{
  "server_time": "2026-07-01T07:35:00Z",
  "market_open": true,
  "gold_price": 141480,          // GOLD future  (header card)
  "goldm_price": 139500,         // GOLD MINI future (header card)
  "ref": 140490,                 // moneyness reference; ATM = strike nearest this
  "higher": "GOLD",              // which future is higher → quotes at ASK
  "lower":  "GOLDM",             // the other → quotes at BID
  "spread1_label": "GOLDM Bid - GOLD Ask",   // ← column header for spread1
  "spread2_label": "GOLD Bid - GOLDM Ask",   // ← column header for spread2
  "status": { "subscribed_options": 112 },
  "expiries": [                  // current month first, then next month
    {
      "expiry_index": 0,
      "gold_expiry":  "2026-07-29T23:30:00",   // show date only
      "goldm_expiry": "2026-07-29T23:30:00",   // may differ from gold (e.g. Aug: 31 vs 28) — show both if different
      "rows": [
        {
          "strike": 120000,
          "type": "PE",          // PE below the price, CE above  (badge: PE red, CE green)
          "goldm_bid": 237.0, "goldm_ask": 239.5, "goldm_ltp": 238.5,
          "gold_bid":  256.5, "gold_ask":  260.0, "gold_ltp":  263.0,
          "spread1": -23.0,      // ← THE cell value (col 1)
          "spread2":  17.0       // ← THE cell value (col 2)
        }
        // ... one row per common 5,000-gap strike
      ]
    }
    // ... expiries[1] = next month
  ]
}
```

## Layout to render (ODIN-style — TWO rows per strike, like the website)
Each strike shows **two stacked rows** — GOLD MINI first, then GOLD — with Strike,
Type and the two Spreads spanning the pair:

| Strike | Type | Contract | Bid | Ask | `spread1_label` | `spread2_label` |
|---|---|---|---|---|---|---|
| **120000** (span 2) | **PE** (span 2) | GOLD MINI | `goldm_bid` | `goldm_ask` | **`spread1`** (span 2) | **`spread2`** (span 2) |
|  |  | GOLD | `gold_bid` | `gold_ask` |  |  |

- **Strike**, **Type**, **`spread1`**, **`spread2`** are per-strike → span both rows.
- ATM row = strike nearest `ref` (highlight the whole pair).
- Type badge: `PE` red, `CE` green.
- Spread colour: **< 0 → red**, **> 0 → green**. Any `null` → `—`.
- (On phones a per-strike card works well: Strike+Type header, GOLD MINI & GOLD Bid/Ask, both spreads.)

## The spread (already computed server-side — just display)
The leg whose **future price is higher** (`higher`) quotes at its **Ask**; the
**lower** (`lower`) quotes at its **Bid**. 1:1, no multiplier.
```
spread1 = lower.Bid  − higher.Ask      (= GOLDM Bid − GOLD Ask, when GOLD is higher)
spread2 = higher.Bid − lower.Ask       (= GOLD Bid − GOLDM Ask)
```
- The `higher`/`lower` sides **auto-flip** if GOLD MINI ever trades above GOLD, so
  **use `spread1_label` / `spread2_label` as the column headers** (don't hard-code).
- **Nothing to calculate in the app — read `spread1` / `spread2` directly.**

## Header cards
`gold_price`, `goldm_price` (futures), and a "Pricing side: `higher` → Ask, `lower` → Bid" chip.

## Notes
- Two expiry months (`expiries[0]` current, `expiries[1]` next). GOLD and GOLD MINI
  option expiry **dates** can differ by a few days within the same month — that's
  expected; show `gold_expiry` (and `goldm_expiry` if different).
- Strikes are the common 5,000-gap strikes available in **both** GOLD and GOLD MINI.
- Some far-OTM strikes may have `null` legs/spreads (illiquid) → render `—`.
