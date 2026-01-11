"""Slack webhook action for sending notifications.

This module implements the Slack action for sending notifications
via Slack webhooks. It includes:
- Webhook message posting (T082)
- Retry semantics with exponential backoff (T083)
- Rate limiting to prevent abuse (T084)
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar

import httpx

if TYPE_CHECKING:
    from concierge.rules.schema import Match

logger = logging.getLogger(__name__)


# =============================================================================
# Rate Limiter (T084)
# =============================================================================


@dataclass
class RateLimiter:
    """Simple rate limiter for Slack messages.

    Implements a sliding window rate limiter to ensure we don't
    exceed the max messages per minute limit.

    Attributes:
        max_requests: Maximum number of requests in the time window.
        window_seconds: Time window in seconds (default: 60).
    """

    max_requests: int = 10
    window_seconds: int = 60
    _timestamps: deque[float] = field(default_factory=deque)

    def acquire(self) -> bool:
        """Try to acquire a rate limit slot.

        Returns:
            True if request is allowed, False if rate limited.
        """
        now = time.monotonic()
        cutoff = now - self.window_seconds

        # Remove expired timestamps
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()

        # Check if we have capacity
        if len(self._timestamps) >= self.max_requests:
            return False

        # Record this request
        self._timestamps.append(now)
        return True

    def time_until_available(self) -> float:
        """Get time in seconds until a slot is available.

        Returns:
            Seconds to wait, or 0 if available now.
        """
        if len(self._timestamps) < self.max_requests:
            return 0.0

        now = time.monotonic()
        oldest = self._timestamps[0]
        wait_time = (oldest + self.window_seconds) - now
        return max(0.0, wait_time)

    @property
    def current_usage(self) -> int:
        """Get current number of requests in the window."""
        now = time.monotonic()
        cutoff = now - self.window_seconds

        # Clean up expired
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()

        return len(self._timestamps)


# =============================================================================
# Slack Action (T082, T083)
# =============================================================================


@dataclass
class SlackResult:
    """Result of a Slack message send attempt."""

    success: bool
    message: str
    status_code: int | None = None
    attempts: int = 1


class SlackAction:
    """Action that sends notifications to Slack via webhook.

    Features:
    - Sends messages to Slack webhooks (T082)
    - Retry semantics: 3 attempts with 1s→2s→4s backoff (T083)
    - Rate limiting: max 10 messages/minute (T084)
    """

    # Retry configuration (T083)
    MAX_RETRIES = 3
    RETRY_DELAYS: ClassVar[list[int]] = [1, 2, 4]  # Seconds: 1s → 2s → 4s

    # Rate limit configuration (T084)
    RATE_LIMIT_MAX = 10
    RATE_LIMIT_WINDOW = 60  # seconds

    def __init__(
        self,
        webhook_url: str,
        *,
        rate_limiter: RateLimiter | None = None,
        timeout: float = 10.0,
    ) -> None:
        """Initialize Slack action.

        Args:
            webhook_url: Slack webhook URL.
            rate_limiter: Optional custom rate limiter.
            timeout: HTTP request timeout in seconds.
        """
        self._webhook_url = webhook_url
        self._timeout = timeout
        self._rate_limiter = rate_limiter or RateLimiter(
            max_requests=self.RATE_LIMIT_MAX,
            window_seconds=self.RATE_LIMIT_WINDOW,
        )

    @property
    def webhook_url(self) -> str:
        """Get the webhook URL (masked for logging)."""
        if len(self._webhook_url) > 40:
            return self._webhook_url[:30] + "..." + self._webhook_url[-5:]
        return "***masked***"

    def execute(
        self,
        match: Match,
        message: str | None = None,
    ) -> SlackResult:
        """Execute the Slack action synchronously.

        Args:
            match: Match containing event and rule info.
            message: Message to send (or uses default format).

        Returns:
            SlackResult with success status.
        """
        # Check rate limit
        if not self._rate_limiter.acquire():
            wait_time = self._rate_limiter.time_until_available()
            logger.warning(
                "Slack rate limit exceeded. Wait %.1f seconds.",
                wait_time,
            )
            return SlackResult(
                success=False,
                message=f"Rate limited. Wait {wait_time:.1f}s",
                attempts=0,
            )

        # Format message
        text = message or self._format_default_message(match)
        payload = self._build_payload(match, text)

        # Send with retries
        return self._send_with_retries(payload)

    async def execute_async(
        self,
        match: Match,
        message: str | None = None,
    ) -> SlackResult:
        """Execute the Slack action asynchronously.

        Args:
            match: Match containing event and rule info.
            message: Message to send (or uses default format).

        Returns:
            SlackResult with success status.
        """
        # Check rate limit
        if not self._rate_limiter.acquire():
            wait_time = self._rate_limiter.time_until_available()
            logger.warning(
                "Slack rate limit exceeded. Wait %.1f seconds.",
                wait_time,
            )
            return SlackResult(
                success=False,
                message=f"Rate limited. Wait {wait_time:.1f}s",
                attempts=0,
            )

        # Format message
        text = message or self._format_default_message(match)
        payload = self._build_payload(match, text)

        # Send with retries
        return await self._send_with_retries_async(payload)

    def _build_payload(
        self,
        match: Match,
        text: str,
    ) -> dict[str, Any]:
        """Build Slack message payload.

        Creates a rich message with attachments for better formatting.

        Args:
            match: Match for context.
            text: Main message text.

        Returns:
            Slack webhook payload.
        """
        event = match.event

        # Build attachment for rich formatting
        attachment: dict[str, Any] = {
            "color": self._get_color_for_event(match),
            "title": f"{event.repo_full_name}",
            "text": text,
            "footer": f"Rule: {match.rule.id}",
            "ts": int(datetime.now(UTC).timestamp()),
        }

        # Add entity link if available
        if event.entity_url:
            if event.entity_number and event.entity_title:
                attachment["title"] = (
                    f"{event.repo_full_name}#{event.entity_number}: {event.entity_title}"
                )
            elif event.entity_number:
                attachment["title"] = f"{event.repo_full_name}#{event.entity_number}"
            attachment["title_link"] = event.entity_url

        # Add fields for additional context
        fields = []
        if event.event_type:
            fields.append({
                "title": "Event Type",
                "value": event.event_type.value,
                "short": True,
            })
        if event.actor:
            fields.append({
                "title": "Actor",
                "value": event.actor,
                "short": True,
            })
        if fields:
            attachment["fields"] = fields

        return {"attachments": [attachment]}

    def _get_color_for_event(self, match: Match) -> str:
        """Get attachment color based on event type.

        Args:
            match: Match with event info.

        Returns:
            Hex color code.
        """
        event_type = match.event.event_type.value.lower()

        color_map = {
            "mention": "#36a64f",  # Green
            "review_requested": "#2eb886",  # Teal
            "assign": "#3aa3e3",  # Blue
            "security_alert": "#dc3545",  # Red
            "ci_status": "#ffc107",  # Yellow
        }

        return color_map.get(event_type, "#439fe0")  # Default blue

    def _format_default_message(self, match: Match) -> str:
        """Format a default message for the notification.

        Args:
            match: Match for context.

        Returns:
            Formatted message string.
        """
        event = match.event
        parts = [f"*{event.event_type.value.upper()}*"]

        if event.entity_title:
            parts.append(f": {event.entity_title}")

        parts.append(f"\n_{match.match_reason}_")

        return "".join(parts)

    def _send_with_retries(self, payload: dict[str, Any]) -> SlackResult:
        """Send message with retry logic (synchronous).

        Implements T083: 3 attempts with 1s→2s→4s backoff.

        Args:
            payload: Slack webhook payload.

        Returns:
            SlackResult with attempt count.
        """
        last_error = ""
        last_status: int | None = None

        for attempt in range(self.MAX_RETRIES):
            try:
                with httpx.Client(timeout=self._timeout) as client:
                    response = client.post(
                        self._webhook_url,
                        json=payload,
                    )
                    last_status = response.status_code

                    if response.status_code == 200:
                        logger.debug(
                            "Slack message sent successfully (attempt %d)",
                            attempt + 1,
                        )
                        return SlackResult(
                            success=True,
                            message="Message sent",
                            status_code=200,
                            attempts=attempt + 1,
                        )

                    # Non-retryable errors
                    if response.status_code in (400, 403, 404):
                        last_error = f"HTTP {response.status_code}: {response.text}"
                        break

                    # Retryable error
                    last_error = f"HTTP {response.status_code}"

            except httpx.TimeoutException:
                last_error = "Request timeout"
            except httpx.RequestError as e:
                last_error = f"Request error: {e}"

            # Wait before retry (T083: 1s → 2s → 4s)
            if attempt < self.MAX_RETRIES - 1:
                delay = self.RETRY_DELAYS[attempt]
                logger.warning(
                    "Slack send failed (attempt %d/%d): %s. Retrying in %ds...",
                    attempt + 1,
                    self.MAX_RETRIES,
                    last_error,
                    delay,
                )
                time.sleep(delay)

        logger.error(
            "Slack send failed after %d attempts: %s",
            self.MAX_RETRIES,
            last_error,
        )
        return SlackResult(
            success=False,
            message=last_error,
            status_code=last_status,
            attempts=self.MAX_RETRIES,
        )

    async def _send_with_retries_async(
        self,
        payload: dict[str, Any],
    ) -> SlackResult:
        """Send message with retry logic (asynchronous).

        Implements T083: 3 attempts with 1s→2s→4s backoff.

        Args:
            payload: Slack webhook payload.

        Returns:
            SlackResult with attempt count.
        """
        last_error = ""
        last_status: int | None = None

        for attempt in range(self.MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(
                        self._webhook_url,
                        json=payload,
                    )
                    last_status = response.status_code

                    if response.status_code == 200:
                        logger.debug(
                            "Slack message sent successfully (attempt %d)",
                            attempt + 1,
                        )
                        return SlackResult(
                            success=True,
                            message="Message sent",
                            status_code=200,
                            attempts=attempt + 1,
                        )

                    # Non-retryable errors
                    if response.status_code in (400, 403, 404):
                        last_error = f"HTTP {response.status_code}: {response.text}"
                        break

                    # Retryable error
                    last_error = f"HTTP {response.status_code}"

            except httpx.TimeoutException:
                last_error = "Request timeout"
            except httpx.RequestError as e:
                last_error = f"Request error: {e}"

            # Wait before retry (T083: 1s → 2s → 4s)
            if attempt < self.MAX_RETRIES - 1:
                delay = self.RETRY_DELAYS[attempt]
                logger.warning(
                    "Slack send failed (attempt %d/%d): %s. Retrying in %ds...",
                    attempt + 1,
                    self.MAX_RETRIES,
                    last_error,
                    delay,
                )
                await asyncio.sleep(delay)

        logger.error(
            "Slack send failed after %d attempts: %s",
            self.MAX_RETRIES,
            last_error,
        )
        return SlackResult(
            success=False,
            message=last_error,
            status_code=last_status,
            attempts=self.MAX_RETRIES,
        )
