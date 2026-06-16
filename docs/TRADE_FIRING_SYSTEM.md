# Trade-Firing System — Full Blueprint (for future re-add)

> **Status:** REMOVED on conversion to watch-only (June 2026).
> This document captures the **entire paper-trade firing/exit system** so it can
> be re-added later if the client decides to enable trade firing again.
>
> Paper trading only — the system never placed real broker orders. It simulated
> entries/exits against live bid/ask and recorded paper PnL.

---

## 1. What stays vs what was removed

| Layer | KEEP (watch-only) | REMOVED (trade-firing) |
|-------|-------------------|------------------------|
| Spread math | `spread_engine.compute_pair/compute_all` (decrease/increase spread + %) | — |
| Live display | snapshot payload, WS stream, all spread tabs | status badges, position counts |
| Engine | — | `trade_engine.py` (entire evaluate→fire→exit loop) |
| Maintenance | history/activity pruning, vacuum, rollover check | `_daily_clear_ladders()` |
| Routes | pairs, price, metals, othercomm, options, calculator, feed, ws, auth, public_v1 | ladders, positions, history, control, config(account) |
| DB | users, last_quotes | positions, trade_history, ladder_rules, account_config, pair_rules |
| Frontend | Live Spread Monitor cards, Calculator, Nifty/Sensex | gear menu, Manage/Positions/History modals, Settings, Activity |

**Golden rule for re-add:** spread computation is the shared boundary. Firing
reads the same `compute_pair()` snapshot but adds the *decision* layer on top.

---

## 2. Core firing math (exact, verified)

`spread_engine.compute_pair(pair)` returns a snapshot `snap` with:

```
big_bid, big_ask, small_bid, small_ask          # executable prices (with LTP fallback)
decrease_spread = big.bid×big_mult − small.ask×small_mult
increase_spread = big.ask×big_mult − small.bid×small_mult
```

`_rate(price, instr) = price × MULTIPLIERS[instr]`

**MULTIPLIERS** (config.py):
```
petal 10.0 · guinea 1.25 · ten 1.0 · mini 1.0 · gold 1.0
silver 1.0 · silverm 1.0 · silvermic 1.0 · silver100 100.0
```

**GRAMS_PER_LOT** (config.py):
```
petal 1 · guinea 8 · ten 10 · mini 100 · gold 1000
silver 30000 · silverm 5000 · silvermic 1000 · silver100 100
```

`cycle_grams(pair) = pair.big_lots × GRAMS_PER_LOT[pair.big]`
`DEFAULT_MAX_WEIGHT_GRAMS = 1000` · `MAX_ALLOWED_WEIGHT_GRAMS = 1000` (hard cap)

---

## 3. The ladder system

Each **pair-side** (decrease / increase) can have many independent **LadderRules**.
Each ladder has its own `entry`, `exit`, `max_weight_grams`, `enabled`, `sort_order`,
and an in-memory **armed** flag (`_armed: dict[ladder_id, bool]`).

### Arm → fire state machine
A ladder must **leave and re-enter** the trigger zone to fire again (prevents
re-firing every tick while parked in-zone).

**Decrease ladder** (`_entry_decrease`, trade_engine.py:216):
```
if dec_spread < entry:            armed = True              # in zone → arm
elif armed:                       # spread left the zone → attempt fire
    if not account_cap_allows:    log fire_blocked once; armed = False
    elif can_open_new_cycle:      OPEN decrease trade; flush
                                  if cap now full: armed = False
    else:                         armed = False             # ladder locked
```

**Increase ladder** (`_entry_increase`, trade_engine.py:240): same logic but
arms when `inc_spread > entry`.

`prime_armed_state(ladder_id)` sets `armed=True` on create/update so it can fire
immediately if already in zone.

### Exit (Pass 2 of `evaluate`, trade_engine.py:182)
```
decrease ladder closes when inc_spread ≤ exit   (cover on the increase side)
increase ladder closes when dec_spread ≥ exit   (cover on the decrease side)
```

---

## 4. Open / close trade

**`_open_trade(db, pair, mode, snap, ladder_id)`** (trade_engine.py:264)
- decrease: big_price = big_bid, small_price = small_ask, spread = decrease_spread
- increase: big_price = big_ask, small_price = small_bid, spread = increase_spread
- Inserts a `Position` (is_paper=True, status="open", ladder_rule_id) + logs `fire` activity.
- weight = big_lots × GRAMS_PER_LOT[big].

