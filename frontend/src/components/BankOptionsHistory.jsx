import React, { useEffect, useMemo, useState } from "react";
import { api } from "../api/client.js";

// History for the BANKEX / BANKNIFTY board (client, 23-Sep-2026): the board
// saved at 10:00 AM and 3:30 PM IST on every trading day, and one board a day
// built from the BSE / NSE bhavcopy closes since January 2024. Each stored
// board renders like the Live view (index cards + the fifteen matched strikes),
// stacked newest first. Fetched on demand only - no polling.
const INDICES = ["BANKEX", "BANKNIFTY"];
const OFFSETS = Array.from({ length: 15 }, (_, index) => (index - 7) * 500);
const SOURCES = [{ key: "snapshot", label: "10:00 / 3:30 boards" }, { key: "daily", label: "Daily close" }];
const SLOTS = [{ key: "both", label: "All" }, { key: "10:00", label: "10:00 AM" }, { key: "15:30", label: "3:30 PM" }];
const WEEKDAYS = [{ key: "", label: "All days" }, { key: "mon", label: "Mon" }, { key: "tue", label: "Tue" }, { key: "wed", label: "Wed" }, { key: "thu", label: "Thu" }, { key: "fri", label: "Fri" }];
const COUNTS = { snapshot: [4, 7, 12, 20, 40], daily: [7, 12, 20, 40, 60, 120] };

function numeric(value) {
  return value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value));
}
function number(value, digits = 2) {
  return numeric(value) ? Number(value).toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits }) : "—";
}
function shortDate(value) {
  if (!value) return "—";
  return new Date(`${value}T00:00:00+05:30`).toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", year: "numeric" });
}
function longDate(value) {
  if (!value) return "—";
  return new Date(`${value}T00:00:00+05:30`).toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", weekday: "long", day: "2-digit", month: "short", year: "numeric" });
}
function slotLabel(slot) {
  return slot === "close" ? "Daily close" : SLOTS.find((s) => s.key === slot)?.label || slot;
}
function tone(value) {
  return numeric(value) && Number(value) !== 0 ? (Number(value) > 0 ? "bo-positive" : "bo-negative") : "";
}
function fromSpot(strike, spot) {
  if (!numeric(strike) || !numeric(spot)) return null;
  const d = Math.round(Number(strike) - Number(spot));
  return `${d > 0 ? "+" : d < 0 ? "−" : ""}${number(Math.abs(d), 0)}`;
}
function stored(key, allowed, fallback) {
  try { const v = localStorage.getItem(key); return allowed.includes(v) ? v : fallback; } catch { return fallback; }
}

function Cells({ row, source, buyIndex, sellIndex }) {
  const buy = row?.[String(buyIndex || "").toLowerCase()];
  const sell = row?.[String(sellIndex || "").toLowerCase()];
  const daily = source === "daily";
  const mark = (leg) => {
    if (!leg) return null;
    if (daily) return leg.listed && !leg.traded && numeric(leg.price) ? <span className="boh-mark" title="Not traded that day: exchange settlement price">s</span> : null;
    return numeric(leg.bid) && numeric(leg.ask) && !leg.fresh && numeric(row?.difference_points) ? <span className="boh-mark" title="Standing quote, older than a minute at capture">•</span> : null;
  };
  const title = (name, leg) => {
    if (!leg) return "";
    if (daily) return `${name} ${number(leg.strike, 0)} ${row.side} · close ${number(leg.close)} · settle ${number(leg.settle)} · OI ${number(leg.oi, 0)} · volume ${number(leg.volume, 0)}`;
    return `${name} ${number(leg.strike, 0)} ${row.side} · Bid ${number(leg.bid)} / Ask ${number(leg.ask)} · LTP ${number(leg.ltp)} · OI ${number(leg.oi, 0)}${numeric(leg.age) ? ` · ${Math.round(leg.age)}s old` : ""}`;
  };
  return (
    <>
      <td className={`bo-quote-cell bo-group-start bo-${(row?.side || "ce").toLowerCase()}-cell`} title={title(buyIndex, buy)}><strong>{number(row?.buy_price)}</strong>{mark(buy)}</td>
      <td className={`bo-quote-cell bo-${(row?.side || "ce").toLowerCase()}-cell`} title={title(sellIndex, sell)}><strong>{number(row?.sell_price)}</strong>{mark(sell)}</td>
      <td className={`bo-value-col ${tone(row?.difference_points)}`}><strong>{number(row?.difference_points)}</strong></td>
    </>
  );
}

