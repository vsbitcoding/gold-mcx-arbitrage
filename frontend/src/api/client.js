const TOKEN_KEY = "arbi_token";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}
export function setToken(t) {
  localStorage.setItem(TOKEN_KEY, t);
}
export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem("arbi_role");
  localStorage.removeItem("arbi_user");
  localStorage.removeItem("arbi_pages");
}

// 'admin' sees the whole dashboard and manages users; 'trader' (the webhook
// client) sees only Auto Trades; 'user' sees the pages the admin ticked. The
// server told us at login (and again on every load via /api/auth/me); this is
// display-gating - the server wall answers 403 outside the list regardless.
export function getRole() {
  return localStorage.getItem("arbi_role") || "admin";
}
// Page keys this login may open; "all" for an admin.
export function getPages() {
  const role = getRole();
  if (role === "admin") return "all";
  if (role === "trader") return ["autotrades"];
  try {
    const v = JSON.parse(localStorage.getItem("arbi_pages") || "[]");
    return Array.isArray(v) ? v : [];
  } catch { return []; }
}
export function storeSession(data) {
  if (data.role) localStorage.setItem("arbi_role", data.role);
  if (data.username) localStorage.setItem("arbi_user", data.username);
  if (Array.isArray(data.pages)) localStorage.setItem("arbi_pages", JSON.stringify(data.pages));
}

