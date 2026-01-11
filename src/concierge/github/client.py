"""GitHub API client with rate limiting and pagination."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import httpx

from concierge.github.auth import get_github_token, mask_token

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)


class RateLimitError(Exception):
    """Raised when GitHub API rate limit is exceeded."""

    def __init__(
        self,
        message: str,
        *,
        reset_at: datetime | None = None,
        remaining: int = 0,
        limit: int = 5000,
    ) -> None:
        """Initialize rate limit error.

        Args:
            message: Error description.
            reset_at: When the rate limit resets.
            remaining: Remaining requests.
            limit: Total rate limit.
        """
        super().__init__(message)
        self.reset_at = reset_at
        self.remaining = remaining
        self.limit = limit


class GitHubAPIError(Exception):
    """Raised for GitHub API errors."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_body: dict[str, Any] | None = None,
    ) -> None:
        """Initialize GitHub API error.

        Args:
            message: Error description.
            status_code: HTTP status code.
            response_body: Response JSON body if available.
        """
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body or {}


@dataclass
class RateLimitInfo:
    """GitHub API rate limit information."""

    limit: int
    remaining: int
    reset_at: datetime
    used: int

    @classmethod
    def from_headers(cls, headers: httpx.Headers) -> RateLimitInfo:
        """Parse rate limit info from response headers.

        Args:
            headers: HTTP response headers.

        Returns:
            RateLimitInfo instance.
        """
        limit = int(headers.get("X-RateLimit-Limit", 5000))
        remaining = int(headers.get("X-RateLimit-Remaining", 0))
        reset_timestamp = int(headers.get("X-RateLimit-Reset", 0))
        used = int(headers.get("X-RateLimit-Used", 0))

        reset_at = datetime.fromtimestamp(reset_timestamp, tz=UTC)

        return cls(
            limit=limit,
            remaining=remaining,
            reset_at=reset_at,
            used=used,
        )

    @property
    def seconds_until_reset(self) -> float:
        """Get seconds until rate limit resets."""
        now = datetime.now(UTC)
        delta = (self.reset_at - now).total_seconds()
        return max(0, delta)


