# Nifty / Sensex — PE Options Spread (App API)

Live PE-options spread table with **two tabs**: **Below ATM** and **Above ATM**.

## Endpoint
```
GET  https://arbitrage.bitcoding.ai/api/v1/options-spread?side=below
GET  https://arbitrage.bitcoding.ai/api/v1/options-spread?side=above
Header:  X-API-Key: <your key>
```

| `side`       | Tab name        | Shows                       | Rows | Legs used (spread)              |
|--------------|-----------------|-----------------------------|------|---------------------------------|
| `below`      | Below ATM       | ATM + 9 **lower** strikes   | 10   | Nifty **bid** / Sensex **ask**  |
| `above`      | Above ATM       | ATM + 14 **higher** strikes | 15   | Nifty **bid** / Sensex **ask**  |
| `squareoff`  | Square off ITM  | same as Above (ITM)         | 15   | Nifty **ask** / Sensex **bid**  |

- Make **three tabs** in the app; call the same endpoint with `side=below` / `side=above` / `side=squareoff`.
- For the leg-price columns use `nifty_leg` / `sensex_leg` (already the correct bid/ask for that side). Header labels: below/above → "N bid" / "S ask"; squareoff → "N ask" / "S bid".
- **Poll every 1–2 s** while the screen is open (no WebSocket for options).
- Render row count from `weeks[i].rows.length` (10 or 15) — don't hard-code.

## Response
```jsonc
{
  "side": "above",                 // echoes the requested side
  "server_time": "2026-06-17T06:04:42Z",
  "market_open": true,
  "nifty_spot": 24093.55,
  "sensex_spot": 77167.60,
  "nifty_atm": 24100,              // header chips
  "sensex_atm": 77200,
  "status": { "subscribed_options": 396 },   // show as "SUBSCRIBED"
  "weeks": [                       // always 3 (week 0 = nearest expiry)
    {
      "week_index": 0,
      "nifty_expiry":  "2026-06-23T14:30:00",   // show date only
      "sensex_expiry": "2026-06-25T15:30:00",
      "rows": [
        {
          "nifty_strike": 24100,
          "sensex_strike": 77200,
          "nifty_pe":   176.80,   // Nifty PE LTP  (info only)
          "sensex_pe":  659.60,   // Sensex PE LTP (info only)
          "nifty_bid":  176.45, "nifty_ask":  187.35,   // both legs always present
          "sensex_bid": 690.30, "sensex_ask": 664.35,
          "nifty_leg":  176.45,   // ← show this in the N column (= bid for below/above, ask for squareoff)
          "sensex_leg": 664.35,   // ← show this in the S column (= ask for below/above, bid for squareoff)
          "nifty_value":  57346.25,  // = nifty_leg  × 325
          "sensex_value": 66435.00,  // = sensex_leg × 100
          "spread":      -9088.75    // = nifty_value − sensex_value   ← THE cell value
        }
        // ... 10 rows (below) or 15 rows (above)
      ]
    }
    // ... week 1, week 2
  ]
}
```

## Row 0 is ATM
- `side=below` → strikes go **down** (24100, 24050, 24000 …)
- `side=above` → strikes go **up**   (24100, 24150, 24200 …)

## Columns to render (same as the website)
| Column     | Value                                              |
|------------|----------------------------------------------------|
| **Strike** | `nifty_strike / sensex_strike`                     |
| **ITM**    | `nifty_strike − nifty_spot`  /  `sensex_strike − sensex_spot` |
| **Variation** | `(sensex_strike − sensex_spot) − (nifty_strike − nifty_spot) × 3.2` |
| **Per week** | `nifty_bid`  ·  `sensex_ask`  ·  `spread`         |

## The spread (already computed server-side — just display)
```
spread = nifty_bid × 325 − sensex_ask × 100      (falls back to LTP if no bid/ask)
```
Colour: **spread < 0 → red**, **spread > 0 → green**. A `null` value → show `—`.

> Nothing to calculate in the app — read `spread` directly. The `?side` switch is the only new thing vs the earlier spec.
