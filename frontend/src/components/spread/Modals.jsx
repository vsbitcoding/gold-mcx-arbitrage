import React, { useEffect, useState } from "react";
import LadderTable from "./LadderTable.jsx";
import PairPositionsTab from "./PairPositionsTab.jsx";
import PairHistoryTab from "./PairHistoryTab.jsx";
import { fmtSpread } from "../../utils/format.js";
import { STATUS_CLASS, STATUS_LABEL } from "./constants.js";

function useEscClose(onClose) {
  useEffect(() => {
    function onKey(e) { if (e.key === "Escape") onClose(); }
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [onClose]);
}

export function LadderModal({ row, onClose, onChange }) {
  const [tab, setTab] = useState("decrease");
  useEscClose(onClose);
  if (!row) return null;
  const decCount = row.decrease_ladders.length;
  const incCount = row.increase_ladders.length;

  return (
    <div className="ladder-modal-overlay" onClick={onClose}>
      <div className="ladder-modal" onClick={(e) => e.stopPropagation()}>
        <div className="ladder-modal-head">
          <div className="ladder-modal-title">
            <span className="pair-card-title">{row.name}</span>
            <span className={`badge ${STATUS_CLASS[row.status] || "badge-idle"}`}>
              <span className="blip" />
              {STATUS_LABEL[row.status] || row.status}
            </span>
          </div>
          <div className="ladder-modal-spreads">
            <div className="modal-spread dec">
              <div className="lbl">▼ Decrease</div>
              <div className="val">{fmtSpread(row.decrease_spread)}</div>
            </div>
            <div className="modal-spread inc">
              <div className="lbl">▲ Increase</div>
              <div className="val">{fmtSpread(row.increase_spread)}</div>
            </div>
          </div>
          <button className="drawer-close" onClick={onClose}>×</button>
        </div>

        <div className="ladder-modal-tabs">
          <button className={`mtab dec ${tab === "decrease" ? "active" : ""}`} onClick={() => setTab("decrease")}>
            ▼ Decrease <span className="mtab-count">{decCount}</span>
          </button>
          <button className={`mtab inc ${tab === "increase" ? "active" : ""}`} onClick={() => setTab("increase")}>
            ▲ Increase <span className="mtab-count">{incCount}</span>
          </button>
        </div>

        <div className="ladder-modal-body">
          <div style={{ display: tab === "decrease" ? "flex" : "none", flex: 1, minHeight: 0, flexDirection: "column" }}>
            <LadderTable
              pairName={row.name} side="decrease"
              ladders={row.decrease_ladders}
              defaultMaxWeight={row.default_max_weight}
              maxAllowed={row.max_allowed_weight}
              onChange={onChange}
            />
          </div>
          <div style={{ display: tab === "increase" ? "flex" : "none", flex: 1, minHeight: 0, flexDirection: "column" }}>
            <LadderTable
              pairName={row.name} side="increase"
              ladders={row.increase_ladders}
              defaultMaxWeight={row.default_max_weight}
              maxAllowed={row.max_allowed_weight}
              onChange={onChange}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

export function PositionsModal({ row, onClose }) {
  useEscClose(onClose);
  if (!row) return null;
  return (
    <div className="ladder-modal-overlay" onClick={onClose}>
      <div className="ladder-modal info-modal" onClick={(e) => e.stopPropagation()}>
        <div className="ladder-modal-head">
          <div className="ladder-modal-title">
            <span className="pair-card-title">{row.name}</span>
            <span className="info-modal-tag">Active Positions</span>
          </div>
          <button className="drawer-close" onClick={onClose}>×</button>
        </div>
        <div className="ladder-modal-body" style={{ overflow: "auto", padding: "16px 20px" }}>
          <PairPositionsTab pairName={row.name} />
        </div>
      </div>
    </div>
  );
}

export function HistoryModal({ row, onClose }) {
  useEscClose(onClose);
  if (!row) return null;
  return (
    <div className="ladder-modal-overlay" onClick={onClose}>
      <div className="ladder-modal info-modal" onClick={(e) => e.stopPropagation()}>
        <div className="ladder-modal-head">
          <div className="ladder-modal-title">
            <span className="pair-card-title">{row.name}</span>
            <span className="info-modal-tag">Trade History</span>
          </div>
          <button className="drawer-close" onClick={onClose}>×</button>
        </div>
        <div className="ladder-modal-body" style={{ overflow: "auto", padding: "16px 20px" }}>
          <PairHistoryTab pairName={row.name} />
        </div>
      </div>
    </div>
  );
}
