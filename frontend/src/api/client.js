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
  return localStorage.getItem("arbi_role") || "user";
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

const READ_TIMEOUT_MS = 10000;
let signingOut = false;

function expireSession(token) {
  // A delayed response from a previous login must not sign out a new session.
  if (getToken() !== token || signingOut) return;
  signingOut = true;
  clearToken();
  window.location.reload();
}

function retryDelay(signal) {
  return new Promise((resolve, reject) => {
    if (signal.aborted) { reject(signal.reason); return; }
    const abort = () => { clearTimeout(timer); reject(signal.reason); };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", abort);
      resolve();
    }, 300 + Math.random() * 200);
    signal.addEventListener("abort", abort, { once: true });
  });
}

async function request(path, opts = {}) {
  const { signal, timeoutMs = READ_TIMEOUT_MS, responseType, ...fetchOpts } = opts;
  const method = (fetchOpts.method || "GET").toUpperCase();
  const token = getToken();
  const headers = new Headers(fetchOpts.headers || {});
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const controller = new AbortController();
  const cancel = () => controller.abort(signal.reason);
  if (signal?.aborted) cancel();
  else signal?.addEventListener("abort", cancel, { once: true });
  let timedOut = false;
  // One deadline covers the request body and any retry, not a new deadline per attempt.
  const deadline = setTimeout(() => { timedOut = true; controller.abort(); }, timeoutMs);
  const maxAttempts = method === "GET" ? 2 : 1;
  try {
    for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
      let res;
      try {
        res = await fetch(path, { ...fetchOpts, headers, signal: controller.signal });
      } catch (error) {
        if (controller.signal.aborted || attempt === maxAttempts - 1) throw error;
        await retryDelay(controller.signal);
        continue;
      }
      if (res.status === 401) {
        expireSession(token);
        throw new Error("Your session has expired. Please sign in again.");
      }
      if (res.status >= 500 && attempt < maxAttempts - 1) {
        await res.body?.cancel();
        await retryDelay(controller.signal);
        continue;
      }
      if (!res.ok) {
        const error = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
        const detail = Array.isArray(error.detail)
          ? error.detail.map((item) => `${(item.loc || []).slice(1).join(".")}: ${item.msg || "Invalid value"}`).join("; ")
          : error.detail;
        const failure = new Error(detail || `HTTP ${res.status}`);
        failure.status = res.status;
        throw failure;
      }
      if (res.status === 204) return null;
      return await (responseType === "blob" ? res.blob() : res.json());
    }
  } catch (error) {
    if (timedOut) throw new Error(method === "GET"
      ? "The update timed out. Displayed values may be stale."
      : "The request timed out. Refresh before retrying; the action may have completed.");
    throw error;
  } finally {
    clearTimeout(deadline);
    signal?.removeEventListener("abort", cancel);
  }
}

