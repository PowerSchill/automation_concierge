# Personal Automation Concierge

> GitHub activity monitoring and automated follow-up actions based on user-defined rules.

## Overview

Personal Automation Concierge is a CLI tool that monitors your GitHub notifications and performs automated actions based on explicit, user-defined rules. It supports:

- **Event Detection**: Mentions, assignments, review requests, label changes
- **Rule-Based Actions**: Console notifications, Slack webhooks, GitHub comments
- **Safe Operation**: Dry-run mode, deduplication, audit logging
- **Continuous Monitoring**: Polling-based with checkpoint resume

## Installation

```bash
# Clone the repository
git clone https://github.com/PowerSchill/automation_concierge.git
cd automation_concierge

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install with dev dependencies
pip install -e ".[dev]"
```

## Quick Start

1. **Set up your GitHub token**:
   ```bash
   export GITHUB_TOKEN="ghp_your_token_here"
   ```

2. **Create a configuration file** (`~/.config/concierge/config.yaml`):
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
       trigger:
         event_type: mention
       action:
         type: console
         message: "You were mentioned in {{ event.source }}"
   ```

3. **Validate your configuration**:
   ```bash
   concierge validate
   ```

4. **Run a single poll cycle**:
   ```bash
   concierge run-once --dry-run
   ```

## File Locations

This application follows the [XDG Base Directory Specification](https://specifications.freedesktop.org/basedir-spec/latest/):

| Type       | Default Location                    | Environment Variable |
| ---------- | ----------------------------------- | -------------------- |
| Config     | `~/.config/concierge/config.yaml`   | `$XDG_CONFIG_HOME`   |
| Data/State | `~/.local/share/concierge/state.db` | `$XDG_DATA_HOME`     |

For backward compatibility, the legacy location `~/.concierge/` is also checked if the XDG paths don't exist.

## CLI Commands

```bash
# Validate configuration
concierge validate --config ~/.config/concierge/config.yaml

# Run single poll cycle
concierge run-once

# Run with dry-run mode (no actions executed)
concierge run-once --dry-run

# Check status
concierge status

# View audit log
concierge audit --limit 10
```

## Configuration

See [quickstart.md](specs/001-github-automation-concierge/quickstart.md) for detailed configuration examples.

### Event Types

- `mention` - You were @mentioned
- `assignment` - You were assigned to an issue/PR
- `review_request` - You were requested to review a PR
- `label_change` - A label was added/removed
- `pr_open` - A PR was opened
- `issue_open` - An issue was opened
- `comment` - A comment was added
- `review` - A review was submitted

### Action Types

- `console` - Print to stdout
- `slack` - POST to Slack webhook
- `github_comment` - Comment on the issue/PR (requires opt-in)

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run linting
ruff check src/ tests/

# Run type checking
pyright src/
```

## License

MIT License - see LICENSE for details.
