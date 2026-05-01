from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String, Boolean, Text

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
