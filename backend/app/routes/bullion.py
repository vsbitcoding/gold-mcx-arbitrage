"""MCXCCL bullion warehouse-stock feed + stock-vs-spread correlation (watch-only).

GET /api/bullion-stock         → latest 'Eligible Units', history, spread history,
                                 and per-pair stock↔spread correlation.
GET /api/bullion-stock/status  → last-run status of the daily scrape.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.security import get_current_user
from app.services import mcxccl_service

router = APIRouter(prefix="/api/bullion-stock", tags=["bullion"])


@router.get("")
def get_bullion(user: str = Depends(get_current_user)):
    return mcxccl_service.report()


@router.get("/status")
def get_status(user: str = Depends(get_current_user)):
    return mcxccl_service.status()


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
