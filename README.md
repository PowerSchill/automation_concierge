# Personal Automation Concierge

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> GitHub activity monitoring and automated follow-up actions based on user-defined rules.

## Overview

Personal Automation Concierge is a CLI tool that monitors your GitHub notifications and performs automated actions based on explicit, user-defined rules. It enables you to:

- **Detect Events**: Mentions, assignments, review requests, label changes, stale PRs
- **Execute Actions**: Console notifications, Slack webhooks, GitHub comments
- **Operate Safely**: Dry-run mode, deduplication, audit logging, rate limiting
- **Run Continuously**: Polling-based with checkpoint resume for reliable operation

### Key Features

- 📋 **Rule-Based Automation**: Define YAML rules to match events and trigger actions
- 🔍 **Audit Trail**: Full explainability for every action taken
- 🛡️ **Safe by Default**: Dry-run mode, rate limiting, opt-in for write actions
- ⏰ **Time-Based Rules**: Detect stale PRs/issues that haven't had activity
- 🏷️ **Label Detection**: React to label additions and removals
- 💬 **Multiple Actions**: Console, Slack, and GitHub comments

## Installation

### Prerequisites

- Python 3.11 or later
- GitHub Personal Access Token with `notifications` and `repo` scopes
- (Optional) Slack webhook URL for Slack notifications

### Install from Source

```bash
# Clone the repository
git clone https://github.com/PowerSchill/automation_concierge.git
cd automation_concierge

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install the package
pip install -e .

# Or with development dependencies
pip install -e ".[dev]"
```

### Verify Installation

```bash
concierge --version
concierge --help
```

## Quick Start

### 1. Set Up GitHub Token

