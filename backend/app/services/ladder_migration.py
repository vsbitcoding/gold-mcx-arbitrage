"""Legacy migration helper. The old PairRule single-rule system is no longer
referenced by the runtime (replaced by ladder_rules + dynamic pair_registry).
Kept as a no-op to preserve backward compatibility with existing tables."""
from __future__ import annotations

import logging

log = logging.getLogger("ladder_migration")


def migrate_once() -> int:
    return 0