function Board({ board, source }) {
  const rows = board.rows || [];
  const grouped = OFFSETS.map((offset) => {
    const ce = rows.find((r) => r.side === "CE" && Number(r.offset_points) === offset);
    const pe = rows.find((r) => r.side === "PE" && Number(r.offset_points) === offset);
    const atm = board.indices?.BANKEX?.atm;
    return { offset, CE: ce, PE: pe,
      bankex: ce?.bankex?.strike ?? pe?.bankex?.strike ?? (numeric(atm) ? Number(atm) + offset : null),
      banknifty: ce?.banknifty?.strike ?? pe?.banknifty?.strike ?? null };
  });
  const priceWord = source === "daily" ? "Close" : null;
  return (
    <section className="boh-board">
      <div className="boh-head">
        <span className="boh-date">{longDate(board.date)}</span>
        <span className="boh-slot" data-slot={board.slot}>{slotLabel(board.slot)}</span>
        {board.captured_at && <span className="boh-captured">captured {String(board.captured_at).slice(11, 16)} IST</span>}
      </div>
      <div className="boh-cards">
        {INDICES.map((name) => {
          const v = board.indices?.[name];
          const isBuy = board.buy_index === name, isSell = board.sell_index === name;
          const action = isBuy ? (priceWord ? "Buy · Close" : "Buy · Ask") : isSell ? (priceWord ? "Sell · Close" : "Sell · Bid") : "—";
          return (
            <div key={name} className="boh-card">
              <h4>{name} <span className={`bo-badge ${isBuy ? "bo-buy" : isSell ? "bo-sell" : ""}`}>{action}</span></h4>
              <strong className="boh-spot" title="Index level">{number(v?.spot)}</strong>
              <span className="boh-expiry" title="Monthly expiry">{shortDate(v?.expiry)}</span>
              <dl><div><dt>ATM</dt><dd>{number(v?.atm, 0)}</dd></div><div><dt>Lot size</dt><dd>{number(v?.lot_size, 0)}</dd></div></dl>
            </div>
          );
        })}
      </div>
      <div className="bo-table-wrap" role="region" aria-label={`Board ${board.date} ${slotLabel(board.slot)}`} tabIndex={0}>
        <table className="bo-table bo-chain-table bo-comparison-table bo-both-sides boh-table">
          <thead>
            <tr className="bo-group-heading">
              <th scope="colgroup" colSpan={3} className="bo-ce-heading"><span className="bo-side-tag">CE</span> Calls</th>
              <th scope="colgroup" colSpan={3} className="bo-strike-heading">Matched strikes <span>Same points from spot</span></th>
              <th scope="colgroup" colSpan={3} className="bo-pe-heading"><span className="bo-side-tag">PE</span> Puts</th>
            </tr>
            <tr className="bo-column-heading">
              <th scope="col">Buy {priceWord || "Ask"}<span className="bo-th-sub">{board.buy_index || "—"}</span></th><th scope="col">Sell {priceWord || "Bid"}<span className="bo-th-sub">{board.sell_index || "—"}</span></th><th scope="col">Difference (pts)</th>
              <th scope="col" className="bo-strike-column bo-group-start">BANKEX<span className="bo-th-sub">strike · pts from spot</span></th><th scope="col" className="bo-strike-column">ATM distance</th><th scope="col" className="bo-strike-column">BANKNIFTY<span className="bo-th-sub">strike · pts from spot</span></th>
              <th scope="col" className="bo-group-start">Buy {priceWord || "Ask"}<span className="bo-th-sub">{board.buy_index || "—"}</span></th><th scope="col">Sell {priceWord || "Bid"}<span className="bo-th-sub">{board.sell_index || "—"}</span></th><th scope="col">Difference (pts)</th>
            </tr>
          </thead>
          <tbody>{grouped.map((group) => (
            <tr key={group.offset} className={group.offset === 0 ? "bo-atm-row" : ""}>
              <Cells row={group.CE} source={source} buyIndex={board.buy_index} sellIndex={board.sell_index} />
              <td className="bo-strike-column bo-group-start"><strong>{number(group.bankex, 0)}</strong><span className="bo-from-spot" title="Points from the BANKEX index level">{fromSpot(group.bankex, board.indices?.BANKEX?.spot)}</span></td>
              <td className="bo-strike-column bo-distance-cell"><strong className={group.offset === 0 ? "bo-atm-badge" : ""}>{group.offset === 0 ? "ATM" : `${group.offset > 0 ? "+" : "−"}${number(Math.abs(group.offset), 0)}`}</strong></td>
              <td className="bo-strike-column"><strong>{number(group.banknifty, 0)}</strong><span className="bo-from-spot" title="Points from the BANKNIFTY index level">{fromSpot(group.banknifty, board.indices?.BANKNIFTY?.spot)}</span></td>
              <Cells row={group.PE} source={source} buyIndex={board.buy_index} sellIndex={board.sell_index} />
            </tr>
          ))}</tbody>
        </table>
      </div>
    </section>
  );
}

