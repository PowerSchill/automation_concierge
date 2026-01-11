# Quickstart: Personal Automation Concierge

**Feature**: 001-github-automation-concierge
**Date**: 2026-01-10

## Prerequisites

- Python 3.11+
- GitHub Personal Access Token with `notifications` and `repo` scopes
- (Optional) Slack webhook URL for Slack notifications

## Installation

```bash
# Clone the repository
git clone https://github.com/PowerSchill/automation_concierge.git
cd automation_concierge

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -e .
```

## Configuration

### 1. Set up GitHub Token

Create a [GitHub Personal Access Token](https://github.com/settings/tokens) with these scopes:
- `notifications` — read notifications
- `repo` — read repository issues/PRs (required for private repos)

```bash
export GITHUB_TOKEN="ghp_your_token_here"
```

### 2. Create Configuration File

Create `~/.concierge/config.yaml`:

```yaml
version: 1

github:
  poll_interval: 60  # seconds
  lookback_window: 3600  # 1 hour on first run

actions:
  slack:
    webhook_url: "${SLACK_WEBHOOK_URL}"  # Set env var, or use direct URL
  github_comment:
    enabled: false  # Opt-in required

rules:
  # Notify when you're mentioned
  - id: mention-notify
    name: "Notify on mentions"
    enabled: true
    trigger:
      event_type: mention
    action:
      type: slack
      message: "🔔 You were mentioned in {{ event.source.owner }}/{{ event.source.repo }}#{{ event.source.number }}: {{ event.subject }}"

  # Notify when assigned to an issue
  - id: assignment-notify
    name: "Notify on assignments"
    enabled: true
    trigger:
      event_type: assignment
    action:
      type: console
      message: "📌 You were assigned to {{ event.source.owner }}/{{ event.source.repo }}#{{ event.source.number }}"
```

### 3. Validate Configuration

```bash
concierge validate
# Output: ✓ Configuration valid (2 rules loaded)
```

## Usage

### Run Once (Test)

```bash
# Process current events and exit
concierge run-once --verbose
```

### Dry Run Mode

```bash
# See what would happen without executing actions
concierge run-once --dry-run --verbose
```

### Continuous Mode

```bash
# Run as a daemon (polls every 60 seconds)
concierge run
```

### Check Status

```bash
# View current state (last checkpoint, pending events)
concierge status
```

### Query Audit Log

```bash
# View recent actions
concierge audit --limit 10

# Filter by rule
concierge audit --rule mention-notify

# Filter by time
concierge audit --since "2026-01-10T00:00:00Z"
```

## Example Rules

### Stale PR Reminder (Time-Based)

```yaml
- id: stale-pr-reminder
  name: "Stale PR reminder"
  enabled: true
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
    message: "⏰ PR #{{ event.source.number }} has been open for 48+ hours with no review"
```

### Label-Based Notification

```yaml
- id: needs-response-alert
  name: "Needs response alert"
  enabled: true
  trigger:
    event_type: label_change
    conditions:
      - type: label_added
        label: needs-response
  action:
    type: console
    message: "🏷️ 'needs-response' label added to {{ event.source.owner }}/{{ event.source.repo }}#{{ event.source.number }}"
```

### Repository-Scoped Rule

```yaml
- id: important-repo-mentions
  name: "Important repo mentions"
  enabled: true
  trigger:
    event_type: mention
    conditions:
      - type: repo_match
        pattern: "myorg/important-*"
  action:
    type: slack
    message: "🚨 IMPORTANT: Mentioned in {{ event.source.owner }}/{{ event.source.repo }}#{{ event.source.number }}"
```

## CLI Reference

```
concierge run [OPTIONS]
    Run in continuous polling mode

    --config PATH       Config file (default: ~/.concierge/config.yaml)
    --state-dir PATH    State directory (default: ~/.concierge/)
    --dry-run           Log actions without executing
    --once              Run one cycle and exit
    --verbose           Enable debug logging
    --poll-interval N   Override poll interval (30-300 seconds)

concierge run-once [OPTIONS]
    Run a single poll cycle and exit
    (same options as run)

concierge validate [OPTIONS]
    Validate configuration
    --config PATH       Config file to validate

concierge status [OPTIONS]
    Show current state
    --state-dir PATH    State directory

concierge audit [OPTIONS]
    Query audit log
    --since DATETIME    Filter by timestamp
    --rule RULE_ID      Filter by rule
    --limit N           Max records (default: 50)
```

## Exit Codes

| Code | Meaning              |
| ---- | -------------------- |
| 0    | Success              |
| 1    | Configuration error  |
| 2    | Authentication error |
| 3    | Partial failure      |
| 4    | Fatal error          |

## Troubleshooting

### "Invalid token" error
- Verify `GITHUB_TOKEN` is set correctly
- Check token has required scopes (`notifications`, `repo`)
- Tokens expire; regenerate if needed

### "Rate limit exceeded"
- Default poll interval (60s) should prevent this
- Check for other tools using same token
- Increase `poll_interval` in config

### "No events found"
- Check `lookback_window` setting
- Ensure you have recent GitHub activity
- Use `--verbose` to see API responses

### Actions not firing
- Check rule is `enabled: true`
- Use `--dry-run` to verify rule matching
- Check `concierge audit` for decision trail

## Development

```bash
# Run tests
pytest

# Run with coverage
pytest --cov=src/concierge

# Type checking
pyright

# Linting
ruff check src/ tests/
```