async function _doRequest(path, opts) {
  const headers = opts.headers || {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  return fetch(path, { ...opts, headers });
}

async function request(path, opts = {}) {
  const method = (opts.method || "GET").toUpperCase();
  // Idempotent reads (GET) get one transparent retry on transient failure.
  // Writes (POST/PUT/DELETE) are NOT retried automatically — caller decides.
  const maxAttempts = method === "GET" ? 2 : 1;
  let lastErr;
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    let res;
    try {
      res = await _doRequest(path, opts);
    } catch (e) {
      lastErr = e;
      if (attempt < maxAttempts - 1) {
        await new Promise((r) => setTimeout(r, 250 + Math.random() * 250));
        continue;
      }
      throw new Error(e?.message || "Network error");
    }
    if (res.status === 401) {
      clearToken();
      window.location.reload();
      throw new Error("unauthorized");
    }
    // Retry only for transient 5xx
    if (res.status >= 500 && res.status < 600 && attempt < maxAttempts - 1) {
      await new Promise((r) => setTimeout(r, 250 + Math.random() * 250));
      continue;
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    return res.status === 204 ? null : res.json();
  }
  throw lastErr || new Error("Request failed");
}

// Fetch a binary file (e.g. PDF) WITH the auth header, returned as a Blob.
// (A plain <a href> can't send the Bearer token, so we fetch then objectURL it.)
async function requestBlob(path) {
  const res = await _doRequest(path, {});
  if (res.status === 401) {
    clearToken();
    window.location.reload();
    throw new Error("unauthorized");
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.blob();
}

export async function login(username, password) {
  const body = new URLSearchParams();
  body.set("username", username);
  body.set("password", password);
  const res = await fetch("/api/auth/login", { method: "POST", body });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Login failed" }));
    throw new Error(err.detail || "Login failed");
  }
  const data = await res.json();
  setToken(data.access_token);
  storeSession(data);
  return data;
}

export const api = {
  livePairs: () => request("/api/pairs/live"),
  // session + user management (admin only on the server)
  me: () => request("/api/auth/me"),
  users: () => request("/api/users"),
  userPages: () => request("/api/users/pages"),
  userSave: (body, id) => request(id ? `/api/users/${id}` : "/api/users", {
    method: id ? "PUT" : "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }),
  userDelete: (id) => request(`/api/users/${id}`, { method: "DELETE" }),
  saveRule: (pair, body) =>
    request(`/api/pairs/${encodeURIComponent(pair)}/rule`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  positions: (pairName) => request(`/api/positions${pairName ? `?pair_name=${encodeURIComponent(pairName)}` : ""}`),
  closePosition: (id) => request(`/api/positions/${id}/close`, { method: "POST" }),
  squareOff: (body) => request(`/api/positions/square-off`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }),
  history: (days = 7, pairName) => request(`/api/history?days=${days}${pairName ? `&pair_name=${encodeURIComponent(pairName)}` : ""}`),
  deleteHistory: (id) => request(`/api/history/${id}`, { method: "DELETE" }),
  health: () => request("/api/health"),
  feedStatus: () => request("/api/feed/status"),
  // Ladder CRUD
  createLadder: (body) => request("/api/ladders", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }),
  updateLadder: (id, body) => request(`/api/ladders/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }),
  deleteLadder: (id) => request(`/api/ladders/${id}`, { method: "DELETE" }),
  // Calculator
  calcQuotes: () => request("/api/calculator/quotes"),
  // Options spread (Nifty / Sensex PE) — side: "below" (ATM+9) | "above" (ATM+15)
  optionsSpread: (side) => request("/api/options/spread" + (side ? `?side=${encodeURIComponent(side)}` : "")),
  // Stored 10:00/15:00 IST board snapshots (weekday compare) — fetched on demand, no polling
  optionsHistory: (p = {}) => {
    const q = new URLSearchParams();
    if (p.weekday) q.set("weekday", p.weekday);
    if (p.slot) q.set("slot", p.slot);
    if (p.side) q.set("side", p.side);
    if (p.weeks) q.set("weeks", p.weeks);
    if (p.date) q.set("date", p.date);
    const s = q.toString();
    return request("/api/options/history" + (s ? `?${s}` : ""));
  },
  // Commodity BIG-vs-MINI option spread (gold | silver | crude | natgas)
  goldOptions: (commodity = "gold") => request("/api/gold-options/spread?commodity=" + encodeURIComponent(commodity)),
  // Base-metal calendar spreads (Metal tab)
  metalsSpread: () => request("/api/metals/spread"),
  // Other-commodity calendar spreads (Crude / NatGas / Electricity)
  otherCommSpread: () => request("/api/othercomm/spread"),
  // Live Buyer/Seller price table (gold & silver active contracts)
  priceTable: () => request("/api/price/table"),
  // Live premium-calc inputs (XAU/USD Deriv + USD/INR TwelveData + MCX gold)
  premiumInputs: () => request("/api/premium-inputs"),
  international: () => request("/api/international"),
  nseMcx: (commodity = "crude", month = 0) =>
    request(`/api/nse-mcx?commodity=${encodeURIComponent(commodity)}&month=${month}`),
  elecHourly: (month = 0, days = 7) =>
    request(`/api/nse-mcx/elec-hourly?month=${month}&days=${days}`),
  nseMcxGraph: ({ commodity = "crude", strike = null, side = "ce", month = 0, days = 30 } = {}) =>
    request(`/api/nse-mcx/graph?commodity=${encodeURIComponent(commodity)}` +
            `&side=${side}&month=${month}&days=${days}` +
            (strike == null ? "" : `&strike=${strike}`)),
  nseMcxHistory: ({ commodity = "crude", slot = "all", days = 7, month = 0 } = {}) =>
    request(`/api/nse-mcx/history?commodity=${encodeURIComponent(commodity)}` +
            `&slot=${encodeURIComponent(slot)}&days=${days}&month=${month}`),
  // currency "inr" restates the US chain in rupees at the USD/INR future. The IV
  // is identical either way - scaling forward, strike and price by one number
  // cannot change it - so this buys comparable premiums, not a different vol.
  crudeIv: (commodity = "crude", currency = "usd", month = 0) =>
    request(`/api/crude-iv?commodity=${encodeURIComponent(commodity)}`
            + `&currency=${currency}&month=${month}`),
  // Half-hourly stored boards. Static once written - fetch on a control change,
  // never poll.
  crudeIvHistory: ({ commodity = "crude", month = 0, slot = "all", days = 3, date } = {}) => {
    const q = new URLSearchParams({ commodity, month, slot, days });
    if (date) q.set("date", date);
    return request(`/api/crude-iv/history?${q.toString()}`);
  },
  // Option calculator, both directions: pass `market` to solve for IV, `vol` to
  // price forwards. Underlying must be the future of the option's OWN month.
  ivCalculator: (p = {}) => {
    const q = new URLSearchParams();
    ["underlying", "strike", "days", "rate", "dividend", "vol", "market", "side"]
      .forEach((k) => { if (p[k] != null && p[k] !== "") q.set(k, p[k]); });
    return request(`/api/iv-calculator?${q.toString()}`);
  },
  // Fire-once mean-reversion signals + accuracy track record
  signals: () => request("/api/signals"),
  signalsHistory: (limit = 100) => request(`/api/signals/history?limit=${limit}`),
  signalsAccuracy: () => request("/api/signals/accuracy"),
  // Account config
  getAccount: () => request("/api/config/account"),
  updateAccount: (body) => request("/api/config/account", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }),
  // Multi-year close history from MCX bhavcopy (calendar + cross, month/continuous)
  bhavOptions: () => request("/api/pairs/bhav/options"),
  bhavSeries: (params) => {
    const q = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== "") q.set(k, v); });
    return request(`/api/pairs/bhav/series?${q.toString()}`);
  },
  // Pairs the history dialog can show - live plus remembered expired ones
  historyPairs: () => request("/api/pairs/history-pairs"),
  // Daily spread history for one calendar/cross pair (History button)
  spreadHistory: (pair, days = 120) =>
    request(`/api/pairs/spread-history?pair=${encodeURIComponent(pair)}&days=${days}`),
  // MCXCCL bullion warehouse stock + stock-vs-spread correlation
  bullionStock: () => request("/api/bullion-stock"),
  bullionStockStatus: () => request("/api/bullion-stock/status"),
  bullionPdf: (download = false) => requestBlob(`/api/bullion-stock/pdf${download ? "?download=1" : ""}`),
  bullionRefresh: () => request("/api/bullion-stock/refresh", { method: "POST" }),
  // Auto Trades (webhook paper trades). Positions poll; trades/signals are
  // fetched on a control change - they only grow when a webhook lands.
  paperPositions: () => request("/api/paper/positions"),
  paperTrades: ({ symbol, side, timeframe, account_id, page = 1, page_size = 20 } = {}) => {
    const q = new URLSearchParams({ page, page_size });
    if (symbol) q.set("symbol", symbol);
    if (side) q.set("side", side);
    if (timeframe) q.set("timeframe", timeframe);
    if (account_id) q.set("account_id", account_id);
    return request(`/api/paper/trades?${q.toString()}`);
  },
  paperSignals: ({ symbol, side, timeframe, account, page = 1, page_size = 20 } = {}) => {
    const q = new URLSearchParams({ page, page_size });
    if (symbol) q.set("symbol", symbol);
    if (side) q.set("side", side);
    if (timeframe) q.set("timeframe", timeframe);
    if (account) q.set("account", account);
    return request(`/api/paper/signals?${q.toString()}`);
  },
  // Accounts the webhook fans out to, and the master symbol list they pick
  // from. Angel fields come back masked; sending them empty on update keeps
  // whatever is stored.
  paperAccounts: () => request("/api/paper/accounts"),
  paperAccountSave: (body, id) => request(id ? `/api/paper/accounts/${id}` : "/api/paper/accounts", {
    method: id ? "PUT" : "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }),
  paperAccountDelete: (id) => request(`/api/paper/accounts/${id}`, { method: "DELETE" }),
  paperSymbolAdd: (symbol, old) => request("/api/paper/symbols", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(old ? { symbol, old } : { symbol }),
  }),
  paperSymbolDelete: (symbol) => request(`/api/paper/symbols/${encodeURIComponent(symbol)}`, { method: "DELETE" }),
  // The Manual Signal button - the webhook's exact path, fired from the page
  // when TradingView drops a delivery. The page confirms before calling.
  paperManualSignal: (body) => request("/api/paper/manual-signal", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }),
  // Manually close ONE open paper trade at the current price. The page
  // double-confirms before calling.
  paperCloseTrade: (id) => request(`/api/paper/close/${id}`, { method: "POST" }),
  // Start/Stop the whole paper system. Stop books every open trade first.
  paperSetState: (enabled) => request("/api/paper/state", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  }),
  // Activity log
  activity: (params = {}) => {
    const q = new URLSearchParams();
    if (params.days) q.set("days", params.days);
    if (params.limit) q.set("limit", params.limit);
    if (params.offset) q.set("offset", params.offset);
    if (params.pair_name) q.set("pair_name", params.pair_name);
    if (params.action) q.set("action", params.action);
    const qs = q.toString();
    return request(`/api/activity${qs ? `?${qs}` : ""}`);
  },
};
