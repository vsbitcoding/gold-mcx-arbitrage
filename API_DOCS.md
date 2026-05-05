# Arbi Public API v1 — Developer Reference

Read-only API for monitoring live MCX gold spread pairs.

**Base URL:** `https://arbitrage.bitcoding.ai`
**Version:** `v1`
**Auth:** API Key (provided separately)

---

## Authentication

Every request (except `/api/v1/health`) requires an API key. Two ways to send it:

| Method | Example |
|--------|---------|
| HTTP header (recommended) | `X-API-Key: arbi_live_xxxxxxxx` |
| Query parameter | `?api_key=arbi_live_xxxxxxxx` |

Invalid or missing key returns `401 Unauthorized`.

---

## Endpoints

### `GET /api/v1/health`

Public uptime check, no auth.

**Response 200:**
```json
{
  "status": "ok",
  "server_time": "2026-05-05T07:35:00Z",
  "market_open": true
}
```

---

### `GET /api/v1/pairs`

List all active spread pairs with current bid/ask and computed spreads.

**Query params:**

| Param | Type | Description |
|-------|------|-------------|
| `type` | `cross` \| `calendar` \| `all` | Filter by pair type. Default: all |
| `search` | string | Text filter on pair label/expiry (case-insensitive) |

**Response 200:**
```json
{
  "total": 55,
  "server_time": "2026-05-05T07:35:00Z",
  "market_open": true,
  "pairs": [
    {
      "id": "Petal-Guinea@2026-05-29",
      "type": "cross",
      "label": "PETAL / GUINEA",
      "expiry": "29 May 2026",
      "expiry_short": "29MAY26",
      "decrease_spread": 320.00,
      "increase_spread": 375.00,
      "big": {
        "instrument": "petal",
        "trading_symbol": "GOLDPETAL-29May2026-FUT",
        "lots": 8,
        "bid": 15028.0,
        "ask": 15042.0
      },
      "small": {
        "instrument": "guinea",
        "trading_symbol": "GOLDGUINEA-29May2026-FUT",
        "lots": 1,
        "bid": 119737.0,
        "ask": 119999.0
      }
    }
  ]
}
```

---

### `GET /api/v1/pairs/{pair_id}`

Single pair detail. Returns same shape as one element of `pairs` array.

**Path param:** `pair_id` from `/api/v1/pairs` response (URL-encode special chars)

**Examples:**
- `/api/v1/pairs/Petal-Guinea@2026-05-29` (cross)
- `/api/v1/pairs/Petal@2026-05-29/2026-06-30` (calendar)

**Response 404** if not found.

---

### `WS /api/v1/stream`

Live WebSocket pushing periodic snapshots.

**Connect:** `wss://arbitrage.bitcoding.ai/api/v1/stream?key=YOUR_KEY&interval=1`

| Query param | Type | Default | Description |
|-------------|------|---------|-------------|
| `key` | string | — | Your API key (required) |
| `interval` | float | 1.0 | Snapshot push interval in seconds (0.5 to 5.0) |

**Server pushes (JSON):**
```json
{
  "type": "snapshot",
  "server_time": "2026-05-05T07:35:00Z",
  "market_open": true,
  "pairs": [ ...same shape as REST pairs... ]
}
```

**Heartbeat:** client may send the literal string `"ping"`, server replies `"pong"`. Recommended every 25–30 sec to keep nginx connection alive.

**Auto-reconnect** strategy on client side recommended — exponential backoff (1s → 2s → 4s → max 30s).

---

## Data Reference

### Pair `type`

| Value | Meaning |
|-------|---------|
| `cross` | Two different instruments, same expiry month (e.g. Petal vs Guinea, 29 May) |
| `calendar` | Same instrument, different months (e.g. Petal Jun vs Petal May — far minus near) |

### Spread fields

| Field | Formula |
|-------|---------|
| `decrease_spread` | `(big.bid × big_mult) − (small.ask × small_mult)` |
| `increase_spread` | `(big.ask × big_mult) − (small.bid × small_mult)` |

### Multipliers per instrument

| Instrument | Multiplier |
|------------|-----------|
| `petal` | × 10 |
| `guinea` | × 1.25 |
| `ten` | × 1 |
| `mini` | × 1 |

For calendar pairs both legs use the same instrument multiplier.

### Lot sizes (cross pairs)

