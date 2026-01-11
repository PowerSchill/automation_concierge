"""Logging module for Personal Automation Concierge.

This module provides structured JSON logging with:
- structlog configuration for consistent log formatting
- Secret redaction for GITHUB_TOKEN and webhook URLs
- Audit logging for decision trails

Usage:
    from concierge.logging import configure_logging, log_decision

    configure_logging(verbose=True)
    log_decision(event, rules_evaluated, actions_taken, disposition)
"""

from concierge.logging.audit import (
    configure_logging,
    get_logger,
    log_decision,
    redact_secrets,
)

__all__ = [
    "configure_logging",
    "get_logger",
    "log_decision",
    "redact_secrets",
]
