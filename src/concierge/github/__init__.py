"""GitHub API client and event normalization."""

from concierge.github.auth import (
    AuthenticationError,
    validate_token,
)
from concierge.github.client import (
    GitHubClient,
    RateLimitError,
)
from concierge.github.events import (
    Event,
    EventSource,
    EventType,
    normalize_notification,
)

__all__ = [
    "AuthenticationError",
    "Event",
    "EventSource",
    "EventType",
    "GitHubClient",
    "RateLimitError",
    "normalize_notification",
    "validate_token",
]
