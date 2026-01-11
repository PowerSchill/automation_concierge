"""Rule evaluation engine."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from concierge.github.events import Event, EventType
from concierge.rules.matchers import get_matcher, match_event_type
from concierge.rules.schema import Match, MatchResult

if TYPE_CHECKING:
    from concierge.config.schema import Rule

logger = logging.getLogger(__name__)


class RulesEngine:
    """Engine for evaluating events against rules."""

    def __init__(
        self,
        rules: list[Rule],
        *,
        now: datetime | None = None,
    ) -> None:
        """Initialize rules engine.

        Args:
            rules: List of rules to evaluate.
            now: Optional current time for time-based conditions.
        """
        self._rules = rules
        self._now = now

    @property
    def now(self) -> datetime:
        """Get current time."""
        return self._now or datetime.now(UTC)

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
                matcher = get_matcher(condition, now=self._now)
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


def evaluate_rules(
    event: Event,
    rules: list[Rule],
    *,
    now: datetime | None = None,
) -> MatchResult:
    """Evaluate an event against a list of rules.

    This is a convenience function that creates a RulesEngine and evaluates.

    Args:
        event: Event to evaluate.
        rules: Rules to check.
        now: Optional current time for time-based conditions.

    Returns:
        MatchResult with all matching rules.
    """
    engine = RulesEngine(rules, now=now)
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
