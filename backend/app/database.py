import logging

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

log = logging.getLogger("database")

is_sqlite = settings.DATABASE_URL.startswith("sqlite")
connect_args = {"check_same_thread": False} if is_sqlite else {}
engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# SQLite tuning: WAL + memory caching for concurrent reads while writes happen
if is_sqlite:
    @event.listens_for(engine, "connect")
    def _sqlite_pragma(conn, _):
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA cache_size=-20000")  # 20 MB page cache
        cur.execute("PRAGMA temp_store=MEMORY")
        cur.close()


# Lightweight auto-migration: add missing columns when models grow.
# Avoids a full Alembic dependency for this small project.
_REQUIRED_COLUMNS = {
    "pair_rules": [
        ("max_weight_grams", "INTEGER"),
        ("pending_max_weight_grams", "INTEGER"),
        ("has_pending_cap", "INTEGER DEFAULT 0"),
    ],
    "trade_history": [
        ("big_entry_price", "FLOAT"),
        ("small_entry_price", "FLOAT"),
        ("big_exit_price", "FLOAT"),
        ("small_exit_price", "FLOAT"),
        ("weight_grams", "INTEGER"),
    ],
}


def run_simple_migrations() -> None:
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, cols in _REQUIRED_COLUMNS.items():
            if not insp.has_table(table):
                continue
            existing = {c["name"] for c in insp.get_columns(table)}
            for name, sql_type in cols:
                if name not in existing:
                    log.warning("Auto-migrate: ALTER TABLE %s ADD COLUMN %s %s", table, name, sql_type)
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