**`_close_trade(db, pos, snap, closed_by)`** (trade_engine.py:296)
```
decrease pos:  exit_spread = increase_spread ; pnl = (entry_spread − exit_spread) × big_lots / 10
increase pos:  exit_spread = decrease_spread ; pnl = (exit_spread − entry_spread) × big_lots / 10
```
- Inserts `TradeHistory` (full per-leg entry/exit prices, weight, pnl, closed_by),
  sets `pos.status="closed"`, logs `exit` activity.

**`manual_close(db, position_id)`** (trade_engine.py:341): user-initiated close via
the same `_close_trade`. **`live_pnl(pos)`** (trade_engine.py:361): unrealized PnL
for display (same PnL formula).

> **PnL note:** the `/ 10` divisor converts the spread move into rupees for the
> per-10g quoting basis used across the gold family. Preserve it exactly on re-add.

---

## 5. Caps (two independent gates)

**A. Lifetime weight cap (per ladder)** — `can_open_new_cycle_for_ladder` (trade_engine.py:75)
```
fired = Σ big_lots×grams across ALL positions (open + closed) on this ladder   # never resets
fire allowed only if fired + cycle_grams(pair) ≤ effective_max_weight(rule)
fired ≥ cap → ladder LOCKED until cap is RAISED (one-way; routes/ladders.py forbids lowering)
```

**B. Account margin cap (global)** — `_account_cap_allows_new_fire` (trade_engine.py:88)
```
cfg = AccountConfig (balance, max_usage_percent)   # if unset → no enforcement
cap_rupees = balance × max_usage_percent / 100
used = Σ margin_for_position(p) for open positions whose ladder is still live (orphans excluded)
this_fire = margin_service.estimated_margin_for_fire(pair)
fire allowed only if used + this_fire ≤ cap_rupees   ; else log fire_blocked once
```
Margin per leg = live LTP × instrument margin % (margin_service.py). Orphan
positions (ladder removed by daily clear) are excluded from `used` so next day's
fresh ladders can still fire.

---

## 6. Evaluate loop & wiring

**`trade_engine.evaluate(db)`** (trade_engine.py:142) — two-pass, runs ~2 Hz:
- Pass 1: per enabled ladder → `_entry_decrease/_entry_increase` (may open+flush).
- Pass 2: one SELECT of all open positions → close those past `exit`.
- Commits only if `dirty` (avoids WAL churn on idle ticks).

**Driven by the feed:** `dhan_feed._eval_and_broadcast()` (dhan_feed.py:77) calls
`evaluate(db)` then broadcasts. Throttled by `last_eval` (~500 ms). Called from
both `_run_real_feed_thread` (dhan_feed.py:~288) and `_run_simulated_thread`
(dhan_feed.py:~392). **Re-add = restore the `evaluate(db)` call here.**

**Daily clear:** `maintenance._daily_clear_ladders()` (maintenance.py:63) deletes
all ladder rules at MCX close (23:35 IST), nulling `ladder_rule_id` FKs on
positions/history to prevent ID-reuse bugs. Called from `maintenance._loop()` (~line 162).

---

## 7. Database models (models.py)

| Table | Model | Key columns |
|-------|-------|-------------|
| `ladder_rules` | `LadderRule` (104-126) | pair_name, side(decrease/increase), entry, exit, max_weight_grams, sort_order, enabled |
| `positions` | `Position` (30-45) | pair_name, mode, entry_spread, big/small_lots, big/small_price, status(open/closed), ladder_rule_id, is_paper, entry_time |
| `trade_history` | `TradeHistory` (48-74) | pair_name, mode, entry/exit_spread, entry/exit_time, big/small_lots, pnl, closed_by, big/small entry+exit prices, weight_grams, ladder_rule_id |
| `account_config` | `AccountConfig` (128-137) | balance, max_usage_percent |
| `pair_rules` | `PairRule` (8-27) | legacy single-rule-per-side (deprecated) |
| `activity_log` | `ActivityLog` (140-153) | action, pair_name, side, ladder_id, actor, summary, details, ts |
| Indexes | line 80, 82 | ix_positions_pair_mode_status, ix_history_exit_pair |

`activity_log` actions used by firing: `fire`, `exit`, `square_off`, `fire_blocked`,
`ladder_created`, `ladder_updated`, `ladder_deleted`, `account_config_updated`,
`daily_clear`, `history_deleted`, `history_purged`.

---

## 8. API routes

