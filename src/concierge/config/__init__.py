"""Configuration module for Personal Automation Concierge.

This module provides configuration loading, validation, and schema definitions
for the concierge application.

Usage:
    from concierge.config import load_config, Config

    config = load_config()  # Auto-discovers config file
    config = load_config("/path/to/config.yaml")  # Explicit path
"""

from concierge.config.loader import discover_config_path, load_config
from concierge.config.schema import (
    Action,
    ActionsConfig,
    ActionType,
    Condition,
    Config,
    EventType,
    GitHubConfig,
    LabelCondition,
    NoActivityCondition,
    RepoCondition,
    Rule,
    StateConfig,
    TimeSinceCondition,
    Trigger,
)

__all__ = [
    "Action",
    "ActionType",
    "ActionsConfig",
    "Condition",
    "Config",
    "EventType",
    "GitHubConfig",
    "LabelCondition",
    "NoActivityCondition",
    "RepoCondition",
    "Rule",
    "StateConfig",
    "TimeSinceCondition",
    "Trigger",
    "discover_config_path",
    "load_config",
]
