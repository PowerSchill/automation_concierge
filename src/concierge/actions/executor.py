"""Action executor for dispatching and running actions.

This module provides the ActionExecutor class which:
- Dispatches actions to appropriate handlers (T090)
- Supports console, Slack, and GitHub comment actions
- Implements message template expansion (T089)
- Provides action failure isolation (T091)
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from concierge.actions.console import ConsoleAction
from concierge.actions.github_comment import GitHubCommentAction
from concierge.actions.slack import SlackAction
from concierge.config.schema import Action, ActionType

if TYPE_CHECKING:
    from concierge.rules.schema import Match

logger = logging.getLogger(__name__)


class ActionStatus(str, Enum):
    """Status of an action execution."""

    SUCCESS = "success"
    FAILURE = "failure"
    SKIPPED = "skipped"
    DRY_RUN = "dry_run"


class ActionResult(BaseModel):
    """Result of an action execution."""

    model_config = ConfigDict(frozen=True)

    action_type: ActionType = Field(..., description="Type of action")
    status: ActionStatus = Field(..., description="Execution status")
    message: str = Field(default="", description="Status message or error")
    executed_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When the action was executed",
    )
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional action-specific details",
    )

    @property
    def is_success(self) -> bool:
        """Check if action succeeded."""
        return self.status == ActionStatus.SUCCESS

    @property
    def is_failure(self) -> bool:
        """Check if action failed."""
        return self.status == ActionStatus.FAILURE


class ActionExecutor:
    """Executor for dispatching actions to appropriate handlers.

    Features:
    - Dispatches to console, Slack, GitHub comment handlers (T090)
    - Supports message template expansion (T089)
    - Provides action failure isolation (T091)
    """

    def __init__(
        self,
        *,
        dry_run: bool = False,
        console_colorize: bool = True,
        slack_webhook_url: str | None = None,
        github_token: str | None = None,
    ) -> None:
        """Initialize action executor.

        Args:
            dry_run: If True, log actions without executing.
            console_colorize: Whether to colorize console output.
            slack_webhook_url: Slack webhook URL for Slack actions.
            github_token: GitHub token for comment actions.
        """
        self._dry_run = dry_run
        self._console = ConsoleAction(colorize=console_colorize)

        # Initialize Slack action if configured
        self._slack: SlackAction | None = None
        if slack_webhook_url:
            self._slack = SlackAction(slack_webhook_url)

        # Initialize GitHub comment action if configured
        self._github_comment: GitHubCommentAction | None = None
        if github_token:
            self._github_comment = GitHubCommentAction(github_token)
        elif os.environ.get("GITHUB_TOKEN"):
            self._github_comment = GitHubCommentAction(os.environ["GITHUB_TOKEN"])

    def execute(
        self,
        match: Match,
        action: Action,
    ) -> ActionResult:
        """Execute a single action for a match.

        Args:
            match: Match that triggered the action.
            action: Action configuration to execute.

        Returns:
            ActionResult with execution status.
        """
        action_type = action.type

        if self._dry_run:
            logger.info(
                "[DRY RUN] Would execute %s action for rule '%s' on event '%s'",
                action_type.value,
                match.rule.id,
                match.event.id,
            )
            return ActionResult(
                action_type=action_type,
                status=ActionStatus.DRY_RUN,
                message=f"Dry run: {action_type.value} action would be executed",
                details={
                    "rule_id": match.rule.id,
                    "event_id": match.event.id,
                },
            )

        try:
            if action_type == ActionType.CONSOLE:
                return self._execute_console(match, action)
            elif action_type == ActionType.SLACK:
                return self._execute_slack(match, action)
            elif action_type == ActionType.GITHUB_COMMENT:
                return self._execute_github_comment(match, action)
            else:
                return ActionResult(
                    action_type=action_type,
                    status=ActionStatus.SKIPPED,
                    message=f"Unknown action type: {action_type}",
                )

        except Exception as e:
            logger.exception("Error executing %s action", action_type.value)
            return ActionResult(
                action_type=action_type,
                status=ActionStatus.FAILURE,
                message=str(e),
            )

    def execute_all(
        self,
        match: Match,
    ) -> list[ActionResult]:
        """Execute the action for a match.

        Note: Rule has a single action, but we return a list for consistency
        with the original API and to support future multi-action rules.

        Args:
            match: Match that triggered the action.

        Returns:
            List of ActionResults (currently always contains one item).
        """
        results: list[ActionResult] = []
        action = match.rule.action

        result = self.execute(match, action)
        results.append(result)

        # Log the result
        if result.is_success:
            logger.info(
                "Action %s succeeded for rule '%s'",
                action.type.value,
                match.rule.id,
            )
        elif result.is_failure:
            logger.error(
                "Action %s failed for rule '%s': %s",
                action.type.value,
                match.rule.id,
                result.message,
            )

        return results

    def execute_all_isolated(
        self,
        matches: list[Match],
    ) -> dict[str, list[ActionResult]]:
        """Execute actions for multiple matches with failure isolation (T091).

        Each match is processed independently. If one action fails,
        it doesn't prevent other actions from being executed.

        Args:
            matches: List of matches to process.

        Returns:
            Dict mapping match event IDs to their action results.
        """
        results: dict[str, list[ActionResult]] = {}

        for match in matches:
            event_id = match.event.id
            try:
                match_results = self.execute_all(match)
                results[event_id] = match_results
            except Exception as e:
                # T091: Isolate failures - log and continue
                logger.exception(
                    "Unhandled error executing actions for event '%s': %s",
                    event_id,
                    e,
                )
                results[event_id] = [
                    ActionResult(
                        action_type=match.rule.action.type,
                        status=ActionStatus.FAILURE,
                        message=f"Unhandled error: {e}",
                    )
                ]

        return results

    def _execute_console(
        self,
        match: Match,
        action: Action,
    ) -> ActionResult:
        """Execute console action.

        Args:
            match: Match that triggered the action.
            action: Action configuration.

        Returns:
            ActionResult.
        """
        message = action.message
        success = self._console.execute(match, message)

        if success:
            return ActionResult(
                action_type=ActionType.CONSOLE,
                status=ActionStatus.SUCCESS,
                message="Notification printed to console",
            )

        return ActionResult(
            action_type=ActionType.CONSOLE,
            status=ActionStatus.FAILURE,
            message="Failed to print notification",
        )

    def _execute_slack(
        self,
        match: Match,
        action: Action,
    ) -> ActionResult:
        """Execute Slack webhook action.

        Args:
            match: Match that triggered the action.
            action: Action configuration.

        Returns:
            ActionResult.
        """
        if self._slack is None:
            logger.warning("Slack action requested but no webhook URL configured")
            return ActionResult(
                action_type=ActionType.SLACK,
                status=ActionStatus.SKIPPED,
                message="Slack webhook URL not configured",
            )

        # Expand message template (T089)
        message = expand_message_template(action.message, match)

        # Execute Slack action
        result = self._slack.execute(match, message)

        if result.success:
            return ActionResult(
                action_type=ActionType.SLACK,
                status=ActionStatus.SUCCESS,
                message="Slack notification sent",
                details={"attempts": result.attempts},
            )

        return ActionResult(
            action_type=ActionType.SLACK,
            status=ActionStatus.FAILURE,
            message=result.message,
            details={"attempts": result.attempts, "status_code": result.status_code},
        )

    def _execute_github_comment(
        self,
        match: Match,
        action: Action,
    ) -> ActionResult:
        """Execute GitHub comment action.

        Args:
            match: Match that triggered the action.
            action: Action configuration.

        Returns:
            ActionResult.
        """
        if self._github_comment is None:
            logger.warning("GitHub comment action requested but no token configured")
            return ActionResult(
                action_type=ActionType.GITHUB_COMMENT,
                status=ActionStatus.SKIPPED,
                message="GitHub token not configured",
            )

        # Expand message template (T089)
        message = expand_message_template(action.message, match)

        # Execute GitHub comment action with opt_in validation (T086)
        result = self._github_comment.execute(
            match,
            message,
            opt_in=action.opt_in,
        )

        if result.success:
            return ActionResult(
                action_type=ActionType.GITHUB_COMMENT,
                status=ActionStatus.SUCCESS,
                message="GitHub comment posted",
                details={
                    "comment_id": result.comment_id,
                    "comment_url": result.comment_url,
                    "attempts": result.attempts,
                },
            )

        return ActionResult(
            action_type=ActionType.GITHUB_COMMENT,
            status=ActionStatus.FAILURE,
            message=result.message,
            details={"attempts": result.attempts, "status_code": result.status_code},
        )


def execute_actions(
    match: Match,
    *,
    dry_run: bool = False,
    slack_webhook_url: str | None = None,
    github_token: str | None = None,
) -> list[ActionResult]:
    """Execute all actions for a match.

    Convenience function that creates an executor and runs actions.

    Args:
        match: Match that triggered the actions.
        dry_run: If True, log actions without executing.
        slack_webhook_url: Slack webhook URL for Slack actions.
        github_token: GitHub token for comment actions.

    Returns:
        List of ActionResults.
    """
    executor = ActionExecutor(
        dry_run=dry_run,
        slack_webhook_url=slack_webhook_url,
        github_token=github_token,
    )
    return executor.execute_all(match)


def execute_actions_isolated(
    matches: list[Match],
    *,
    dry_run: bool = False,
    slack_webhook_url: str | None = None,
    github_token: str | None = None,
) -> dict[str, list[ActionResult]]:
    """Execute actions for multiple matches with failure isolation.

    Convenience function that creates an executor and processes
    all matches, isolating failures (T091).

    Args:
        matches: List of matches to process.
        dry_run: If True, log actions without executing.
        slack_webhook_url: Slack webhook URL for Slack actions.
        github_token: GitHub token for comment actions.

    Returns:
        Dict mapping event IDs to action results.
    """
    executor = ActionExecutor(
        dry_run=dry_run,
        slack_webhook_url=slack_webhook_url,
        github_token=github_token,
    )
    return executor.execute_all_isolated(matches)


def expand_message_template(
    template: str,
    match: Match,
) -> str:
    """Expand template variables in a message.

    Supports {{ variable }} syntax.

    Args:
        template: Message template.
        match: Match for variable substitution.

    Returns:
        Expanded message.
    """
    event = match.event
    rule = match.rule

    variables = {
        "event.id": event.id,
        "event.type": event.event_type.value,
        "event.repo": event.repo_full_name,
        "event.entity_number": str(event.entity_number) if event.entity_number else "",
        "event.entity_title": event.entity_title or "",
        "event.entity_url": event.entity_url or "",
        "rule.id": rule.id,
        "rule.name": rule.name or rule.id,
        "match.reason": match.match_reason,
    }

    result = template
    for key, value in variables.items():
        result = result.replace("{{ " + key + " }}", value)
        result = result.replace("{{" + key + "}}", value)

    return result
