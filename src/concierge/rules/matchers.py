"""Rule matchers for different condition types.

This module provides matchers for evaluating event conditions:
- EventTypeMatcher: Match by event type
- RepoMatcher: Match by repository name/pattern
- LabelMatcher: Match by label presence/changes
- TimeSinceMatcher: Match by time elapsed since event (T071)
- NoActivityMatcher: Match by lack of activity (T072)

TimeProvider abstraction (T073) enables testable time-based matchers.
"""

from __future__ import annotations

import fnmatch
import logging
import re
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

from concierge.config.schema import (
    Condition,
    LabelCondition,
    NoActivityCondition,
    RepoCondition,
    TimeSinceCondition,
)

if TYPE_CHECKING:
    from concierge.github.events import Event, EventType

logger = logging.getLogger(__name__)


# =============================================================================
# T073: Injectable TimeProvider for testability
# =============================================================================


class TimeProvider(Protocol):
    """Protocol for providing current time.

    This abstraction allows time-based matchers to be tested
    with deterministic time values.
    """

    def now(self) -> datetime:
        """Get the current UTC time.

        Returns:
            Current datetime in UTC.
        """
        ...


class SystemTimeProvider:
    """Default time provider using system clock."""

    def now(self) -> datetime:
        """Get current UTC time from system clock."""
        return datetime.now(UTC)


class FixedTimeProvider:
    """Time provider with a fixed time (for testing).

    Example:
        >>> provider = FixedTimeProvider(datetime(2026, 1, 10, 12, 0, 0, tzinfo=UTC))
        >>> provider.now()
        datetime.datetime(2026, 1, 10, 12, 0, 0, tzinfo=datetime.timezone.utc)
    """

    def __init__(self, fixed_time: datetime) -> None:
        """Initialize with a fixed time.

        Args:
            fixed_time: The time to always return.
        """
        self._fixed_time = fixed_time

    def now(self) -> datetime:
        """Return the fixed time."""
        return self._fixed_time


# Global default time provider (can be replaced for testing)
_default_time_provider: TimeProvider = SystemTimeProvider()


def get_time_provider() -> TimeProvider:
    """Get the current default time provider."""
    return _default_time_provider


def set_time_provider(provider: TimeProvider) -> None:
    """Set the default time provider (for testing)."""
    global _default_time_provider  # noqa: PLW0603
    _default_time_provider = provider


def reset_time_provider() -> None:
    """Reset to the default system time provider."""
    global _default_time_provider  # noqa: PLW0603
    _default_time_provider = SystemTimeProvider()


class Matcher(ABC):
    """Base class for rule condition matchers."""

    @abstractmethod
    def matches(self, event: Event, condition: Condition) -> tuple[bool, str]:
        """Check if an event matches a condition.

        Args:
            event: Event to check.
            condition: Condition to match against.

        Returns:
            Tuple of (matched, reason).
        """
        ...


class EventTypeMatcher(Matcher):
    """Matcher for event type conditions."""

    def matches(
        self,
        event: Event,  # noqa: ARG002
        condition: Condition,  # noqa: ARG002
    ) -> tuple[bool, str]:
        """Check if event type matches the trigger's event_type.

        Note: This matcher doesn't use a condition object directly,
        but is called with the event type from the trigger.

        Args:
            event: Event to check.
            condition: Not used for event type matching.

        Returns:
            Tuple of (matched, reason).
        """
        # This is handled differently - see match_event_type
        return False, "EventTypeMatcher requires explicit event_type parameter"


def match_event_type(event: Event, expected_types: list[EventType]) -> tuple[bool, str]:
    """Check if event type matches any of the expected types.

    Args:
        event: Event to check.
        expected_types: List of event types to match.

    Returns:
        Tuple of (matched, reason).
    """
    if not expected_types:
        return True, "No event type filter specified (matches all)"

    if event.event_type in expected_types:
        return True, f"Event type '{event.event_type.value}' matches trigger"

    expected_values = [t.value for t in expected_types]
    return False, f"Event type '{event.event_type.value}' not in {expected_values}"


class RepoMatcher(Matcher):
    """Matcher for repository conditions."""

    def matches(self, event: Event, condition: Condition) -> tuple[bool, str]:
        """Check if event's repository matches the condition.

        Args:
            event: Event to check.
            condition: RepoCondition to match.

        Returns:
            Tuple of (matched, reason).
        """
        if not isinstance(condition, RepoCondition):
            return False, f"Expected RepoCondition, got {type(condition).__name__}"

        repo_pattern = condition.pattern

        # Check if it's a glob pattern
        if "*" in repo_pattern or "?" in repo_pattern:
            if fnmatch.fnmatch(event.repo_full_name, repo_pattern):
                return (
                    True,
                    f"Repository '{event.repo_full_name}' matches pattern '{repo_pattern}'",
                )
            return (
                False,
                f"Repository '{event.repo_full_name}' doesn't match pattern '{repo_pattern}'",
            )

        # Exact match
        if event.repo_full_name == repo_pattern:
            return True, f"Repository matches '{repo_pattern}'"

        # Check if it's owner-only pattern (e.g., "owner/*" or just "owner")
        if "/" not in repo_pattern and event.repo_owner == repo_pattern:
            return True, f"Repository owner matches '{repo_pattern}'"

        return False, f"Repository '{event.repo_full_name}' doesn't match '{repo_pattern}'"


class LabelMatcher(Matcher):
    """Matcher for label conditions."""

    def matches(  # noqa: PLR0911
        self,
        event: Event,
        condition: Condition,
    ) -> tuple[bool, str]:
        """Check if event's labels match the condition.

        Args:
            event: Event to check.
            condition: LabelCondition to match.

        Returns:
            Tuple of (matched, reason).
        """
        if not isinstance(condition, LabelCondition):
            return False, f"Expected LabelCondition, got {type(condition).__name__}"

        label = condition.label
        labels_lower = [lbl.lower() for lbl in event.labels]
        label_lower = label.lower()

        # Check based on condition type
        if condition.type == "label_present":
            if label_lower in labels_lower:
                return True, f"Label '{label}' is present"
            return False, f"Label '{label}' is not present"

        if condition.type == "label_added":
            # For label_added, we need the label to be in the current set
            # (In a full implementation, we'd compare with previous state)
            if label_lower in labels_lower:
                return True, f"Label '{label}' added (present in current labels)"
            return False, f"Label '{label}' not added (not in current labels)"

        if condition.type == "label_removed":
            # For label_removed, the label should NOT be present
            if label_lower not in labels_lower:
                return True, f"Label '{label}' is absent (removed)"
            return False, f"Label '{label}' is still present"

        # Unknown type
        return False, f"Unknown label condition type: {condition.type}"


