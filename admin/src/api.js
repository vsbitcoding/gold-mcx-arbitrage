// Same-origin API (nginx proxies /api → uvicorn). Reuses the arbi JWT auth.
const TOKEN_KEY = "gk_admin_token";

export const getToken = () => { try { return localStorage.getItem(TOKEN_KEY); } catch { return null; } };
export const setToken = (t) => { try { localStorage.setItem(TOKEN_KEY, t); } catch {} };
export const clearToken = () => { try { localStorage.removeItem(TOKEN_KEY); } catch {} };

async function req(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (opts.json !== undefined) {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(opts.json);
    delete opts.json;
  }
  const res = await fetch(path, { ...opts, headers });
  if (res.status === 401) { clearToken(); throw new Error("Session expired — log in again."); }
  if (!res.ok) throw new Error((await res.text().catch(() => "")) || `HTTP ${res.status}`);
  return res.status === 204 ? null : res.json();
}

export async function login(username, password) {
  const body = new URLSearchParams({ username, password });
  const res = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  if (!res.ok) throw new Error("Wrong username or password");
  const data = await res.json();
  setToken(data.access_token);
  return data;
}

export const api = {
  listScrips: (template = "gurukrupa") => req(`/api/scrips?template=${encodeURIComponent(template)}`),
  createScrip: (s) => req("/api/scrips", { method: "POST", json: s }),
  updateScrip: (id, s) => req(`/api/scrips/${id}`, { method: "PUT", json: s }),
  deleteScrip: (id) => req(`/api/scrips/${id}`, { method: "DELETE" }),
  reorder: (order) => req("/api/scrips/reorder", { method: "POST", json: { order } }),
  seed: () => req("/api/scrips/seed", { method: "POST" }),
};
