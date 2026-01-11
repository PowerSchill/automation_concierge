"""Rule matchers for different condition types."""

from __future__ import annotations

import fnmatch
import logging
import re
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

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
    """Matcher for time-based conditions."""

    def __init__(self, now: datetime | None = None) -> None:
        """Initialize with optional time provider.

        Args:
            now: Current time (for testing). If None, uses datetime.now(UTC).
        """
        self._now = now

    @property
    def now(self) -> datetime:
        """Get current time."""
        return self._now or datetime.now(UTC)

    def matches(self, event: Event, condition: Condition) -> tuple[bool, str]:
        """Check if time since event exceeds threshold.

        Args:
            event: Event to check.
            condition: TimeSinceCondition to match.

        Returns:
            Tuple of (matched, reason).
        """
        if not isinstance(condition, TimeSinceCondition):
            return False, f"Expected TimeSinceCondition, got {type(condition).__name__}"

        threshold_seconds = parse_duration(condition.threshold)
        elapsed = (self.now - event.timestamp).total_seconds()

        if elapsed >= threshold_seconds:
            elapsed_str = format_duration(elapsed)
            threshold = condition.threshold
            return True, f"Time since event ({elapsed_str}) exceeds threshold ({threshold})"
        elapsed_str = format_duration(elapsed)
        threshold = condition.threshold
        return False, f"Time since event ({elapsed_str}) < threshold ({threshold})"


class NoActivityMatcher(Matcher):
    """Matcher for no-activity conditions.

    Note: This matcher requires additional context (activity history)
    that's not available in the Event alone. For US1, we'll defer
    this to a later phase.
    """

    def __init__(self, now: datetime | None = None) -> None:
        """Initialize with optional time provider.

        Args:
            now: Current time (for testing).
        """
        self._now = now

    @property
    def now(self) -> datetime:
        """Get current time."""
        return self._now or datetime.now(UTC)

    def matches(self, event: Event, condition: Condition) -> tuple[bool, str]:
        """Check for no activity on an entity.

        Args:
            event: Event to check.
            condition: NoActivityCondition to match.

        Returns:
            Tuple of (matched, reason).

        Note:
            This is a stub implementation for US1. Full implementation
            requires fetching activity history from GitHub API.
        """
        if not isinstance(condition, NoActivityCondition):
            return False, f"Expected NoActivityCondition, got {type(condition).__name__}"

        # Stub: For now, just check time since the event
        threshold_seconds = parse_duration(condition.since)
        elapsed = (self.now - event.timestamp).total_seconds()

        if elapsed >= threshold_seconds:
            elapsed_str = format_duration(elapsed)
            return True, f"No activity detected for {elapsed_str} (threshold: {condition.since})"
        elapsed_str = format_duration(elapsed)
        return False, f"Activity within threshold ({elapsed_str} < {condition.since})"


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


def get_matcher(condition: Condition, now: datetime | None = None) -> Matcher:
    """Get the appropriate matcher for a condition type.

    Args:
        condition: Condition to get matcher for.
        now: Optional current time for time-based matchers.

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

    # Time-based matchers need the 'now' parameter
    if matcher_class in (TimeSinceMatcher, NoActivityMatcher):
        return matcher_class(now=now)

    return matcher_class()