class TimeSinceMatcher(Matcher):
    """Matcher for time-based conditions (T071).

    Checks if the time elapsed since a specific timestamp field
    exceeds a configured threshold. Supports thresholds like "48h", "7d".

    Example:
        A rule that triggers when a PR has been open for more than 48 hours:
        - condition: { type: "time_since", field: "created_at", threshold: "48h" }
    """

    def __init__(
        self,
        time_provider: TimeProvider | None = None,
        now: datetime | None = None,
    ) -> None:
        """Initialize with optional time provider.

        Args:
            time_provider: TimeProvider instance for current time.
            now: Deprecated - use time_provider. If provided, creates a FixedTimeProvider.
        """
        if time_provider is not None:
            self._time_provider = time_provider
        elif now is not None:
            # Backward compatibility
            self._time_provider = FixedTimeProvider(now)
        else:
            self._time_provider = get_time_provider()

    @property
    def now(self) -> datetime:
        """Get current time from provider."""
        return self._time_provider.now()

    def matches(self, event: Event, condition: Condition) -> tuple[bool, str]:
        """Check if time since event field exceeds threshold.

        For TimeSinceCondition, this checks if the time elapsed since
        the specified field (created_at or updated_at) exceeds the threshold.

        Args:
            event: Event to check.
            condition: TimeSinceCondition to match.

        Returns:
            Tuple of (matched, reason).
        """
        if not isinstance(condition, TimeSinceCondition):
            return False, f"Expected TimeSinceCondition, got {type(condition).__name__}"

        # Parse threshold to seconds
        try:
            threshold_seconds = condition.threshold_seconds()
        except ValueError:
            threshold_seconds = parse_duration(condition.threshold)

        # Get the timestamp field to check
        field = condition.field
        timestamp = self._get_timestamp_field(event, field)

        if timestamp is None:
            return False, f"Event does not have timestamp field '{field}'"

        # Calculate elapsed time
        elapsed = (self.now - timestamp).total_seconds()

        if elapsed >= threshold_seconds:
            elapsed_str = format_duration(elapsed)
            threshold_str = condition.threshold
            return True, f"Time since {field} ({elapsed_str}) >= threshold ({threshold_str})"

        elapsed_str = format_duration(elapsed)
        threshold_str = condition.threshold
        remaining = threshold_seconds - elapsed
        remaining_str = format_duration(remaining)
        return False, (
            f"Time since {field} ({elapsed_str}) < threshold ({threshold_str}); "
            f"{remaining_str} remaining"
        )

    def _get_timestamp_field(self, event: Event, field: str) -> datetime | None:
        """Get a timestamp field from the event.

        Args:
            event: Event to get field from.
            field: Field name ('created_at' or 'updated_at').

        Returns:
            Timestamp or None if not available.
        """
        if field == "created_at":
            # For events, created_at typically maps to the event timestamp
            # or can be fetched from raw_data
            if "created_at" in event.raw_data:
                try:
                    return datetime.fromisoformat(
                        event.raw_data["created_at"].replace("Z", "+00:00")
                    )
                except (ValueError, AttributeError, TypeError):
                    pass
            # Fall back to event timestamp for notifications
            return event.timestamp

        if field == "updated_at":
            # Check raw_data first
            if "updated_at" in event.raw_data:
                try:
                    return datetime.fromisoformat(
                        event.raw_data["updated_at"].replace("Z", "+00:00")
                    )
                except (ValueError, AttributeError, TypeError):
                    pass
            # Fall back to event timestamp
            return event.timestamp

        return None


class NoActivityMatcher(Matcher):
    """Matcher for no-activity conditions (T072).

    Checks if there has been no specific activity (review, comment, commit)
    on an entity since a specified time. This is used for rules like
    "PR open > 48h without review".

    Note: Full implementation requires activity history from GitHub API.
    This implementation checks if the event's updated_at equals its
    created_at (indicating no updates since creation) or uses activity
    data if available in the event's raw_data.
    """

    def __init__(
        self,
        time_provider: TimeProvider | None = None,
        now: datetime | None = None,
    ) -> None:
        """Initialize with optional time provider.

        Args:
            time_provider: TimeProvider instance for current time.
            now: Deprecated - use time_provider.
        """
        if time_provider is not None:
            self._time_provider = time_provider
        elif now is not None:
            self._time_provider = FixedTimeProvider(now)
        else:
            self._time_provider = get_time_provider()

    @property
    def now(self) -> datetime:
        """Get current time from provider."""
        return self._time_provider.now()

    def matches(self, event: Event, condition: Condition) -> tuple[bool, str]:
        """Check for no activity on an entity.

        Checks if the specified type of activity (review, comment, commit)
        has NOT occurred since the entity was created/last checked.

        Args:
            event: Event to check.
            condition: NoActivityCondition to match.

        Returns:
            Tuple of (matched, reason).
        """
        if not isinstance(condition, NoActivityCondition):
            return False, f"Expected NoActivityCondition, got {type(condition).__name__}"

        activity_type = condition.activity
        since_field = condition.since

        # Get the base timestamp to check from
        base_timestamp = self._get_timestamp_field(event, since_field)
        if base_timestamp is None:
            return False, f"Event does not have timestamp field '{since_field}'"

        # Check for activity based on type
        has_activity, activity_info = self._check_activity(event, activity_type)

        if not has_activity:
            elapsed = (self.now - base_timestamp).total_seconds()
            elapsed_str = format_duration(elapsed)
            return True, (
                f"No {activity_type} activity detected since {since_field} "
                f"({elapsed_str} ago)"
            )

        return False, f"Activity detected: {activity_info}"

    def _get_timestamp_field(self, event: Event, field: str) -> datetime | None:
        """Get a timestamp field from the event."""
        if field == "created_at":
            if "created_at" in event.raw_data:
                try:
                    return datetime.fromisoformat(
                        event.raw_data["created_at"].replace("Z", "+00:00")
                    )
                except (ValueError, AttributeError, TypeError):
                    pass
            return event.timestamp

        if field == "updated_at":
            if "updated_at" in event.raw_data:
                try:
                    return datetime.fromisoformat(
                        event.raw_data["updated_at"].replace("Z", "+00:00")
                    )
                except (ValueError, AttributeError, TypeError):
                    pass
            return event.timestamp

        return None

    def _check_activity(  # noqa: PLR0911
        self,
        event: Event,
        activity_type: str,
    ) -> tuple[bool, str]:
        """Check if specific activity exists.

        This checks the event's raw_data for activity indicators.

        Args:
            event: Event to check.
            activity_type: Type of activity to check for.

        Returns:
            Tuple of (has_activity, description).
        """
        raw = event.raw_data

        if activity_type == "review":
            # Check for review indicators in PR data
            # Look for review data in subject or linked data
            if raw.get("subject", {}).get("type") == "PullRequest":
                # Check if there are reviews (would need API fetch for full data)
                # For now, check if updated_at != created_at as a heuristic
                created = raw.get("created_at")
                updated = raw.get("updated_at")
                if created and updated and created != updated:
                    return True, "Entity has been updated (possible review activity)"
            return False, "No review activity detected"

        if activity_type == "comment":
            # Check for comment count or activity
            comments = raw.get("comments", 0)
            if comments and comments > 0:
                return True, f"{comments} comment(s) exist"
            return False, "No comments detected"

        if activity_type == "commit":
            # Check for commit activity (PRs only)
            commits = raw.get("commits", 0)
            if commits and commits > 0:
                return True, f"{commits} commit(s) exist"
            return False, "No commits detected"

        return False, f"Unknown activity type: {activity_type}"


