"""Rule matching result models."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from concierge.config.schema import Rule
    from concierge.github.events import Event


class Match(BaseModel):
    """Result of a successful rule match against an event."""

    model_config = ConfigDict(frozen=True)

    event: Event = Field(..., description="The event that matched")
    rule: Rule = Field(..., description="The rule that matched")
    match_reason: str = Field(..., description="Human-readable explanation of why the rule matched")

    @property
    def match_key(self) -> str:
        """Get a unique key for this match (event_id + rule_id).

        Used for deduplication.
        """
        return f"{self.event.id}:{self.rule.id}"


class MatchResult(BaseModel):
    """Collection of all matches for an event."""

    model_config = ConfigDict(frozen=True)

    event: Event = Field(..., description="The event being evaluated")
    matches: list[Match] = Field(default_factory=list, description="All rules that matched")
    rules_evaluated: int = Field(default=0, description="Total number of rules evaluated")

    @property
    def has_matches(self) -> bool:
        """Check if any rules matched."""
        return len(self.matches) > 0

    @property
    def matched_rule_ids(self) -> list[str]:
        """Get list of matched rule IDs."""
        return [m.rule.id for m in self.matches]
