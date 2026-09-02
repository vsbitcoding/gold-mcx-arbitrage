from datetime import datetime

from sqlalchemy import (Boolean, Column, DateTime, Float, Integer, LargeBinary,
                        String, Text, UniqueConstraint)

from app.database import Base


class PairRule(Base):
    """One row per pair holding both sides' entry/exit values."""
    __tablename__ = "pair_rules"

    id = Column(Integer, primary_key=True)
    pair_name = Column(String(64), unique=True, nullable=False, index=True)

    decrease_entry = Column(Float, nullable=True)
    decrease_exit = Column(Float, nullable=True)
    increase_entry = Column(Float, nullable=True)
    increase_exit = Column(Float, nullable=True)

    decrease_status = Column(String(32), default="idle")
    increase_status = Column(String(32), default="idle")

    max_weight_grams = Column(Integer, nullable=True)  # ACTIVE cap currently in force
    pending_max_weight_grams = Column(Integer, nullable=True)  # set if cap changed mid-round
    has_pending_cap = Column(Integer, default=0, nullable=False)  # 1 if a pending change exists

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Position(Base):
    """An open trade (paper or live)."""
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True)
    pair_name = Column(String(64), nullable=False, index=True)
    mode = Column(String(16), nullable=False, index=True)  # decrease | increase
    entry_spread = Column(Float, nullable=False)
    entry_time = Column(DateTime, default=datetime.utcnow)
    big_lots = Column(Integer, nullable=False)
    small_lots = Column(Integer, nullable=False)
    big_price = Column(Float, nullable=False)
    small_price = Column(Float, nullable=False)
    is_paper = Column(Boolean, default=True)
    status = Column(String(16), default="open", index=True)  # open | closed
    ladder_rule_id = Column(Integer, nullable=True, index=True)


class TradeHistory(Base):
    """Closed trade record."""
    __tablename__ = "trade_history"

    id = Column(Integer, primary_key=True)
    pair_name = Column(String(64), nullable=False, index=True)
    mode = Column(String(16), nullable=False)
    entry_spread = Column(Float, nullable=False)
    exit_spread = Column(Float, nullable=False)
    entry_time = Column(DateTime, nullable=False)
    exit_time = Column(DateTime, default=datetime.utcnow)
    big_lots = Column(Integer, nullable=False)
    small_lots = Column(Integer, nullable=False)
    pnl = Column(Float, nullable=False)
    is_paper = Column(Boolean, default=True)
    closed_by = Column(String(16), default="auto")  # auto | manual
    notes = Column(Text, nullable=True)

    # Per-leg snapshot prices for audit / detail views
    big_entry_price = Column(Float, nullable=True)
    small_entry_price = Column(Float, nullable=True)
    big_exit_price = Column(Float, nullable=True)
    small_exit_price = Column(Float, nullable=True)
    weight_grams = Column(Integer, nullable=True)

    # Link back to source ladder for lifetime-fired counter
    ladder_rule_id = Column(Integer, nullable=True, index=True)


from sqlalchemy import Index  # noqa: E402

# Composite index for frequent open-position-by-(pair, mode) lookups
Index("ix_positions_pair_mode_status", Position.pair_name, Position.mode, Position.status)
# Composite index for history queries by date+pair
Index("ix_history_exit_pair", TradeHistory.exit_time, TradeHistory.pair_name)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, nullable=False)
    password_hash = Column(String(256), nullable=False)
    # 'admin' sees the whole dashboard; 'trader' sees only the Auto Trades page.
    role = Column(String(16), nullable=False, default="admin")
    created_at = Column(DateTime, default=datetime.utcnow)


