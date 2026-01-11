"""Logging module for Personal Automation Concierge.

This module provides structured JSON logging with:
- structlog configuration for consistent log formatting
- Secret redaction for GITHUB_TOKEN and webhook URLs
- Audit logging for decision trails
- Structured log events for event processing

Usage:
    from concierge.logging import configure_logging, log_decision

    configure_logging(verbose=True)
    log_decision(event, rules_evaluated, actions_taken, disposition)
"""

from concierge.logging.audit import (
    configure_logging,
    get_logger,
    log_action_taken,
    log_decision,
    log_event_received,
    log_poll_cycle,
    log_rate_limit,
    log_rule_evaluated,
    redact_secrets,
)

__all__ = [
    "configure_logging",
    "get_logger",
    "log_action_taken",
    "log_decision",
    "log_event_received",
    "log_poll_cycle",
    "log_rate_limit",
    "log_rule_evaluated",
    "redact_secrets",
]
