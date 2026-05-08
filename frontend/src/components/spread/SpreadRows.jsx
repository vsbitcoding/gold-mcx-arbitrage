import React, { memo } from "react";
import SpreadCell from "./SpreadCell.jsx";
import { fmtNum } from "../../utils/format.js";
import { STATUS_CLASS, STATUS_LABEL } from "./constants.js";

function LtpCell({ value, instrument, className = "" }) {
  return (
    <td className={`ltp-cell num ${className}`.trim()}>
      <div className="ltp-instrument">{instrument || "—"}</div>
      <div className="ltp-value">{value === null || value === undefined ? "—" : fmtNum(value, 2)}</div>
    </td>
  );
}

export const FrontRow = memo(function FrontRow({ row, label, hasMore, expanded, onToggle, onManage, onPositions, onHistory }) {
  const decCount = row.decrease_ladders.length;
  const incCount = row.increase_ladders.length;

  function handleRowClick(e) {
    if (e.target.closest("button")) return;
    if (!hasMore) return;
    onToggle();
  }

  return (
    <tr
      className={`pair-row status-${row.status} ${expanded ? "open" : ""}`}
      onClick={handleRowClick}
      style={{ cursor: hasMore ? "pointer" : "default" }}
    >
      <td className="pair-name gc-identity">
        <div className="front-row-name">
          {hasMore && <span className="caret">{expanded ? "▾" : "▸"}</span>}
          <span className="group-label">{label}</span>
        </div>
      </td>
      <td className="gc-identity col-end-group">
        <div className="pair-expiry">{row.expiry_label || "—"}</div>
      </td>
      <LtpCell value={row.big_ltp} instrument={(row.big || "").toUpperCase()} className="gc-ltp" />
      <LtpCell value={row.small_ltp} instrument={(row.small || "").toUpperCase()} className="gc-ltp col-end-group" />
      <SpreadCell value={row.decrease_spread} tone="dec" className="gc-decrease" />
      <SpreadCell value={row.increase_spread} tone="inc" className="gc-increase col-end-group" />
      <td className="gc-status">
        <span className={`badge ${STATUS_CLASS[row.status] || "badge-idle"}`}>
          <span className="blip" />
          {STATUS_LABEL[row.status] || row.status}
        </span>
      </td>
      <td className="gc-status"><span className="ladder-count-pill dec">▼ {decCount}</span></td>
      <td className="gc-status col-end-group"><span className="ladder-count-pill inc">▲ {incCount}</span></td>
      <td className="gc-action">
        <div className="front-actions">
          <button className="btn btn-primary btn-xs" onClick={(e) => { e.stopPropagation(); onManage(row.name); }}>Manage</button>
          <button className="btn btn-secondary btn-xs" onClick={(e) => { e.stopPropagation(); onPositions(row.name); }}>Positions</button>
          <button className="btn btn-secondary btn-xs" onClick={(e) => { e.stopPropagation(); onHistory(row.name); }}>History</button>
        </div>
      </td>
    </tr>
  );
}, (prev, next) => (
  prev.expanded === next.expanded &&
  prev.hasMore === next.hasMore &&
  prev.row.decrease_spread === next.row.decrease_spread &&
  prev.row.increase_spread === next.row.increase_spread &&
  prev.row.big_ltp === next.row.big_ltp &&
  prev.row.small_ltp === next.row.small_ltp &&
  prev.row.status === next.row.status &&
  prev.row.decrease_ladders === next.row.decrease_ladders &&
  prev.row.increase_ladders === next.row.increase_ladders
));

export const OtherMonthRow = memo(function OtherMonthRow({ row, onManage, onPositions, onHistory, isLast }) {
  const decCount = row.decrease_ladders.length;
  const incCount = row.increase_ladders.length;
  return (
    <tr className={`pair-row sub-row status-${row.status} ${isLast ? "last-sub" : ""}`}>
      <td className="gc-identity sub-name" colSpan={2}>
        <div className="sub-row-label">
          <span className="sub-indent">└</span>
          <span className="sub-expiry-text">{row.expiry_label || "—"}</span>
        </div>
      </td>
      <LtpCell value={row.big_ltp} instrument={(row.big || "").toUpperCase()} className="gc-ltp" />
      <LtpCell value={row.small_ltp} instrument={(row.small || "").toUpperCase()} className="gc-ltp col-end-group" />
      <SpreadCell value={row.decrease_spread} tone="dec" className="gc-decrease" />
      <SpreadCell value={row.increase_spread} tone="inc" className="gc-increase col-end-group" />
      <td className="gc-status">
        <span className={`badge ${STATUS_CLASS[row.status] || "badge-idle"}`}>
          <span className="blip" />
          {STATUS_LABEL[row.status] || row.status}
        </span>
      </td>
      <td className="gc-status"><span className="ladder-count-pill dec">▼ {decCount}</span></td>
      <td className="gc-status col-end-group"><span className="ladder-count-pill inc">▲ {incCount}</span></td>
      <td className="gc-action">
        <div className="front-actions">
          <button className="btn btn-primary btn-xs" onClick={() => onManage(row.name)}>Manage</button>
          <button className="btn btn-secondary btn-xs" onClick={() => onPositions(row.name)}>Positions</button>
          <button className="btn btn-secondary btn-xs" onClick={() => onHistory(row.name)}>History</button>
        </div>
      </td>
    </tr>
  );
}, (prev, next) => (
  prev.isLast === next.isLast &&
  prev.row.decrease_spread === next.row.decrease_spread &&
  prev.row.increase_spread === next.row.increase_spread &&
  prev.row.big_ltp === next.row.big_ltp &&
  prev.row.small_ltp === next.row.small_ltp &&
  prev.row.status === next.row.status &&
  prev.row.decrease_ladders === next.row.decrease_ladders &&
  prev.row.increase_ladders === next.row.increase_ladders &&
  prev.row.expiry_label === next.row.expiry_label
));

export function SortableTh({ label, field, sort, setSort, ...rest }) {
  const active = sort.field === field;
  const dir = active ? sort.dir : null;
  function toggle() {
    if (!active) setSort({ field, dir: "asc" });
    else if (dir === "asc") setSort({ field, dir: "desc" });
    else setSort({ field: null, dir: "asc" });
  }
  return (
    <th {...rest} onClick={toggle} className={`sortable ${rest.className || ""}`}>
      <span className="th-label">{label}</span>
      <span className="sort-arrow">
        {active ? (dir === "asc" ? "▲" : "▼") : <span className="dim">⇅</span>}
      </span>
    </th>
  );
}
