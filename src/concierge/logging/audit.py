"""Structured JSON logging and audit trail functionality.

This module provides:
- structlog configuration for JSON logging to stderr
- Secret redaction for sensitive values (GITHUB_TOKEN, webhook URLs)
- Structured log events for event processing, rule evaluation, action execution
- Audit log decision formatting
"""

from __future__ import annotations

import logging
import re
import sys
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from collections.abc import Callable

    from structlog.typing import EventDict, WrappedLogger

# Patterns for secret redaction
SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # GitHub tokens (ghp_, gho_, ghu_, ghs_, ghr_ prefixes)
    (re.compile(r"(gh[pousr]_[A-Za-z0-9_]{36,})"), "[REDACTED_GITHUB_TOKEN]"),
    # Generic tokens that look like they might be sensitive
    (re.compile(r"(token[=:]\s*['\"]?)([A-Za-z0-9_-]{20,})"), r"\1[REDACTED]"),
    # Slack webhook URLs
    (
        re.compile(r"(https://hooks\.slack\.com/services/)([A-Z0-9/]+)"),
        r"\1[REDACTED]",
    ),
    # Generic webhook URLs with tokens
    (re.compile(r"(webhook[_-]?url[=:]\s*['\"]?)([^\s'\"]+)"), r"\1[REDACTED_URL]"),
    # Bearer tokens in headers
    (re.compile(r"(Bearer\s+)([A-Za-z0-9._-]+)", re.IGNORECASE), r"\1[REDACTED]"),
    # Authorization headers
    (re.compile(r"(authorization[=:]\s*['\"]?)([^\s'\"]+)", re.IGNORECASE), r"\1[REDACTED]"),
]


def redact_secrets(value: Any) -> Any:
    """Redact sensitive values from a string, dict, or list.

    Applies pattern-based redaction for:
    - GitHub tokens (ghp_, gho_, etc.)
    - Slack webhook URLs
    - Authorization headers
    - Generic tokens

    Args:
        value: Value to redact. Can be str, dict, list, or other.

    Returns:
        Value with sensitive data redacted
    """
    if isinstance(value, str):
        result = value
        for pattern, replacement in SECRET_PATTERNS:
            result = pattern.sub(replacement, result)
        return result

    if isinstance(value, dict):
        return {k: redact_secrets(v) for k, v in value.items()}

    if isinstance(value, list):
        return [redact_secrets(item) for item in value]

    return value


