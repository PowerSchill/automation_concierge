"""GitHub authentication and token validation."""

from __future__ import annotations

import os

import httpx


class AuthenticationError(Exception):
    """Raised when GitHub authentication fails."""

    def __init__(
        self,
        message: str,
        *,
        missing_scopes: list[str] | None = None,
        status_code: int | None = None,
    ) -> None:
        """Initialize authentication error.

        Args:
            message: Error description.
            missing_scopes: List of required but missing OAuth scopes.
            status_code: HTTP status code if from API response.
        """
        super().__init__(message)
        self.missing_scopes = missing_scopes or []
        self.status_code = status_code


def get_github_token() -> str:
    """Get GitHub token from environment.

    Returns:
        GitHub personal access token.

    Raises:
        AuthenticationError: If GITHUB_TOKEN is not set.
    """
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise AuthenticationError(
            "GITHUB_TOKEN environment variable is not set. "
            "Please set it to a valid GitHub personal access token."
        )
    return token


async def validate_token(
    token: str | None = None,
    *,
    base_url: str = "https://api.github.com",
    client: httpx.AsyncClient | None = None,
) -> dict[str, str | list[str]]:
    """Validate GitHub token and check required scopes.

    Args:
        token: GitHub personal access token. If None, reads from GITHUB_TOKEN.
        base_url: GitHub API base URL.
        client: Optional httpx client for testing.

    Returns:
        Dictionary with:
            - user: Authenticated username
            - scopes: List of granted OAuth scopes

    Raises:
        AuthenticationError: If token is invalid or missing required scopes.
    """
    if token is None:
        token = get_github_token()

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "automation-concierge/0.1.0",
    }

    # Use provided client or create a new one
    should_close = client is None
    if client is None:
        client = httpx.AsyncClient()

    try:
        # GET /user to validate token and get scopes
        response = await client.get(f"{base_url}/user", headers=headers)

        if response.status_code == 401:
            raise AuthenticationError(
                "GitHub token is invalid or expired.",
                status_code=401,
            )

        if response.status_code == 403:
            raise AuthenticationError(
                "GitHub token access denied. Check token permissions.",
                status_code=403,
            )

        if response.status_code != 200:
            raise AuthenticationError(
                f"Unexpected response from GitHub API: {response.status_code}",
                status_code=response.status_code,
            )

        # Parse user data
        user_data = response.json()
        username = user_data.get("login", "unknown")

        # Get scopes from X-OAuth-Scopes header
        scopes_header = response.headers.get("X-OAuth-Scopes", "")
        scopes = [s.strip() for s in scopes_header.split(",") if s.strip()]

        # Check required scopes for notifications API
        # notifications scope or repo scope is required
        required_any = {"notifications", "repo"}
        has_required = bool(required_any & set(scopes))

        if not has_required:
            raise AuthenticationError(
                "GitHub token is missing required scopes. "
                "Token needs 'notifications' or 'repo' scope to access notifications.",
                missing_scopes=list(required_any),
            )

        return {"user": username, "scopes": scopes}

    except httpx.RequestError as e:
        raise AuthenticationError(
            f"Failed to connect to GitHub API: {e}"
        ) from e

    finally:
        if should_close:
            await client.aclose()


def mask_token(token: str) -> str:
    """Mask a token for safe logging.

    Args:
        token: Token to mask.

    Returns:
        Masked token showing first 4 and last 4 characters.
    """
    if len(token) <= 8:
        return "***"
    return f"{token[:4]}...{token[-4:]}"
