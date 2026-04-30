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

async function request(path, opts = {}) {
  const headers = opts.headers || {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(path, { ...opts, headers });
  if (res.status === 401) {
    clearToken();
    window.location.reload();
    throw new Error("unauthorized");
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(err.detail || "Request failed");
  }
  return res.status === 204 ? null : res.json();
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
  positions: () => request("/api/positions"),
  closePosition: (id) => request(`/api/positions/${id}/close`, { method: "POST" }),
  history: (days = 30) => request(`/api/history?days=${days}`),
  pauseAll: () => request("/api/control/pause-all", { method: "POST" }),
  health: () => request("/api/health"),
  feedStatus: () => request("/api/feed/status"),
};
