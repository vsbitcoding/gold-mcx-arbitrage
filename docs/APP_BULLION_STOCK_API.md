# Bullion Warehouse Stock — MCXCCL (App API)

Daily MCXCCL exchange-deliverable **bullion stock** ("Eligible Units") per
commodity, with day-by-day history and a stock-vs-spread correlation. Everything
is computed server-side.

## Endpoints
```
GET  https://arbitrage.bitcoding.ai/api/v1/bullion-stock
Header:  X-API-Key: <your key>

GET  https://arbitrage.bitcoding.ai/api/v1/bullion-stock/pdf?download=1&api_key=<your key>
     (the raw MCXCCL PDF, served from our server; key can be a query param so it opens directly)
```
- Data updates **~once a day** → fetch on screen open and refresh at most **every 60 s** (the server caches for 60 s). No WebSocket.
- Published data **lags 1–2 days** (`stale_days`) — that's the exchange's timing, not a bug.

## Response
```jsonc
{
  "server_time": "2026-07-01T08:10:00Z",
  "as_on_date": "2026-06-30",        // date printed in the PDF (header: "As on …")
  "stale_days": 1,                    // how old vs today → show a small "Xd old" chip
  "pdf_available": true,
  "pdf_name": "warehouse-vault-wise-stock-position-as-on-date-30-06-2026.pdf",
  "status": { "ok": true, "msg": "…", "as_on_date": "2026-06-30" },

  "latest": [                         // the headline table (newest day)
    { "commodity": "GOLD",      "unit": "KG", "eligible_units": 2010.0 },
    { "commodity": "GOLD MINI", "unit": "GM", "eligible_units": 4085400.0 },
    { "commodity": "SILVER",    "unit": "KG", "eligible_units": 122394.04 }
    // … 8 commodities: GOLD GUINEA, GOLD MINI, GOLD TEN, GOLD, GOLDPETAL, SILVER 100, SILVER, SILVERMIC
  ],

  "stock_history": {                  // per commodity, oldest→newest (for the chart + Δ)
    "GOLD":      [ { "date": "2026-06-17", "units": 1877.0 }, … ],
    "SILVER 100":[ { "date": "2026-06-17", "units": 1170000.0 }, … ]
    // … one array per commodity
  },

  "spread_history": {                 // per pair, oldest→newest (drives the correlation)
    "SILVER 100 / SILVER MIC": [ { "date": "2026-06-29", "spread": 12.5 }, … ]
  },

  "correlation": [                    // appears once enough history exists
    { "pair": "SILVER 100 / SILVER MIC", "commodity": "SILVER 100", "n": 3, "r": -1.0 }
  ]
}
```

## Screens to render (same as the website "Bullion Stock" tab)
1. **Eligible Units** (headline table) — from `latest[]`: Commodity · Unit · Eligible Units · **Δ 1 day**.
   - Δ 1 day = `stock_history[commodity]` last two entries: `units[last] − units[last-1]` (▲ green / ▼ red / `—`).
2. **Daily History** — pick a commodity → line chart of `stock_history[commodity]` (default **GOLD**); optionally a full matrix (date × commodities).
3. **Stock ↔ Spread correlation** — from `correlation[]`: pair · commodity · `n` days · `r` (−1…+1). Reading: `r < 0` = "stock ↑ → spread ↓". If `correlation` is empty show "building…".
4. **View / Download PDF** — link to `/api/v1/bullion-stock/pdf` (add `&download=1` to force download). If `pdf_available` is false, hide the button.

## Notes
- `eligible_units` units differ per commodity (`unit`: GM or KG) — show the `unit`.
- Numbers use Indian formatting (lakh/crore) on the site; match if you like.
- Nothing to calculate except the simple Δ; correlation/`r` is pre-computed.
