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

    # Label events (T080)
    LABEL_CHANGE = "label_change"
    LABEL_ADDED = "label_added"
    LABEL_REMOVED = "label_removed"

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
    labels_added: list[str] = Field(
        default_factory=list,
        description="Labels added in this event (T081)",
    )
    labels_removed: list[str] = Field(
        default_factory=list,
        description="Labels removed in this event (T081)",
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

    @property
    def has_label_changes(self) -> bool:
        """Check if this event has any label changes (T081)."""
        return bool(self.labels_added or self.labels_removed)


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


# =============================================================================
# Label Change Detection (T079, T080)
# =============================================================================


def extract_labels_from_payload(payload: dict[str, Any]) -> list[str]:
    """Extract label names from a GitHub event payload.

    Handles various payload structures where labels might be found.

    Args:
        payload: GitHub event/notification payload.

    Returns:
        List of label names.
    """
    labels: list[str] = []

    # Check for labels array at top level (issue/PR detail)
    if "labels" in payload:
        for label in payload.get("labels", []):
            if isinstance(label, dict):
                name = label.get("name", "")
                if name:
                    labels.append(name)
            elif isinstance(label, str):
                labels.append(label)

    # Check for issue/pull_request nested object
    for key in ("issue", "pull_request"):
        nested = payload.get(key, {})
        if nested and "labels" in nested:
            for label in nested.get("labels", []):
                if isinstance(label, dict):
                    name = label.get("name", "")
                    if name and name not in labels:
                        labels.append(name)
                elif isinstance(label, str) and label not in labels:
                    labels.append(label)

    return labels


def detect_label_changes(
    payload: dict[str, Any],
    previous_labels: list[str] | None = None,
) -> tuple[list[str], list[str], list[str]]:
    """Detect label changes from a GitHub webhook or event payload.

    For webhook payloads with action="labeled" or action="unlabeled",
    extracts the specific label that changed. For other cases, compares
    current labels to previous labels if provided.

    Args:
        payload: GitHub webhook/event payload.
        previous_labels: Optional list of previous labels for comparison.

    Returns:
        Tuple of (current_labels, labels_added, labels_removed).
    """
    current_labels = extract_labels_from_payload(payload)
    labels_added: list[str] = []
    labels_removed: list[str] = []

    # Check for webhook-style label action
    action = payload.get("action", "")

    if action == "labeled":
        # Label was added - extract from the "label" field
        label_data = payload.get("label", {})
        if isinstance(label_data, dict):
            label_name = label_data.get("name", "")
            if label_name:
                labels_added = [label_name]
    elif action == "unlabeled":
        # Label was removed - extract from the "label" field
        label_data = payload.get("label", {})
        if isinstance(label_data, dict):
            label_name = label_data.get("name", "")
            if label_name:
                labels_removed = [label_name]
    elif previous_labels is not None:
        # Compare current to previous
        prev_set = {lbl.lower() for lbl in previous_labels}
        curr_set = {lbl.lower() for lbl in current_labels}

        # Find added labels (in current but not in previous)
        for label in current_labels:
            if label.lower() not in prev_set:
                labels_added.append(label)

        # Find removed labels (in previous but not in current)
        for label in previous_labels:
            if label.lower() not in curr_set:
                labels_removed.append(label)

    return current_labels, labels_added, labels_removed


def normalize_label_event(
    payload: dict[str, Any],
    previous_labels: list[str] | None = None,
) -> Event:
    """Normalize a GitHub label webhook event to an Event.

    Creates an Event with LABEL_CHANGE, LABEL_ADDED, or LABEL_REMOVED
    event type based on the payload action.

    Args:
        payload: GitHub webhook payload for a label event.
        previous_labels: Optional previous labels for comparison.

    Returns:
        Normalized Event with label change information.
    """
    # Detect label changes
    current_labels, labels_added, labels_removed = detect_label_changes(
        payload,
        previous_labels,
    )

    # Determine event type based on action
    action = payload.get("action", "")
    if action == "labeled":
        event_type = EventType.LABEL_ADDED
    elif action == "unlabeled":
        event_type = EventType.LABEL_REMOVED
    else:
        event_type = EventType.LABEL_CHANGE

    # Extract repository info
    repo = payload.get("repository", {})
    repo_full_name = repo.get("full_name", "unknown/unknown")
    if "/" in repo_full_name:
        owner, name = repo_full_name.split("/", 1)
    else:
        owner, name = "unknown", repo_full_name

    # Extract issue/PR info
    issue_data = payload.get("issue") or payload.get("pull_request") or {}
    entity_number = issue_data.get("number")
    entity_title = issue_data.get("title")
    entity_url = issue_data.get("html_url")
    entity_type = "PullRequest" if payload.get("pull_request") else "Issue"

    # Parse timestamp
    timestamp_str = issue_data.get("updated_at", "")
    try:
        timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        timestamp = datetime.now(UTC)

    # Extract actor (sender)
    sender = payload.get("sender", {})
    actor = sender.get("login")

    # Generate event ID
    event_id = f"label_{repo_full_name}_{entity_number}_{timestamp.timestamp():.0f}"

    return Event(
        id=event_id,
        event_type=event_type,
        source=EventSource.WEBHOOK,
        timestamp=timestamp,
        repo_owner=owner,
        repo_name=name,
        repo_full_name=repo_full_name,
        entity_type=entity_type,
        entity_number=entity_number,
        entity_title=entity_title,
        entity_url=entity_url,
        actor=actor,
        labels=current_labels,
        labels_added=labels_added,
        labels_removed=labels_removed,
        raw_data=payload,
    )
