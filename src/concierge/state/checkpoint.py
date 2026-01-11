"""Checkpoint model and operations for polling position tracking.

A checkpoint tracks the system's position in the event stream,
enabling resumable polling and preventing duplicate event processing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from concierge.state.store import StateStore

logger = logging.getLogger(__name__)


@dataclass
class Checkpoint:
    """Tracks the system's position in the event stream.

    Attributes:
        id: Checkpoint identifier (default: 'main', supports future multi-stream)
        last_event_timestamp: UTC timestamp of last processed event
        last_poll_timestamp: UTC timestamp of last poll
        updated_at: UTC timestamp when checkpoint was saved

    Invariants:
        - last_event_timestamp is monotonically increasing
        - last_poll_timestamp >= last_event_timestamp
    """

    id: str = "main"
    last_event_timestamp: datetime | None = None
    last_poll_timestamp: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_row(cls, row: tuple[str, str | None, str | None, str | None]) -> Checkpoint:
        """Create a Checkpoint from a database row.

        Args:
            row: Tuple of (id, last_event_timestamp, last_poll_timestamp, updated_at)

        Returns:
            Checkpoint instance
        """
        checkpoint_id, event_ts, poll_ts, updated_ts = row

        return cls(
            id=checkpoint_id,
            last_event_timestamp=_parse_timestamp(event_ts),
            last_poll_timestamp=_parse_timestamp(poll_ts),
            updated_at=_parse_timestamp(updated_ts),
        )

    def update(
        self,
        event_timestamp: datetime | None = None,
        poll_timestamp: datetime | None = None,
    ) -> Checkpoint:
        """Create a new checkpoint with updated timestamps.

        Enforces the invariant that event_timestamp is monotonically increasing.

        Args:
            event_timestamp: New last event timestamp (if later than current)
            poll_timestamp: New last poll timestamp

        Returns:
            New Checkpoint with updated values
        """
        new_event_ts = self.last_event_timestamp
        if event_timestamp is not None and (
            new_event_ts is None or event_timestamp > new_event_ts
        ):
            new_event_ts = event_timestamp

        new_poll_ts = poll_timestamp or self.last_poll_timestamp

        return Checkpoint(
            id=self.id,
            last_event_timestamp=new_event_ts,
            last_poll_timestamp=new_poll_ts,
            updated_at=datetime.now(UTC),
        )

    def is_empty(self) -> bool:
        """Check if this is an empty/new checkpoint.

        Returns:
            True if no events or polls have been recorded.
        """
        return (
            self.last_event_timestamp is None
            and self.last_poll_timestamp is None
        )


def _parse_timestamp(value: str | None) -> datetime | None:
    """Parse an ISO format timestamp string to datetime.

    Args:
        value: ISO format timestamp string or None

    Returns:
        datetime in UTC or None
    """
    if value is None:
        return None

    # Handle SQLite datetime format (no timezone)
    if "T" in value:
        # ISO format with T separator
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        # SQLite default format: "YYYY-MM-DD HH:MM:SS"
        dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")

    # Ensure UTC timezone
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)

    return dt


def format_timestamp(dt: datetime | None) -> str | None:
    """Format a datetime to ISO string for storage.

    Args:
        dt: datetime to format (should be UTC)

    Returns:
        ISO format string or None
    """
    if dt is None:
        return None
    return dt.isoformat()


def save_checkpoint_atomic(store: StateStore, checkpoint: Checkpoint) -> None:
    """Save checkpoint atomically after successful poll cycle.

    This function ensures that the checkpoint is saved atomically,
    preventing partial writes that could corrupt state.

    The atomic save is implemented via SQLite's transaction mechanism
    in the StateStore.save_checkpoint method, which uses BEGIN/COMMIT.

    Args:
        store: StateStore instance to save checkpoint to.
        checkpoint: Checkpoint to save.
    """
    # Update the timestamp before saving
    checkpoint_to_save = Checkpoint(
        id=checkpoint.id,
        last_event_timestamp=checkpoint.last_event_timestamp,
        last_poll_timestamp=checkpoint.last_poll_timestamp,
        updated_at=datetime.now(UTC),
    )

    # The StateStore.save_checkpoint already uses transactions for atomicity
    store.save_checkpoint(checkpoint_to_save)
    logger.debug(
        "Atomically saved checkpoint: id=%s, last_event=%s, last_poll=%s",
        checkpoint_to_save.id,
        checkpoint_to_save.last_event_timestamp,
        checkpoint_to_save.last_poll_timestamp,
    )
