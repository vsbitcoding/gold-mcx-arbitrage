import { getToken } from "./client.js";

/** Live spread WebSocket. Subscribers receive snapshot arrays as they arrive.
 * Auto-reconnects. Falls back to polling if disconnected for >10s. */
export function createLiveSocket({ onSnapshot, onState }) {
  let ws = null;
  let reconnectTimer = null;
  let pingTimer = null;
  let closed = false;
  let attempt = 0;

  function setState(s) { onState?.(s); }

  function url() {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    const token = encodeURIComponent(getToken() || "");
    return `${proto}//${host}/ws/live?token=${token}`;
  }

  function connect() {
    if (closed) return;
    setState("connecting");
    try {
      ws = new WebSocket(url());
    } catch (e) {
      schedule();
      return;
    }

    ws.onopen = () => {
      attempt = 0;
      setState("live");
      // Heartbeat every 25s
      pingTimer = setInterval(() => {
        try { ws?.readyState === 1 && ws.send("ping"); } catch {}
      }, 25000);
    };

    ws.onmessage = (e) => {
      if (e.data === "pong") return;
      try {
        const msg = JSON.parse(e.data);
        if (msg.type === "snapshot" && Array.isArray(msg.data)) {
          onSnapshot?.(msg.data);
        }
      } catch {}
    };

    ws.onclose = () => {
      clearInterval(pingTimer);
      if (closed) return;
      setState("reconnecting");
      schedule();
    };

    ws.onerror = () => {
      try { ws.close(); } catch {}
    };
  }

  function schedule() {
    clearTimeout(reconnectTimer);
    const wait = Math.min(1000 * Math.pow(1.5, attempt++), 15000);
    reconnectTimer = setTimeout(connect, wait);
  }

  function close() {
    closed = true;
    clearTimeout(reconnectTimer);
    clearInterval(pingTimer);
    try { ws?.close(); } catch {}
  }

  connect();
  return { close };
}
