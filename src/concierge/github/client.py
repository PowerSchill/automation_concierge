"""GitHub API client with rate limiting and pagination.

This module provides the GitHubClient class which handles:
- Rate limit checking with proactive pausing (pause when remaining < 100)
- Jitter on rate limit pauses (sleep until reset + random 0-10s jitter)
- 403 rate limit response handling with retry
- Exponential backoff for transient failures (5xx, network errors)
- Secondary rate limit (abuse detection) handling
- Lookback window for first run
- Entity cache for PR/issue details within poll cycles (T075)
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, ClassVar

import httpx

from concierge.github.auth import get_github_token, mask_token

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)

# Default lookback window for first run (1 hour in seconds)
DEFAULT_LOOKBACK_WINDOW = 3600


class RateLimitError(Exception):
    """Raised when GitHub API rate limit is exceeded."""

    def __init__(
        self,
        message: str,
        *,
        reset_at: datetime | None = None,
        remaining: int = 0,
        limit: int = 5000,
        is_secondary: bool = False,
    ) -> None:
        """Initialize rate limit error.

        Args:
            message: Error description.
            reset_at: When the rate limit resets.
            remaining: Remaining requests.
            limit: Total rate limit.
            is_secondary: Whether this is a secondary (abuse) rate limit.
        """
        super().__init__(message)
        self.reset_at = reset_at
        self.remaining = remaining
        self.limit = limit
        self.is_secondary = is_secondary


class TransientError(Exception):
    """Raised for transient errors that should be retried.

    This includes 5xx server errors and network connectivity errors.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after: int | None = None,
    ) -> None:
        """Initialize transient error.

        Args:
            message: Error description.
            status_code: HTTP status code if available.
            retry_after: Suggested retry delay in seconds.
        """
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


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


@dataclass
class EntityCache:
    """Cache for PR/issue details within a poll cycle (T075).

    This cache stores fetched entity data to avoid repeated API calls
    for the same entity within a single poll cycle. The cache is cleared
    at the start of each poll cycle.

    The cache uses a dict with keys in the format "owner/repo#number"
    to store both issues and pull requests.
    """

    _cache: dict[str, dict[str, Any]] = field(default_factory=dict)
    _created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    _hits: int = 0
    _misses: int = 0

    def get(self, owner: str, repo: str, number: int) -> dict[str, Any] | None:
        """Get cached entity data if available.

        Args:
            owner: Repository owner.
            repo: Repository name.
            number: Issue/PR number.

        Returns:
            Cached entity data or None if not cached.
        """
        key = self._make_key(owner, repo, number)
        data = self._cache.get(key)
        if data is not None:
            self._hits += 1
            logger.debug("Entity cache hit: %s", key)
        else:
            self._misses += 1
            logger.debug("Entity cache miss: %s", key)
        return data

    def put(
        self,
        owner: str,
        repo: str,
        number: int,
        data: dict[str, Any],
    ) -> None:
        """Store entity data in cache.

        Args:
            owner: Repository owner.
            repo: Repository name.
            number: Issue/PR number.
            data: Entity data to cache.
        """
        key = self._make_key(owner, repo, number)
        self._cache[key] = data
        logger.debug("Entity cached: %s", key)

    def clear(self) -> None:
        """Clear all cached data.

        Call this at the start of each poll cycle to ensure fresh data.
        """
        size = len(self._cache)
        if size > 0:
            logger.debug(
                "Clearing entity cache: %d entries, %d hits, %d misses",
                size,
                self._hits,
                self._misses,
            )
        self._cache.clear()
        self._hits = 0
        self._misses = 0
        self._created_at = datetime.now(UTC)

    @staticmethod
    def _make_key(owner: str, repo: str, number: int) -> str:
        """Create cache key from entity identifiers."""
        return f"{owner}/{repo}#{number}"

    @property
    def size(self) -> int:
        """Get number of cached entities."""
        return len(self._cache)

    @property
    def stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        return {
            "size": self.size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": (
                self._hits / (self._hits + self._misses)
                if (self._hits + self._misses) > 0
                else 0.0
            ),
            "created_at": self._created_at.isoformat(),
        }


