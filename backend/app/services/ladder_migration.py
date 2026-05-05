"""One-time migration: copy each existing PairRule's single decrease/increase
rule into its own LadderRule row, so the new multi-ladder system has data.
Idempotent — only creates LadderRule rows that don't already exist."""
from __future__ import annotations

import logging

from app.database import SessionLocal
from app.models import LadderRule, PairRule

log = logging.getLogger("ladder_migration")


def migrate_once() -> int:
    """Returns number of LadderRule rows created."""
    db = SessionLocal()
    created = 0
    try:
        rules = db.query(PairRule).all()
        for r in rules:
            # Decrease side
            if r.decrease_entry is not None or r.decrease_exit is not None:
                exists = (
                    db.query(LadderRule)
                    .filter(
                        LadderRule.pair_name == r.pair_name,
                        LadderRule.side == "decrease",
                    )
                    .first()
                )
                if not exists:
                    db.add(LadderRule(
                        pair_name=r.pair_name,
                        side="decrease",
                        entry=r.decrease_entry,
                        exit=r.decrease_exit,
                        max_weight_grams=r.max_weight_grams,
                        sort_order=0,
                        enabled=True,
                    ))
                    created += 1
            # Increase side
            if r.increase_entry is not None or r.increase_exit is not None:
                exists = (
                    db.query(LadderRule)
                    .filter(
                        LadderRule.pair_name == r.pair_name,
                        LadderRule.side == "increase",
                    )
                    .first()
                )
                if not exists:
                    db.add(LadderRule(
                        pair_name=r.pair_name,
                        side="increase",
                        entry=r.increase_entry,
                        exit=r.increase_exit,
                        max_weight_grams=r.max_weight_grams,
                        sort_order=0,
                        enabled=True,
                    ))
                    created += 1
        db.commit()
        if created:
            log.info("Ladder migration: created %d LadderRule rows from PairRule", created)
        return created
    finally:
        db.close()
