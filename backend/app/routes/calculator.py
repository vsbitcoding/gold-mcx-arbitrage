"""Live quotes for the Calculator page (GOLDBEES ETF + Full Gold MCX).

Silver placeholder is included for future use once the client confirms its
multiplier / divisor / contract.
"""
from fastapi import APIRouter, Depends

from app.security import get_current_user
from app.services import extra_instruments
from app.services.market_data import quote_store

router = APIRouter(prefix="/api/calculator", tags=["calculator"])


def _quote_dict(security_id: str | None):
    if not security_id:
        return None
    q = quote_store.get(security_id)
    return {
        "ltp": q.ltp or None,
        "bid": q.bid or None,
        "ask": q.ask or None,
    }


def _build_metal(etf_symbol: str, etf_id: str, mcx_rec: dict | None) -> dict:
    return {
        "etf": {
            "trading_symbol": etf_symbol,
            "security_id": etf_id,
            **(_quote_dict(etf_id) or {"ltp": None, "bid": None, "ask": None}),
        },
        "mcx_full": {
            "trading_symbol": mcx_rec["trading_symbol"] if mcx_rec else None,
            "security_id": mcx_rec["security_id"] if mcx_rec else None,
            "expiry": mcx_rec["expiry"].isoformat() if mcx_rec else None,
            **(_quote_dict(mcx_rec["security_id"] if mcx_rec else None) or {"ltp": None, "bid": None, "ask": None}),
        },
    }


@router.get("/quotes")
def quotes(user: str = Depends(get_current_user)):
    """Return live LTP for the Calculator's reference instruments."""
    return {
        "gold": _build_metal(
            extra_instruments.GOLDBEES_TRADING_SYMBOL,
            extra_instruments.GOLDBEES_NSE_SECURITY_ID,
            extra_instruments.get_full_gold(),
        ),
        "silver": _build_metal(
            extra_instruments.SILVERBEES_TRADING_SYMBOL,
            extra_instruments.SILVERBEES_NSE_SECURITY_ID,
            extra_instruments.get_full_silver(),
        ),
    }
