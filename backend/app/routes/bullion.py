"""MCXCCL bullion warehouse-stock feed + stock-vs-spread correlation (watch-only).

GET /api/bullion-stock         → latest 'Eligible Units', history, spread history,
                                 and per-pair stock↔spread correlation.
GET /api/bullion-stock/status  → last-run status of the daily scrape.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.security import get_current_user
from app.services import mcxccl_service, spread_backfill

router = APIRouter(prefix="/api/bullion-stock", tags=["bullion"])


@router.get("")
def get_bullion(user: str = Depends(get_current_user)):
    return mcxccl_service.report()


@router.get("/status")
def get_status(user: str = Depends(get_current_user)):
    return mcxccl_service.status()


@router.post("/refresh")
def force_refresh(user: str = Depends(get_current_user)):
    """Trigger the scrape + spread snapshot now (on-demand / for testing).
    Serialised by an internal lock so it can't overlap the daily job."""
    ok = mcxccl_service.refresh()
    return {"ok": ok, "status": mcxccl_service.status()}


@router.post("/backfill-spread")
def backfill_spread(days: int = Query(185, ge=7, le=400), user: str = Depends(get_current_user)):
    """One-time: rebuild ~6 months of daily %-spread history from Dhan closes
    (runs in a background thread using the live feed token; idempotent)."""
    started = spread_backfill.start(days)
    return {"started": started, "status": spread_backfill.status()}


@router.get("/backfill-spread")
def backfill_spread_status(user: str = Depends(get_current_user)):
    return spread_backfill.status()


@router.get("/pdf")
def get_pdf(download: bool = Query(False), user: str = Depends(get_current_user)):
    """Serve the stored MCXCCL stock PDF from our own server (inline = view,
    download=1 = save). Tiny file, served on demand only."""
    pdf = mcxccl_service.get_latest_pdf()
    if not pdf:
        raise HTTPException(status_code=404, detail="No bullion PDF available yet")
    content, name, _src = pdf
    disposition = "attachment" if download else "inline"
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disposition}; filename="{name}"'},
    )
