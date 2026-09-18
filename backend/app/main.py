import asyncio
import threading
import logging
import uuid

from fastapi import HTTPException, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import Base, engine, run_simple_migrations
from app.routes import auth, users as users_route, bullion as bullion_route, crude_iv as crude_iv_route, iv_calculator as iv_calc_route, nse_mcx as nse_mcx_route, international as international_route, calculator, feed, gold_options as gold_options_route, metals as metals_route, options as options_route, othercomm as othercomm_route, pairs, paper as paper_route, premium as premium_route, price as price_route, public_v1, signals as signals_route, ws as ws_route
from app.services.broadcaster import broadcaster
from app.services.live_feed import start_feed_in_background
from app.services.ladder_migration import migrate_once as migrate_ladders
from app.services.maintenance import start_in_background as start_maintenance
from app.services.market_data import quote_store
from app.services.angel_feed import start_in_background as start_angel_feed
from app.services.crude_iv_service import start_in_background as start_crude_iv
from app.services.nse_mcx_paper import start_in_background as start_nse_mcx_paper
from app.routes import market_calendar as market_calendar_route
from app.routes import bank_options as bank_options_route
from app.services import market_calendar
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
app.include_router(users_route.router)
app.include_router(market_calendar_route.router)
app.include_router(bank_options_route.router)
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
app.include_router(international_route.router)
app.include_router(crude_iv_route.router)
app.include_router(nse_mcx_route.router)
app.include_router(iv_calc_route.router)
app.include_router(paper_route.router)


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


@app.middleware("http")
async def _api_wall(request, call_next):
    """Every /api call needs a valid session, except the few that are public
    by design (login, health, the key-authenticated /api/v1 client routes and
    the TradingView webhook). Review 18-Sep, finding 1: routes that carried no
    auth dependency of their own answered 200 to no token at all.

    The session is checked here once and handed to the route via
    request.state, so a route's own get_current_user does not decode twice.
    Page permissions (Manage Users) are enforced on the same pass.
    """
    path = request.url.path
    if path.startswith("/api") and not _is_public_api(path):
        from fastapi.responses import JSONResponse
        from app import security as sec
        auth = request.headers.get("authorization", "")
        # The Auto Trades reads also take the token as ?token= (plain-URL
        # access, 20-Aug); that envelope must meet the same wall.
        tok = auth[7:] if auth.lower().startswith("bearer ") else request.query_params.get("token", "")
        if not tok:
            return JSONResponse(status_code=401, content={"detail": "Not authenticated"},
                                headers={"WWW-Authenticate": "Bearer"})
        try:
            user = sec.authenticate(tok)
        except HTTPException as e:
            return JSONResponse(status_code=e.status_code, content={"detail": e.detail},
                                headers=e.headers or {})
        if not sec.may(user, path):
            perm = sec.perms_of(user)
            if not perm["active"]:
                return JSONResponse(status_code=401, content={"detail": "This login has been disabled."})
            return JSONResponse(status_code=403, content={
                "detail": "This login is not allowed on this page."})
        request.state.auth_token = tok
        request.state.auth_user = user
    return await call_next(request)


_PUBLIC_API_EXACT = ("/api/health", "/api/auth/login")
_PUBLIC_API_PREFIXES = ("/api/v1/",)          # API-key clients and the trade webhook check their own key


def _is_public_api(path: str) -> bool:
    return path in _PUBLIC_API_EXACT or any(path.startswith(p) for p in _PUBLIC_API_PREFIXES)


@app.on_event("startup")
async def startup() -> None:
    Base.metadata.create_all(bind=engine)
    run_simple_migrations()
    threading.Thread(target=market_calendar.ensure_loaded, daemon=True, name="market-calendar").start()
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
    start_nse_mcx_paper()
    start_angel_feed()


@app.get("/api/health")
def health():
    return {"status": "ok", "mode": settings.TRADING_MODE}
