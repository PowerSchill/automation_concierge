"""Shared pytest fixtures for concierge tests.

This module provides common fixtures for:
- Temporary config files
- Mock time (via freezegun)
- Test database instances
- Sample GitHub API responses
"""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import yaml

from concierge.state import StateStore

if TYPE_CHECKING:
    from collections.abc import Callable, Generator


# ============================================================================
# Time Fixtures
# ============================================================================


@pytest.fixture
def frozen_time() -> datetime:
    """Return a fixed datetime for deterministic tests.

    Use with freezegun's freeze_time decorator:

        @freeze_time("2026-01-10T15:30:00Z")
        def test_something(frozen_time):
            assert datetime.now(UTC) == frozen_time
    """
    return datetime(2026, 1, 10, 15, 30, 0, tzinfo=UTC)


# ============================================================================
# Configuration Fixtures
# ============================================================================


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for test files.

    Yields:
        Path to temporary directory (cleaned up after test)
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def minimal_config() -> dict[str, Any]:
    """Return a minimal valid configuration dictionary."""
    return {
        "version": 1,
        "rules": [],
    }


@pytest.fixture
def sample_config() -> dict[str, Any]:
    """Return a sample configuration with one rule."""
    return {
        "version": 1,
        "github": {
            "poll_interval": 60,
            "lookback_window": 3600,
        },
        "rules": [
            {
                "id": "mention-notify",
                "name": "Notify on mentions",
                "trigger": {
                    "event_type": "mention",
                },
                "action": {
                    "type": "console",
                    "message": "You were mentioned in {{ event.source }}",
                },
            }
        ],
    }


@pytest.fixture
def config_with_slack() -> dict[str, Any]:
    """Return a configuration with Slack action."""
    return {
        "version": 1,
        "actions": {
            "slack": {
                "webhook_url": "https://hooks.slack.com/services/T00/B00/xxxx",
            },
        },
        "rules": [
            {
                "id": "mention-slack",
                "name": "Slack on mentions",
                "trigger": {
                    "event_type": "mention",
                },
                "action": {
                    "type": "slack",
                    "message": "You were mentioned!",
                },
            }
        ],
    }


@pytest.fixture
def write_config(temp_dir: Path) -> Callable[[dict[str, Any], str], Path]:
    """Factory fixture to write config files.

    Args:
        config: Configuration dictionary
        filename: Name of the config file (default: config.yaml)

    Returns:
        Path to the written config file
    """

    def _write(config: dict[str, Any], filename: str = "config.yaml") -> Path:
        path = temp_dir / filename
        with path.open("w") as f:
            yaml.safe_dump(config, f)
        return path

    return _write


# ============================================================================
# Database Fixtures
# ============================================================================


@pytest.fixture
def test_db_path(temp_dir: Path) -> Path:
    """Return path for a test database file."""
    return temp_dir / "test_state.db"


@pytest.fixture
def state_store(test_db_path: Path) -> Generator[StateStore, None, None]:
    """Create a StateStore for testing.

    Yields:
        Initialized StateStore instance (closed after test)
    """
    store = StateStore(test_db_path)
    yield store
    store.close()


# ============================================================================
# GitHub API Response Fixtures
# ============================================================================


@pytest.fixture
def github_notification_response() -> dict[str, Any]:
    """Return a sample GitHub notification API response."""
    return {
        "id": "123456789",
        "unread": True,
        "reason": "mention",
        "updated_at": "2026-01-10T15:30:00Z",
        "last_read_at": None,
        "subject": {
            "title": "Bug: Something is broken",
            "url": "https://api.github.com/repos/octocat/hello-world/issues/42",
            "latest_comment_url": "https://api.github.com/repos/octocat/hello-world/issues/comments/987654",
            "type": "Issue",
        },
        "repository": {
            "id": 1296269,
            "name": "hello-world",
            "full_name": "octocat/hello-world",
            "owner": {
                "login": "octocat",
                "id": 1,
            },
            "html_url": "https://github.com/octocat/hello-world",
        },
        "url": "https://api.github.com/notifications/threads/123456789",
    }


@pytest.fixture
def github_rate_limit_response() -> dict[str, Any]:
    """Return a sample GitHub rate limit API response."""
    return {
        "resources": {
            "core": {
                "limit": 5000,
                "remaining": 4999,
                "reset": 1704899400,
                "used": 1,
            },
            "search": {
                "limit": 30,
                "remaining": 30,
                "reset": 1704895860,
                "used": 0,
            },
        },
        "rate": {
            "limit": 5000,
            "remaining": 4999,
            "reset": 1704899400,
            "used": 1,
        },
    }


@pytest.fixture
def github_issue_response() -> dict[str, Any]:
    """Return a sample GitHub issue API response."""
    return {
        "id": 1,
        "number": 42,
        "title": "Bug: Something is broken",
        "state": "open",
        "locked": False,
        "user": {
            "login": "reporter",
            "id": 2,
        },
        "labels": [
            {"name": "bug", "color": "d73a4a"},
            {"name": "priority:high", "color": "ff0000"},
        ],
        "created_at": "2026-01-09T10:00:00Z",
        "updated_at": "2026-01-10T15:30:00Z",
        "body": "Description of the bug...",
        "html_url": "https://github.com/octocat/hello-world/issues/42",
    }


@pytest.fixture
def github_pr_response() -> dict[str, Any]:
    """Return a sample GitHub pull request API response."""
    return {
        "id": 100,
        "number": 123,
        "title": "Add new feature",
        "state": "open",
        "draft": False,
        "user": {
            "login": "contributor",
            "id": 3,
        },
        "labels": [],
        "created_at": "2026-01-08T09:00:00Z",
        "updated_at": "2026-01-10T14:00:00Z",
        "body": "This PR adds...",
        "html_url": "https://github.com/octocat/hello-world/pull/123",
        "requested_reviewers": [
            {"login": "reviewer1", "id": 4},
        ],
        "merged": False,
        "mergeable": True,
    }


# ============================================================================
# Event Fixtures
# ============================================================================


@pytest.fixture
def sample_event() -> dict[str, Any]:
    """Return a sample normalized Event dictionary."""
    return {
        "id": "notif_123456789",
        "github_id": "123456789",
        "event_type": "mention",
        "timestamp": "2026-01-10T15:30:00Z",
        "source": {
            "owner": "octocat",
            "repo": "hello-world",
            "type": "issue",
            "number": 42,
        },
        "actor": "collaborator",
        "subject": "Bug: Something is broken",
        "url": "https://github.com/octocat/hello-world/issues/42",
        "payload": {},
        "received_at": "2026-01-10T15:31:00Z",
    }


# ============================================================================
# Fixture File Loading
# ============================================================================


@pytest.fixture
def fixtures_dir() -> Path:
    """Return path to the fixtures directory."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def load_fixture(fixtures_dir: Path) -> Callable[[str], dict[str, Any]]:
    """Factory fixture to load JSON fixture files.

    Args:
        filename: Name of the fixture file (with .json extension)

    Returns:
        Parsed JSON data
    """

    def _load(filename: str) -> dict[str, Any]:
        path = fixtures_dir / filename
        if not path.exists():
            pytest.skip(f"Fixture file not found: {path}")
        with path.open() as f:
            return json.load(f)

    return _load
