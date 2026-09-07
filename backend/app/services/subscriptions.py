"""Everything the live socket must carry, resolved fresh on every (re)connect.

One place for the list that dhan_feed used to assemble inline: the pair
registry, the calculator extras, Nifty/Sensex options, metals, other
commodities, gold option spreads, electricity, the NSE-vs-MCX MCX strikes,
the paper-trade symbols, and the price tab. Each service's own refresh() is
called here, in the same order the Dhan loop used, so a contract roll walks
through every screen at once.

Returns {security_id: meta}. `meta["exch"]` names the exchange segment the
token lives on (MCX / NSE / BSE / NFO / BFO) - filled from what each service
says about itself, else from the master - which is what a feed needs to
subscribe on the right channel.
"""
from __future__ import annotations

import logging

from app.services import pair_registry

log = logging.getLogger("subscriptions")


def build() -> tuple[dict[str, dict], int]:
    """(subs, pair_count). Raises when the pair registry resolves nothing."""
    n = pair_registry.refresh(min_days_ahead=1, max_per_instrument=6)
    try:
        from app.services.spread_close_history import record_pairs
        record_pairs()
    except Exception as e:  # noqa: BLE001
        log.warning("pair-leg record failed: %s", e)
    if n == 0:
        raise RuntimeError("Pair registry empty - no active MCX gold contracts resolved.")
    subs: dict[str, dict] = dict(pair_registry.get_subscriptions())

    from app.services import (elec_service, extra_instruments, goldopt_service, mcx_opt_stream,
                              metals_service, options_service, othercomm_service, paper_trades,
                              price_service)
    steps = [
        ("calculator extras", extra_instruments.refresh, extra_instruments.get_subscription_meta),
        ("index options", options_service.refresh, options_service.get_subscription_meta),
        ("metals", metals_service.refresh, metals_service.get_subscription_meta),
        ("other commodities", othercomm_service.refresh, othercomm_service.get_subscription_meta),
        ("gold options", goldopt_service.refresh, goldopt_service.get_subscription_meta),
        ("electricity", elec_service.refresh, elec_service.get_subscription_meta),
        ("mcx option stream", mcx_opt_stream.refresh, mcx_opt_stream.get_subscription_meta),
        ("paper symbols", paper_trades.refresh, paper_trades.get_subscription_meta),
    ]
    for name, refresh, meta_of in steps:
        try:
            refresh()
        except Exception as e:  # noqa: BLE001 - one screen's master trouble must not stop the rest
            log.warning("%s refresh failed: %s", name, e)
        try:
            for sid, m in meta_of().items():
                subs.setdefault(str(sid), m)
        except Exception as e:  # noqa: BLE001
            log.warning("%s subscription meta failed: %s", name, e)
    try:
        price_service.refresh()
    except Exception as e:  # noqa: BLE001
        log.warning("price_service.refresh() failed: %s", e)
    return subs, n


def exchange_of(sid: str, meta: dict) -> str:
    """Which exchange segment carries this token."""
    ex = meta.get("exch")
    if ex:
        return ex
    kind = meta.get("kind")
    if kind == "etf":
        return "NSE"
    if kind == "index":
        return "BSE" if meta.get("trading_symbol") == "SENSEX" else "NSE"
    if kind == "option_pe":
        return "NFO" if meta.get("underlying") == "NIFTY" else "BFO"
    try:
        from app.services import angel_master
        return angel_master.segment_of(sid) or "MCX"
    except Exception:  # noqa: BLE001
        return "MCX"
