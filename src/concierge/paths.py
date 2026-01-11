"""XDG Base Directory Specification path utilities.

This module provides XDG-compliant paths for:
- Configuration files ($XDG_CONFIG_HOME/concierge, default: ~/.config/concierge)
- State/data files ($XDG_DATA_HOME/concierge, default: ~/.local/share/concierge)

Reference: https://specifications.freedesktop.org/basedir-spec/latest/

The module also supports legacy paths (~/.concierge/) for backward compatibility,
automatically migrating to XDG paths when legacy files are found.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# XDG environment variable names
XDG_CONFIG_HOME = "XDG_CONFIG_HOME"
XDG_DATA_HOME = "XDG_DATA_HOME"

# Application name used in XDG directories
APP_NAME = "concierge"


def get_config_home() -> Path:
    """Get the XDG config home directory.

    Returns:
        Path from $XDG_CONFIG_HOME or ~/.config if not set
    """
    xdg_config = os.environ.get(XDG_CONFIG_HOME)
    if xdg_config:
        return Path(xdg_config).expanduser()
    return Path.home() / ".config"


def get_data_home() -> Path:
    """Get the XDG data home directory.

    Returns:
        Path from $XDG_DATA_HOME or ~/.local/share if not set
    """
    xdg_data = os.environ.get(XDG_DATA_HOME)
    if xdg_data:
        return Path(xdg_data).expanduser()
    return Path.home() / ".local" / "share"


def get_config_dir() -> Path:
    """Get the application config directory.

    Uses XDG_CONFIG_HOME/concierge, falling back to legacy ~/.concierge
    if it exists and the XDG path doesn't.

    Returns:
        Path to the config directory
    """
    xdg_path = get_config_home() / APP_NAME
    legacy_path = Path.home() / ".concierge"

    # Prefer XDG path if it exists
    if xdg_path.exists():
        return xdg_path

    # Fall back to legacy path if it exists
    if legacy_path.exists():
        logger.debug("Using legacy config directory: %s", legacy_path)
        return legacy_path

    # Default to XDG path for new installations
    return xdg_path


def get_data_dir() -> Path:
    """Get the application data directory (for state, databases, etc).

    Uses XDG_DATA_HOME/concierge, falling back to legacy ~/.concierge
    if it exists and the XDG path doesn't.

    Returns:
        Path to the data directory
    """
    xdg_path = get_data_home() / APP_NAME
    legacy_path = Path.home() / ".concierge"

    # Prefer XDG path if it exists
    if xdg_path.exists():
        return xdg_path

    # Fall back to legacy path if it exists (and contains state.db)
    if (legacy_path / "state.db").exists():
        logger.debug("Using legacy data directory: %s", legacy_path)
        return legacy_path

    # Default to XDG path for new installations
    return xdg_path


def get_default_config_path() -> Path:
    """Get the default config file path.

    Returns:
        Path to config.yaml in the config directory
    """
    return get_config_dir() / "config.yaml"


def get_default_state_dir() -> Path:
    """Get the default state/data directory.

    This is the directory where state.db and other persistent data is stored.

    Returns:
        Path to the data directory
    """
    return get_data_dir()


def get_default_db_path() -> Path:
    """Get the default database path.

    Returns:
        Path to state.db in the data directory
    """
    return get_data_dir() / "state.db"


def ensure_config_dir() -> Path:
    """Ensure the config directory exists and return its path.

    Creates the directory with appropriate permissions if it doesn't exist.

    Returns:
        Path to the config directory
    """
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def ensure_data_dir() -> Path:
    """Ensure the data directory exists and return its path.

    Creates the directory with appropriate permissions if it doesn't exist.

    Returns:
        Path to the data directory
    """
    data_dir = get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir
