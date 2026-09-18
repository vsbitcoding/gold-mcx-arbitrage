import { useEffect, useRef, useState } from "react";

// Schedule the next read after the previous one settles. A key identifies the
// data being requested, so neither old filters nor hidden tabs accept results.
export function usePolling(read, { key, interval = 2000, enabled = true, onData } = {}) {
  const readRef = useRef(read);
  const onDataRef = useRef(onData);
  readRef.current = read;
  onDataRef.current = onData;
  const [state, setState] = useState({ key: null, data: null, error: null, pending: true, paused: false });

  useEffect(() => {
    if (!enabled) return undefined;
    let active = true, timer = null, controller = null, generation = 0;
    const current = (id) => active && !document.hidden && id === generation;
    function cancel() {
      clearTimeout(timer);
      timer = null;
      generation += 1;
      controller?.abort();
      controller = null;
    }
    async function load() {
      if (!active || document.hidden || controller) return;
      const request = new AbortController();
      controller = request;
      const id = ++generation;
      try {
        const data = await readRef.current(request.signal);
        if (!current(id)) return;
        setState({ key, data, error: null, pending: false, paused: false });
        onDataRef.current?.(data);
      } catch (error) {
        if (current(id)) setState((old) => ({
          key, data: old.key === key ? old.data : null,
          error: error.message || "Unable to update data.", pending: false, paused: false,
        }));
      } finally {
        if (controller === request) controller = null;
        if (current(id)) timer = setTimeout(load, interval);
      }
    }
    function onVisibility() {
      cancel();
      setState((old) => ({ ...old, pending: !document.hidden, paused: document.hidden }));
      if (!document.hidden) load();
    }
    setState((old) => ({
      key, data: old.key === key ? old.data : null, error: null,
      pending: true, paused: document.hidden,
    }));
    document.addEventListener("visibilitychange", onVisibility);
    load();
    return () => {
      active = false;
      cancel();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [key, interval, enabled]);

  return state.key === key ? state : { data: null, error: null, pending: true, paused: document.hidden };
}