| File | Prefix | Endpoints | Role |
|------|--------|-----------|------|
| `routes/ladders.py` | `/api/ladders` | GET, POST, PUT/{id}, DELETE/{id} | ladder CRUD (PUT/POST call `prime_armed_state`; cap may only increase) |
| `routes/positions.py` | `/api/positions` | GET, POST /{id}/close, POST /square-off | list open, manual close, FIFO square-off by weight |
| `routes/history.py` | `/api/history` | GET, DELETE/{id} | closed-trade audit, delete record |
| `routes/control.py` | `/api/control` | POST /pause-all | disable all ladders |
| `routes/config.py` | `/api/config` | GET/PUT /account | account balance + max-usage % (margin cap) |

`main.py` registered these at lines 35, 36, 37, 39, 42 (imports on line 11).
Public API (`public_v1.py`) exposed **no** trade data — only spreads/prices — so it
was untouched.

---

## 9. Frontend components

**Delete (entirely):**
- `components/Settings.jsx` — account balance / max-usage cap / live cap status
- `components/Activity.jsx` — trade audit log
- `components/spread/Modals.jsx` — LadderModal, PositionsModal, HistoryModal
- `components/spread/LadderTable.jsx` — ladder editor (entry/exit/cap rows, add/save/delete, weight bar)
- `components/spread/PairPositionsTab.jsx` — open positions + manual square-off panel
- `components/spread/PairHistoryTab.jsx` — closed trades + delete record

**Modify (strip trade bits, keep watch):**
- `components/spread/SpreadCards.jsx` — remove gear menu (⚙) + Manage/Positions/History, status colors, open-position count pills; keep pair/expiry/dec/inc/% display.
- `components/LiveSpreadTable.jsx` — remove status filter tabs (All/Armed/In Position/Idle), `counts`, modal state, onManage/onPositions/onHistory; keep search, expiry filter, the 5 tabs (Cross/Calendar/Metal/Price/Other Commodity).
- `components/Header.jsx` — remove Settings & Activity nav buttons; keep Dashboard, Calculator, Nifty/Sensex.
- `App.jsx` — remove `positions`/`history`/`account` state, `refreshAccount()`, Settings/Activity routes; drop "settings"/"activity" from `VALID_PAGES`.
- `components/spread/SpreadRows.jsx` (table view, if used) — remove action buttons + status badges.
- `api/client.js` — trade methods may stay dormant (harmless) but are no longer called: `createLadder`, `updateLadder`, `deleteLadder`, `closePosition`, `squareOff`, `positions`, `history`, `deleteHistory`, `activity`, `getAccount`, `updateAccount`, `saveRule`.

---

## 10. How to RE-ADD trade firing (checklist)

1. **DB:** restore models `LadderRule`, `Position`, `TradeHistory`, `AccountConfig` (+ indexes) in `models.py`; `Base.metadata.create_all` recreates tables.
2. **Engine:** restore `trade_engine.py` (this file documents every function/formula).
3. **Feed:** re-add the `evaluate(db)` call in `dhan_feed._eval_and_broadcast()`.
4. **Maintenance:** re-add `_daily_clear_ladders()` call in `maintenance._loop()`.
5. **Routes:** restore `ladders.py`, `positions.py`, `history.py`, `control.py`, `config.py`; re-register in `main.py` (imports + `include_router`).
6. **Margin:** restore `margin_service.estimated_margin_for_fire()` (account-cap path).
7. **Snapshot:** re-attach ladder defs + status (idle/armed/in_position) in `snapshot.build_live_payload` if the UI needs them.
8. **Frontend:** restore the 6 deleted components + revert the 5 modified ones (gear menu, status filters, Settings/Activity nav, App routing).
9. **Verify:** create a ladder, watch it arm/fire/exit on paper, check Positions/History/Activity, confirm caps (weight + account) block correctly.

> Use `git log` / `git show` of the removal commit to recover exact original code
> for any file — this doc is the map; git is the source of truth.

---

## 11. Key gotchas to preserve on re-add
- **Executable prices only:** decrease uses big **bid** / small **ask**; increase uses big **ask** / small **bid**. Never LTP for the decision.
- **PnL `/10` divisor** — keep exactly (per-10g rupee basis).
- **Lifetime cap never resets**; unlock only by raising the cap (one-way).
- **Orphan positions excluded** from account-cap `used` (post daily-clear).
- **Arm requires leave+re-enter** the zone — don't fire every in-zone tick.
- **`dirty`-gated commit** in `evaluate` — avoids SQLite WAL churn at ~2 Hz.
