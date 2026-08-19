import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import BrandMark from "./BrandMark.jsx";

const NAV_ITEMS = [
  { key: "cross", label: "Cross Pairs" },
  { key: "calendar", label: "Calendar" },
  { key: "metals", label: "Metal" },
  { key: "price", label: "Price" },
  { key: "othercomm", label: "Other Commodity" },
  { key: "calculator", label: "ETF vs MCX" },
  { key: "making", label: "Making Price" },
  { key: "premium", label: "Premium" },
  { key: "options", label: "Nifty / Sensex" },
  { key: "goldopt", label: "Commodity Options" },
  { key: "stock", label: "Bullion Stock" },
  { key: "signals", label: "⚡ Signals" },
  { key: "crude", label: "Crude / Gas" },
  { key: "crudeinr", label: "Crude / Gas INR" },
  { key: "nsemcx", label: "NSE vs MCX" },
  { key: "ivcalc", label: "IV Calculator" },
  { key: "intl", label: "International" },
];

// Clean monochrome line icons (match the app's drawer look).
function NavIcon({ name }) {
  const c = { width: 19, height: 19, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
    strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round" };
  switch (name) {
    case "signals": return <svg width="19" height="19" viewBox="0 0 24 24" fill="currentColor"><path d="M13 2 3 14h7l-1 8 10-12h-7z" /></svg>;
    case "cross": return <svg {...c}><path d="M16 3l4 4-4 4M20 7H8M8 21l-4-4 4-4M4 17h12" /></svg>;
    case "calendar": return <svg {...c}><rect x="3" y="4" width="18" height="18" rx="2" /><path d="M16 2v4M8 2v4M3 10h18" /></svg>;
    case "metals": return <svg {...c}><path d="M12 2l9 5-9 5-9-5 9-5z" /><path d="M3 12l9 5 9-5M3 17l9 5 9-5" /></svg>;
    case "price": return <svg {...c}><rect x="2" y="6" width="20" height="12" rx="2" /><circle cx="12" cy="12" r="2.5" /></svg>;
    case "othercomm": return <svg width="19" height="19" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2.7l5.7 5.6a8 8 0 1 1-11.4 0z" /></svg>;
    case "calculator": return <svg {...c}><rect x="4" y="2" width="16" height="20" rx="2" /><path d="M8 6h8M8 11h.01M12 11h.01M16 11h.01M8 15h.01M12 15h.01M16 15h.01M8 19h8" /></svg>;
    case "options": return <svg {...c}><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></svg>;
    case "stock": return <svg {...c}><path d="M3 21h18" /><rect x="5" y="11" width="4" height="7" /><rect x="15" y="11" width="4" height="7" /><path d="M7 11V7l5-4 5 4v4" /></svg>;
    case "goldopt": return <svg {...c}><circle cx="12" cy="12" r="9" /><path d="M8 12h8M12 8v8" /></svg>;
    case "making": return <svg {...c}><path d="M20.6 13.4 12 22l-9-9V4h9z" /><circle cx="7.5" cy="7.5" r="1.5" /></svg>;
    case "premium": return <svg {...c}><path d="M3 17l6-6 4 4 8-8" /><path d="M17 7h4v4" /></svg>;
    default: return null;
  }
}

export default function Header({
  user,
  onLogout,
  theme,
  onToggleTheme,
  density,
  onToggleDensity,
  feedStatus,
  wsState,
  page,
  onNavigate,
  counts = {},
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [userMenu, setUserMenu] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const userMenuRef = useRef(null);
  const tabsRef = useRef(null);
  const moreRef = useRef(null);
  const widthsRef = useRef(null);
  const [visibleCount, setVisibleCount] = useState(NAV_ITEMS.length);

  // Fourteen tabs do not fit on one row even at 1920px. Rather than scrolling
  // (which clipped labels mid-word) or wrapping (which made the header two rows
  // tall), measure what actually fits and put the rest behind "More".
  useLayoutEffect(() => {
    const nav = tabsRef.current;
    if (!nav) return;

    function measure() {
      if (!widthsRef.current) {
        const btns = [...nav.querySelectorAll(".nav-tab[data-key]")];
        if (btns.length !== NAV_ITEMS.length) return;      // still hidden, retry next resize
        widthsRef.current = btns.map((b) => b.getBoundingClientRect().width);
      }
      const widths = widthsRef.current;
      const gap = parseFloat(getComputedStyle(nav).columnGap || "4") || 4;
      // Measure the ROW's free space rather than the nav box: the strip hugs its
      // tabs now (so More sits right beside them instead of drifting to the far
      // right), which means the nav's own width is content, not budget.
      const row = nav.parentElement;
      const rowGap = parseFloat(getComputedStyle(row).columnGap || "0") || 0;
      const kids = [...row.children];
      let taken = rowGap * Math.max(0, kids.length - 1);
      for (const k of kids) {
        if (k !== nav) taken += k.getBoundingClientRect().width;
      }
      // reserve room for More whenever it is not already in the row
      const hasMore = kids.some((k) => k.classList.contains("nav-more"));
      const avail = row.clientWidth - taken - (hasMore ? 0 : 86) - 2;

      let used = 0, n = 0;
      for (let i = 0; i < widths.length; i++) {
        const next = used + widths[i] + (i ? gap : 0);
        if (next > avail) break;
        used = next; n++;
      }
      setVisibleCount(Math.max(1, n));
    }

    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(nav);
    if (nav.parentElement) ro.observe(nav.parentElement);
    window.addEventListener("resize", measure);
    // Web fonts land after first paint and change every label's width.
    document.fonts?.ready?.then(() => { widthsRef.current = null; measure(); });
    return () => { ro.disconnect(); window.removeEventListener("resize", measure); };
  }, []);

  // Close the overflow menu on outside-click / Escape.
  useEffect(() => {
    if (!moreOpen) return;
    function onDoc(e) { if (moreRef.current && !moreRef.current.contains(e.target)) setMoreOpen(false); }
    function onKey(e) { if (e.key === "Escape") setMoreOpen(false); }
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDoc); document.removeEventListener("keydown", onKey); };
  }, [moreOpen]);

  // Close drawer on Escape; lock page scroll while open.
  useEffect(() => {
    if (!menuOpen) return;
    function onKey(e) { if (e.key === "Escape") setMenuOpen(false); }
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => { document.removeEventListener("keydown", onKey); document.body.style.overflow = ""; };
  }, [menuOpen]);

  // User dropdown: close on outside-click / Escape.
  useEffect(() => {
    if (!userMenu) return;
    function onDoc(e) { if (userMenuRef.current && !userMenuRef.current.contains(e.target)) setUserMenu(false); }
    function onKey(e) { if (e.key === "Escape") setUserMenu(false); }
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDoc); document.removeEventListener("keydown", onKey); };
  }, [userMenu]);

  // Combined health: worst of (browser↔server WS) and (server↔Dhan feed)
  const dhanMode = feedStatus?.mode;
  const tickAge = feedStatus?.last_tick_age_seconds;
  const tokenSecs = feedStatus?.token_expires_in_seconds;
  const marketOpen = feedStatus?.market_open;

  let label = "LIVE";
  let cls = "health-live";
  let extra = "";

  if (wsState !== "live") {
    label = wsState === "connecting" ? "CONNECTING" : "POLLING";
    cls = wsState === "connecting" ? "health-warn" : "health-poll";
  } else if (!feedStatus) {
    label = "LOADING";
    cls = "health-warn";
  } else if (dhanMode === "simulated") {
    label = "DEMO";
    cls = "health-poll";
  } else if (dhanMode !== "live") {
    label = "FEED DOWN";
    cls = "health-down";
  } else if (!marketOpen) {
    label = "MARKET CLOSED";
    cls = "health-poll";
    extra = "";
  } else if (tickAge !== null && tickAge > 30) {
    label = "STALE";
    cls = "health-warn";
    extra = `${tickAge}s`;
  } else {
    const h = Math.floor((tokenSecs || 0) / 3600);
    const m = Math.floor(((tokenSecs || 0) % 3600) / 60);
    extra = h > 0 ? `${h}h ${m}m` : `${m}m`;
  }

  const tooltip = feedStatus
    ? [
        `Browser ↔ Server: ${wsState}`,
        `Server ↔ Dhan: ${dhanMode || "—"}`,
        `Market: ${marketOpen ? "OPEN" : "CLOSED"}`,
        `Client: ${feedStatus.client_name || "—"}`,
        `Token expires in: ${tokenSecs ? Math.floor(tokenSecs/3600)+"h "+Math.floor((tokenSecs%3600)/60)+"m" : "—"}`,
        `Last tick: ${tickAge === null ? "never" : tickAge + "s ago"}`,
      ].join("\n")
    : "Connecting...";

  const go = (key) => { onNavigate(key); setMenuOpen(false); };

  // Whatever fits stays on the bar; the rest goes behind More. The current page
  // is always pulled onto the bar so you can see where you are.
  let shownItems = NAV_ITEMS.slice(0, visibleCount);
  let overflowItems = NAV_ITEMS.slice(visibleCount);
  if (overflowItems.length && !shownItems.some((i) => i.key === page)) {
    const cur = overflowItems.find((i) => i.key === page);
    if (cur && shownItems.length) {
      const dropped = shownItems[shownItems.length - 1];
      shownItems = [...shownItems.slice(0, -1), cur];
      overflowItems = [dropped, ...overflowItems.filter((i) => i.key !== cur.key)];
    }
  }

  return (
    <div className="header">
      <div className="header-left">
        <button className="nav-hamburger" onClick={() => setMenuOpen(true)} aria-label="Menu">☰</button>
        <div className="brand">
          <BrandMark className="brand-logo" size={28} />
          <span className="brand-name">Gurukrupa</span>
          <span className="brand-sub">Bullion</span>
        </div>
        <nav className="nav-tabs" ref={tabsRef}>
          {shownItems.map((it) => (
            <button
              key={it.key}
              data-key={it.key}
              className={`nav-tab ${page === it.key ? "active" : ""}${it.key === "signals" ? " nav-tab-signals" : ""}`}
              onClick={() => onNavigate(it.key)}
            >
              {it.label}
              {counts[it.key] != null && <span className="nav-count">{counts[it.key]}</span>}
            </button>
          ))}
        </nav>
        {overflowItems.length > 0 && (
          <div className="nav-more" ref={moreRef}>
            <button type="button"
              className={`nav-tab nav-more-btn ${overflowItems.some((i) => i.key === page) ? "active" : ""}`}
              onClick={() => setMoreOpen((v) => !v)}
              aria-haspopup="menu" aria-expanded={moreOpen}>
              More <span className="nav-more-n">{overflowItems.length}</span>
              <span className="nav-more-caret">▾</span>
            </button>
            {moreOpen && (
              <div className="nav-more-menu" role="menu">
                {overflowItems.map((it) => (
                  <button key={it.key} type="button" role="menuitem"
                    className={`nav-more-item ${page === it.key ? "active" : ""}`}
                    onClick={() => { onNavigate(it.key); setMoreOpen(false); }}>
                    <span>{it.label}</span>
                    {counts[it.key] != null && <span className="nav-more-count">{counts[it.key]}</span>}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
      <div className="header-right">
        <span className={`health-pill ${cls}`} title={tooltip}>
          <span className="health-dot" />
          <span className="health-label">{label}</span>
          {extra && <span className="health-meta">{extra}</span>}
        </span>
        <div className="user-menu hide-mobile" ref={userMenuRef}>
          <button
            className="user-trigger user-gear"
            onClick={() => setUserMenu((v) => !v)}
            aria-haspopup="menu"
            aria-expanded={userMenu}
            title="Settings"
          >
            <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h.01a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51h.01a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v.01a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
            </svg>
          </button>
          {userMenu && (
            <div className="user-panel" role="menu">
              <div className="user-panel-head">
                <span className="user-avatar lg">{(user || "U").charAt(0).toUpperCase()}</span>
                <div className="user-panel-id">
                  <div className="user-panel-name">{user || "User"}</div>
                  <div className="user-panel-sub">Signed in</div>
                </div>
              </div>
              <button className="user-item" role="menuitem" onClick={onToggleTheme}>
                <span className="user-item-ic">{theme === "dark" ? "☀" : "☾"}</span>
                <span className="user-item-lbl">{theme === "dark" ? "Light mode" : "Dark mode"}</span>
              </button>
              <button className="user-item danger" role="menuitem" onClick={() => { setUserMenu(false); onLogout(); }}>
                <span className="user-item-ic">⎋</span>
                <span className="user-item-lbl">Logout</span>
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Mobile slide-in navigation drawer */}
      {menuOpen && (
        <>
          <div className="nav-drawer-overlay" onClick={() => setMenuOpen(false)} />
          <nav className="nav-drawer">
            <div className="nav-drawer-head">
              <div className="nav-drawer-brand">
                <BrandMark size={32} />
                <div>
                  <div className="ndb-title">Gurukrupa <span className="ndb-b">Bullion</span></div>
                  <div className="ndb-sub">Spread Monitor</div>
                </div>
              </div>
              <button className="nav-drawer-x" onClick={() => setMenuOpen(false)} aria-label="Close">×</button>
            </div>
            <div className="nav-drawer-list">
              {NAV_ITEMS.map((it) => (
                <button
                  key={it.key}
                  className={`nav-drawer-item ${page === it.key ? "active" : ""}`}
                  onClick={() => go(it.key)}
                >
                  <span className="nav-drawer-ic"><NavIcon name={it.key} /></span>
                  <span className="nav-drawer-lbl">{it.label.replace(/^⚡\s*/, "")}</span>
                  {counts[it.key] != null && <span className="nav-drawer-count">{counts[it.key]}</span>}
                </button>
              ))}
            </div>
            <div className="nav-drawer-foot">
              <span className="username-chip">{user || "User"}</span>
              <button className="theme-toggle" onClick={onToggleTheme} title="Toggle theme">
                {theme === "dark" ? "☀" : "☾"}
              </button>
              <button className="btn btn-secondary" onClick={() => { setMenuOpen(false); onLogout(); }}>Logout</button>
            </div>
          </nav>
        </>
      )}
    </div>
  );
}
