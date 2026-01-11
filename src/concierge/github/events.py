"""GitHub event models and notification normalization."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EventType(str, Enum):
    """Types of GitHub events that can trigger rules."""

    # Notification events
    MENTION = "mention"
    ASSIGN = "assign"
    REVIEW_REQUESTED = "review_requested"
    SUBSCRIBED = "subscribed"
    COMMENT = "comment"
    STATE_CHANGE = "state_change"

    # Pull request specific
    CI_STATUS = "ci_status"
    SECURITY_ALERT = "security_alert"

    TIME_BASED = "time_based"  # Synthetic time-based event

    # Generic
    GENERIC = "generic"

    @classmethod
    def from_notification_reason(cls, reason: str) -> EventType:
        """Map GitHub notification reason to EventType.

        Args:
            reason: GitHub notification reason string.

        Returns:
            Corresponding EventType.
        """
        mapping = {
            "mention": cls.MENTION,
            "team_mention": cls.MENTION,
            "assign": cls.ASSIGN,
            "review_requested": cls.REVIEW_REQUESTED,
            "subscribed": cls.SUBSCRIBED,
            "comment": cls.COMMENT,
            "state_change": cls.STATE_CHANGE,
            "ci_activity": cls.CI_STATUS,
            "security_alert": cls.SECURITY_ALERT,
        }
        return mapping.get(reason, cls.GENERIC)


class EventSource(str, Enum):
    """Source of the GitHub event."""

    NOTIFICATION = "notification"
    WEBHOOK = "webhook"
    POLL = "poll"


class Event(BaseModel):
    """Normalized GitHub event for rule evaluation.

    This model represents a unified event format that can be evaluated
    against rules, regardless of the original source (notification, webhook, etc).
    """

    model_config = ConfigDict(frozen=True)

    # Unique event identifier
    id: str = Field(..., description="Unique event ID (e.g., notif_123456)")

    # Event classification
    event_type: EventType = Field(..., description="Type of event")
    source: EventSource = Field(
        default=EventSource.NOTIFICATION,
        description="How this event was received",
    )

    # Timestamps
    timestamp: datetime = Field(..., description="When the event occurred")
    received_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When we received the event",
    )

    # Repository context
    repo_owner: str = Field(..., description="Repository owner")
    repo_name: str = Field(..., description="Repository name")
    repo_full_name: str = Field(..., description="Full repository name (owner/repo)")

    # Entity context (issue, PR, etc)
    entity_type: str | None = Field(
        default=None,
        description="Type of entity: Issue, PullRequest, etc",
    )
    entity_number: int | None = Field(
        default=None,
        description="Issue or PR number",
    )
    entity_title: str | None = Field(
        default=None,
        description="Issue or PR title",
    )
    entity_url: str | None = Field(
        default=None,
        description="URL to the entity",
    )

    # Additional context
    actor: str | None = Field(
        default=None,
        description="User who triggered the event",
    )
    labels: list[str] = Field(
        default_factory=list,
        description="Current labels on the entity",
    )
    reason: str | None = Field(
        default=None,
        description="Original notification reason",
    )

    # Raw data for debugging
    raw_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Original event data for debugging",
    )

    @property
    def entity_id(self) -> str:
        """Get a unique identifier for the entity (repo/number)."""
        if self.entity_number:
            return f"{self.repo_full_name}#{self.entity_number}"
        return self.repo_full_name

    @property
    def display_name(self) -> str:
        """Get a human-readable display name for the event."""
        if self.entity_title and self.entity_number:
            return f"{self.repo_full_name}#{self.entity_number}: {self.entity_title}"
        if self.entity_number:
            return f"{self.repo_full_name}#{self.entity_number}"
        return self.repo_full_name


def normalize_notification(
    notification: dict[str, Any],
) -> Event:
    """Normalize a GitHub notification to an Event.

    Args:
        notification: Raw notification from GitHub API.

    Returns:
        Normalized Event object.
    """
    # Extract notification ID
    notif_id = notification.get("id", "")
    event_id = f"notif_{notif_id}"

    # Parse reason to event type
    reason = notification.get("reason", "generic")
    event_type = EventType.from_notification_reason(reason)

    # Extract repository info
    repo = notification.get("repository", {})
    repo_full_name = repo.get("full_name", "unknown/unknown")
    if "/" in repo_full_name:
        owner, name = repo_full_name.split("/", 1)
    else:
        owner, name = "unknown", repo_full_name

    # Parse timestamp
    updated_at_str = notification.get("updated_at", "")
    try:
        timestamp = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        timestamp = datetime.now(UTC)

    # Extract subject info (issue, PR, etc)
    subject = notification.get("subject", {})
    entity_type = subject.get("type")  # Issue, PullRequest, etc
    entity_title = subject.get("title")
    entity_url = subject.get("url")

    # Extract issue/PR number from URL
    entity_number: int | None = None
    if entity_url:
        # URL format: https://api.github.com/repos/owner/repo/issues/123
        parts = entity_url.rstrip("/").split("/")
        if parts:
            with contextlib.suppress(ValueError):
                entity_number = int(parts[-1])

    # Build web URL from API URL
    web_url = None
    if entity_url:
        web_url = (
            entity_url
            .replace("api.github.com/repos", "github.com")
            .replace("/pulls/", "/pull/")
        )

    return Event(
        id=event_id,
        event_type=event_type,
        source=EventSource.NOTIFICATION,
        timestamp=timestamp,
        repo_owner=owner,
        repo_name=name,
        repo_full_name=repo_full_name,
        entity_type=entity_type,
        entity_number=entity_number,
        entity_title=entity_title,
        entity_url=web_url,
        reason=reason,
        raw_data=notification,
    )


def generate_event_id(source: str, github_id: str) -> str:
    """Generate a unique event ID.

    Args:
        source: Event source (notif, webhook, poll).
        github_id: GitHub's ID for the entity.

    Returns:
        Unique event ID string.
    """
    return f"{source}_{github_id}"
