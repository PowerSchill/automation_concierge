"""Pydantic schema models for configuration.

This module defines all configuration models per the data-model.md specification:
- Config: Top-level configuration container
- GitHubConfig: GitHub API settings
- ActionsConfig: Action type configurations
- StateConfig: State storage settings
- Rule: User-defined automation rules
- Trigger: Rule trigger conditions
- Action: Action execution configuration
- Condition types: Label, TimeSince, NoActivity, Repo
"""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from concierge.paths import get_default_state_dir


class EventType(str, Enum):
    """Type of GitHub activity that can trigger a rule."""

    MENTION = "mention"
    ASSIGNMENT = "assignment"
    REVIEW_REQUEST = "review_request"
    LABEL_CHANGE = "label_change"
    PR_OPEN = "pr_open"
    ISSUE_OPEN = "issue_open"
    COMMENT = "comment"
    REVIEW = "review"


class ActionType(str, Enum):
    """Type of action to execute when a rule matches."""

    CONSOLE = "console"
    SLACK = "slack"
    GITHUB_COMMENT = "github_comment"


class LabelCondition(BaseModel):
    """Condition that checks for label presence or changes.

    Attributes:
        type: One of 'label_present', 'label_added', 'label_removed'
        label: The label name to match
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["label_present", "label_added", "label_removed"]
    label: Annotated[str, Field(min_length=1, max_length=50)]


class TimeSinceCondition(BaseModel):
    """Condition that checks time elapsed since a timestamp field.

    Attributes:
        type: Always 'time_since'
        field: Which timestamp to measure from ('created_at' or 'updated_at')
        threshold: Duration string like '48h' or '7d'
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["time_since"]
    field: Literal["created_at", "updated_at"]
    threshold: str

    @field_validator("threshold")
    @classmethod
    def validate_threshold(cls, v: str) -> str:
        """Validate threshold is a valid duration string."""
        if not re.match(r"^\d+[hd]$", v):
            msg = "threshold must be a duration like '48h' or '7d'"
            raise ValueError(msg)
        return v

    def threshold_seconds(self) -> int:
        """Convert threshold to seconds."""
        value = int(self.threshold[:-1])
        unit = self.threshold[-1]
        if unit == "h":
            return value * 3600
        if unit == "d":
            return value * 86400
        msg = f"Unknown time unit: {unit}"
        raise ValueError(msg)


class NoActivityCondition(BaseModel):
    """Condition that checks for lack of specific activity.

    Attributes:
        type: Always 'no_activity'
        activity: Type of activity to check for ('review', 'comment', 'commit')
        since: Which timestamp to measure from (default: 'created_at')
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["no_activity"]
    activity: Literal["review", "comment", "commit"]
    since: Literal["created_at", "updated_at"] = "created_at"


class RepoCondition(BaseModel):
    """Condition that matches repository name against a pattern.

    Attributes:
        type: Always 'repo_match'
        pattern: Glob pattern like 'myorg/*' or 'owner/repo'
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["repo_match"]
    pattern: str


# Union type for all condition types
Condition = LabelCondition | TimeSinceCondition | NoActivityCondition | RepoCondition


class Action(BaseModel):
    """Action configuration for a rule.

    Attributes:
        type: The type of action to execute
        message: Message template with {{ event.field }} placeholders
        opt_in: Required to be True for github_comment actions (safety)
    """

    model_config = ConfigDict(extra="forbid")

    type: ActionType
    message: Annotated[str, Field(min_length=1, max_length=1000)]
    opt_in: bool | None = None

    @model_validator(mode="after")
    def validate_github_comment_opt_in(self) -> Action:
        """Ensure github_comment actions have explicit opt_in: true."""
        if self.type == ActionType.GITHUB_COMMENT and self.opt_in is not True:
            msg = "github_comment action requires 'opt_in: true' for safety"
            raise ValueError(msg)
        return self


class Trigger(BaseModel):
    """Trigger configuration for a rule.

    Attributes:
        event_type: The type of event to match
        conditions: Optional list of additional conditions to check
    """

    model_config = ConfigDict(extra="forbid")

    event_type: EventType
    conditions: list[Condition] | None = None


