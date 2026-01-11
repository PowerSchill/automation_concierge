"""GitHub comment action for posting comments on issues/PRs.

This module implements the GitHub comment action for posting
comments on issues and pull requests. It includes:
- Comment posting via GitHub API (T085)
- opt_in validation for safety (T086)
- Retry semantics with backoff (T087)
- Rate limiting per issue (T088)
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar

import httpx

if TYPE_CHECKING:
    from concierge.rules.schema import Match

logger = logging.getLogger(__name__)


# =============================================================================
# Rate Limiter (T088)
# =============================================================================


@dataclass
class IssueRateLimiter:
    """Rate limiter for GitHub comments per issue.

    Implements T088: max 1 comment per issue per hour.

    Tracks the last comment time for each issue and prevents
    excessive commenting on the same issue.

    Attributes:
        window_seconds: Time window in seconds (default: 3600 = 1 hour).
    """

    window_seconds: int = 3600
    _last_comment: dict[str, float] = field(default_factory=lambda: defaultdict(float))

    def can_comment(self, issue_key: str) -> bool:
        """Check if we can comment on this issue.

        Args:
            issue_key: Unique issue identifier (e.g., "owner/repo#123").

        Returns:
            True if comment is allowed, False if rate limited.
        """
        now = time.monotonic()
        last = self._last_comment.get(issue_key, 0.0)

        return not (now - last < self.window_seconds)

    def record_comment(self, issue_key: str) -> None:
        """Record that we commented on an issue.

        Args:
            issue_key: Unique issue identifier.
        """
        self._last_comment[issue_key] = time.monotonic()

    def time_until_available(self, issue_key: str) -> float:
        """Get time in seconds until we can comment again.

        Args:
            issue_key: Unique issue identifier.

        Returns:
            Seconds to wait, or 0 if available now.
        """
        now = time.monotonic()
        last = self._last_comment.get(issue_key, 0.0)
        wait_time = (last + self.window_seconds) - now
        return max(0.0, wait_time)

    def clear(self, issue_key: str | None = None) -> None:
        """Clear rate limit records.

        Args:
            issue_key: Specific issue to clear, or None to clear all.
        """
        if issue_key:
            self._last_comment.pop(issue_key, None)
        else:
            self._last_comment.clear()


# =============================================================================
# GitHub Comment Action (T085, T086, T087)
# =============================================================================


class OptInRequiredError(Exception):
    """Raised when opt_in is not set for GitHub comment action."""

    def __init__(self, message: str = "GitHub comment action requires opt_in: true") -> None:
        """Initialize the error."""
        super().__init__(message)


@dataclass
class GitHubCommentResult:
    """Result of a GitHub comment post attempt."""

    success: bool
    message: str
    comment_id: int | None = None
    comment_url: str | None = None
    status_code: int | None = None
    attempts: int = 1


class GitHubCommentAction:
    """Action that posts comments on GitHub issues/PRs.

    Features:
    - Posts comments via GitHub API (T085)
    - Requires opt_in for safety (T086)
    - Retry semantics: 2 attempts with 2s→5s backoff (T087)
    - Rate limiting: max 1 comment per issue per hour (T088)
    """

    # Retry configuration (T087)
    MAX_RETRIES = 2
    RETRY_DELAYS: ClassVar[list[int]] = [2, 5]  # Seconds: 2s → 5s

    # Rate limit configuration (T088)
    RATE_LIMIT_WINDOW = 3600  # 1 hour

    def __init__(
        self,
        token: str,
        *,
        base_url: str = "https://api.github.com",
        rate_limiter: IssueRateLimiter | None = None,
        timeout: float = 15.0,
    ) -> None:
        """Initialize GitHub comment action.

        Args:
            token: GitHub personal access token.
            base_url: GitHub API base URL.
            rate_limiter: Optional custom rate limiter.
            timeout: HTTP request timeout in seconds.
        """
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._rate_limiter = rate_limiter or IssueRateLimiter(
            window_seconds=self.RATE_LIMIT_WINDOW,
        )

    @property
    def headers(self) -> dict[str, str]:
        """Get request headers."""
        return {
            "Authorization": f"token {self._token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "automation-concierge/0.1.0",
        }

    def validate_opt_in(self, opt_in: bool | None) -> None:
        """Validate that opt_in is explicitly set to True.

        Implements T086: Safety gate for GitHub comments.

        Args:
            opt_in: The opt_in value from action config.

        Raises:
            OptInRequiredError: If opt_in is not True.
        """
        if opt_in is not True:
            raise OptInRequiredError(
                "GitHub comment action requires 'opt_in: true' in action config. "
                "This is a safety measure to prevent accidental comment spam."
            )

    def execute(
        self,
        match: Match,
        message: str,
        *,
        opt_in: bool | None = None,
    ) -> GitHubCommentResult:
        """Execute the GitHub comment action synchronously.

        Args:
            match: Match containing event and rule info.
            message: Comment body to post.
            opt_in: Must be True to allow commenting (T086).

        Returns:
            GitHubCommentResult with success status.
        """
        # Validate opt_in (T086)
        try:
            self.validate_opt_in(opt_in)
        except OptInRequiredError as e:
            logger.error("GitHub comment blocked: %s", e)
            return GitHubCommentResult(
                success=False,
                message=str(e),
                attempts=0,
            )

        event = match.event

        # Validate we have entity info
        if not event.entity_number:
            return GitHubCommentResult(
                success=False,
                message="Event has no entity number for commenting",
                attempts=0,
            )

        # Build issue key for rate limiting
        issue_key = f"{event.repo_full_name}#{event.entity_number}"

        # Check rate limit (T088)
        if not self._rate_limiter.can_comment(issue_key):
            wait_time = self._rate_limiter.time_until_available(issue_key)
            logger.warning(
                "GitHub comment rate limited for %s. Wait %.0f seconds.",
                issue_key,
                wait_time,
            )
            return GitHubCommentResult(
                success=False,
                message=f"Rate limited for {issue_key}. Wait {wait_time:.0f}s",
                attempts=0,
            )

        # Build API URL
        url = (
            f"{self._base_url}/repos/{event.repo_owner}/{event.repo_name}"
            f"/issues/{event.entity_number}/comments"
        )

        # Send with retries
        result = self._send_with_retries(url, message)

        # Record successful comment for rate limiting
        if result.success:
            self._rate_limiter.record_comment(issue_key)

        return result

    async def execute_async(
        self,
        match: Match,
        message: str,
        *,
        opt_in: bool | None = None,
    ) -> GitHubCommentResult:
        """Execute the GitHub comment action asynchronously.

        Args:
            match: Match containing event and rule info.
            message: Comment body to post.
            opt_in: Must be True to allow commenting (T086).

        Returns:
            GitHubCommentResult with success status.
        """
        # Validate opt_in (T086)
        try:
            self.validate_opt_in(opt_in)
        except OptInRequiredError as e:
            logger.error("GitHub comment blocked: %s", e)
            return GitHubCommentResult(
                success=False,
                message=str(e),
                attempts=0,
            )

        event = match.event

        # Validate we have entity info
        if not event.entity_number:
            return GitHubCommentResult(
                success=False,
                message="Event has no entity number for commenting",
                attempts=0,
            )

        # Build issue key for rate limiting
        issue_key = f"{event.repo_full_name}#{event.entity_number}"

        # Check rate limit (T088)
        if not self._rate_limiter.can_comment(issue_key):
            wait_time = self._rate_limiter.time_until_available(issue_key)
            logger.warning(
                "GitHub comment rate limited for %s. Wait %.0f seconds.",
                issue_key,
                wait_time,
            )
            return GitHubCommentResult(
                success=False,
                message=f"Rate limited for {issue_key}. Wait {wait_time:.0f}s",
                attempts=0,
            )

        # Build API URL
        url = (
            f"{self._base_url}/repos/{event.repo_owner}/{event.repo_name}"
            f"/issues/{event.entity_number}/comments"
        )

        # Send with retries
        result = await self._send_with_retries_async(url, message)

        # Record successful comment for rate limiting
        if result.success:
            self._rate_limiter.record_comment(issue_key)

        return result

    def _send_with_retries(
        self,
        url: str,
        body: str,
    ) -> GitHubCommentResult:
        """Send comment with retry logic (synchronous).

        Implements T087: 2 attempts with 2s→5s backoff.

        Args:
            url: GitHub API URL for comments.
            body: Comment body.

        Returns:
            GitHubCommentResult with attempt count.
        """
        last_error = ""
        last_status: int | None = None
        payload = {"body": body}

        for attempt in range(self.MAX_RETRIES):
            try:
                with httpx.Client(timeout=self._timeout) as client:
                    response = client.post(
                        url,
                        json=payload,
                        headers=self.headers,
                    )
                    last_status = response.status_code

                    if response.status_code == 201:
                        data = response.json()
                        logger.info(
                            "GitHub comment posted successfully (attempt %d)",
                            attempt + 1,
                        )
                        return GitHubCommentResult(
                            success=True,
                            message="Comment posted",
                            comment_id=data.get("id"),
                            comment_url=data.get("html_url"),
                            status_code=201,
                            attempts=attempt + 1,
                        )

                    # Non-retryable errors
                    if response.status_code in (401, 403, 404, 422):
                        last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                        break

                    # Retryable error
                    last_error = f"HTTP {response.status_code}"

            except httpx.TimeoutException:
                last_error = "Request timeout"
            except httpx.RequestError as e:
                last_error = f"Request error: {e}"

            # Wait before retry (T087: 2s → 5s)
            if attempt < self.MAX_RETRIES - 1:
                delay = self.RETRY_DELAYS[attempt]
                logger.warning(
                    "GitHub comment failed (attempt %d/%d): %s. Retrying in %ds...",
                    attempt + 1,
                    self.MAX_RETRIES,
                    last_error,
                    delay,
                )
                time.sleep(delay)

        logger.error(
            "GitHub comment failed after %d attempts: %s",
            self.MAX_RETRIES,
            last_error,
        )
        return GitHubCommentResult(
            success=False,
            message=last_error,
            status_code=last_status,
            attempts=self.MAX_RETRIES,
        )

    async def _send_with_retries_async(
        self,
        url: str,
        body: str,
    ) -> GitHubCommentResult:
        """Send comment with retry logic (asynchronous).

        Implements T087: 2 attempts with 2s→5s backoff.

        Args:
            url: GitHub API URL for comments.
            body: Comment body.

        Returns:
            GitHubCommentResult with attempt count.
        """
        last_error = ""
        last_status: int | None = None
        payload = {"body": body}

        for attempt in range(self.MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(
                        url,
                        json=payload,
                        headers=self.headers,
                    )
                    last_status = response.status_code

                    if response.status_code == 201:
                        data = response.json()
                        logger.info(
                            "GitHub comment posted successfully (attempt %d)",
                            attempt + 1,
                        )
                        return GitHubCommentResult(
                            success=True,
                            message="Comment posted",
                            comment_id=data.get("id"),
                            comment_url=data.get("html_url"),
                            status_code=201,
                            attempts=attempt + 1,
                        )

                    # Non-retryable errors
                    if response.status_code in (401, 403, 404, 422):
                        last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                        break

                    # Retryable error
                    last_error = f"HTTP {response.status_code}"

            except httpx.TimeoutException:
                last_error = "Request timeout"
            except httpx.RequestError as e:
                last_error = f"Request error: {e}"

            # Wait before retry (T087: 2s → 5s)
            if attempt < self.MAX_RETRIES - 1:
                delay = self.RETRY_DELAYS[attempt]
                logger.warning(
                    "GitHub comment failed (attempt %d/%d): %s. Retrying in %ds...",
                    attempt + 1,
                    self.MAX_RETRIES,
                    last_error,
                    delay,
                )
                await asyncio.sleep(delay)

        logger.error(
            "GitHub comment failed after %d attempts: %s",
            self.MAX_RETRIES,
            last_error,
        )
        return GitHubCommentResult(
            success=False,
            message=last_error,
            status_code=last_status,
            attempts=self.MAX_RETRIES,
        )