| Pair combination | Big lots | Small lots |
|-----------------|----------|------------|
| Petal / Guinea | 8 | 1 |
| Petal / Ten | 10 | 1 |
| Petal / Mini | 100 | 1 |
| Guinea / Ten | 5 | 4 |
| Guinea / Mini | 25 | 2 |
| Ten / Mini | 10 | 1 |

Calendar spreads always use 1:1 lots.

### `null` spreads

If `decrease_spread` or `increase_spread` is `null`, the corresponding leg has no bid/ask data (market closed, holiday, or new contract). Treat as "not tradeable".

---

## Code Samples

### JavaScript / Browser

```js
const KEY = "arbi_live_xxxxxxxx";

// REST
const res = await fetch("https://arbitrage.bitcoding.ai/api/v1/pairs", {
  headers: { "X-API-Key": KEY },
});
const { pairs } = await res.json();

// WebSocket
const ws = new WebSocket(
  `wss://arbitrage.bitcoding.ai/api/v1/stream?key=${KEY}&interval=1`
);
ws.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  if (msg.type === "snapshot") {
    msg.pairs.forEach(p => console.log(p.label, p.decrease_spread, p.increase_spread));
  }
};
setInterval(() => ws.readyState === 1 && ws.send("ping"), 25000);
```

### Swift (iOS)

```swift
let url = URL(string: "https://arbitrage.bitcoding.ai/api/v1/pairs")!
var req = URLRequest(url: url)
req.addValue("arbi_live_xxxxxxxx", forHTTPHeaderField: "X-API-Key")
URLSession.shared.dataTask(with: req) { data, _, _ in
  if let data = data, let json = try? JSONSerialization.jsonObject(with: data) {
    print(json)
  }
}.resume()

// WebSocket (URLSessionWebSocketTask)
let wsURL = URL(string: "wss://arbitrage.bitcoding.ai/api/v1/stream?key=arbi_live_xxxxxxxx")!
let task = URLSession.shared.webSocketTask(with: wsURL)
task.resume()
task.receive { result in /* handle messages */ }
```

### Kotlin (Android, OkHttp)

```kotlin
val client = OkHttpClient()
val req = Request.Builder()
  .url("https://arbitrage.bitcoding.ai/api/v1/pairs")
  .header("X-API-Key", "arbi_live_xxxxxxxx")
  .build()
client.newCall(req).execute().use { resp ->
  println(resp.body?.string())
}

// WebSocket
val wsReq = Request.Builder()
  .url("wss://arbitrage.bitcoding.ai/api/v1/stream?key=arbi_live_xxxxxxxx")
  .build()
client.newWebSocket(wsReq, object : WebSocketListener() {
  override fun onMessage(ws: WebSocket, text: String) {
    println(text)
  }
})
```

### Python (test client)

```python
import requests, websockets, asyncio, json

KEY = "arbi_live_xxxxxxxx"

# REST
r = requests.get("https://arbitrage.bitcoding.ai/api/v1/pairs",
                 headers={"X-API-Key": KEY})
print(r.json()["total"], "pairs")

# WebSocket
async def stream():
    url = f"wss://arbitrage.bitcoding.ai/api/v1/stream?key={KEY}"
    async with websockets.connect(url) as ws:
        async for msg in ws:
            data = json.loads(msg)
            print(len(data["pairs"]), "pairs received")

asyncio.run(stream())
```

---

## Error Codes

| Code | Meaning |
|------|---------|
| 200  | OK |
| 401  | Missing or invalid API key |
| 404  | Pair not found |
| 429  | Rate limited (currently no hard limit on `/api/v1/*`, but reasonable use expected) |
| 500  | Server error — retry with backoff |

WebSocket close codes:

| Code | Meaning |
|------|---------|
| 1008 | Policy violation (auth failed) |
| 1011 | Server error |

---

## Best Practices

| Tip | Why |
|-----|-----|
| Use WebSocket for live updates | Lower latency + lower bandwidth than REST polling |
| Send `ping` every 25-30 sec | Keeps nginx and CDN connections alive |
| Cache pair list locally | The pair set rarely changes (only when months roll) |
| Re-fetch list once a day | To pick up new contract months as they're listed |
| Implement reconnect with backoff | Handle network drops gracefully |
| Treat `null` spreads as "no data" | Don't display 0 or alert on these |

---

## Rate Limits

No hard limit currently. The system supports tens of thousands of req/min easily. WebSocket is preferred for high-frequency monitoring.

If you need bulk historical data or higher rates, contact the platform team.

---

## Support

- API contact: bitcoding.ai@gmail.com
- Issues / change requests: contact above
- Status: `/api/v1/health` (no auth needed)
