import asyncio
import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import Base, engine, run_simple_migrations
from app.routes import auth, bullion as bullion_route, crude_iv as crude_iv_route, international as international_route, calculator, feed, gold_options as gold_options_route, metals as metals_route, options as options_route, othercomm as othercomm_route, pairs, premium as premium_route, price as price_route, public_v1, scrip_master as scrip_master_route, signals as signals_route, ws as ws_route
from app.services.broadcaster import broadcaster
from app.services.dhan_feed import start_feed_in_background
from app.services.ladder_migration import migrate_once as migrate_ladders
from app.services.maintenance import start_in_background as start_maintenance
from app.services.market_data import quote_store
from app.services.angel_feed import start_in_background as start_angel_feed
from app.services.crude_iv_service import start_in_background as start_crude_iv
from app.services.ibkr_feed import start_in_background as start_ibkr_feed
from app.services.premium_feed import start_in_background as start_premium_feed
from app.services.signal_service import start_in_background as start_signals

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(title="Gold MCX Arbitrage", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(pairs.router)
app.include_router(feed.router)
app.include_router(calculator.router)
app.include_router(options_route.router)
app.include_router(metals_route.router)
app.include_router(othercomm_route.router)
app.include_router(price_route.router)
app.include_router(premium_route.router)
app.include_router(signals_route.router)
app.include_router(ws_route.router)
app.include_router(public_v1.router)
app.include_router(bullion_route.router)
app.include_router(gold_options_route.router)
app.include_router(scrip_master_route.router)
app.include_router(international_route.router)
app.include_router(crude_iv_route.router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Catch-all so the client gets a clean JSON instead of HTML 500 page.
    Logs with a unique trace_id so we can grep it in journalctl."""
    trace_id = uuid.uuid4().hex[:12]
    logging.getLogger("api").exception("[%s] Unhandled error on %s %s", trace_id, request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "trace_id": trace_id,
        },
    )


@app.on_event("startup")
async def startup() -> None:
    Base.metadata.create_all(bind=engine)
    run_simple_migrations()
    migrate_ladders()
    restored = quote_store.restore_from_db()
    if restored:
        logging.getLogger("startup").info("Restored %d cached quotes from DB", restored)
    loop = asyncio.get_event_loop()
    broadcaster.bind_loop(loop)
    start_feed_in_background(loop)
    start_maintenance()
    start_signals()
    start_premium_feed()
    start_ibkr_feed()
    start_crude_iv()
    start_angel_feed()


@app.get("/api/health")
def health():
    return {"status": "ok", "mode": settings.TRADING_MODE}