Create a [GitHub Personal Access Token](https://github.com/settings/tokens) with these scopes:
- `notifications` — read your notifications
- `repo` — read repository issues/PRs (required for private repos)

```bash
export GITHUB_TOKEN="ghp_your_token_here"
```

### 2. Create Configuration

Create a configuration file at `~/.config/concierge/config.yaml`:

```bash
mkdir -p ~/.config/concierge
```

```yaml
version: 1

github:
  poll_interval: 60  # seconds

rules:
  - id: mention-notify
    name: Notify on mentions
    enabled: true
    trigger:
      event_type: mention
    action:
      type: console
      message: "🔔 You were mentioned in {{ event.repo_full_name }}#{{ event.entity_number }}"

  - id: assignment-notify
    name: Notify on assignments
    enabled: true
    trigger:
      event_type: assignment
    action:
      type: console
      message: "📌 Assigned to {{ event.repo_full_name }}#{{ event.entity_number }}"
```

See [examples/concierge.yaml](examples/concierge.yaml) for a complete example configuration.

### 3. Validate Configuration

```bash
concierge validate
# Output: ✓ Configuration valid (2 rules loaded)
```

### 4. Test with Dry Run

```bash
concierge run-once --dry-run --verbose
```

### 5. Run Continuously

```bash
concierge run
```

## Configuration

### File Locations

This application follows the [XDG Base Directory Specification](https://specifications.freedesktop.org/basedir-spec/latest/):

| Type       | Default Location                    | Environment Variable |
| ---------- | ----------------------------------- | -------------------- |
| Config     | `~/.config/concierge/config.yaml`   | `$XDG_CONFIG_HOME`   |
| Data/State | `~/.local/share/concierge/state.db` | `$XDG_DATA_HOME`     |

Legacy location `~/.concierge/` is also checked for backward compatibility.

### Configuration Options

```yaml
version: 1

github:
  poll_interval: 60       # Polling interval in seconds (30-300)
  lookback_window: 3600   # How far back to look on first run (seconds)

actions:
  slack:
    webhook_url: "${SLACK_WEBHOOK_URL}"  # Environment variable reference
  github_comment:
    enabled: false  # Must be true to enable GitHub comments

state:
  retention_days: 30  # How long to keep processed event records

rules:
  - id: rule-id           # Unique identifier (lowercase, alphanumeric, hyphens)
    name: "Rule Name"     # Human-readable name
    enabled: true         # Whether rule is active
    trigger:
      event_type: mention  # Event type to match
      conditions: []       # Optional conditions
    action:
      type: console        # Action type: console, slack, github_comment
      message: "Template"  # Message with {{ event.field }} placeholders
```

### Event Types

| Event Type       | Description                       |
| ---------------- | --------------------------------- |
| `mention`        | You were @mentioned               |
| `assignment`     | You were assigned to an issue/PR  |
| `review_request` | You were requested to review a PR |
| `label_change`   | A label was added or removed      |
| `pr_open`        | A PR was opened                   |
| `issue_open`     | An issue was opened               |
| `comment`        | A comment was added               |
| `review`         | A review was submitted            |

### Action Types

| Action Type      | Description             | Requirements             |
| ---------------- | ----------------------- | ------------------------ |
| `console`        | Print to stdout         | None                     |
| `slack`          | POST to Slack webhook   | `webhook_url` configured |
| `github_comment` | Comment on the issue/PR | `opt_in: true` in action |

### Conditions

```yaml
# Time-based condition (e.g., PR open > 48 hours)
conditions:
  - type: time_since
    field: created_at    # or updated_at
    threshold: 48h       # Duration: 48h, 7d, etc.

# No activity condition
conditions:
  - type: no_activity
    activity: review     # review, comment, or commit

# Label condition
conditions:
  - type: label_added    # or label_removed, label_present
    label: needs-review

# Repository pattern
conditions:
  - type: repo_match
    pattern: "myorg/important-*"
```

### Message Templates

Use `{{ event.field }}` placeholders in messages:

| Placeholder                  | Description                       |
| ---------------------------- | --------------------------------- |
| `{{ event.repo_full_name }}` | Repository full name (owner/repo) |
| `{{ event.entity_number }}`  | Issue/PR number                   |
| `{{ event.entity_title }}`   | Issue/PR title                    |
| `{{ event.entity_url }}`     | URL to the issue/PR               |
| `{{ event.actor }}`          | User who triggered the event      |

## CLI Reference

### Commands

```bash
# Run in continuous mode (daemon)
concierge run [OPTIONS]

# Run a single poll cycle and exit
concierge run-once [OPTIONS]

# Validate configuration file
concierge validate [OPTIONS]

# Show current status
concierge status [OPTIONS]

# Query audit log
concierge audit [OPTIONS]
```

### Options

```
--config PATH         Config file path (default: ~/.config/concierge/config.yaml)
--state-dir PATH      State directory (default: ~/.local/share/concierge/)
--dry-run             Log actions without executing them
--verbose, -v         Enable debug logging
--poll-interval N     Override poll interval (30-300 seconds)
```

### Exit Codes

| Code | Meaning                               |
| ---- | ------------------------------------- |
| 0    | Success                               |
| 1    | Configuration error                   |
| 2    | Authentication error                  |
| 3    | Partial failure (some actions failed) |
| 4    | Fatal error                           |

## Examples

### Basic Mention Notification

```yaml
- id: mention-notify
  name: Notify on mentions
  trigger:
    event_type: mention
  action:
    type: console
    message: "You were mentioned in {{ event.repo_full_name }}#{{ event.entity_number }}"
```

### Slack Notification

```yaml
- id: mention-slack
  name: Slack for mentions
  trigger:
    event_type: mention
  action:
    type: slack
    message: "🔔 Mentioned in <{{ event.entity_url }}|{{ event.repo_full_name }}#{{ event.entity_number }}>"
```

### Stale PR Detection

```yaml
- id: stale-pr
  name: Stale PR reminder
  trigger:
    event_type: pr_open
    conditions:
      - type: time_since
        field: created_at
        threshold: 48h
      - type: no_activity
        activity: review
  action:
    type: slack
    message: "⏰ Stale PR: {{ event.repo_full_name }}#{{ event.entity_number }} needs review"
```

### Label-Based Alert

```yaml
- id: urgent-label
  name: Urgent label alert
  trigger:
    event_type: label_change
    conditions:
      - type: label_added
        label: urgent
  action:
    type: slack
    message: "🚨 Urgent label added to {{ event.repo_full_name }}#{{ event.entity_number }}"
```

## Troubleshooting

### "Invalid token" error
- Verify `GITHUB_TOKEN` is set: `echo $GITHUB_TOKEN`
- Check token has required scopes (`notifications`, `repo`)
- Regenerate token if expired

### "Rate limit exceeded"
- Default poll interval (60s) should prevent this
- Increase `poll_interval` in config if needed
- Check for other tools using the same token

### "No events found"
- Verify you have recent GitHub activity
- Check `lookback_window` setting
- Use `--verbose` to see API responses

### Actions not firing
- Verify rule has `enabled: true`
- Use `--dry-run` to test rule matching
- Check `concierge audit` for decision trail

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run tests with coverage
pytest --cov=src/concierge --cov-report=term-missing

# Type checking
pyright src/

# Linting
ruff check src/ tests/

# Format code
ruff format src/ tests/
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      CLI Entry Point                         │
│                  (run, run-once, validate)                  │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐   ┌─────────────────┐   ┌─────────────────┐
│ GitHub Client │   │  Rules Engine   │   │ Action Executor │
│   (httpx)     │   │   (matchers)    │   │ (console/slack) │
└───────────────┘   └─────────────────┘   └─────────────────┘
        │                     │                     │
        └─────────────────────┼─────────────────────┘
                              ▼
              ┌───────────────────────────────┐
              │        State Store            │
              │  (SQLite: checkpoints, audit) │
              └───────────────────────────────┘
```

## License

MIT License - see [LICENSE](LICENSE) for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
