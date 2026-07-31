# International Market — IBKR COMEX / NYMEX (App API)

The six international items, streamed **real-time** from Interactive Brokers
(COMEX Level 1 + NYMEX Level 1) on our server:

| # | Item | Symbol | Unit |
|---|------|--------|------|
| 1 | Gold spot | XAU/USD | $/oz |
| 2 | Silver spot | XAG/USD | $/oz |
| 3 | Gold future | COMEX GC | $/oz |
| 4 | Silver future | COMEX SI | $/oz |
| 5 | Crude future | NYMEX WTI CL | $/bbl |
| 6 | Crude options | NYMEX, 11 strikes around the money | premium in $ |

Mid prices, spreads, ATM strike, ITM side and the summary numbers are all
computed **server-side** — the app only renders what it receives.

## Endpoint
```
GET  https://arbitrage.bitcoding.ai/api/v1/international
Header:  X-API-Key: <your key>          (same key you already use)
```
- Live data. Poll every **2 s** while the screen is visible, **stop polling when
  it is not** (background / another tab). No WebSocket for this screen.
- One tiny in-memory read on our side — no database, no rate limit worries.
- `age` on every quote = seconds since the last tick. Under ~5 s means live.

## Response
```jsonc
{
  "server_time": "2026-07-30T14:22:10Z",
  "source": "Interactive Brokers (COMEX + NYMEX)",
  "connected": true,          // false => show "feed disconnected"
  "delayed": false,           // true  => show a "delayed" chip instead of "live"

  "items": [                  // always these 5, always in this order
    {
      "name": "GOLD SPOT",
      "symbol": "XAU/USD",
      "unit": "$/oz",
      "decimals": 2,          // how many decimals to print
      "bid": 4081.20,
      "ask": 4081.49,
      "mid": 4081.35,         // show this as the big number
      "spread": 0.29,
      "contract": null,       // futures only, e.g. "GCV6"
      "expiry": null,         // futures only, "YYYYMMDD"
      "age": 0.4
    },
    { "name": "SILVER SPOT",   "symbol": "XAG/USD",      "decimals": 3, ... },
    { "name": "GOLD FUTURE",   "symbol": "COMEX GC",     "contract": "GCV6", ... },
    { "name": "SILVER FUTURE", "symbol": "COMEX SI",     "contract": "SIU6", ... },
    { "name": "CRUDE FUTURE",  "symbol": "NYMEX WTI CL", "contract": "CLU6", ... }
  ],

  "crude_options": {
    "exchange": "NYMEX",
    "expiry": "20260807",     // YYYYMMDD -> print as 07-08-2026
    "underlying": 81.91,      // live crude future price
    "atm_strike": 82.00,
    "age": 0.4,
    "rows": [                 // 11 strikes, low to high, already sorted
      {
        "strike": 81.75,
        "atm": false,
        "itm": "call",        // "call" | "put" | null -> shade that side
        "call": { "bid": 3.13, "ask": 3.27, "mid": 3.20 },
        "put":  { "bid": 2.96, "ask": 3.11, "mid": 3.04 }
      },
      { "strike": 82.00, "atm": true, "itm": null, ... }
    ]
  },

  "summary": {
    "gold_basis": 26.55,             // gold future - gold spot
    "silver_basis": 0.234,           // silver future - silver spot
    "gold_silver_ratio_spot": 69.81,
    "gold_silver_ratio_future": 69.98,
    "atm_straddle": 6.29             // ATM call mid + ATM put mid
  }
}
```

## Suggested screen
1. **Five cards** across the top — one per item in `items`, in the order given.
   Big number = `mid`, small green/red boxes = `bid` / `ask`, footer =
   `symbol` (+ `contract` for futures) and `spread`.
2. **Summary strip** — the five values in `summary` as small tiles. Colour
   `gold_basis` / `silver_basis` green when positive, red when negative.
3. **Option chain** — `crude_options.rows`: CALL bid/ask/mid on the left,
   STRIKE in the middle, PUT mid/bid/ask on the right.
   - `atm: true` → highlight the whole row and put an "ATM" pill under the strike.
   - `itm: "call"` → tint the three call cells; `"put"` → tint the put cells.
4. **Status chip** — from `connected` / `delayed`.
   `connected && !delayed` = "Live real-time".

## Notes
- Print each value with the `decimals` the API gives (silver is 3, gold 2).
- Any field can be `null` for a few seconds right after our server restarts —
  show "—", do not crash.
- Numbers are in **USD**. There is no USD/INR in this response; if a rupee value
  is needed on the screen, take `usdinr` from `/api/v1/premium-inputs`.
- This data is licensed to Gurukrupa Bullion for their own use. Keep the screen
  inside the logged-in app — it must not be exposed on a public page or shared
  outside the client's own users.
