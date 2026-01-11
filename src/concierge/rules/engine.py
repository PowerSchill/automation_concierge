"""Rule evaluation engine.

This module provides the RulesEngine class for evaluating events
against configured rules. It handles:
- Event type matching
- Condition evaluation via matchers
- Time-based threshold crossing detection (T077)
- TimeProvider integration for testable time-based rules
"""

from __future__ import annotations

import logging
from datetime import datetime  # noqa: TC003 - used in property return type
from typing import TYPE_CHECKING

from concierge.config.schema import NoActivityCondition, TimeSinceCondition
from concierge.github.events import Event, EventType
from concierge.rules.matchers import (
    TimeProvider,
    get_matcher,
    get_time_provider,
    match_event_type,
)
from concierge.rules.schema import Match, MatchResult

if TYPE_CHECKING:
    from concierge.config.schema import Rule
    from concierge.state.store import StateStore

logger = logging.getLogger(__name__)


class RulesEngine:
    """Engine for evaluating events against rules.

    Supports:
    - Standard condition matching
    - Time-based threshold crossing detection (T077)
    - Injectable TimeProvider for testability

    The threshold crossing detection ensures that time-based rules
    (like "PR open > 48h without review") only fire once when the
    threshold is crossed, not repeatedly on every poll.
    """

    def __init__(
        self,
        rules: list[Rule],
        *,
        now: datetime | None = None,
        time_provider: TimeProvider | None = None,
        state_store: StateStore | None = None,
    ) -> None:
        """Initialize rules engine.

        Args:
            rules: List of rules to evaluate.
            now: Optional current time (deprecated, use time_provider).
            time_provider: Optional TimeProvider for time-based conditions.
            state_store: Optional StateStore for threshold deduplication.
        """
        self._rules = rules
        self._now = now
        self._time_provider = time_provider or get_time_provider()
        self._state_store = state_store

    @property
    def now(self) -> datetime:
        """Get current time."""
        if self._now is not None:
            return self._now
        return self._time_provider.now()

    def evaluate(self, event: Event) -> MatchResult:
        """Evaluate an event against all rules.

        Args:
            event: Event to evaluate.

        Returns:
            MatchResult with all matching rules.
        """
        matches: list[Match] = []
        rules_evaluated = 0

        for rule in self._rules:
            rules_evaluated += 1
            matched, reason = self._evaluate_rule(event, rule)

            if matched:
                # Check threshold deduplication for time-based rules
                if self._is_threshold_rule(rule) and self._state_store is not None:
                    threshold = self._get_rule_threshold(rule)
                    entity_id = self._make_entity_id(event)

                    if self._state_store.has_threshold_fired(
                        entity_id, rule.id, threshold
                    ):
                        logger.debug(
                            "Threshold already fired for %s on rule '%s' (threshold: %s)",
                            entity_id,
                            rule.id,
                            threshold,
                        )
                        continue  # Skip - already fired

                matches.append(
                    Match(
                        event=event,
                        rule=rule,
                        match_reason=reason,
                    )
                )
                logger.debug(
                    "Rule '%s' matched event '%s': %s",
                    rule.id,
                    event.id,
                    reason,
                )
            else:
                logger.debug(
                    "Rule '%s' did not match event '%s': %s",
                    rule.id,
                    event.id,
                    reason,
                )

        return MatchResult(
            event=event,
            matches=matches,
            rules_evaluated=rules_evaluated,
        )

    def _evaluate_rule(
        self,
        event: Event,
        rule: Rule,
    ) -> tuple[bool, str]:
        """Evaluate a single rule against an event.

        Args:
            event: Event to check.
            rule: Rule to evaluate.

        Returns:
            Tuple of (matched, reason).
        """
        reasons: list[str] = []

        # Check event type from trigger
        trigger = rule.trigger
        expected_types = self._get_expected_event_types(trigger.event_type)

        event_matched, event_reason = match_event_type(event, expected_types)
        if not event_matched:
            return False, event_reason

        reasons.append(event_reason)

        # Check all conditions
        conditions = trigger.conditions or []
        for condition in conditions:
            try:
                matcher = get_matcher(
                    condition,
                    now=self._now,
                    time_provider=self._time_provider,
                )
                matched, reason = matcher.matches(event, condition)

                if not matched:
                    return False, f"Condition failed: {reason}"

                reasons.append(reason)

            except Exception as e:
                logger.warning(
                    "Error evaluating condition for rule '%s': %s",
                    rule.id,
                    e,
                )
                return False, f"Condition evaluation error: {e}"

        # All conditions matched
        combined_reason = "; ".join(reasons)
        return True, combined_reason

    def _get_expected_event_types(
        self,
        event_type_config: str | list[str],
    ) -> list[EventType]:
        """Convert trigger event_type config to list of EventTypes.

        Args:
            event_type_config: Event type from trigger (string or list).

        Returns:
            List of EventType enums.
        """
        types = [event_type_config] if isinstance(event_type_config, str) else event_type_config

        result: list[EventType] = []
        for t in types:
            try:
                result.append(EventType(t))
            except ValueError:
                logger.warning("Unknown event type in rule: %s", t)

        return result

    def _is_threshold_rule(self, rule: Rule) -> bool:
        """Check if a rule has time-based threshold conditions.

        Args:
            rule: Rule to check.

        Returns:
            True if rule has time_since or no_activity conditions.
        """
        conditions = rule.trigger.conditions or []
        for condition in conditions:
            if isinstance(condition, TimeSinceCondition | NoActivityCondition):
                return True
        return False

    def _get_rule_threshold(self, rule: Rule) -> str:
        """Get the threshold string from a time-based rule.

        For rules with multiple thresholds, returns the first one.
        This is used for deduplication key generation.

        Args:
            rule: Rule to get threshold from.

        Returns:
            Threshold string (e.g., "48h") or "default" if none found.
        """
        conditions = rule.trigger.conditions or []
        for condition in conditions:
            if isinstance(condition, TimeSinceCondition):
                return condition.threshold
            if isinstance(condition, NoActivityCondition):
                # NoActivityCondition doesn't have a direct threshold,
                # use the 'since' field as a stable identifier
                return f"since:{condition.since}"
        return "default"

    def _make_entity_id(self, event: Event) -> str:
        """Create a unique entity identifier from an event.

        Args:
            event: Event to create ID from.

        Returns:
            Entity ID in format "owner/repo#number" or event ID.
        """
        if event.entity_number:
            return f"{event.repo_full_name}#{event.entity_number}"
        return event.id