class PaperSymbol(Base):
    """An MCX symbol the webhook trader has used, resolved once and kept.

    Nothing is hard-coded on our side (client, 20-Aug): the first webhook that
    names a symbol resolves it against the Dhan scrip master - active front
    month, security id, lot units - and the row keeps it on the live feed across
    restarts. Gold and silver are pre-seeded so their very first signal is
    instant instead of paying the one-time resolve.
    """
    __tablename__ = "paper_symbols"
    id = Column(Integer, primary_key=True)
    symbol = Column(String(32), unique=True, nullable=False)      # GOLDM, SILVERM...
    security_id = Column(String(16), nullable=False)
    trading_symbol = Column(String(64), nullable=True)            # GOLDM-05DEC2026-FUT
    lot_units = Column(Float, nullable=True)                      # rupees per point per lot
    expiry = Column(String(10), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, default=datetime.utcnow)


class PaperTrade(Base):
    """A DUMMY trade fired by the TradingView webhook - never a real order.

    Entry and exit are the exchange LTP at the moment each signal arrived, read
    from the live socket's in-memory store; `temp_*` is whatever price the
    client's alert happened to carry, saved only so the difference can be shown.
    One open position per symbol, flipped by the opposite signal.
    """
    __tablename__ = "paper_trades"
    id = Column(Integer, primary_key=True)
    symbol = Column(String(32), nullable=False, index=True)
    side = Column(String(5), nullable=False)                      # long | short
    lots = Column(Float, nullable=False, default=1)
    lot_units = Column(Float, nullable=True)                      # frozen at entry
    timeframe = Column(String(8), nullable=True)
    status = Column(String(6), nullable=False, default="open", index=True)
    entry_time = Column(DateTime, nullable=False)                 # IST naive
    entry_ltp = Column(Float, nullable=False)
    entry_temp = Column(Float, nullable=True)
    exit_time = Column(DateTime, nullable=True)
    exit_ltp = Column(Float, nullable=True)
    exit_temp = Column(Float, nullable=True)
    points = Column(Float, nullable=True)                         # signed, side-aware
    pnl = Column(Float, nullable=True)                            # points x lots x lot_units
    # 'signal' = the opposite webhook flipped it; 'stop' = the client pressed
    # Stop and everything open was booked at that moment's price.
    exit_reason = Column(String(12), nullable=True)
    # Which account this trade belongs to (paper_accounts.id). The ledger key
    # is account + symbol + timeframe since 24-Aug.
    account_id = Column(Integer, nullable=True, index=True)
    entry_diff = Column(Float, nullable=True)                     # entry_temp - entry_ltp
    exit_diff = Column(Float, nullable=True)
    duration_s = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class PaperAccount(Base):
    """A trading account the webhook fans out to (client, 24-Aug).

    One webhook, one symbol -> a separate paper trade in EVERY account whose
    symbol list contains it. The Angel One fields are stored-only for now -
    the client supplies placeholders and trades stay paper; when he one day
    says "real", the plumbing gets built against these same fields. They are
    never logged and never sent to any UI unmasked.
    """
    __tablename__ = "paper_accounts"
    id = Column(Integer, primary_key=True)
    name = Column(String(64), unique=True, nullable=False)
    angel_client_id = Column(String(64), nullable=True)
    angel_mpin = Column(String(64), nullable=True)
    angel_totp = Column(String(128), nullable=True)
    symbols_json = Column(Text, nullable=False, default="[]")   # ["GOLDM", ...]
    created_at = Column(DateTime, default=datetime.utcnow)


class PaperState(Base):
    """One row: is the paper-trade system accepting signals?

    Stop books every open trade at that moment's price and then refuses new
    webhooks (still logged, so missed signals stay visible); Start resumes.
    Lives in the database so a server restart cannot silently re-arm a system
    the client stopped on purpose.
    """
    __tablename__ = "paper_state"
    id = Column(Integer, primary_key=True)                        # always 1
    enabled = Column(Boolean, nullable=False, default=True)
    changed_at = Column(DateTime, nullable=True)
    changed_by = Column(String(64), nullable=True)


