"""SQLite state store for persistence.

This module provides the main StateStore class that handles:
- Database initialization with schema migrations
- Checkpoint save/load operations
- Processed event tracking (deduplication)
- Action history (per-rule idempotency)
- Audit log entries
- File permissions (chmod 600) on database creation
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from concierge.state.checkpoint import Checkpoint, format_timestamp
from concierge.state.migrations import migrate_database

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)


class Disposition(str, Enum):
    """Final disposition of an event after processing."""

    ACTION_EXECUTED = "action_executed"
    NO_MATCH = "no_match"
    DRY_RUN = "dry_run"
    ERROR = "error"
    SKIPPED = "skipped"


class ResultStatus(str, Enum):
    """Result status of an action execution."""

    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    PENDING = "pending"


class StateStore:
    """SQLite-based state persistence.

    Handles all state operations including:
    - Checkpoints for polling position
    - Processed events for deduplication
    - Action history for per-rule idempotency
    - Audit log for decision trail

    The database file is created with chmod 600 for security.

    Args:
        db_path: Path to the SQLite database file
        retention_days: How long to keep processed events (default: 30)

    Example:
        >>> from concierge.paths import get_default_db_path
        >>> store = StateStore(get_default_db_path())
        >>> checkpoint = store.get_checkpoint()
        >>> store.mark_processed("event_123", Disposition.ACTION_EXECUTED)
    """

    def __init__(
        self,
        db_path: str | Path,
        retention_days: int = 30,
    ) -> None:
        """Initialize the state store.

        Args:
            db_path: Path to the SQLite database file
            retention_days: Days to retain processed events (default: 30)
        """
        self.db_path = Path(db_path).expanduser().resolve()
        self.retention_days = retention_days
        self._conn: sqlite3.Connection | None = None

        self._ensure_database()

    def _ensure_database(self) -> None:
        """Ensure database exists and is initialized.

        Creates the database directory if needed, sets proper permissions,
        and runs migrations.
        """
        # Create directory if needed
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Check if this is a new database
        is_new = not self.db_path.exists()

        # Connect and migrate
        conn = self._get_connection()
        migrate_database(conn)

        # Set permissions on new database (chmod 600)
        if is_new and self.db_path.exists():
            try:
                os.chmod(self.db_path, 0o600)  # noqa: PTH101
                logger.debug("Set database permissions to 600: %s", self.db_path)
            except OSError as e:
                logger.warning("Could not set database permissions: %s", e)

    def _get_connection(self) -> sqlite3.Connection:
        """Get or create the database connection.

        Returns:
            SQLite connection with row factory set
        """
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            # Enable WAL mode for better concurrency
            self._conn.execute("PRAGMA journal_mode=WAL")
            # Enable foreign keys
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Context manager for transactional operations.

        Yields:
            The database connection

        Raises:
            Exception: Re-raises any exception after rollback
        """
        conn = self._get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # -------------------------------------------------------------------------
    # Checkpoint Operations
    # -------------------------------------------------------------------------

    def get_checkpoint(self, checkpoint_id: str = "main") -> Checkpoint:
        """Load checkpoint from the database.

        Args:
            checkpoint_id: Checkpoint identifier (default: 'main')

        Returns:
            Checkpoint instance (empty if not found)
        """
        conn = self._get_connection()
        cursor = conn.execute(
            """
            SELECT id, last_event_timestamp, last_poll_timestamp, updated_at
            FROM checkpoints
            WHERE id = ?
            """,
            (checkpoint_id,),
        )
        row = cursor.fetchone()

        if row is None:
            return Checkpoint(id=checkpoint_id)

        return Checkpoint.from_row((
            row["id"],
            row["last_event_timestamp"],
            row["last_poll_timestamp"],
            row["updated_at"],
        ))

    def save_checkpoint(self, checkpoint: Checkpoint) -> None:
        """Save checkpoint to the database atomically.

        Args:
            checkpoint: Checkpoint to save
        """
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO checkpoints
                (id, last_event_timestamp, last_poll_timestamp, updated_at)
                VALUES (?, ?, ?, datetime('now'))
                """,
                (
                    checkpoint.id,
                    format_timestamp(checkpoint.last_event_timestamp),
                    format_timestamp(checkpoint.last_poll_timestamp),
                ),
            )
        logger.debug("Saved checkpoint: %s", checkpoint.id)

    # -------------------------------------------------------------------------
    # Processed Events Operations
    # -------------------------------------------------------------------------

    def is_processed(self, event_id: str) -> bool:
        """Check if an event has already been processed.

        Args:
            event_id: Unique event identifier

        Returns:
            True if event was already processed
        """
        conn = self._get_connection()
        cursor = conn.execute(
            "SELECT 1 FROM processed_events WHERE event_id = ?",
            (event_id,),
        )
        return cursor.fetchone() is not None

    def mark_processed(
        self,
        event_id: str,
        event_type: str,
        disposition: Disposition,
    ) -> None:
        """Mark an event as processed.

        Args:
            event_id: Unique event identifier
            event_type: Type of the event (e.g., 'mention')
            disposition: Final disposition of the event
        """
        ttl_expires = datetime.now(UTC) + timedelta(days=self.retention_days)

        with self.transaction() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO processed_events
                (event_id, event_type, disposition, processed_at, ttl_expires_at)
                VALUES (?, ?, ?, datetime('now'), ?)
                """,
                (event_id, event_type, disposition.value, ttl_expires.isoformat()),
            )
        logger.debug("Marked event processed: %s (%s)", event_id, disposition.value)

    def get_processed_count(self) -> int:
        """Get count of processed events.

        Returns:
            Number of processed events in the database
        """
        conn = self._get_connection()
        cursor = conn.execute("SELECT COUNT(*) FROM processed_events")
        row = cursor.fetchone()
        return row[0] if row else 0

    def cleanup_expired(self) -> int:
        """Remove expired processed events.

        Returns:
            Number of events removed
        """
        with self.transaction() as conn:
            cursor = conn.execute(
                """
                DELETE FROM processed_events
                WHERE ttl_expires_at < datetime('now')
                """,
            )
            count = cursor.rowcount
        if count > 0:
            logger.info("Cleaned up %d expired processed events", count)
        return count

    # -------------------------------------------------------------------------
    # Action History Operations
    # -------------------------------------------------------------------------

    def has_action_executed(self, event_id: str, rule_id: str) -> bool:
        """Check if an action was already executed for an event+rule pair.

        This provides per-rule idempotency: the same rule won't fire twice
        for the same event.

        Args:
            event_id: Unique event identifier
            rule_id: Rule identifier

        Returns:
            True if action was already executed
        """
        conn = self._get_connection()
        cursor = conn.execute(
            """
            SELECT 1 FROM action_history
            WHERE event_id = ? AND rule_id = ?
            """,
            (event_id, rule_id),
        )
        return cursor.fetchone() is not None

    def record_action(
        self,
        event_id: str,
        rule_id: str,
        action_type: str,
        result: ResultStatus,
        message: str | None = None,
    ) -> None:
        """Record an action execution for an event+rule pair.

        Args:
            event_id: Unique event identifier
            rule_id: Rule identifier
            action_type: Type of action (e.g., 'slack')
            result: Result status of the action
            message: Optional message that was sent
        """
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO action_history
                (event_id, rule_id, action_type, result, message, executed_at)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
                """,
                (event_id, rule_id, action_type, result.value, message),
            )
        logger.debug(
            "Recorded action: event=%s rule=%s result=%s",
            event_id,
            rule_id,
            result.value,
        )

    # -------------------------------------------------------------------------
    # Audit Log Operations
    # -------------------------------------------------------------------------

    def write_audit_entry(
        self,
        disposition: Disposition,
        message: str,
        event_id: str | None = None,
        event_type: str | None = None,
        event_source: str | None = None,
        rules_evaluated: list[dict[str, Any]] | None = None,
        actions_taken: list[dict[str, Any]] | None = None,
    ) -> int:
        """Write an audit log entry.

        Args:
            disposition: Final disposition of the event
            message: Human-readable summary
            event_id: Optional event identifier
            event_type: Optional event type
            event_source: Optional event source (e.g., 'owner/repo#123')
            rules_evaluated: Optional list of rule evaluation results
            actions_taken: Optional list of action summaries

        Returns:
            ID of the inserted audit log entry
        """
        with self.transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO audit_log
                (timestamp, event_id, event_type, event_source,
                 rules_evaluated, actions_taken, disposition, message)
                VALUES (datetime('now'), ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    event_type,
                    event_source,
                    json.dumps(rules_evaluated) if rules_evaluated else None,
                    json.dumps(actions_taken) if actions_taken else None,
                    disposition.value,
                    message,
                ),
            )
            return cursor.lastrowid or 0

    def query_audit_log(
        self,
        since: datetime | None = None,
        rule_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Query the audit log with optional filters.

        Args:
            since: Only return entries after this timestamp
            rule_id: Only return entries involving this rule
            limit: Maximum number of entries to return

        Returns:
            List of audit log entries as dictionaries
        """
        conn = self._get_connection()

        query = "SELECT * FROM audit_log WHERE 1=1"
        params: list[Any] = []

        if since is not None:
            query += " AND timestamp >= ?"
            params.append(since.isoformat())

        if rule_id is not None:
            # Search in JSON for rule_id
            query += " AND rules_evaluated LIKE ?"
            params.append(f'%"rule_id": "{rule_id}"%')

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        cursor = conn.execute(query, params)
        rows = cursor.fetchall()

        results = []
        for row in rows:
            entry = dict(row)
            # Parse JSON fields
            if entry.get("rules_evaluated"):
                entry["rules_evaluated"] = json.loads(entry["rules_evaluated"])
            if entry.get("actions_taken"):
                entry["actions_taken"] = json.loads(entry["actions_taken"])
            results.append(entry)

        return results

    def get_audit_count(self) -> int:
        """Get count of audit log entries.

        Returns:
            Number of audit log entries
        """
        conn = self._get_connection()
        cursor = conn.execute("SELECT COUNT(*) FROM audit_log")
        row = cursor.fetchone()
        return row[0] if row else 0

    # -------------------------------------------------------------------------
    # Time-Based Threshold Operations (T076)
    # -------------------------------------------------------------------------

    def has_threshold_fired(
        self,
        entity_id: str,
        rule_id: str,
        threshold: str,
    ) -> bool:
        """Check if a threshold has already fired for an entity+rule pair.

        This provides time-based deduplication: once a threshold (e.g., "48h")
        is crossed for an entity, we don't re-trigger until conditions change.

        The dedupe key format is: "{entity_id}:{rule_id}:{threshold}"

        Args:
            entity_id: Entity identifier (e.g., "owner/repo#123")
            rule_id: Rule identifier
            threshold: Threshold string (e.g., "48h", "7d")

        Returns:
            True if threshold was already fired
        """
        dedupe_key = self._make_threshold_key(entity_id, rule_id, threshold)
        conn = self._get_connection()
        cursor = conn.execute(
            """
            SELECT 1 FROM action_history
            WHERE event_id = ? AND rule_id = ?
            """,
            (dedupe_key, rule_id),
        )
        return cursor.fetchone() is not None

    def record_threshold_fired(
        self,
        entity_id: str,
        rule_id: str,
        threshold: str,
        action_type: str,
        result: ResultStatus,
        message: str | None = None,
    ) -> None:
        """Record that a threshold has been crossed and action taken.

        Once recorded, has_threshold_fired() will return True for this
        entity+rule+threshold combination.

        Args:
            entity_id: Entity identifier (e.g., "owner/repo#123")
            rule_id: Rule identifier
            threshold: Threshold string (e.g., "48h")
            action_type: Type of action executed
            result: Result status of the action
            message: Optional action message
        """
        dedupe_key = self._make_threshold_key(entity_id, rule_id, threshold)
        self.record_action(
            event_id=dedupe_key,
            rule_id=rule_id,
            action_type=action_type,
            result=result,
            message=message,
        )
        logger.debug(
            "Recorded threshold fired: entity=%s rule=%s threshold=%s",
            entity_id,
            rule_id,
            threshold,
        )

    def clear_threshold_fired(
        self,
        entity_id: str,
        rule_id: str,
        threshold: str,
    ) -> bool:
        """Clear a threshold record, allowing it to fire again.

        Call this when conditions change (e.g., PR was reviewed after
        the "no review in 48h" rule fired, and now it's been 48h since
        that review with no new reviews).

        Args:
            entity_id: Entity identifier
            rule_id: Rule identifier
            threshold: Threshold string

        Returns:
            True if a record was deleted, False if none existed
        """
        dedupe_key = self._make_threshold_key(entity_id, rule_id, threshold)
        with self.transaction() as conn:
            cursor = conn.execute(
                """
                DELETE FROM action_history
                WHERE event_id = ? AND rule_id = ?
                """,
                (dedupe_key, rule_id),
            )
            deleted = cursor.rowcount > 0
        if deleted:
            logger.debug(
                "Cleared threshold record: entity=%s rule=%s threshold=%s",
                entity_id,
                rule_id,
                threshold,
            )
        return deleted

    @staticmethod
    def _make_threshold_key(entity_id: str, rule_id: str, threshold: str) -> str:
        """Create a unique key for threshold deduplication.

        The key format is designed to be unique across:
        - Different entities (same rule, same threshold)
        - Same entity, different rules
        - Same entity, same rule, different thresholds

        Args:
            entity_id: Entity identifier
            rule_id: Rule identifier
            threshold: Threshold string

        Returns:
            Unique dedupe key string
        """
        return f"threshold:{entity_id}:{rule_id}:{threshold}"
