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


@router.get("/quotes")
def quotes(user: str = Depends(get_current_user)):
    """Return live LTP for the Calculator's reference instruments."""
    full_gold = extra_instruments.get_full_gold()

    return {
        "gold": {
            "etf": {
                "trading_symbol": extra_instruments.GOLDBEES_TRADING_SYMBOL,
                "security_id": extra_instruments.GOLDBEES_NSE_SECURITY_ID,
                **(_quote_dict(extra_instruments.GOLDBEES_NSE_SECURITY_ID) or {"ltp": None, "bid": None, "ask": None}),
            },
            "mcx_full": {
                "trading_symbol": full_gold["trading_symbol"] if full_gold else None,
                "security_id": full_gold["security_id"] if full_gold else None,
                "expiry": full_gold["expiry"].isoformat() if full_gold else None,
                **(_quote_dict(full_gold["security_id"] if full_gold else None) or {"ltp": None, "bid": None, "ask": None}),
            },
        },
        # Silver coming once the client shares the formula
        "silver": None,
    }