// PDFs may take longer to generate; they use the same authentication and retry rules.
async function requestBlob(path) {
  return request(path, { responseType: "blob", timeoutMs: 60000 });
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
  livePairs: (signal) => request("/api/pairs/live", { signal }),
  // session + user management (admin only on the server)
  me: (signal) => request("/api/auth/me", { signal }),
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
  feedStatus: (signal) => request("/api/feed/status", { signal }),
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
  calcQuotes: (signal) => request("/api/calculator/quotes", { signal }),
  // Options spread (Nifty / Sensex PE) — side: "below" (ATM+9) | "above" (ATM+15)
  optionsSpread: (side, signal) => request("/api/options/spread" + (side ? `?side=${encodeURIComponent(side)}` : ""), { signal }),
  bankOptionsLive: (params = {}, signal) => {
    const q = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") q.set(key, value);
    });
    return request(`/api/bank-options/live?${q.toString()}`, { signal });
  },
  bankOptionsPositions: (signal) => request("/api/bank-options/positions", { signal }),
  bankOptionsOpen: (body) => request("/api/bank-options/positions", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  }),
  bankOptionsClose: (id) => request(`/api/bank-options/positions/${encodeURIComponent(id)}/close`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}),
  }),
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
  metalsSpread: (signal) => request("/api/metals/spread", { signal }),
  // Other-commodity calendar spreads (Crude / NatGas / Electricity)
  otherCommSpread: (signal) => request("/api/othercomm/spread", { signal }),
  // Live Buyer/Seller price table (gold & silver active contracts)
  priceTable: (signal) => request("/api/price/table", { signal }),
  // Live premium-calc inputs (XAU/USD Deriv + USD/INR TwelveData + MCX gold)
  premiumInputs: () => request("/api/premium-inputs"),
  international: () => request("/api/international"),
  nseMcx: (commodity = "crude", month = 0, signal) =>
    request(`/api/nse-mcx?commodity=${encodeURIComponent(commodity)}&month=${month}`, { signal }),
  elecHourly: (month = 0, days = 7) =>
    request(`/api/nse-mcx/elec-hourly?month=${month}&days=${days}`),
  nseMcxGraph: ({ commodity = "crude", strike = null, side = "ce", month = 0, days = 30 } = {}) =>
    request(`/api/nse-mcx/graph?commodity=${encodeURIComponent(commodity)}` +
            `&side=${side}&month=${month}&days=${days}` +
            (strike == null ? "" : `&strike=${strike}`)),
  nseMcxBacktest: (params, signal) => request("/api/nse-mcx/backtest", { signal, timeoutMs: 120000, method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(params || {}) }),
  marketHolidays: (year) => request(`/api/market-calendar${year ? `?year=${year}` : ""}`),
  marketHolidaySave: (body) => request("/api/market-calendar", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  marketHolidayDelete: (id) => request(`/api/market-calendar/${id}`, { method: "DELETE" }),
  marketHolidayRefresh: (year) => request(`/api/market-calendar/refresh${year ? `?year=${year}` : ""}`, { method: "POST" }),
  nseMcxPaper: (commodity = "crude") => request(`/api/nse-mcx/paper?commodity=${commodity}`),
  nseMcxPaperSettings: (commodity, params) => request(`/api/nse-mcx/paper/settings?commodity=${commodity}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(params || {}) }),
  nseMcxPaperEnable: (commodity, enabled) => request(`/api/nse-mcx/paper/enable?commodity=${commodity}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled }) }),
  nseMcxPaperClose: (commodity, id) => request(`/api/nse-mcx/paper/close/${id}?commodity=${commodity}`, { method: "POST" }),
  nseMcxPaperCloseAll: (commodity) => request(`/api/nse-mcx/paper/close-all?commodity=${commodity}`, { method: "POST" }),
  nseMcxPaperClear: (commodity) => request(`/api/nse-mcx/paper/clear?commodity=${commodity}`, { method: "POST" }),
  nseMcxDailyExpiries: (commodity = "crude", signal) => request(`/api/nse-mcx/daily/expiries?commodity=${commodity}`, { signal }),
  nseMcxDaily: ({ commodity = "crude", expiry, mcxExpiry = null, start = null, end = null, type = null, strike = null } = {}) => {
    const q = new URLSearchParams({ commodity, expiry });
    if (mcxExpiry) q.set("mcx_expiry", mcxExpiry);
    if (start) q.set("start", start);
    if (end) q.set("end", end);
    if (type) q.set("type", type);
    if (strike != null && strike !== "") q.set("strike", strike);
    return request(`/api/nse-mcx/daily?${q.toString()}`);
  },
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
  ivCalculator: (p = {}, signal) => {
    const q = new URLSearchParams();
    ["underlying", "strike", "days", "rate", "dividend", "vol", "market", "side"]
      .forEach((k) => { if (p[k] != null && p[k] !== "") q.set(k, p[k]); });
    return request(`/api/iv-calculator?${q.toString()}`, { signal });
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
  // Daily spread history for one calendar/cross pair (History button)
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
