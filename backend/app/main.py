import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import Base, engine
from app.routes import auth, control, feed, history, pairs, positions, ws as ws_route
from app.services.broadcaster import broadcaster
from app.services.dhan_feed import start_feed_in_background
from app.services.maintenance import start_in_background as start_maintenance

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
app.include_router(positions.router)
app.include_router(history.router)
app.include_router(control.router)
app.include_router(feed.router)
app.include_router(ws_route.router)


@app.on_event("startup")
async def startup() -> None:
    Base.metadata.create_all(bind=engine)
    loop = asyncio.get_event_loop()
    broadcaster.bind_loop(loop)
    start_feed_in_background(loop)
    start_maintenance()


@app.get("/api/health")
def health():
    return {"status": "ok", "mode": settings.TRADING_MODE}
