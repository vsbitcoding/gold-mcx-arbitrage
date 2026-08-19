import React, { useEffect, useRef, useState } from "react";
import { api } from "../api/client.js";
import { fmtNum } from "../utils/format.js";

// The client's own reference tool, in-house (18-Aug).
//
// He sent option-price.com with a note mapping its fields to what he trades:
// underlying = the FUTURE price, strike = his strike, interest and dividend both
// zero, market price = that call or put price. That mapping is right - with a
// futures underlying and no carry, Black-Scholes is Black-76.
//
// Two reasons it lives here rather than as a bookmark. His site's endpoint takes
// volatility IN and returns a price, the opposite direction; its implied-vol
// page runs in the browser, so there is nothing to call. And the numbers he
// needs are already on this screen - PREFILL takes them off the live board so he
// is not copying six figures per strike while the future moves under him.
//
// Fed his site's own example this returns its numbers to six decimals, which is
// the point of having the page at all: he can check us against the tool he
// already trusts.

const SIDES = [{ key: "ce", label: "Call" }, { key: "pe", label: "Put" }];
const MODES = [
  { key: "iv", label: "Find IV", hint: "market price in, volatility out" },
  { key: "price", label: "Find price", hint: "volatility in, price and greeks out" },
];
const PRODUCTS = [
  { key: "crude", label: "Crude Oil", dec: 1 },
  { key: "natgas", label: "Natural Gas", dec: 2 },
];

const N = (v) => (v === "" || v == null ? null : Number(v));
const ok = (v) => v != null && Number.isFinite(v);

function Field({ label, unit, value, onChange, hint, step }) {
  return (
    <label className="ivc-field">
      <span>{label}{unit ? <em>{unit}</em> : null}</span>
      <input type="number" inputMode="decimal" step={step || "any"}
        value={value} onChange={(e) => onChange(e.target.value)} />
      {hint ? <u>{hint}</u> : null}
    </label>
  );
}

