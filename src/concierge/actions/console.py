"""Console action for printing notifications to stdout."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING, TextIO

if TYPE_CHECKING:
    from concierge.github.events import Event
    from concierge.rules.schema import Match


class ConsoleAction:
    """Action that prints notifications to console (stdout)."""

    def __init__(
        self,
        output: TextIO | None = None,
        *,
        colorize: bool = True,
    ) -> None:
        """Initialize console action.

        Args:
            output: Output stream (defaults to stdout).
            colorize: Whether to use ANSI colors.
        """
        self._output = output or sys.stdout
        self._colorize = colorize and self._output.isatty()

    def execute(
        self,
        match: Match,
        message: str | None = None,
    ) -> bool:
        """Execute the console action.

        Args:
            match: Match containing event and rule info.
            message: Optional custom message template.

        Returns:
            True if successful, False otherwise.
        """
        try:
            formatted = self._format_notification(match, message)
            print(formatted, file=self._output)
            return True
        except Exception:
            return False

    def _format_notification(
        self,
        match: Match,
        message: str | None = None,
    ) -> str:
        """Format a notification for console output.

        Args:
            match: Match containing event and rule info.
            message: Optional custom message template.

        Returns:
            Formatted string for console output.
        """
        event = match.event
        rule = match.rule

        # Use custom message if provided, otherwise build default
        if message:
            return self._expand_template(message, match)

        # Build default notification format
        lines = []

        # Header with rule and event type
        header = f"🔔 [{rule.id}] {event.event_type.value.upper()}"
        if self._colorize:
            header = f"\033[1;34m{header}\033[0m"
        lines.append(header)

        # Repository and entity info
        if event.entity_number and event.entity_title:
            entity_line = f"   {event.repo_full_name}#{event.entity_number}: {event.entity_title}"
        elif event.entity_number:
            entity_line = f"   {event.repo_full_name}#{event.entity_number}"
        else:
            entity_line = f"   {event.repo_full_name}"
        lines.append(entity_line)

        # URL if available
        if event.entity_url:
            url_line = f"   {event.entity_url}"
            if self._colorize:
                url_line = f"   \033[4;36m{event.entity_url}\033[0m"
            lines.append(url_line)

        # Reason why rule matched
        reason_line = f"   Reason: {match.match_reason}"
        if self._colorize:
            reason_line = f"   \033[2m{match.match_reason}\033[0m"
        lines.append(reason_line)

        return "\n".join(lines)

    def _expand_template(
        self,
        template: str,
        match: Match,
    ) -> str:
        """Expand template variables in a message.

        Supports {{ variable }} syntax with event and rule fields.

        Args:
            template: Message template.
            match: Match for variable substitution.

        Returns:
            Expanded message.
        """
        event = match.event
        rule = match.rule

        # Build substitution dict
        variables = {
            "event.id": event.id,
            "event.type": event.event_type.value,
            "event.repo": event.repo_full_name,
            "event.repo_owner": event.repo_owner,
            "event.repo_name": event.repo_name,
            "event.entity_type": event.entity_type or "",
            "event.entity_number": str(event.entity_number) if event.entity_number else "",
            "event.entity_title": event.entity_title or "",
            "event.entity_url": event.entity_url or "",
            "event.actor": event.actor or "",
            "event.reason": event.reason or "",
            "event.timestamp": event.timestamp.isoformat(),
            "rule.id": rule.id,
            "rule.name": rule.name or rule.id,
            "match.reason": match.match_reason,
        }

        result = template
        for key, value in variables.items():
            result = result.replace("{{ " + key + " }}", value)
            result = result.replace("{{" + key + "}}", value)

        return result


def format_event_summary(event: Event) -> str:
    """Format a brief event summary for logging.

    Args:
        event: Event to summarize.

    Returns:
        Single-line summary.
    """
    parts = [
        f"[{event.event_type.value}]",
        event.repo_full_name,
    ]

    if event.entity_number:
        parts[-1] += f"#{event.entity_number}"

    if event.entity_title:
        # Truncate long titles
        title = event.entity_title
        if len(title) > 50:
            title = title[:47] + "..."
        parts.append(f'"{title}"')

    return " ".join(parts)


def get_notification_timestamp() -> str:
    """Get formatted timestamp for notifications.

    Returns:
        ISO format timestamp.
    """
    return datetime.now(UTC).isoformat()
