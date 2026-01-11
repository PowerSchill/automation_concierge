"""Configuration file loading and environment variable expansion.

This module provides:
- Environment variable expansion for config values (${VAR} syntax)
- YAML config file loading with Pydantic validation
- Config file discovery (--config, $CONCIERGE_CONFIG, ./concierge.yaml, XDG config path)

Config discovery follows XDG Base Directory Specification:
- Default: $XDG_CONFIG_HOME/concierge/config.yaml (~/.config/concierge/config.yaml)
- Legacy fallback: ~/.concierge/config.yaml (for backward compatibility)
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from concierge.config.schema import Config
from concierge.paths import get_default_config_path


class ConfigError(Exception):
    """Raised when configuration loading or validation fails."""

    def __init__(self, message: str, path: Path | None = None) -> None:
        """Initialize ConfigError with message and optional path.

        Args:
            message: Error description
            path: Path to the config file that caused the error
        """
        self.path = path
        super().__init__(message)


class ConfigNotFoundError(ConfigError):
    """Raised when no config file can be found."""


class ConfigValidationError(ConfigError):
    """Raised when config validation fails."""

    def __init__(
        self,
        message: str,
        path: Path | None = None,
        validation_errors: list[dict[str, Any]] | None = None,
    ) -> None:
        """Initialize ConfigValidationError.

        Args:
            message: Error description
            path: Path to the config file
            validation_errors: List of Pydantic validation error dicts
        """
        self.validation_errors = validation_errors or []
        super().__init__(message, path)


class EnvironmentVariableError(ConfigError):
    """Raised when a referenced environment variable is not set."""

    def __init__(self, var_name: str, path: Path | None = None) -> None:
        """Initialize EnvironmentVariableError.

        Args:
            var_name: Name of the missing environment variable
            path: Path to the config file
        """
        self.var_name = var_name
        message = (
            f"Environment variable '{var_name}' is not set. "
            f"Set it or update your config to use a different value."
        )
        super().__init__(message, path)


# Pattern for environment variable references: ${VAR_NAME}
ENV_VAR_PATTERN = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


def expand_env_vars(value: Any, *, strict: bool = True) -> Any:
    """Expand environment variable references in a value.

    Supports the ${VAR_NAME} syntax. Environment variable names must:
    - Start with A-Z or underscore
    - Contain only A-Z, 0-9, or underscore

    Args:
        value: The value to expand. Can be a string, list, or dict.
        strict: If True, raise an error for undefined env vars.
                If False, leave the ${VAR} reference unchanged.

    Returns:
        The value with environment variables expanded.

    Raises:
        EnvironmentVariableError: If strict=True and an env var is not set.

    Examples:
        >>> os.environ["API_KEY"] = "secret"
        >>> expand_env_vars("Key: ${API_KEY}")
        'Key: secret'
        >>> expand_env_vars({"url": "${WEBHOOK_URL}"})  # Expands nested
        {'url': '...'}
    """
    if isinstance(value, str):
        return _expand_string(value, strict=strict)
    if isinstance(value, dict):
        return {k: expand_env_vars(v, strict=strict) for k, v in value.items()}
    if isinstance(value, list):
        return [expand_env_vars(item, strict=strict) for item in value]
    return value


def _expand_string(s: str, *, strict: bool) -> str:
    """Expand environment variables in a string.

    Args:
        s: String potentially containing ${VAR} references
        strict: If True, raise error for undefined vars

    Returns:
        String with env vars expanded

    Raises:
        EnvironmentVariableError: If strict and var not defined
    """

    def replace_match(match: re.Match[str]) -> str:
        var_name = match.group(1)
        value = os.environ.get(var_name)
        if value is None:
            if strict:
                raise EnvironmentVariableError(var_name)
            # Leave the reference unchanged
            return match.group(0)
        return value

    return ENV_VAR_PATTERN.sub(replace_match, s)


def discover_config_path(explicit_path: str | Path | None = None) -> Path:
    """Discover the config file path using priority order.

    Discovery order:
    1. explicit_path (from --config flag)
    2. $CONCIERGE_CONFIG environment variable
    3. ./concierge.yaml (current directory)
    4. XDG config path ($XDG_CONFIG_HOME/concierge/config.yaml)
       Falls back to ~/.concierge/config.yaml for legacy compatibility

    Args:
        explicit_path: Optional explicit path from CLI --config flag

    Returns:
        Path to the config file

    Raises:
        ConfigNotFoundError: If no config file is found at any location
    """
    candidates: list[Path] = []

    # 1. Explicit path takes priority
    if explicit_path:
        path = Path(explicit_path).expanduser().resolve()
        if path.exists():
            return path
        msg = f"Config file not found: {path}"
        raise ConfigNotFoundError(msg, path)

    # 2. Environment variable
    env_path = os.environ.get("CONCIERGE_CONFIG")
    if env_path:
        path = Path(env_path).expanduser().resolve()
        if path.exists():
            return path
        candidates.append(path)

    # 3. Current directory
    cwd_path = Path.cwd() / "concierge.yaml"
    if cwd_path.exists():
        return cwd_path
    candidates.append(cwd_path)

    # 4. XDG config path (with legacy fallback handled by get_default_config_path)
    default_path = get_default_config_path()
    if default_path.exists():
        return default_path
    candidates.append(default_path)

    # Also check legacy path explicitly if XDG path doesn't exist
    legacy_path = Path.home() / ".concierge" / "config.yaml"
    if legacy_path != default_path and legacy_path.exists():
        return legacy_path
    if legacy_path != default_path:
        candidates.append(legacy_path)

    # No config found
    locations = "\n  - ".join(str(p) for p in candidates)
    msg = f"No config file found. Searched locations:\n  - {locations}"
    raise ConfigNotFoundError(msg)


def load_yaml(path: Path) -> dict[str, Any]:
    """Load and parse a YAML file.

    Args:
        path: Path to the YAML file

    Returns:
        Parsed YAML as a dictionary

    Raises:
        ConfigError: If the file cannot be read or parsed
    """
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as e:
        msg = f"Cannot read config file: {e}"
        raise ConfigError(msg, path) from e

    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as e:
        msg = f"Invalid YAML syntax: {e}"
        raise ConfigError(msg, path) from e

    if data is None:
        # Empty file
        return {}

    if not isinstance(data, dict):
        msg = "Config file must contain a YAML mapping (dictionary), not a list or scalar"
        raise ConfigError(msg, path)

    return data


def load_config(
    path: str | Path | None = None,
    *,
    expand_env: bool = True,
) -> Config:
    """Load and validate configuration from a YAML file.

    This function:
    1. Discovers the config file using the priority order
    2. Parses the YAML content
    3. Expands environment variable references (${VAR})
    4. Validates against the Config schema

    Args:
        path: Optional explicit path to config file. If None, uses discovery.
        expand_env: Whether to expand ${VAR} environment variable references.

    Returns:
        Validated Config object

    Raises:
        ConfigNotFoundError: If no config file is found
        ConfigError: If the file cannot be read or parsed
        EnvironmentVariableError: If a required env var is not set
        ConfigValidationError: If the config fails schema validation

    Example:
        >>> config = load_config()  # Auto-discovers config
        >>> config = load_config("~/.config/concierge/config.yaml")
        >>> config.github.poll_interval
        60
    """
    # Discover config path
    config_path = discover_config_path(path)

    # Load YAML
    raw_config = load_yaml(config_path)

    # Expand environment variables
    if expand_env:
        try:
            raw_config = expand_env_vars(raw_config, strict=True)
        except EnvironmentVariableError as e:
            e.path = config_path
            raise

    # Validate with Pydantic
    try:
        config = Config.model_validate(raw_config)
    except ValidationError as e:
        errors = e.errors()
        # Format error message
        error_msgs: list[str] = []
        for err in errors:
            loc = ".".join(str(loc) for loc in err["loc"])
            msg = err["msg"]
            error_msgs.append(f"  - {loc}: {msg}")

        message = (
            f"Config validation failed ({len(errors)} error(s)):\n"
            + "\n".join(error_msgs)
        )
        # Convert ErrorDetails to dict for storage
        validation_error_dicts = [dict(err) for err in errors]
        raise ConfigValidationError(
            message, path=config_path, validation_errors=validation_error_dicts
        ) from e

    return config