export default function IvCalculator() {
  const [mode, setMode] = useState("iv");
  const [side, setSide] = useState("ce");
  const [product, setProduct] = useState("crude");

  const [underlying, setUnderlying] = useState("");
  const [strike, setStrike] = useState("");
  const [days, setDays] = useState("");
  const [rate, setRate] = useState("0");
  const [dividend, setDividend] = useState("0");
  const [market, setMarket] = useState("");
  const [vol, setVol] = useState("25");

  const [board, setBoard] = useState(null);
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const seq = useRef(0);

  // The live board, only so the prefill buttons have something to offer. One
  // fetch on a commodity change, no polling - this page is a calculator, not a
  // ticker, and a number moving under the cursor mid-typing is worse than stale.
  useEffect(() => {
    let alive = true;
    api.nseMcx(product, 0)
      .then((r) => { if (alive) setBoard(r); })
      .catch(() => { if (alive) setBoard(null); });
    return () => { alive = false; };
  }, [product]);

  const cfg = PRODUCTS.find((p) => p.key === product) || PRODUCTS[0];
  const basis = board?.iv_basis;

  function prefill(exchange) {
    const b = basis?.[exchange];
    if (!b?.forward) return;
    // The forward the chain's own prices imply, NOT the future on the board.
    // That future is the front month while the options are the month after, and
    // using it is exactly the mistake that made a vendor's IV wrong.
    setUnderlying(String(b.forward));
    setDays(String(b.days ?? ""));
    setRate("0");
    setDividend("0");
    const rows = board?.options?.rows || [];
    const atm = rows.find((r) => r.atm) || rows[Math.floor(rows.length / 2)];
    if (atm) {
      setStrike(String(atm.strike));
      const leg = atm[side]?.[exchange];
      if (leg?.mid != null) setMarket(String(leg.mid));
    }
    setMode("iv");
  }

  const inputsOk = ok(N(underlying)) && ok(N(strike)) && ok(N(days)) && N(days) > 0
    && (mode === "iv" ? ok(N(market)) : ok(N(vol)));

  useEffect(() => {
    if (!inputsOk) { setRes(null); setErr(null); return undefined; }
    const my = ++seq.current;
    setBusy(true);
    const p = {
      underlying: N(underlying), strike: N(strike), days: N(days),
      rate: N(rate) || 0, dividend: N(dividend) || 0, side,
    };
    if (mode === "iv") p.market = N(market); else p.vol = N(vol);
    api.ivCalculator(p)
      .then((r) => { if (my === seq.current) { setRes(r); setErr(null); } })
      .catch((e) => { if (my === seq.current) { setErr(e.message); setRes(null); } })
      .finally(() => { if (my === seq.current) setBusy(false); });
    return undefined;
  }, [mode, side, underlying, strike, days, rate, dividend, market, vol, inputsOk]);

  const g = res?.greeks;
  const dec = cfg.dec;

  return (
    <div className={`ivc-page ${busy ? "ivc-busy" : ""}`}>
      <div className="nm-head">
        <div className="nm-head-left">
          <h2>Option Calculator</h2>
          <span className="intl-status on">Black-76</span>
        </div>
        <div className="nm-head-end">
          <div className="oh-group" role="tablist" aria-label="Direction">
            {MODES.map((m) => (
              <button key={m.key} type="button" role="tab" aria-selected={mode === m.key}
                className={`oh-chip ${mode === m.key ? "on" : ""}`} title={m.hint}
                onClick={() => setMode(m.key)}>{m.label}</button>
            ))}
          </div>
          <div className="oh-group" role="tablist" aria-label="Side">
            {SIDES.map((s) => (
              <button key={s.key} type="button" role="tab" aria-selected={side === s.key}
                className={`oh-chip ${side === s.key ? "on" : ""}`}
                onClick={() => setSide(s.key)}>{s.label}</button>
            ))}
          </div>
        </div>
      </div>

      <div className="ivc-grid">
        <section className="nmg-card ivc-inputs">
          <div className="nmg-rhd"><b>INPUTS</b>
            <span>{mode === "iv" ? "market price in" : "volatility in"}</span>
          </div>
          <div className="ivc-body">
            <Field label="Underlying" unit="future price" value={underlying}
              onChange={setUnderlying}
              hint="the future of the option's OWN month, not the front month" />
            <Field label="Strike" value={strike} onChange={setStrike} />
            <Field label="Days to expiry" unit="days" value={days} onChange={setDays}
              step="1" />
            {mode === "iv"
              ? <Field label="Market price" unit={side === "ce" ? "call" : "put"}
                  value={market} onChange={setMarket} />
              : <Field label="Volatility" unit="%" value={vol} onChange={setVol} />}
            <Field label="Interest rate" unit="%" value={rate} onChange={setRate}
              hint="0 for an option on a future" />
            <Field label="Dividend yield" unit="%" value={dividend} onChange={setDividend}
              hint="0 for an option on a future" />
          </div>

          {/* Six numbers per strike is a lot to retype while the market moves,
              and the whole reason the vendor figure was wrong is that the
              obvious number to reach for is the wrong one. */}
          <div className="ivc-prefill">
            <span>Fill from the live board</span>
            <div className="oh-group">
              {PRODUCTS.map((p) => (
                <button key={p.key} type="button"
                  className={`oh-chip ${product === p.key ? "on" : ""}`}
                  onClick={() => setProduct(p.key)}>{p.label}</button>
              ))}
            </div>
            <div className="ivc-prefill-btns">
              {["nse", "mcx"].map((ex) => (
                <button key={ex} type="button" className="oh-chip"
                  disabled={!basis?.[ex]?.forward}
                  title={basis?.[ex]?.forward
                    ? `forward ${basis[ex].forward} from ${basis[ex].strikes} strikes, ${basis[ex].days} days`
                    : "no forward available yet"}
                  onClick={() => prefill(ex)}>{ex.toUpperCase()} ATM</button>
              ))}
            </div>
          </div>
        </section>

        <section className="nmg-card ivc-out">
          <div className="nmg-rhd"><b>RESULT</b>
            <span>{res?.model || "Black-Scholes / Black-76"}</span>
          </div>

          {err && <div className="settings-banner danger">⚠ {err}</div>}

          {!inputsOk && !err && (
            <div className="nmg-empty">
              <b>Fill the inputs</b>
              <span>
                Underlying, strike, days and {mode === "iv" ? "a market price" : "a volatility"}.
                Interest and dividend stay at zero for an option on a future.
              </span>
            </div>
          )}

          {inputsOk && res && (
            <div className="ivc-body">
              <div className="ivc-hero">
                {mode === "iv" ? (
                  <>
                    <em>IMPLIED VOLATILITY</em>
                    <b className={res.implied_vol == null ? "ivc-none" : ""}>
                      {res.implied_vol == null ? "—" : `${fmtNum(res.implied_vol, 2)}%`}
                    </b>
                  </>
                ) : (
                  <>
                    <em>{side === "ce" ? "CALL" : "PUT"} PRICE</em>
                    <b>{res.price == null ? "—" : fmtNum(res.price, dec + 2)}</b>
                  </>
                )}
              </div>

              {res.note && <p className="nmg-widenote">{res.note}</p>}

              {res.price != null && (
                <>
                  <div className="ivc-pair">
                    <div><em>Call</em><b>{fmtNum(res.call_price, dec + 2)}</b></div>
                    <div><em>Put</em><b>{fmtNum(res.put_price, dec + 2)}</b></div>
                    <div><em>Intrinsic</em><b>{fmtNum(res.intrinsic, dec)}</b></div>
                    <div><em>Time value</em><b>{fmtNum(res.time_value, dec + 2)}</b></div>
                  </div>

                  {g && (
                    <table className="cru-table ivc-greeks">
                      <tbody>
                        <tr><th>Delta</th><td>{fmtNum(g.delta, 4)}</td></tr>
                        <tr><th>Gamma</th><td>{fmtNum(g.gamma, 6)}</td></tr>
                        <tr><th>Vega<em>per 1% vol</em></th><td>{fmtNum(g.vega, 4)}</td></tr>
                        <tr><th>Theta<em>per day</em></th><td>{fmtNum(g.theta, 4)}</td></tr>
                        <tr><th>Rho<em>per 1% rate</em></th><td>{fmtNum(g.rho, 4)}</td></tr>
                      </tbody>
                    </table>
                  )}

                  {/* Both legs are priced at one volatility, so K + C - P must
                      return the underlying. If it does not, something above is
                      wrong - and this is the exact check that exposed the
                      vendor's IV. */}
                  <p className="nmg-widenote">
                    Parity check: strike + call − put = {" "}
                    <b>{fmtNum(N(strike) + res.call_price - res.put_price, dec)}</b>, and the
                    underlying you entered is <b>{fmtNum(N(underlying), dec)}</b>. These
                    must agree. When a call and a put at one strike disagree on
                    volatility, the underlying is the wrong month.
                  </p>
                </>
              )}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