def parse_duration(duration: str) -> float:
    """Parse a duration string to seconds.

    Supports: "30s", "5m", "2h", "7d"

    Args:
        duration: Duration string.

    Returns:
        Duration in seconds.

    Raises:
        ValueError: If format is invalid.
    """
    pattern = r"^(\d+(?:\.\d+)?)\s*([smhd])$"
    match = re.match(pattern, duration.strip().lower())

    if not match:
        raise ValueError(
            f"Invalid duration format: '{duration}'. "
            "Expected format: number + unit (s, m, h, d), e.g., '30s', '5m', '2h', '7d'"
        )

    value = float(match.group(1))
    unit = match.group(2)

    multipliers: dict[str, float] = {
        "s": 1,
        "m": 60,
        "h": 3600,
        "d": 86400,
    }

    return value * multipliers[unit]


def format_duration(seconds: float) -> str:
    """Format seconds as a human-readable duration.

    Args:
        seconds: Duration in seconds.

    Returns:
        Formatted string like "2h 30m" or "5d 3h".
    """
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.1f}m"
    if seconds < 86400:
        hours = seconds / 3600
        return f"{hours:.1f}h"

    days = seconds / 86400
    return f"{days:.1f}d"


def get_matcher(
    condition: Condition,
    now: datetime | None = None,
    time_provider: TimeProvider | None = None,
) -> Matcher:
    """Get the appropriate matcher for a condition type.

    Args:
        condition: Condition to get matcher for.
        now: Optional current time for time-based matchers (deprecated).
        time_provider: Optional TimeProvider for time-based matchers.
            Takes precedence over 'now' if both are provided.

    Returns:
        Matcher instance.

    Raises:
        ValueError: If condition type is unknown.
    """
    matchers: dict[type[Any], type[Matcher]] = {
        RepoCondition: RepoMatcher,
        LabelCondition: LabelMatcher,
        TimeSinceCondition: TimeSinceMatcher,
        NoActivityCondition: NoActivityMatcher,
    }

    matcher_class = matchers.get(type(condition))
    if matcher_class is None:
        raise ValueError(f"Unknown condition type: {type(condition).__name__}")

    # Time-based matchers need a time provider
    if matcher_class in (TimeSinceMatcher, NoActivityMatcher):
        return matcher_class(time_provider=time_provider, now=now)

    return matcher_class()
