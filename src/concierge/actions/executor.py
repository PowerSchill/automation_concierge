"""Action executor for dispatching and running actions."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from concierge.actions.console import ConsoleAction
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
    """Executor for dispatching actions to appropriate handlers."""

    def __init__(
        self,
        *,
        dry_run: bool = False,
        console_colorize: bool = True,
    ) -> None:
        """Initialize action executor.

        Args:
            dry_run: If True, log actions without executing.
            console_colorize: Whether to colorize console output.
        """
        self._dry_run = dry_run
        self._console = ConsoleAction(colorize=console_colorize)

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
        match: Match,  # noqa: ARG002
        action: Action,  # noqa: ARG002
    ) -> ActionResult:
        """Execute Slack webhook action.

        Note: This is a stub for US1. Full implementation in US6.

        Args:
            match: Match that triggered the action.
            action: Action configuration.

        Returns:
            ActionResult.
        """
        logger.warning("Slack action not yet implemented (coming in US6)")
        return ActionResult(
            action_type=ActionType.SLACK,
            status=ActionStatus.SKIPPED,
            message="Slack action not yet implemented",
        )

    def _execute_github_comment(
        self,
        match: Match,  # noqa: ARG002
        action: Action,  # noqa: ARG002
    ) -> ActionResult:
        """Execute GitHub comment action.

        Note: This is a stub for US1. Full implementation in US6.

        Args:
            match: Match that triggered the action.
            action: Action configuration.

        Returns:
            ActionResult.
        """
        logger.warning("GitHub comment action not yet implemented (coming in US6)")
        return ActionResult(
            action_type=ActionType.GITHUB_COMMENT,
            status=ActionStatus.SKIPPED,
            message="GitHub comment action not yet implemented",
        )


def execute_actions(
    match: Match,
    *,
    dry_run: bool = False,
) -> list[ActionResult]:
    """Execute all actions for a match.

    Convenience function that creates an executor and runs actions.

    Args:
        match: Match that triggered the actions.
        dry_run: If True, log actions without executing.

    Returns:
        List of ActionResults.
    """
    executor = ActionExecutor(dry_run=dry_run)
    return executor.execute_all(match)


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
