import React, { createContext, useCallback, useContext, useState, useRef } from "react";

const ToastCtx = createContext(null);

export function ToastProvider({ children }) {
  const [items, setItems] = useState([]);
  const idRef = useRef(0);

  const push = useCallback((kind, msg, ttl = 3000) => {
    const id = ++idRef.current;
    setItems((it) => [...it, { id, kind, msg }]);
    setTimeout(() => setItems((it) => it.filter((x) => x.id !== id)), ttl);
  }, []);

  const api = {
    success: (m) => push("success", m),
    error: (m) => push("error", m, 5000),
    info: (m) => push("info", m),
  };

  return (
    <ToastCtx.Provider value={api}>
      {children}
      <div className="toast-stack">
        {items.map((t) => (
          <div key={t.id} className={`toast toast-${t.kind}`}>
            {t.msg}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export function useToast() {
  return useContext(ToastCtx);
}