class GitHubClient:
    """Async GitHub API client with rate limiting and pagination."""

    # Threshold to pause before hitting rate limit
    RATE_LIMIT_THRESHOLD = 100

    def __init__(
        self,
        token: str | None = None,
        *,
        base_url: str = "https://api.github.com",
        user_agent: str = "automation-concierge/0.1.0",
    ) -> None:
        """Initialize GitHub client.

        Args:
            token: GitHub personal access token. If None, reads from GITHUB_TOKEN.
            base_url: GitHub API base URL.
            user_agent: User-Agent header value.
        """
        self._token = token if token is not None else get_github_token()
        self._base_url = base_url.rstrip("/")
        self._user_agent = user_agent
        self._client: httpx.AsyncClient | None = None
        self._rate_limit: RateLimitInfo | None = None

    @property
    def headers(self) -> dict[str, str]:
        """Get default request headers."""
        return {
            "Authorization": f"token {self._token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": self._user_agent,
        }

    async def __aenter__(self) -> GitHubClient:
        """Enter async context."""
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=self.headers,
            timeout=30.0,
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Exit async context."""
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def rate_limit(self) -> RateLimitInfo | None:
        """Get current rate limit information."""
        return self._rate_limit

    async def _ensure_client(self) -> httpx.AsyncClient:
        """Ensure we have an active client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers=self.headers,
                timeout=30.0,
            )
        return self._client

    async def _check_rate_limit(self) -> None:
        """Check if we should pause due to rate limiting.

        This method checks the current rate limit status and pauses
        if we're getting close to the limit.
        """
        if self._rate_limit is None:
            return

        if self._rate_limit.remaining < self.RATE_LIMIT_THRESHOLD:
            wait_time = self._rate_limit.seconds_until_reset + 10  # Add 10s buffer
            logger.warning(
                "Rate limit low (%d remaining), pausing for %.0f seconds",
                self._rate_limit.remaining,
                wait_time,
            )
            await asyncio.sleep(wait_time)

    async def _handle_response(
        self,
        response: httpx.Response,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """Handle API response and update rate limit info.

        Args:
            response: HTTP response.

        Returns:
            Parsed JSON response.

        Raises:
            RateLimitError: If rate limit exceeded.
            GitHubAPIError: For other API errors.
        """
        # Update rate limit info
        self._rate_limit = RateLimitInfo.from_headers(response.headers)

        if response.status_code == 200:
            return response.json()  # type: ignore[no-any-return]

        if response.status_code == 304:
            # Not Modified - return empty list for conditional requests
            return []

        if response.status_code == 403:
            # Check if it's a rate limit error
            body = response.json() if response.content else {}
            message = body.get("message", "")

            if "rate limit" in message.lower():
                raise RateLimitError(
                    f"GitHub API rate limit exceeded: {message}",
                    reset_at=self._rate_limit.reset_at,
                    remaining=self._rate_limit.remaining,
                    limit=self._rate_limit.limit,
                )

            # Secondary rate limit (abuse detection)
            if "secondary rate limit" in message.lower():
                # Wait and retry
                retry_after = int(response.headers.get("Retry-After", 60))
                logger.warning(
                    "Secondary rate limit hit, waiting %d seconds",
                    retry_after,
                )
                await asyncio.sleep(retry_after)
                raise RateLimitError(
                    f"GitHub secondary rate limit: {message}",
                    reset_at=self._rate_limit.reset_at,
                    remaining=self._rate_limit.remaining,
                    limit=self._rate_limit.limit,
                )

            raise GitHubAPIError(
                f"GitHub API access denied: {message}",
                status_code=403,
                response_body=body,
            )

        if response.status_code == 401:
            raise GitHubAPIError(
                "GitHub API authentication failed",
                status_code=401,
            )

        if response.status_code >= 500:
            raise GitHubAPIError(
                f"GitHub API server error: {response.status_code}",
                status_code=response.status_code,
            )

        # Other errors
        try:
            body = response.json()
        except Exception:
            body = {"message": response.text}

        raise GitHubAPIError(
            f"GitHub API error: {response.status_code} - {body.get('message', 'Unknown error')}",
            status_code=response.status_code,
            response_body=body,
        )

    async def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """Make a GET request to the GitHub API.

        Args:
            path: API path (e.g., "/notifications").
            params: Query parameters.

        Returns:
            Parsed JSON response.
        """
        await self._check_rate_limit()
        client = await self._ensure_client()

        response = await client.get(path, params=params)
        return await self._handle_response(response)

    async def get_paginated(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        max_pages: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Make paginated GET requests to the GitHub API.

        Args:
            path: API path.
            params: Query parameters.
            max_pages: Maximum number of pages to fetch (None for unlimited).

        Yields:
            Items from each page.
        """
        await self._check_rate_limit()
        client = await self._ensure_client()

        params = dict(params or {})
        params.setdefault("per_page", 100)

        next_url: str | None = path
        page_count = 0

        while next_url:
            if max_pages and page_count >= max_pages:
                break

            # Determine if this is a full URL or a path
            if next_url.startswith("http"):
                response = await client.get(next_url)
            else:
                response = await client.get(next_url, params=params)

            result = await self._handle_response(response)

            # Yield items
            if isinstance(result, list):
                for item in result:
                    yield item
            else:
                yield result

            page_count += 1

            # Parse Link header for next page
            next_url = self._parse_next_link(response.headers.get("Link", ""))

            # Clear params for subsequent requests (they're in the URL)
            params = {}

    @staticmethod
    def _parse_next_link(link_header: str) -> str | None:
        """Parse the 'next' URL from Link header.

        Args:
            link_header: Link header value.

        Returns:
            Next page URL or None.
        """
        if not link_header:
            return None

        # Link header format: <url>; rel="next", <url>; rel="last"
        for part in link_header.split(","):
            match = re.match(r'<([^>]+)>;\s*rel="next"', part.strip())
            if match:
                return match.group(1)

        return None

    async def get_notifications(
        self,
        *,
        all_notifications: bool = False,
        participating: bool = False,
        since: datetime | None = None,
        before: datetime | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Get GitHub notifications.

        Args:
            all_notifications: If True, show read notifications too.
            participating: If True, only participating notifications.
            since: Only notifications updated after this time.
            before: Only notifications updated before this time.

        Yields:
            Notification objects.
        """
        params: dict[str, Any] = {
            "all": str(all_notifications).lower(),
            "participating": str(participating).lower(),
        }

        if since:
            params["since"] = since.isoformat()
        if before:
            params["before"] = before.isoformat()

        async for notification in self.get_paginated(
            "/notifications",
            params=params,
        ):
            yield notification

    async def get_rate_limit(self) -> dict[str, Any]:
        """Get current rate limit status.

        Returns:
            Rate limit information from /rate_limit endpoint.
        """
        result = await self.get("/rate_limit")
        if isinstance(result, dict):
            return result
        return {}

    async def get_issue(
        self,
        owner: str,
        repo: str,
        issue_number: int,
    ) -> dict[str, Any]:
        """Get issue or pull request details.

        Args:
            owner: Repository owner.
            repo: Repository name.
            issue_number: Issue or PR number.

        Returns:
            Issue/PR data.
        """
        result = await self.get(f"/repos/{owner}/{repo}/issues/{issue_number}")
        if isinstance(result, dict):
            return result
        return {}

    async def get_pull_request(
        self,
        owner: str,
        repo: str,
        pr_number: int,
    ) -> dict[str, Any]:
        """Get pull request details.

        Args:
            owner: Repository owner.
            repo: Repository name.
            pr_number: PR number.

        Returns:
            Pull request data.
        """
        result = await self.get(f"/repos/{owner}/{repo}/pulls/{pr_number}")
        if isinstance(result, dict):
            return result
        return {}

    def __repr__(self) -> str:
        """Get string representation."""
        return (
            f"GitHubClient(base_url={self._base_url!r}, "
            f"token={mask_token(self._token)!r})"
        )
