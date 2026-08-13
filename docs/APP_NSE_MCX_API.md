# NSE vs MCX — Crude Oil & Natural Gas (App API)

The same contract on two exchanges, side by side, with the difference on every
leg in **rupees and percent**.

| Side | Source |
|------|--------|
| NSE commodity | Angel One SmartAPI (the only provider that carries NSE's commodity segment) |
| MCX | Dhan option chain, same feed the rest of the app already uses |

Only **crude oil** and **natural gas** are offered. NSE lists gold, silver and
copper too, but they are dead: bid 0 / ask 0 all day against a months-old LTP
(NSE gold printed 112,578 while MCX traded 152,000). Comparing them would print
a number that looks real and is not.

---

## 1. Live board

```
GET  https://arbitrage.bitcoding.ai/api/v1/nse-mcx?commodity=crude
Header:  X-API-Key: <your key>          (same key you already use)
```

| Param | Values | Default |
|-------|--------|---------|
| `commodity` | `crude` \| `natgas` | `crude` |
| `window` | 1..25 strikes each side of ATM | `10` → 21 rows |

- Poll every **3 s** while the screen is visible, **stop when it is not**.
- One in-memory read on our side. No database, no rate-limit worries.
- NSE chains take turns (crude, then gas), so `nse.chain_age` runs up to ~6 s
  while `nse.age` (the futures) stays under 3 s. MCX refreshes every ~5 s.

### Response

```jsonc
{
  "commodity": "crude",
  "label": "CRUDE OIL",

  "future": {
    "nse": { "symbol": "CRUDEOIL26AUGFUT", "expiry": "2026-08-19",
             "bid": 7816.0, "ask": 7823.0, "mid": 7819.5, "ltp": 7820.0,
             "volume": 1420, "oi": 3310 },
    "mcx": { "symbol": "CRUDEOIL-19Aug2026-FUT", "expiry": "2026-08-19",
             "mid": 7801.5 },
    "diff": { "rupees": 18.0, "percent": 0.23 },
    "same_expiry": true            // true on both commodities
  },

  "options": {
    "nse_expiry": "2026-09-10",    // print as 10-09-2026
    "mcx_expiry": "2026-09-17",
    "same_expiry": false,          // see the warning below
    "atm": 7800.0,
    "rows": [                      // 21 strikes, low to high, already sorted
      {
        "strike": 7800.0,
        "atm": true,
        "ce": {
          "nse": { "bid": 212.0, "ask": 219.0, "mid": 215.5, "oi": 74, "traded": true },
          "mcx": { "bid": 268.0, "ask": 272.0, "mid": 270.0, "oi": 1902, "traded": true },
          "diff": { "rupees": -54.5, "percent": -20.19 }
        },
        "pe": { "nse": {...}, "mcx": {...}, "diff": {...} }
      }
    ]
  },

  "usdinr": { "symbol": "USDINR26AUGFUT", "bid": 95.4775, "ask": 95.48, "mid": 95.48 },

  "nse": { "ok": true, "age": 0.2, "chain_age": 3.3, "error": null },
  "mcx": { "ok": true, "age": 4.1, "error": null }
}
```

### Two rules you must follow when rendering

**1. Never use `ltp` for the comparison.** A dead contract still prints its last
trade from weeks ago. Use `mid`, and when `mid` is `null` show a dash.

`mid` is filled **only when both bid and ask are quoted**, and `diff` only when
both exchanges pass that test. A one-sided quote would otherwise make the mid
whatever that single side happens to be: NSE's 0.05 bid with no ask on the gas
275 put against MCX's 13.30 is a -13.25 "difference" that does not exist.
`traded: false` means the leg has neither bid nor ask; `traded: true` with a
`null` mid means only one side is quoted. Both render as a dash. The ITM half
of the NSE chain is usually like this — normal, not a bug.

**2. Show both expiry dates.** The futures line up (crude 19-Aug, gas 26-Aug),
so that difference is clean. The **options never do**:

| | NSE | MCX | Gap |
|---|---|---|---|
| Crude | 10-Sep | 17-Sep | 7 days |
| Natural gas | 20-Aug | 24-Aug | 4 days |

The MCX leg therefore carries more time value, and part of every premium
difference is time, not a real market gap. Put both dates in the column headers
so nobody reads the number as pure arbitrage.

### Suggested screen

Mirror the two sides around the strike so each pair reads inward:

```
        CALL                    STRIKE                   PUT
  NSE      MCX     Diff                    Diff     MCX      NSE
10-09-26 17-09-26                                 17-09-26 10-09-26
```

- Big number in each price cell = `mid`; small line underneath = `bid / ask`.
- Diff cell: rupees on top (bold, green positive / red negative), percent under.
- `atm: true` → highlight the row and put an "ATM" pill under the strike.
- Header chips: NSE FUTURE and MCX FUTURE with their `mid`, expiry and bid/ask.

---

## 2. History (10:00 AM, 12:00 PM, 3:00 PM IST)

```
GET  https://arbitrage.bitcoding.ai/api/v1/nse-mcx/history?commodity=crude&days=7
Header:  X-API-Key: <your key>
```

| Param | Values | Default |
|-------|--------|---------|
| `commodity` | `crude` \| `natgas` | `crude` |
| `slot` | `all` \| `10:00` \| `12:00` \| `15:00` | `all` |
| `days` | 1..60 snapshot days back | `7` |
| `date` | `YYYY-MM-DD` → that day only | — |

The **whole table** is stored at each slot, not just the ATM row.

```jsonc
{
  "commodity": "crude",
  "slot": "all",
  "slots": ["10:00", "12:00", "15:00"],
  "count": 21,
  "dates": ["2026-08-14", "2026-08-13", ...],
  "snapshots": [                 // newest first
    {
      "snap_date": "2026-08-14",
      "weekday": "fri",
      "slot": "15:00",
      "captured_at": "2026-08-14T15:00:07",
      "nse_future": 7819.5,
      "mcx_future": 7801.5,
      "future_diff": 18.0,
      "atm": 7800.0,
      "board": { ...exactly the live response above... }
    }
  ]
}
```

`board` has the **same shape as the live endpoint**, so one renderer draws both
views. Rows never change once written — fetch on control change, do **not**
poll.

### Things to tell the user on this screen

- A weekend or holiday simply has no snapshot; render the gap, do not retry.
- **No exchange sells NSE commodity history.** Angel, Dhan and IBKR all refuse
  it. Nothing before our first capture exists and nothing ever will, so the
  screen fills up going forward only.
- A slot is skipped rather than stored if the feed was cold or the market shut,
  so a missing slot means "we had nothing honest to save", not "zero".

---

## Notes

- `/api/v1/nse-mcx-crude` still works and now accepts `commodity` too. It is
  kept only for the build already shipped; use `/api/v1/nse-mcx` for new work.
- Any field can be `null` for a few seconds after our server restarts — show a
  dash, do not crash.
- All values are in **rupees**. `usdinr` is the live NSE currency future if a
  dollar conversion is needed anywhere on the screen.