class PaperSignal(Base):
    """Every webhook that arrived, verbatim, with what was done about it.

    The ignored and rejected ones matter most - "મેં મોકલ્યું, કેમ ના થયું?" is
    answered here, with the reason, instead of by silence.
    """
    __tablename__ = "paper_signals"
    id = Column(Integer, primary_key=True)
    received_at = Column(DateTime, nullable=False, index=True)    # IST naive
    symbol_raw = Column(String(64), nullable=True)
    symbol = Column(String(32), nullable=True, index=True)
    side = Column(String(8), nullable=True)                       # buy | sell
    lots = Column(Float, nullable=True)
    timeframe = Column(String(8), nullable=True)
    temp_price = Column(Float, nullable=True)
    action = Column(String(12), nullable=False)                   # opened|flipped|ignored|rejected
    account = Column(String(64), nullable=True, index=True)       # which account this row is about
    reason = Column(String(160), nullable=True)
    ltp = Column(Float, nullable=True)                            # the price the action used
    trade_id = Column(Integer, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    raw_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class LastQuote(Base):
    """Persists last known good bid/ask/ltp per instrument so the dashboard
    survives service restarts and market holidays without going blank."""
    __tablename__ = "last_quotes"
    instrument = Column(String(32), primary_key=True)
    bid = Column(Float, default=0.0)
    ask = Column(Float, default=0.0)
    ltp = Column(Float, default=0.0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class LadderRule(Base):
    """Multiple entry/exit/cap ladders per pair-side. Each ladder fires and
    runs independently with its own weight cap and armed state."""
    __tablename__ = "ladder_rules"

    id = Column(Integer, primary_key=True)
    pair_name = Column(String(64), nullable=False, index=True)
    side = Column(String(16), nullable=False, index=True)  # decrease | increase

    entry = Column(Float, nullable=True)
    exit = Column(Float, nullable=True)
    max_weight_grams = Column(Integer, nullable=True)

    # Legacy pending-cap columns kept for backward compatibility (no longer written)
    pending_max_weight_grams = Column(Integer, nullable=True)
    has_pending_cap = Column(Integer, default=0, nullable=False)

    sort_order = Column(Integer, default=0)
    enabled = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AccountConfig(Base):
    """Singleton row: account balance, max usage %, single margin value
    used by the trade engine to block fires that would exceed the cap."""
    __tablename__ = "account_config"

    id = Column(Integer, primary_key=True)
    balance = Column(Float, default=0.0, nullable=False)            # ₹ total account
    max_usage_percent = Column(Float, default=80.0, nullable=False)
    margin_per_fire = Column(Float, default=0.0, nullable=False)    # ₹ deducted per fire
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ActivityLog(Base):
    """Audit trail of every meaningful action: ladder lifecycle, fires, exits,
    deletions, daily auto-clear, history purge."""
    __tablename__ = "activity_log"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    action = Column(String(48), nullable=False, index=True)
    pair_name = Column(String(64), nullable=True, index=True)
    side = Column(String(16), nullable=True)         # decrease | increase | None
    ladder_id = Column(Integer, nullable=True)
    actor = Column(String(16), default="user")       # user | system | auto
    summary = Column(String(255), nullable=True)     # human-readable line
    details = Column(Text, nullable=True)            # JSON blob with extra context


class Signal(Base):
    """A FROZEN, fire-once mean-reversion signal on a cross spread.

    Once written, entry/target/probability never change. Outcome is tracked:
    status moves open → hit (reached target) | expired (didn't, within max-hold).
    This builds a verifiable accuracy track record.
    """
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True)
    pair_name = Column(String(64), nullable=False, index=True)
    label = Column(String(64), nullable=True)         # e.g. "PETAL / GUINEA"
    expiry_label = Column(String(48), nullable=True)
    direction = Column(String(8), nullable=False)     # narrow | widen
    entry_spread = Column(Float, nullable=False)       # FROZEN at fire
    target_spread = Column(Float, nullable=False)      # FROZEN at fire (the mean)
    stop_spread = Column(Float, nullable=True)         # FROZEN at fire (1:1 disaster stop)
    probability = Column(Float, nullable=True)         # % chance to hit target (from history)
    z_at_entry = Column(Float, nullable=True)          # how stretched at fire (σ)
    expected_days = Column(Float, nullable=True)       # historical avg days to target
    fired_at = Column(DateTime, default=datetime.utcnow, index=True)
    status = Column(String(12), default="open", index=True)  # open | hit | expired
    exit_spread = Column(Float, nullable=True)         # spread when resolved
    resolved_at = Column(DateTime, nullable=True)
    days_held = Column(Float, nullable=True)           # calendar days open→resolve


class DeviceToken(Base):
    """A mobile device registered for push notifications (FCM).

    The app POSTs {token, device_id, platform} to /api/v1/devices/register.
    Identity is device_id (one row per device); `token` is the current FCM
    registration token. A blank token never overwrites a saved one.
    """
    __tablename__ = "device_tokens"

    id = Column(Integer, primary_key=True)
    device_id = Column(String(255), unique=True, index=True, nullable=False)
    token = Column(Text, nullable=False)
    platform = Column(String(16), default="android")  # android | ios
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class BullionStock(Base):
    """Daily MCXCCL warehouse 'Eligible Units' per bullion commodity.

    One row per (as_on_date, commodity), scraped from the 'Summary of Stock –
    Bullion Commodities' table (last page of the daily Warehouse & Vault PDF).
    `as_on_date` is the date printed in the PDF (it can lag the calendar date).
    Tiny table: ~7 rows whenever the published PDF changes.
    """
    __tablename__ = "bullion_stock"

    id = Column(Integer, primary_key=True)
    as_on_date = Column(String(10), nullable=False, index=True)   # 'YYYY-MM-DD' from the PDF
    commodity = Column(String(40), nullable=False, index=True)    # GOLD | GOLD MINI | SILVER ...
    unit = Column(String(8), nullable=True)                       # GM | KG
    eligible_units = Column(Float, nullable=False)
    fetched_at = Column(DateTime, default=datetime.utcnow)        # when we scraped it


class DailySpread(Base):
    """Once-a-day snapshot of each pair's spread, taken in-process from the live
    quote_store. There is no continuous spread history otherwise, so this is what
    the stock-vs-spread correlation is computed against. ~N pairs rows per day.
    """
    __tablename__ = "daily_spread"

    id = Column(Integer, primary_key=True)
    snap_date = Column(String(10), nullable=False, index=True)    # 'YYYY-MM-DD' IST
    pair_name = Column(String(64), nullable=False, index=True)
    decrease_spread = Column(Float, nullable=True)
    increase_spread = Column(Float, nullable=True)
    # Client's % logic: spread ÷ small/near-leg value × 100 (comparable across
    # price levels). Live snapshots store both; Dhan close-based backfill rows
    # store decrease_* only.
    decrease_pct = Column(Float, nullable=True)
    increase_pct = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Scrip(Base):
    """A product line in the new admin's Scrip Master (modern rebuild of the
    dealer's rate board). Each scrip tracks a live reference (a market feed OR
    another scrip) and adds a buy/sell parity → live Buy/Sell rate. Visible =
    show on the public board/app; allow_trade = customer can order it.
    """
    __tablename__ = "scrips"

    id = Column(Integer, primary_key=True)
    template = Column(String(40), nullable=False, default="gurukrupa", index=True)
    name = Column(String(80), nullable=False)
    code = Column(String(20), nullable=True)
    # reference: what this scrip's rate is based on
    ref_type = Column(String(10), nullable=False, default="feed")   # feed | scrip | manual
    ref_key = Column(String(40), nullable=True)                     # feed key OR referenced scrip id
    buy_parity = Column(Float, nullable=True, default=0.0)
    sell_parity = Column(Float, nullable=True, default=0.0)
    buy_manual = Column(Float, nullable=True)                       # optional hard override
    sell_manual = Column(Float, nullable=True)
    visible = Column(Boolean, nullable=False, default=True)
    allow_trade = Column(Boolean, nullable=False, default=False)
    position = Column(Integer, nullable=False, default=0, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class OptionsSnapshot(Base):
    """Four times a day (10:00, 15:00, 15:15 & 15:35 IST) snapshot of the full Nifty/Sensex PE
    options board — replaces the client's manual 10am/3pm screenshots. One row
    per (snap_date, slot); payload_json stores the raw 'below' + 'above' boards
    (square-off is derived from 'above' at read time). ~2 small rows per
    trading day, pruned after ~370 days.
    """
    __tablename__ = "options_snapshot"

    id = Column(Integer, primary_key=True)
    snap_date = Column(String(10), nullable=False, index=True)   # 'YYYY-MM-DD' IST
    slot = Column(String(5), nullable=False, index=True)         # '10:00' | '15:00'
    weekday = Column(Integer, nullable=False, index=True)        # 0=Mon .. 6=Sun (IST, set at write)
    nifty_spot = Column(Float, nullable=True)
    sensex_spot = Column(Float, nullable=True)
    india_vix = Column(Float, nullable=True)
    nifty_atm = Column(Integer, nullable=True)
    sensex_atm = Column(Integer, nullable=True)
    payload_json = Column(Text, nullable=False)                  # {"captured_at", "below": {...}, "above": {...}}
    created_at = Column(DateTime, default=datetime.utcnow)


class CrudeIvSnapshot(Base):
    """Half-hourly snapshot of the MCX-vs-US option comparison (client, 19-Aug).

    One row per (snap_date, slot, commodity, month): 30 slots from 09:00 to 23:30
    IST, two commodities, two expiry months, so 120 rows on a full trading day.

    `payload_json` is COMPACT, not the live board. The board serialises to 14.8
    KB and would come to 433 MB a year, against a standing "no DB load"
    constraint; every column the table actually shows - strike, bid, ask, IV,
    delta, and OI on the MCX side - packs into 3 KB and 89 MB, in line with the
    NSE-vs-MCX history already running at 65 MB. What is dropped is symbols,
    volumes and greeks nobody reads back.

    Written only when BOTH exchanges are live and quoting two-way. The client
    asked for "only while both markets are open"; US crude in fact trades nearly
    around the clock and its one daily break falls outside MCX hours, so the
    honest test is the data rather than a clock, and a thin hour simply stores
    nothing instead of storing something misleading.
    """
    __tablename__ = "crude_iv_snapshot"
    __table_args__ = (
        UniqueConstraint("snap_date", "slot", "commodity", "month",
                         name="uq_crude_iv_snap"),
    )

    id = Column(Integer, primary_key=True)
    snap_date = Column(String(10), nullable=False, index=True)   # 'YYYY-MM-DD' IST
    slot = Column(String(5), nullable=False, index=True)         # '09:00' .. '23:30'
    commodity = Column(String(10), nullable=False, index=True)   # 'crude' | 'natgas'
    month = Column(Integer, nullable=False, default=0)           # 0 front, 1 next
    weekday = Column(Integer, nullable=False, index=True)        # 0=Mon .. 6=Sun
    # Headline numbers, denormalised so a chart never has to open the payload.
    mcx_forward = Column(Float, nullable=True)
    mcx_future = Column(Float, nullable=True)
    us_future = Column(Float, nullable=True)
    usdinr = Column(Float, nullable=True)
    mcx_atm_iv = Column(Float, nullable=True)
    us_atm_iv = Column(Float, nullable=True)
    iv_diff = Column(Float, nullable=True)                       # MCX − US, points
    payload_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class PairLeg(Base):
    """Which contracts a calendar pair was made of - remembered PAST expiry.

    The live registry forgets a pair the moment its near leg expires, which
    made its history unreachable (client, 03-Sep: "expired contract not remove
    rate from history"). Dhan still serves candles for expired security ids,
    so keeping name -> legs here keeps every pair's close history viewable
    for as long as Dhan keeps the candles.
    """
    __tablename__ = "pair_legs"
    id = Column(Integer, primary_key=True)
    name = Column(String(64), unique=True, nullable=False)
    group_label = Column(String(32), nullable=True)
    big_security_id = Column(String(16), nullable=False)
    small_security_id = Column(String(16), nullable=False)
    big_symbol = Column(String(40), nullable=True)
    small_symbol = Column(String(40), nullable=True)
    last_seen = Column(DateTime, nullable=True)


class ElecHourly(Base):
    """Hourly NSE-vs-MCX electricity future prices - ONE difference per row
    (client's single-value rule). Recorded live at the top of each hour; it
    cannot be backfilled because Angel's historical API has no NCO segment."""
    __tablename__ = "elec_hourly"
    id = Column(Integer, primary_key=True)
    hour = Column(String(16), nullable=False, index=True)     # "2026-09-02 14:00"
    month = Column(Integer, nullable=False, default=0)        # 0 front, 1 next
    nse_close = Column(Float, nullable=True)
    mcx_close = Column(Float, nullable=True)
    diff = Column(Float, nullable=True)                       # MCX minus NSE
    pct = Column(Float, nullable=True)
    nse_symbol = Column(String(32), nullable=True)
    mcx_symbol = Column(String(40), nullable=True)


class NseMcxSnapshot(Base):
    """Thrice-daily (10:00, 12:00 & 15:00 IST) snapshot of the NSE-vs-MCX
    comparison board — the client asked to track how the same strike drifts
    apart through the day. One row per (snap_date, slot, commodity); the client
    chose the WHOLE table, so payload_json holds every strike with both
    exchanges' bid/ask and the difference, exactly as the live screen shows it.
    ~6 small rows per trading day (2 commodities × 3 slots), pruned after ~370
    days. NSE commodity has no historical API anywhere, so this file is the only
    record that will ever exist — it can only build forward from today.
    """
    __tablename__ = "nse_mcx_snapshot"

    id = Column(Integer, primary_key=True)
    snap_date = Column(String(10), nullable=False, index=True)   # 'YYYY-MM-DD' IST
    slot = Column(String(5), nullable=False, index=True)         # '10:00' | '12:00' | '15:00'
    commodity = Column(String(10), nullable=False, index=True)   # 'crude' | 'natgas'
    weekday = Column(Integer, nullable=False, index=True)        # 0=Mon .. 6=Sun (IST, set at write)
    nse_future = Column(Float, nullable=True)
    mcx_future = Column(Float, nullable=True)
    future_diff = Column(Float, nullable=True)                   # NSE − MCX, rupees
    atm = Column(Float, nullable=True)
    payload_json = Column(Text, nullable=False)                  # the full board, live shape
    created_at = Column(DateTime, default=datetime.utcnow)


class BullionPdf(Base):
    """The latest scraped 'Warehouse & Vault Wise Stock Position' PDF (~47 KB),
    kept so the dashboard can View/Download it from our own server (no Akamai or
    cross-origin issue at view-time). Only the most recent row is retained.
    """
    __tablename__ = "bullion_pdf"

    id = Column(Integer, primary_key=True)
    as_on_date = Column(String(10), nullable=False)
    filename = Column(String(160), nullable=True)
    source_url = Column(Text, nullable=True)
    content = Column(LargeBinary, nullable=False)
    fetched_at = Column(DateTime, default=datetime.utcnow)


# Composite UNIQUE indexes → make the daily ingest idempotent (a re-run for the
# same PDF date / same calendar day simply finds the rows already present).
Index("ix_bullion_date_comm", BullionStock.as_on_date, BullionStock.commodity, unique=True)
Index("ix_dailyspread_date_pair", DailySpread.snap_date, DailySpread.pair_name, unique=True)
Index("ix_optsnap_date_slot", OptionsSnapshot.snap_date, OptionsSnapshot.slot, unique=True)
Index("ix_nmsnap_date_slot_comm", NseMcxSnapshot.snap_date, NseMcxSnapshot.slot,
      NseMcxSnapshot.commodity, unique=True)