class Rule(BaseModel):
    """User-defined automation rule.

    A rule consists of a trigger (what events to match) and an action
    (what to do when matched).

    Attributes:
        id: Unique rule identifier (lowercase, alphanumeric, hyphens)
        name: Human-readable rule name
        enabled: Whether rule is active (default: True)
        description: Optional rule description
        trigger: What events to match
        action: What to do when matched
    """

    model_config = ConfigDict(extra="forbid")

    id: Annotated[str, Field(min_length=2, max_length=64)]
    name: Annotated[str, Field(min_length=1, max_length=100)]
    enabled: bool = True
    description: Annotated[str | None, Field(max_length=500)] = None
    trigger: Trigger
    action: Action

    @field_validator("id")
    @classmethod
    def validate_rule_id(cls, v: str) -> str:
        """Validate rule ID format: lowercase, alphanumeric, hyphens."""
        # Pattern: starts with alphanumeric, optionally followed by alphanumeric/hyphens,
        # and ends with alphanumeric (for IDs >= 2 chars)
        if len(v) >= 2:
            if not re.match(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$", v):
                msg = (
                    "rule id must be lowercase alphanumeric with hyphens, "
                    "starting and ending with alphanumeric"
                )
                raise ValueError(msg)
        elif len(v) == 1 and not re.match(r"^[a-z0-9]$", v):
            msg = "rule id must be lowercase alphanumeric"
            raise ValueError(msg)
        return v


class GitHubConfig(BaseModel):
    """GitHub API configuration.

    Attributes:
        poll_interval: Polling interval in seconds (30-300, default: 60)
        lookback_window: How far back to look on first run in seconds
                        (300-604800, default: 3600)
    """

    model_config = ConfigDict(extra="forbid")

    poll_interval: Annotated[int, Field(ge=30, le=300)] = 60
    lookback_window: Annotated[int, Field(ge=300, le=604800)] = 3600


class SlackConfig(BaseModel):
    """Slack notification configuration.

    Attributes:
        webhook_url: Slack webhook URL or env var reference (${VAR})
    """

    model_config = ConfigDict(extra="forbid")

    webhook_url: str

    @field_validator("webhook_url")
    @classmethod
    def validate_webhook_url(cls, v: str) -> str:
        """Validate webhook URL format (URL or env var reference)."""
        if v.startswith("${") and v.endswith("}"):
            # Environment variable reference - valid
            return v
        if v.startswith("https://hooks.slack.com/"):
            # Valid Slack webhook URL
            return v
        msg = (
            "webhook_url must be a Slack webhook URL "
            "(https://hooks.slack.com/...) or env var reference (${VAR})"
        )
        raise ValueError(msg)


class GitHubCommentConfig(BaseModel):
    """GitHub comment action configuration.

    Attributes:
        enabled: Must be true to enable GitHub comments (safety gate)
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False


class ActionsConfig(BaseModel):
    """Action type configurations.

    Attributes:
        slack: Optional Slack configuration
        github_comment: Optional GitHub comment configuration
    """

    model_config = ConfigDict(extra="forbid")

    slack: SlackConfig | None = None
    github_comment: GitHubCommentConfig | None = None


class StateConfig(BaseModel):
    """State storage configuration.

    Attributes:
        directory: State directory path (default: XDG data dir)
                   Uses $XDG_DATA_HOME/concierge (~/.local/share/concierge)
        retention_days: How long to retain processed events (1-365, default: 30)
    """

    model_config = ConfigDict(extra="forbid")

    directory: str | None = None
    retention_days: Annotated[int, Field(ge=1, le=365)] = 30

    def get_directory(self) -> Path:
        """Get the state directory path, expanding ~ if needed."""
        if self.directory:
            return Path(self.directory).expanduser()
        return get_default_state_dir()


class Config(BaseModel):
    """Top-level configuration loaded from YAML.

    Attributes:
        version: Schema version (must be 1)
        github: GitHub API settings
        actions: Action type configurations
        state: State storage settings
        rules: List of automation rules
    """

    model_config = ConfigDict(extra="forbid")

    version: Literal[1]
    github: GitHubConfig = Field(default_factory=GitHubConfig)
    actions: ActionsConfig = Field(default_factory=ActionsConfig)
    state: StateConfig = Field(default_factory=StateConfig)
    rules: list[Rule] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_rule_ids(self) -> Config:
        """Ensure all rule IDs are unique."""
        ids = [rule.id for rule in self.rules]
        duplicates = [id_ for id_ in ids if ids.count(id_) > 1]
        if duplicates:
            msg = f"Duplicate rule IDs found: {set(duplicates)}"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def validate_slack_rules_have_config(self) -> Config:
        """Ensure Slack rules have Slack configured."""
        has_slack_rules = any(
            rule.action.type == ActionType.SLACK for rule in self.rules if rule.enabled
        )
        if has_slack_rules and self.actions.slack is None:
            msg = (
                "Rule uses 'slack' action but no Slack configuration provided. "
                "Add actions.slack.webhook_url to your config."
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def validate_github_comment_rules_have_config(self) -> Config:
        """Ensure GitHub comment rules have the action enabled."""
        has_comment_rules = any(
            rule.action.type == ActionType.GITHUB_COMMENT
            for rule in self.rules
            if rule.enabled
        )
        gh_enabled = (
            self.actions.github_comment is not None
            and self.actions.github_comment.enabled
        )
        if has_comment_rules and not gh_enabled:
            msg = (
                "Rule uses 'github_comment' action but GitHub comments not enabled. "
                "Add actions.github_comment.enabled: true to your config."
            )
            raise ValueError(msg)
        return self

    def get_enabled_rules(self) -> list[Rule]:
        """Return only enabled rules."""
        return [rule for rule in self.rules if rule.enabled]
