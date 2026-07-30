"""International market screen — one read of two in-memory feeds, zero DB.

Combines what the dashboard already streams:
  IBKR   : XAU/XAG spot, COMEX gold/silver futures, NYMEX crude future +
           CL option chain, Brent future  (the client's 6 international items)
  TwelveData: USD/INR (the only item IBKR cannot supply on an LLC account)
  Dhan   : MCX gold/silver (for side-by-side comparison)

Everything here is a dict lookup — no database, no upstream call per request.
"""
from fastapi import APIRouter

from app.services import ibkr_feed, premium_feed

router = APIRouter(prefix="/api", tags=["international"])


@router.get("/international")
def international():
    ib = ibkr_feed.get_data()
    pf = premium_feed.get_inputs()
    return {
        "ibkr": ib,
        "spot": {
            "gold": {"price": pf.get("xauusd"), "age": pf.get("xauusd_age"),
                     "source": pf.get("xauusd_source")},
            "silver": {"price": pf.get("xagusd"), "age": pf.get("xagusd_age"),
                       "source": pf.get("xagusd_source")},
            "wti": {"price": pf.get("wti"), "age": pf.get("wti_age"), "source": "IBKR CL"},
            "brent": {"price": pf.get("brent"), "age": pf.get("brent_age"), "source": "IBKR BZ"},
            "usdinr": {"price": pf.get("usdinr"), "age": pf.get("usdinr_age"),
                       "source": pf.get("usdinr_source")},
        },
        "mcx": {"gold": pf.get("mcx_gold"), "silver": pf.get("mcx_silver")},
        "server_time": ib.get("server_time"),
    }
