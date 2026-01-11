"""State management module for Personal Automation Concierge.

This module provides SQLite-based state persistence for:
- Checkpoints (polling position tracking)
- Processed events (deduplication)
- Action history (per-rule idempotency)
- Audit log (decision trail)

Usage:
    from concierge.state import StateStore
    from concierge.paths import get_default_db_path

    store = StateStore(get_default_db_path())  # XDG data path
    checkpoint = store.get_checkpoint()
    store.mark_processed(event_id, disposition)
"""

from concierge.state.checkpoint import Checkpoint
from concierge.state.migrations import CURRENT_SCHEMA_VERSION, migrate_database
from concierge.state.store import StateStore

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "Checkpoint",
    "StateStore",
    "migrate_database",
]
