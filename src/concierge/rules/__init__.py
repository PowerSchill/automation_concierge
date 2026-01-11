"""Rules engine for event evaluation and matching."""

from concierge.rules.engine import RulesEngine, evaluate_rules
from concierge.rules.matchers import (
    EventTypeMatcher,
    FixedTimeProvider,
    LabelMatcher,
    Matcher,
    NoActivityMatcher,
    RepoMatcher,
    SystemTimeProvider,
    TimeProvider,
    TimeSinceMatcher,
    get_time_provider,
    reset_time_provider,
    set_time_provider,
)
from concierge.rules.schema import Match, MatchResult

__all__ = [
    "EventTypeMatcher",
    "FixedTimeProvider",
    "LabelMatcher",
    "Match",
    "MatchResult",
    "Matcher",
    "NoActivityMatcher",
    "RepoMatcher",
    "RulesEngine",
    "SystemTimeProvider",
    "TimeProvider",
    "TimeSinceMatcher",
    "evaluate_rules",
    "get_time_provider",
    "reset_time_provider",
    "set_time_provider",
]