export default function BankOptionsHistory() {
  const [source, setSource] = useState(() => stored("arbi_bankhist_src", SOURCES.map((s) => s.key), "snapshot"));
  const [slot, setSlot] = useState(() => stored("arbi_bankhist_slot", SLOTS.map((s) => s.key), "both"));
  const [weekday, setWeekday] = useState(() => stored("arbi_bankhist_wd", WEEKDAYS.map((w) => w.key), ""));
  const [days, setDays] = useState(7);
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState(null);

  useEffect(() => { try { localStorage.setItem("arbi_bankhist_src", source); } catch {} }, [source]);
  useEffect(() => { try { localStorage.setItem("arbi_bankhist_slot", slot); } catch {} }, [slot]);
  useEffect(() => { try { localStorage.setItem("arbi_bankhist_wd", weekday); } catch {} }, [weekday]);

  // Fetch on control change only - history is static once written.
  useEffect(() => {
    let alive = true;
    const controller = new AbortController();
    setLoading(true);
    api.bankOptionsHistory({ source, slot: source === "snapshot" ? slot : undefined, weekday: weekday || undefined, days }, controller.signal)
      .then((r) => { if (alive) { setData(r); setErr(null); } })
      .catch((e) => { if (alive && !controller.signal.aborted) setErr(e.message || "Failed to load history"); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; controller.abort(); };
  }, [source, slot, weekday, days]);

  // The daily store fills in the background after deployment; say how far it has got when a filter comes back empty.
  useEffect(() => {
    if (source !== "daily" || loading || (data?.count || 0) > 0) return undefined;
    let alive = true;
    api.bankOptionsHistoryStatus().then((r) => { if (alive) setStatus(r?.daily || null); }).catch(() => {});
    return () => { alive = false; };
  }, [source, loading, data]);

  const boards = data?.boards || [];
  const counts = COUNTS[source] || COUNTS.snapshot;
  const dayCount = useMemo(() => new Set(boards.map((b) => b.date)).size, [boards]);

  function downloadCsv() {
    const head = ["Date", "Board", "Side", "ATM distance", "BANKEX strike", "BANKNIFTY strike", "Buy index", "Buy price", "Sell index", "Sell price", "Difference (pts)", "Note", "BANKEX spot", "BANKNIFTY spot", "BANKEX expiry", "BANKNIFTY expiry"];
    const lines = [head.join(",")];
    boards.forEach((b) => (b.rows || []).forEach((r) => {
      const note = source === "daily" ? (r.settled ? "settlement price" : "") : (r.stale ? "quote older than a minute" : "");
      lines.push([b.date, slotLabel(b.slot), r.side, r.offset_points, r.bankex?.strike ?? "", r.banknifty?.strike ?? "", b.buy_index || "", r.buy_price ?? "", b.sell_index || "", r.sell_price ?? "", r.difference_points ?? "", note,
        b.indices?.BANKEX?.spot ?? "", b.indices?.BANKNIFTY?.spot ?? "", b.indices?.BANKEX?.expiry ?? "", b.indices?.BANKNIFTY?.expiry ?? ""].join(","));
    }));
    const blob = new Blob([lines.join("\n")], { type: "text/csv" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = `bankex-banknifty-${source}-history.csv`; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }

  return (
    <div className="boh-wrap">
      <div className="boh-controls">
        <div className="oh-group" role="tablist" aria-label="History source">
          {SOURCES.map((s) => <button key={s.key} type="button" role="tab" aria-selected={source === s.key} className={`oh-chip ${source === s.key ? "on" : ""}`} onClick={() => { setSource(s.key); setDays(7); }}>{s.label}</button>)}
        </div>
        {source === "snapshot" && (
          <div className="oh-group" role="tablist" aria-label="Time">
            {SLOTS.map((s) => <button key={s.key} type="button" role="tab" aria-selected={slot === s.key} className={`oh-chip ${slot === s.key ? "on" : ""}`} onClick={() => setSlot(s.key)}>{s.label}</button>)}
          </div>
        )}
        <div className="oh-group" role="tablist" aria-label="Weekday">
          {WEEKDAYS.map((w) => <button key={w.key || "all"} type="button" role="tab" aria-selected={weekday === w.key} className={`oh-chip ${weekday === w.key ? "on" : ""}`} onClick={() => setWeekday(w.key)}>{w.label}</button>)}
        </div>
        <select className="oh-weeks" value={days} onChange={(e) => setDays(Number(e.target.value))} title="How many past days">
          {counts.map((n) => <option key={n} value={n}>Last {n} days</option>)}
        </select>
        <button type="button" className="oh-chip" disabled={!boards.length} onClick={downloadCsv}>CSV</button>
      </div>

      <p className="boh-note">{source === "snapshot"
        ? "Boards are saved automatically at 10:00 AM and 3:30 PM IST on every trading day. Each pair is priced from the last two-way quote of each leg (Sell Bid − Buy Ask); • marks a standing quote older than a minute at capture."
        : "One board per trading day from the BSE and NSE bhavcopy, since January 2024. Legs are priced at the day's close (Sell close − Buy close); s marks a strike that did not trade that day, priced at the exchange settlement price. The current contract is the nearest expiry after that day (the monthly since 2025; the front weekly in 2024) and the matched BANKNIFTY strike follows the Live rule. Strikes nobody traded are not in the exchange files and show as —."}</p>

      {err && <div className="bo-alert bo-error" role="alert">{err}</div>}
      {loading && !data && <div className="bo-empty"><strong>Loading history…</strong></div>}
      {!loading && !err && boards.length === 0 && (
        <div className="bo-empty">
          <strong>No boards for this filter yet.</strong>
          <p>{source === "snapshot"
            ? "Boards are stored at 10:00 AM and 3:30 PM IST on trading days; holidays and weekends have none."
            : status?.running ? `Daily history is still being fetched (${status.msg || "working"}; ${number(status.stored_days, 0)} days stored so far). Check back in a few minutes.`
              : status?.stored_days ? `${number(status.stored_days, 0)} days stored (${shortDate(status.first)} to ${shortDate(status.last)}); none match this filter.`
                : "The daily history has not been fetched yet."}</p>
        </div>
      )}
      {boards.length > 0 && dayCount < days && weekday && <div className="boh-note">{dayCount} of the last {days} {WEEKDAYS.find((w) => w.key === weekday)?.label}s found (holidays have no board).</div>}
      {boards.map((b) => <Board key={`${b.date}-${b.slot}`} board={b} source={source} />)}
    </div>
  );
}