class GitHubClient:
    """Async GitHub API client with rate limiting and pagination.

    Features:
    - Proactive rate limit checking (pause when remaining < 100)
    - Jitter on rate limit pauses (sleep until reset + random 0-10s)
    - 403 rate limit response handling with automatic retry
    - Exponential backoff for transient failures (5xx, network errors)
    - Secondary rate limit (abuse detection) handling
    - Lookback window for first run

    The client supports both context manager and standalone usage.
    """

    # Threshold to pause before hitting rate limit
    RATE_LIMIT_THRESHOLD = 100

    # Jitter range for rate limit pause (0-10 seconds)
    RATE_LIMIT_JITTER_MIN = 0
    RATE_LIMIT_JITTER_MAX = 10

    # Exponential backoff settings for transient errors
    MAX_RETRIES = 4
    INITIAL_BACKOFF_SECONDS = 60  # 1 minute
    MAX_BACKOFF_SECONDS = 480  # 8 minutes

    # Secondary rate limit backoff (abuse detection)
    SECONDARY_BACKOFF_MULTIPLIERS: ClassVar[list[int]] = [1, 2, 4, 8]  # minutes

    def __init__(
        self,
        token: str | None = None,
        *,
        base_url: str = "https://api.github.com",
        user_agent: str = "automation-concierge/0.1.0",
        lookback_window: int = DEFAULT_LOOKBACK_WINDOW,
    ) -> None:
        """Initialize GitHub client.

        Args:
            token: GitHub personal access token. If None, reads from GITHUB_TOKEN.
            base_url: GitHub API base URL.
            user_agent: User-Agent header value.
            lookback_window: How far back to look on first run in seconds (default: 3600).
        """
        self._token = token if token is not None else get_github_token()
        self._base_url = base_url.rstrip("/")
        self._user_agent = user_agent
        self._lookback_window = lookback_window
        self._client: httpx.AsyncClient | None = None
        self._rate_limit: RateLimitInfo | None = None
        self._secondary_rate_limit_retries = 0
        self._entity_cache = EntityCache()  # T075: Entity cache

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

    @property
    def lookback_window(self) -> int:
        """Get the lookback window in seconds for first run."""
        return self._lookback_window

    def get_lookback_since(self) -> datetime:
        """Get the 'since' timestamp for first run based on lookback window.

        Returns:
            datetime in UTC representing how far back to look.
        """
        return datetime.now(UTC) - timedelta(seconds=self._lookback_window)

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
        if we're getting close to the limit. Implements proactive
        rate limit checking as specified in plan.md:
        - Pause when remaining < 100 (RATE_LIMIT_THRESHOLD)
        - Sleep until reset + random jitter (0-10s)
        """
        if self._rate_limit is None:
            return

        if self._rate_limit.remaining < self.RATE_LIMIT_THRESHOLD:
            # Add random jitter between 0-10 seconds
            jitter = random.uniform(
                self.RATE_LIMIT_JITTER_MIN,
                self.RATE_LIMIT_JITTER_MAX,
            )
            wait_time = self._rate_limit.seconds_until_reset + jitter
            logger.warning(
                "Rate limit low (%d remaining), pausing for %.0f seconds "
                "(reset + %.1fs jitter)",
                self._rate_limit.remaining,
                wait_time,
                jitter,
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
            TransientError: For 5xx errors that should be retried.
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

            # Primary rate limit error
            if "rate limit" in message.lower() or self._rate_limit.remaining == 0:
                raise RateLimitError(
                    f"GitHub API rate limit exceeded: {message}",
                    reset_at=self._rate_limit.reset_at,
                    remaining=self._rate_limit.remaining,
                    limit=self._rate_limit.limit,
                    is_secondary=False,
                )

            # Secondary rate limit (abuse detection)
            if (
                "secondary rate limit" in message.lower()
                or "abuse" in message.lower()
            ):
                retry_after = int(response.headers.get("Retry-After", 60))
                raise RateLimitError(
                    f"GitHub secondary rate limit: {message}",
                    reset_at=self._rate_limit.reset_at,
                    remaining=self._rate_limit.remaining,
                    limit=self._rate_limit.limit,
                    is_secondary=True,
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
            # Transient server error - should be retried with backoff
            retry_after = int(response.headers.get("Retry-After", 0)) or None
            raise TransientError(
                f"GitHub API server error: {response.status_code}",
                status_code=response.status_code,
                retry_after=retry_after,
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

    async def _request_with_retry(  # noqa: PLR0912, PLR0915
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """Make a request with automatic retry for transient errors.

        Implements:
        - Exponential backoff for 5xx and network errors (1min → 2min → 4min → 8min)
        - Rate limit handling with jitter pause
        - Secondary rate limit handling with exponential backoff

        Args:
            method: HTTP method.
            path: API path or full URL.
            params: Query parameters.

        Returns:
            Parsed JSON response.

        Raises:
            GitHubAPIError: For non-recoverable errors.
            RateLimitError: If rate limit exceeded after retries.
        """
        client = await self._ensure_client()
        last_error: Exception | None = None

        for attempt in range(self.MAX_RETRIES):
            try:
                await self._check_rate_limit()

                # Determine if path is a full URL or a path
                if path.startswith("http"):
                    response = await client.request(method, path)
                else:
                    response = await client.request(method, path, params=params)

                # Reset secondary rate limit counter on success
                self._secondary_rate_limit_retries = 0
                return await self._handle_response(response)

            except RateLimitError as e:
                if e.is_secondary:
                    # Secondary rate limit - exponential backoff
                    if self._secondary_rate_limit_retries >= len(
                        self.SECONDARY_BACKOFF_MULTIPLIERS
                    ):
                        logger.error(
                            "Secondary rate limit: max retries exceeded (%d)",
                            self._secondary_rate_limit_retries,
                        )
                        raise

                    backoff_minutes = self.SECONDARY_BACKOFF_MULTIPLIERS[
                        self._secondary_rate_limit_retries
                    ]
                    wait_time = backoff_minutes * 60
                    self._secondary_rate_limit_retries += 1

                    logger.warning(
                        "Secondary rate limit hit (attempt %d/%d), "
                        "waiting %d minutes",
                        self._secondary_rate_limit_retries,
                        len(self.SECONDARY_BACKOFF_MULTIPLIERS),
                        backoff_minutes,
                    )
                    await asyncio.sleep(wait_time)
                    last_error = e
                    continue
                else:
                    # Primary rate limit - wait until reset + jitter
                    if e.reset_at:
                        jitter = random.uniform(
                            self.RATE_LIMIT_JITTER_MIN,
                            self.RATE_LIMIT_JITTER_MAX,
                        )
                        wait_time = (
                            e.reset_at - datetime.now(UTC)
                        ).total_seconds() + jitter
                        wait_time = max(0, wait_time)

                        logger.warning(
                            "Rate limit exceeded, waiting %.0f seconds "
                            "(reset + %.1fs jitter)",
                            wait_time,
                            jitter,
                        )
                        await asyncio.sleep(wait_time)
                        last_error = e
                        continue
                    raise

            except TransientError as e:
                # Exponential backoff: 1min → 2min → 4min → 8min
                backoff = min(
                    self.INITIAL_BACKOFF_SECONDS * (2**attempt),
                    self.MAX_BACKOFF_SECONDS,
                )
                # Use server-provided retry-after if available
                if e.retry_after:
                    backoff = e.retry_after

                logger.warning(
                    "Transient error (attempt %d/%d): %s. "
                    "Retrying in %d seconds",
                    attempt + 1,
                    self.MAX_RETRIES,
                    e,
                    backoff,
                )
                await asyncio.sleep(backoff)
                last_error = e
                continue

            except httpx.RequestError as e:
                # Network errors - also use exponential backoff
                backoff = min(
                    self.INITIAL_BACKOFF_SECONDS * (2**attempt),
                    self.MAX_BACKOFF_SECONDS,
                )
                logger.warning(
                    "Network error (attempt %d/%d): %s. "
                    "Retrying in %d seconds",
                    attempt + 1,
                    self.MAX_RETRIES,
                    e,
                    backoff,
                )
                await asyncio.sleep(backoff)
                last_error = e
                continue

        # If we get here, we've exhausted retries
        if last_error:
            if isinstance(last_error, RateLimitError | GitHubAPIError):
                raise last_error
            raise GitHubAPIError(
                f"Request failed after {self.MAX_RETRIES} retries: {last_error}",
                status_code=None,
            ) from last_error

        # Should not reach here
        raise GitHubAPIError("Request failed with unknown error")

    async def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """Make a GET request to the GitHub API.

        Uses automatic retry with exponential backoff for transient errors.

        Args:
            path: API path (e.g., "/notifications").
            params: Query parameters.

        Returns:
            Parsed JSON response.
        """
        return await self._request_with_retry("GET", path, params=params)

    async def get_paginated(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        max_pages: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Make paginated GET requests to the GitHub API.

        Uses automatic retry with exponential backoff for transient errors.

        Args:
            path: API path.
            params: Query parameters.
            max_pages: Maximum number of pages to fetch (None for unlimited).

        Yields:
            Items from each page.
        """
        params = dict(params or {})
        params.setdefault("per_page", 100)

        next_url: str | None = path
        page_count = 0
        current_params: dict[str, Any] | None = params

        while next_url:
            if max_pages and page_count >= max_pages:
                break

            # Use the internal paginated request that returns both data and next URL
            result, next_url = await self._get_page_with_link(
                next_url,
                params=current_params,
            )

            # Yield items
            if isinstance(result, list):
                for item in result:
                    yield item
            else:
                yield result

            page_count += 1
            # Clear params for subsequent requests (they're in the URL)
            current_params = None

    async def _get_page_with_link(  # noqa: PLR0912, PLR0915
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | list[dict[str, Any]], str | None]:
        """Get a single page and return data with next link.

        Uses automatic retry with exponential backoff.

        Args:
            path: API path or full URL.
            params: Query parameters.

        Returns:
            Tuple of (data, next_url) where next_url is None if no more pages.
        """
        client = await self._ensure_client()
        last_error: Exception | None = None

        for attempt in range(self.MAX_RETRIES):
            try:
                await self._check_rate_limit()

                # Determine if path is a full URL or a path
                if path.startswith("http"):
                    response = await client.get(path)
                else:
                    response = await client.get(path, params=params)

                # Reset secondary rate limit counter on success
                self._secondary_rate_limit_retries = 0
                result = await self._handle_response(response)

                # Parse Link header for next page
                next_url = self._parse_next_link(response.headers.get("Link", ""))

                return result, next_url

            except RateLimitError as e:
                if e.is_secondary:
                    if self._secondary_rate_limit_retries >= len(
                        self.SECONDARY_BACKOFF_MULTIPLIERS
                    ):
                        raise

                    backoff_minutes = self.SECONDARY_BACKOFF_MULTIPLIERS[
                        self._secondary_rate_limit_retries
                    ]
                    wait_time = backoff_minutes * 60
                    self._secondary_rate_limit_retries += 1

                    logger.warning(
                        "Secondary rate limit hit (attempt %d/%d), "
                        "waiting %d minutes",
                        self._secondary_rate_limit_retries,
                        len(self.SECONDARY_BACKOFF_MULTIPLIERS),
                        backoff_minutes,
                    )
                    await asyncio.sleep(wait_time)
                    last_error = e
                    continue
                else:
                    if e.reset_at:
                        jitter = random.uniform(
                            self.RATE_LIMIT_JITTER_MIN,
                            self.RATE_LIMIT_JITTER_MAX,
                        )
                        wait_time = (
                            e.reset_at - datetime.now(UTC)
                        ).total_seconds() + jitter
                        wait_time = max(0, wait_time)

                        logger.warning(
                            "Rate limit exceeded, waiting %.0f seconds",
                            wait_time,
                        )
                        await asyncio.sleep(wait_time)
                        last_error = e
                        continue
                    raise

            except TransientError as e:
                backoff = min(
                    self.INITIAL_BACKOFF_SECONDS * (2**attempt),
                    self.MAX_BACKOFF_SECONDS,
                )
                if e.retry_after:
                    backoff = e.retry_after

                logger.warning(
                    "Transient error (attempt %d/%d): %s. Retrying in %d seconds",
                    attempt + 1,
                    self.MAX_RETRIES,
                    e,
                    backoff,
                )
                await asyncio.sleep(backoff)
                last_error = e
                continue

            except httpx.RequestError as e:
                backoff = min(
                    self.INITIAL_BACKOFF_SECONDS * (2**attempt),
                    self.MAX_BACKOFF_SECONDS,
                )
                logger.warning(
                    "Network error (attempt %d/%d): %s. Retrying in %d seconds",
                    attempt + 1,
                    self.MAX_RETRIES,
                    e,
                    backoff,
                )
                await asyncio.sleep(backoff)
                last_error = e
                continue

        if last_error:
            if isinstance(last_error, RateLimitError | GitHubAPIError):
                raise last_error
            raise GitHubAPIError(
                f"Request failed after {self.MAX_RETRIES} retries: {last_error}",
            ) from last_error

        raise GitHubAPIError("Request failed with unknown error")

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
        *,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        """Get issue or pull request details.

        Uses the entity cache by default to avoid repeated API calls
        for the same entity within a poll cycle.

        Args:
            owner: Repository owner.
            repo: Repository name.
            issue_number: Issue or PR number.
            use_cache: Whether to use/update the entity cache (default True).

        Returns:
            Issue/PR data.
        """
        # Check cache first
        if use_cache:
            cached = self._entity_cache.get(owner, repo, issue_number)
            if cached is not None:
                return cached

        # Fetch from API
        result = await self.get(f"/repos/{owner}/{repo}/issues/{issue_number}")
        data = result if isinstance(result, dict) else {}

        # Cache the result
        if use_cache and data:
            self._entity_cache.put(owner, repo, issue_number, data)

        return data

    async def get_pull_request(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        *,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        """Get pull request details.

        Uses the entity cache by default to avoid repeated API calls
        for the same entity within a poll cycle.

        Args:
            owner: Repository owner.
            repo: Repository name.
            pr_number: PR number.
            use_cache: Whether to use/update the entity cache (default True).

        Returns:
            Pull request data.
        """
        # Check cache first (use same key as issue since PRs are also issues)
        if use_cache:
            cached = self._entity_cache.get(owner, repo, pr_number)
            if cached is not None:
                return cached

        # Fetch from API
        result = await self.get(f"/repos/{owner}/{repo}/pulls/{pr_number}")
        data = result if isinstance(result, dict) else {}

        # Cache the result
        if use_cache and data:
            self._entity_cache.put(owner, repo, pr_number, data)

        return data

    def clear_entity_cache(self) -> None:
        """Clear the entity cache.

        Call this at the start of each poll cycle to ensure fresh data.
        """
        self._entity_cache.clear()

    @property
    def entity_cache(self) -> EntityCache:
        """Get the entity cache instance.

        Returns:
            The EntityCache for PR/issue data.
        """
        return self._entity_cache

    @property
    def entity_cache_stats(self) -> dict[str, Any]:
        """Get entity cache statistics.

        Returns:
            Dict with cache size, hits, misses, and hit rate.
        """
        return self._entity_cache.stats

    def __repr__(self) -> str:
        """Get string representation."""
        return (
            f"GitHubClient(base_url={self._base_url!r}, "
            f"token={mask_token(self._token)!r})"
        )
