# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-01-11

### Added

#### Core Features (User Story 1: Define and Trigger Rules)
- CLI application with `run`, `run-once`, `validate`, `status`, and `audit` commands
- YAML configuration file with Pydantic validation
- GitHub notification polling with pagination support
- Event normalization from GitHub notifications
- Rules engine with event-type matching
- Console action for stdout notifications
- SQLite state store for checkpoints and processed event tracking
- Event deduplication to prevent duplicate notifications

#### Audit & Explainability (User Story 2)
- Structured JSON logging with structlog
- Audit log table with full decision trail
- `concierge audit` command with filtering options (--since, --rule, --limit)
- `concierge status` command showing last checkpoint and pending events
- Match reason generation for every rule evaluation

#### Continuous Operation (User Story 3)
- Graceful shutdown with SIGTERM/SIGINT handlers
- Checkpoint resume on restart
- Rate limit monitoring with proactive pause (remaining < 100)
- Exponential backoff for transient failures (5xx, network errors)
- Secondary rate limit (abuse detection) handling
- Poll interval jitter (0-10%) for stability
- Lookback window for first run (default: 1 hour)

#### Time-Based Rules (User Story 4)
- `time_since` condition matcher (e.g., "PR open > 48h")
- `no_activity` condition matcher (review, comment, commit)
- Injectable TimeProvider for testability
- Entity cache for efficient API usage
- Threshold crossing detection (fires once per threshold)

#### Label-Based Rules (User Story 5)
- `label_present`, `label_added`, `label_removed` conditions
- Label change detection from GitHub event payloads
- Label list tracking on Event model

#### Multiple Action Types (User Story 6)
- Slack webhook action with retry (3 attempts, 1s→2s→4s backoff)
- Slack rate limiting (max 10 messages/minute)
- GitHub comment action with retry (2 attempts, 2s→5s backoff)
- GitHub comment rate limiting (max 1 per issue per hour)
- `opt_in: true` requirement for GitHub comment safety
- Message template expansion with `{{ event.field }}` placeholders
- Action failure isolation (one failure doesn't block others)

#### Configuration & CLI
- Configuration file discovery (--config, $CONCIERGE_CONFIG, ./concierge.yaml, ~/.concierge/config.yaml)
- Environment variable expansion in config values (${VAR} syntax)
- XDG Base Directory support for config and state
- Dry-run mode (--dry-run flag)
- Exit codes: 0 (success), 1 (config error), 2 (auth error), 3 (partial failure), 4 (fatal)

#### Security
- GITHUB_TOKEN redaction in all log output
- Slack webhook URL redaction in logs
- State database file permissions (chmod 600)
- Token scope validation at startup

### Changed
- N/A (initial release)

### Deprecated
- N/A

### Removed
- N/A

### Fixed
- N/A

### Security
- All secrets (GITHUB_TOKEN, webhook URLs) are redacted in log output
- State database created with restricted permissions (chmod 600)
- GitHub comment action requires explicit opt-in for safety

## [0.1.0] - 2026-01-10

### Added
- Initial project structure and configuration
- CLI skeleton with Typer
- Configuration loader with YAML parsing and Pydantic validation
- GitHub API client with rate limiting
- Event normalization from GitHub notifications
- Rules engine with event-type matching
- Console action for notifications
- SQLite state store for checkpoints and deduplication
- Structured JSON logging with structlog

[Unreleased]: https://github.com/PowerSchill/automation_concierge/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/PowerSchill/automation_concierge/compare/v0.1.0...v1.0.0
[0.1.0]: https://github.com/PowerSchill/automation_concierge/releases/tag/v0.1.0