def evaluate_rules(
    event: Event,
    rules: list[Rule],
    *,
    now: datetime | None = None,
    time_provider: TimeProvider | None = None,
    state_store: StateStore | None = None,
) -> MatchResult:
    """Evaluate an event against a list of rules.

    This is a convenience function that creates a RulesEngine and evaluates.

    Args:
        event: Event to evaluate.
        rules: Rules to check.
        now: Optional current time for time-based conditions (deprecated).
        time_provider: Optional TimeProvider for time-based conditions.
        state_store: Optional StateStore for threshold deduplication.

    Returns:
        MatchResult with all matching rules.
    """
    engine = RulesEngine(
        rules,
        now=now,
        time_provider=time_provider,
        state_store=state_store,
    )
    return engine.evaluate(event)


def generate_match_reason(
    rule: Rule,
    event: Event,
    condition_results: list[tuple[str, bool, str]],
) -> str:
    """Generate a human-readable match reason.

    Args:
        rule: Rule that matched.
        event: Event that was matched.
        condition_results: List of (condition_type, matched, reason) tuples.

    Returns:
        Human-readable explanation of why the rule matched.
    """
    parts = [
        f"Rule '{rule.id}' matched {event.event_type.value} event "
        f"on {event.repo_full_name}"
    ]

    if event.entity_number:
        parts[0] += f"#{event.entity_number}"

    for cond_type, matched, reason in condition_results:
        if matched:
            parts.append(f"  ✓ {cond_type}: {reason}")
        else:
            parts.append(f"  ✗ {cond_type}: {reason}")

    return "\n".join(parts)
