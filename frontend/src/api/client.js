const TOKEN_KEY = "arbi_token";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}
export function setToken(t) {
  localStorage.setItem(TOKEN_KEY, t);
}
export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
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
  return data;
}

export const api = {
  livePairs: () => request("/api/pairs/live"),
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
  // Base-metal calendar spreads (Metal tab)
  metalsSpread: () => request("/api/metals/spread"),
  // Other-commodity calendar spreads (Crude / NatGas / Electricity)
  otherCommSpread: () => request("/api/othercomm/spread"),
  // Live Buyer/Seller price table (gold & silver active contracts)
  priceTable: () => request("/api/price/table"),
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
