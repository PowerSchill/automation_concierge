# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

### Changed
- N/A

### Deprecated
- N/A

### Removed
- N/A

### Fixed
- N/A

### Security
- Token redaction in logs
- Webhook URL redaction in logs
- State database file permissions (chmod 600)

## [0.1.0] - Unreleased

Initial development release.

### Added
- Core rule-trigger-notify loop (User Story 1)
- Audit logging and explainability (User Story 2)
- Safe continuous operation (User Story 3)

[Unreleased]: https://github.com/PowerSchill/automation_concierge/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/PowerSchill/automation_concierge/releases/tag/v0.1.0
