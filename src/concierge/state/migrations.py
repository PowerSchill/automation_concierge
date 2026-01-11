"""Schema migrations framework for SQLite state store.

This module handles database schema versioning and migrations:
- Tracks current schema version
- Applies migrations in order
- Supports fresh database initialization

Migrations are applied incrementally from the current version to the target.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable

    MigrationFunc = Callable[[sqlite3.Connection], None]

logger = logging.getLogger(__name__)

# Current schema version - increment when adding migrations
CURRENT_SCHEMA_VERSION = 1


def _migration_v1(conn: sqlite3.Connection) -> None:
    """Initial schema: v0 -> v1.

    Creates all tables for the first version:
    - schema_version: Migration tracking
    - checkpoints: Polling position
    - processed_events: Deduplication
    - action_history: Per-rule idempotency
    - audit_log: Decision trail
    """
    cursor = conn.cursor()

    # Schema version table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    # Checkpoints table - tracks polling position
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS checkpoints (
            id TEXT PRIMARY KEY DEFAULT 'main',
            last_event_timestamp TEXT,
            last_poll_timestamp TEXT,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    # Processed events table - deduplication
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS processed_events (
            event_id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            disposition TEXT NOT NULL,
            processed_at TEXT NOT NULL DEFAULT (datetime('now')),
            ttl_expires_at TEXT NOT NULL
        )
    """)

    # Index for cleanup queries by timestamp
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_processed_events_timestamp
        ON processed_events(processed_at)
    """)

    # Index for TTL expiration cleanup
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_processed_events_ttl
        ON processed_events(ttl_expires_at)
    """)

    # Action history table - per-rule idempotency
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS action_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL,
            rule_id TEXT NOT NULL,
            action_type TEXT NOT NULL,
            result TEXT NOT NULL,
            message TEXT,
            executed_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(event_id, rule_id)
        )
    """)

    # Index for lookup by event
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_action_history_event
        ON action_history(event_id)
    """)

    # Audit log table - full decision trail
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL DEFAULT (datetime('now')),
            event_id TEXT,
            event_type TEXT,
            event_source TEXT,
            rules_evaluated TEXT,
            actions_taken TEXT,
            disposition TEXT NOT NULL,
            message TEXT NOT NULL
        )
    """)

    # Index for time-range queries on audit log
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp
        ON audit_log(timestamp)
    """)

    # Record the migration
    cursor.execute(
        "INSERT OR REPLACE INTO schema_version (version, applied_at) VALUES (?, datetime('now'))",
        (1,),
    )

    conn.commit()
    logger.info("Applied migration v1: initial schema")


# Registry of migrations keyed by target version
MIGRATIONS: dict[int, MigrationFunc] = {
    1: _migration_v1,
}


def get_schema_version(conn: sqlite3.Connection) -> int:
    """Get the current schema version from the database.

    Args:
        conn: SQLite database connection

    Returns:
        Current schema version, or 0 if not initialized
    """
    cursor = conn.cursor()

    # Check if schema_version table exists
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='schema_version'
    """)

    if cursor.fetchone() is None:
        return 0

    # Get highest version
    cursor.execute("SELECT MAX(version) FROM schema_version")
    row = cursor.fetchone()
    return row[0] if row[0] is not None else 0


def migrate_database(
    conn: sqlite3.Connection,
    target_version: int | None = None,
) -> int:
    """Apply all pending migrations to reach the target version.

    Args:
        conn: SQLite database connection
        target_version: Version to migrate to (default: CURRENT_SCHEMA_VERSION)

    Returns:
        The final schema version after migrations

    Raises:
        ValueError: If target_version is invalid or a migration fails
    """
    if target_version is None:
        target_version = CURRENT_SCHEMA_VERSION

    if target_version < 0 or target_version > CURRENT_SCHEMA_VERSION:
        msg = f"Invalid target version: {target_version} (current max: {CURRENT_SCHEMA_VERSION})"
        raise ValueError(msg)

    current_version = get_schema_version(conn)

    if current_version >= target_version:
        logger.debug(
            "Database already at version %d (target: %d)",
            current_version,
            target_version,
        )
        return current_version

    logger.info(
        "Migrating database from v%d to v%d",
        current_version,
        target_version,
    )

    # Apply migrations in order
    for version in range(current_version + 1, target_version + 1):
        migration = MIGRATIONS.get(version)
        if migration is None:
            msg = f"No migration found for version {version}"
            raise ValueError(msg)

        logger.debug("Applying migration to v%d", version)
        migration(conn)

    return target_version
