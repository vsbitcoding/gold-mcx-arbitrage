# Commodity Options Spread — Gold / Silver / Crude Oil / Natural Gas (App API)

Live **BIG contract vs its MINI** option-spread per commodity (watch-only), for the
**current + next monthly expiry**. Everything is computed server-side.

## Endpoint
```
GET  https://arbitrage.bitcoding.ai/api/v1/gold-options-spread?commodity=gold
Header:  X-API-Key: <your key>
```
`commodity` = **`gold` | `silver` | `crude` | `natgas`** (the response also lists them in `commodities`).
- **Poll every 1–2 s** while the screen is open. No WebSocket.
- Row count per expiry varies — read `expiries[i].rows.length`, don't hard-code.

## Response
```jsonc
{
  "server_time": "2026-07-01T09:31:00Z",
  "market_open": true,
  "commodity": "gold",
  "label": "Gold",
  "big_name": "GOLD",          // BIG contract display name
  "mini_name": "GOLD MINI",    // MINI contract display name
  "big_price": 141634,         // BIG future  (header card)
  "mini_price": 139654,        // MINI future (header card)
  "ref": 140644,               // moneyness reference; ATM = strike nearest this
  "higher": "GOLD",            // whichever future is higher → quotes at ASK
  "lower":  "GOLD MINI",       // the other → quotes at BID   (auto-flips! e.g. Silver MINI is currently higher)
  "spread1_label": "GOLD MINI Bid - GOLD Ask",  // ← column header for spread1
  "spread2_label": "GOLD Bid - GOLD MINI Ask",  // ← column header for spread2
  "commodities": [ {"key":"gold","label":"Gold"}, {"key":"silver","label":"Silver"},
                   {"key":"crude","label":"Crude Oil"}, {"key":"natgas","label":"Natural Gas"} ],
  "expiries": [                // current month first, then next month
    {
      "expiry_index": 0,
      "big_expiry":  "2026-07-29T23:30:00",   // show date only
      "mini_expiry": "2026-07-29T23:30:00",   // may differ from big (a few days) — show both if different
      "rows": [
        {
          "strike": 120000,
          "type": "PE",        // PE below the price, CE above
          "big_bid": 260.0, "big_ask": 261.0,     // BIG option bid/ask
          "mini_bid": 239.5, "mini_ask": 240.5,   // MINI option bid/ask
          "spread1": -21.5,    // ← cell value (col 1)
          "spread2":  19.5     // ← cell value (col 2)
        }
        // ... one row per common strike (any numeric may be null → show —)
      ]
    }
    // ... expiries[1] = next month
  ]
}
```

## Layout — ODIN-style, TWO rows per strike (same as the website)
Each strike shows a **MINI row** then a **BIG row** (Contract | Bid | Ask), with
Strike, Type and both Spreads spanning the pair:

| Strike | Type | Contract | Bid | Ask | `spread1_label` | `spread2_label` |
|---|---|---|---|---|---|---|
| **120000** (span 2) | **PE** (span 2) | `mini_name` | `mini_bid` | `mini_ask` | **`spread1`** (span 2) | **`spread2`** (span 2) |
|  |  | `big_name` | `big_bid` | `big_ask` |  |  |

- Add a **commodity selector** (Gold / Silver / Crude Oil / Natural Gas) from `commodities`; re-fetch with `?commodity=`.
- ATM row = strike nearest `ref` (highlight the whole pair). Type: PE red, CE green.
- Spread colour: **< 0 red**, **> 0 green**, `null` → `—`.
- **Use `spread1_label` / `spread2_label` as the column headers** and `big_name`/`mini_name` for the Contract cells — the higher/lower side **auto-flips** per commodity.
- (Phones: a per-strike card works well — Strike+Type, MINI & BIG Bid/Ask, both spreads.)

## The spread (already computed server-side — just display)
The leg whose **future is higher** (`higher`) quotes at its **Ask**; the **lower**
(`lower`) at its **Bid**. 1:1, no multiplier.
```
spread1 = lower.Bid  - higher.Ask
spread2 = higher.Bid - lower.Ask
```
**Nothing to calculate in the app — read `spread1` / `spread2` directly.**
