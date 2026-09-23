import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";

const ConfirmCtx = createContext(null);

export function ConfirmProvider({ children }) {
  const [opt, setOpt] = useState(null);
  const resolverRef = useRef(null);
  const dialogRef = useRef(null);

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

  useEffect(() => {
    if (!opt) return;
    const previous = document.activeElement;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const buttons = Array.from(dialogRef.current?.querySelectorAll("button") || []);
    buttons[0]?.focus();
    function onKey(event) {
      if (event.key === "Escape") { event.preventDefault(); close(false); }
      if (event.key !== "Tab") return;
      const first = buttons[0], last = buttons[buttons.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
      if (previous?.isConnected) previous.focus();
    };
  }, [opt]);

  return (
    <ConfirmCtx.Provider value={confirm}>
      {children}
      {opt && (
        <div className="confirm-overlay" onClick={() => close(false)}>
          <div className={`confirm-card ${opt.danger ? "danger" : ""}`} ref={dialogRef} role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" aria-describedby="confirm-message" onClick={(e) => e.stopPropagation()}>
            <h3 id="confirm-title">{opt.title}</h3>
            <p id="confirm-message">{opt.message}</p>
            <div className="confirm-actions">
              <button type="button" className="btn btn-secondary" onClick={() => close(false)}>{opt.cancelText}</button>
              <button type="button" className={`btn ${opt.danger ? "btn-danger-solid" : "btn-primary"}`} onClick={() => close(true)}>
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
