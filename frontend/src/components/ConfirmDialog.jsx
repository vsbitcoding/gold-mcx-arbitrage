import React, { createContext, useCallback, useContext, useRef, useState } from "react";

const ConfirmCtx = createContext(null);

export function ConfirmProvider({ children }) {
  const [opt, setOpt] = useState(null);
  const resolverRef = useRef(null);

  const confirm = useCallback((options) => {
    return new Promise((resolve) => {
      resolverRef.current = resolve;
      setOpt({
        title: options.title || "Confirm",
        message: options.message || "Are you sure?",
        confirmText: options.confirmText || "Confirm",
        cancelText: options.cancelText || "Cancel",
        danger: options.danger ?? false,
      });
    });
  }, []);

  function close(value) {
    setOpt(null);
    resolverRef.current?.(value);
    resolverRef.current = null;
  }

  return (
    <ConfirmCtx.Provider value={confirm}>
      {children}
      {opt && (
        <div className="confirm-overlay" onClick={() => close(false)}>
          <div className={`confirm-card ${opt.danger ? "danger" : ""}`} onClick={(e) => e.stopPropagation()}>
            <h3>{opt.title}</h3>
            <p>{opt.message}</p>
            <div className="confirm-actions">
              <button className="btn btn-secondary" onClick={() => close(false)}>{opt.cancelText}</button>
              <button className={`btn ${opt.danger ? "btn-danger-solid" : "btn-primary"}`} onClick={() => close(true)}>
                {opt.confirmText}
              </button>
            </div>
          </div>
        </div>
      )}
    </ConfirmCtx.Provider>
  );
}

export function useConfirm() {
  return useContext(ConfirmCtx);
}