def _redact_processor(
    _logger: WrappedLogger,
    _method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """structlog processor that redacts secrets from log events.

    Args:
        logger: The wrapped logger
        method_name: The name of the method called
        event_dict: The event dictionary

    Returns:
        Event dictionary with secrets redacted
    """
    return redact_secrets(event_dict)


def configure_logging(
    verbose: bool = False,
    json_output: bool = True,
) -> None:
    """Configure structured logging for the application.

    Sets up structlog with JSON formatting to stderr, including:
    - Timestamp in ISO format
    - Log level
    - Secret redaction
    - Exception formatting

    Args:
        verbose: If True, enable DEBUG level. Otherwise INFO.
        json_output: If True, output JSON. Otherwise use console format.
    """
    level = logging.DEBUG if verbose else logging.INFO

    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=level,
    )

    # Build processor chain
    processors: list[Callable[..., Any]] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _redact_processor,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if json_output:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a configured structlog logger.

    Args:
        name: Optional logger name (typically __name__)

    Returns:
        Bound structlog logger
    """
    return structlog.get_logger(name)


def log_decision(
    event_id: str,
    event_type: str,
    event_source: str,
    rules_evaluated: list[dict[str, Any]],
    actions_taken: list[dict[str, Any]],
    disposition: str,
    message: str,
) -> None:
    """Log a full decision trail for an event.

    This creates a structured log entry with the complete audit trail,
    including which rules were evaluated, which matched, and what
    actions were taken.

    Args:
        event_id: Unique event identifier
        event_type: Type of event (e.g., 'mention')
        event_source: Source string (e.g., 'owner/repo#123')
        rules_evaluated: List of rule evaluation results
        actions_taken: List of action execution results
        disposition: Final disposition (e.g., 'action_executed')
        message: Human-readable summary
    """
    log = get_logger("concierge.audit")

    # Count matches and actions
    matched_count = sum(1 for r in rules_evaluated if r.get("matched"))
    success_count = sum(1 for a in actions_taken if a.get("result") == "success")

    log.info(
        "decision",
        event_id=event_id,
        event_type=event_type,
        event_source=event_source,
        rules_evaluated=rules_evaluated,
        rules_matched=matched_count,
        actions_taken=actions_taken,
        actions_succeeded=success_count,
        disposition=disposition,
        message=message,
    )


# Structured log event helpers


def log_event_received(
    event_id: str,
    event_type: str,
    event_source: str,
) -> None:
    """Log when an event is received from GitHub.

    Args:
        event_id: Unique event identifier
        event_type: Type of event
        event_source: Source string
    """
    log = get_logger("concierge.events")
    log.debug(
        "event_received",
        event_id=event_id,
        event_type=event_type,
        event_source=event_source,
    )


def log_rule_evaluated(
    event_id: str,
    rule_id: str,
    rule_name: str,
    matched: bool,
    match_reason: str,
) -> None:
    """Log when a rule is evaluated against an event.

    Args:
        event_id: Event being evaluated
        rule_id: Rule identifier
        rule_name: Human-readable rule name
        matched: Whether the rule matched
        match_reason: Explanation of match/no-match
    """
    log = get_logger("concierge.rules")
    log.debug(
        "rule_evaluated",
        event_id=event_id,
        rule_id=rule_id,
        rule_name=rule_name,
        matched=matched,
        match_reason=match_reason,
    )


def log_action_taken(
    event_id: str,
    rule_id: str,
    action_type: str,
    target: str,
    result: str,
    message_preview: str | None = None,
    error: str | None = None,
) -> None:
    """Log when an action is executed.

    Args:
        event_id: Event that triggered the action
        rule_id: Rule that matched
        action_type: Type of action (e.g., 'slack')
        target: Where action was sent
        result: Result status ('success', 'failed', etc.)
        message_preview: First 100 chars of message
        error: Error message if failed
    """
    log = get_logger("concierge.actions")

    log_func = log.info if result == "success" else log.warning

    log_func(
        "action_taken",
        event_id=event_id,
        rule_id=rule_id,
        action_type=action_type,
        target=target,
        result=result,
        message_preview=message_preview,
        error=error,
    )


def log_poll_cycle(
    events_fetched: int,
    events_processed: int,
    actions_taken: int,
    duration_ms: float,
) -> None:
    """Log poll cycle completion.

    Args:
        events_fetched: Number of events fetched from GitHub
        events_processed: Number of events actually processed (after dedupe)
        actions_taken: Number of actions executed
        duration_ms: Cycle duration in milliseconds
    """
    log = get_logger("concierge.poll")
    log.info(
        "poll_cycle_complete",
        events_fetched=events_fetched,
        events_processed=events_processed,
        actions_taken=actions_taken,
        duration_ms=round(duration_ms, 2),
    )


def log_rate_limit(
    remaining: int,
    limit: int,
    reset_at: str,
    pausing: bool = False,
) -> None:
    """Log rate limit status.

    Args:
        remaining: Remaining API calls
        limit: Total API call limit
        reset_at: ISO timestamp when limit resets
        pausing: Whether we're pausing due to low quota
    """
    log = get_logger("concierge.ratelimit")

    if pausing:
        log.warning(
            "rate_limit_pause",
            remaining=remaining,
            limit=limit,
            reset_at=reset_at,
            message=f"Pausing until {reset_at} (remaining: {remaining}/{limit})",
        )
    else:
        log.debug(
            "rate_limit_check",
            remaining=remaining,
            limit=limit,
            reset_at=reset_at,
        )
