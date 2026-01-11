# Research: Personal Automation Concierge

**Feature**: 001-github-automation-concierge
**Date**: 2026-01-10
**Status**: Complete

## Overview

This document captures research findings and technical decisions made during the planning phase. All "NEEDS CLARIFICATION" items from the initial Technical Context have been resolved.

---

## 1. GitHub API Research

### Decision: Polling vs Webhooks

**Chosen**: Polling (for v1)

**Rationale**:
- Webhooks require publicly accessible HTTP endpoint (ngrok, cloud hosting, reverse proxy)
- Single-user tool doesn't justify infrastructure complexity
- Polling at 60s intervals uses ~100 req/hour (2% of 5000 rate limit)
- Easier debugging: can simulate events without webhook delivery issues

**Alternatives Considered**:
| Approach              | Pros                 | Cons                                                | Why Rejected            |
| --------------------- | -------------------- | --------------------------------------------------- | ----------------------- |
| Webhooks              | Real-time, efficient | Requires public endpoint, delivery failures         | Infrastructure overhead |
| GitHub Actions        | Built-in triggers    | Limited to repo events, can't monitor user globally | Scope too narrow        |
| GraphQL Subscriptions | Efficient streaming  | Not available for notifications                     | Not supported           |

### Decision: Authentication Method

**Chosen**: Personal Access Token (PAT) via `GITHUB_TOKEN` env var

**Rationale**:
- Simplest auth for single-user tool
- GitHub now offers fine-grained PATs with minimal scopes
- No OAuth redirect flow needed
- No token refresh complexity

**Required Scopes**:
- `notifications` — access notification inbox
- `repo` — access private repository issues/PRs (needed for full event context)

**Alternatives Considered**:
| Approach   | Pros                           | Cons                                   | Why Rejected             |
| ---------- | ------------------------------ | -------------------------------------- | ------------------------ |
| GitHub App | Installation tokens, org-level | Complex setup, multi-user focus        | Overkill for single user |
| OAuth App  | User-delegated auth            | Requires redirect flow, refresh tokens | Unnecessary complexity   |

### API Endpoints Selected

| Endpoint                                    | Purpose                    | Notes                                   |
| ------------------------------------------- | -------------------------- | --------------------------------------- |
| `GET /notifications`                        | Primary event source       | Includes mentions, assignments, reviews |
| `GET /users/{user}/events`                  | Secondary (broader events) | Polled less frequently                  |
| `GET /repos/{owner}/{repo}/issues/{number}` | Entity details             | For time-based rules                    |
| `GET /rate_limit`                           | Quota checking             | Before each poll cycle                  |

---

## 2. Python Dependencies Research

### Decision: HTTP Client

**Chosen**: `httpx`

**Rationale**:
- Modern async-capable HTTP client
- Excellent typing support
- Built-in retry mechanisms
- Superior to `requests` for long-running applications

**Alternatives Considered**:
| Library    | Pros               | Cons                              | Why Rejected      |
| ---------- | ------------------ | --------------------------------- | ----------------- |
| `requests` | Simple, ubiquitous | No async, less active development | Legacy            |
| `aiohttp`  | Async-first        | Steeper learning curve            | More than needed  |
| `urllib3`  | Low-level, fast    | Too low-level for this use case   | Not a full client |

### Decision: CLI Framework

**Chosen**: `typer`

**Rationale**:
- Type-hint based argument parsing
- Auto-generated help text
- Excellent developer experience
- Built on `click`, well-maintained

**Alternatives Considered**:
| Library    | Pros             | Cons                        | Why Rejected          |
| ---------- | ---------------- | --------------------------- | --------------------- |
| `argparse` | Stdlib, no deps  | Verbose, no auto-completion | Poor DX               |
| `click`    | Mature, flexible | Manual decorators           | Typer wraps it better |
| `fire`     | Minimal code     | Limited validation          | Less control          |

### Decision: Configuration Validation

**Chosen**: `pydantic` (v2)

**Rationale**:
- Type-safe validation
- Excellent error messages
- JSON Schema export for documentation
- YAML integration via `pyyaml`

### Decision: Structured Logging

**Chosen**: `structlog`

**Rationale**:
- JSON output for machine parsing
- Context binding (request IDs, etc.)
- Human-readable dev mode
- Integrates with stdlib logging

### Final Dependencies

```
httpx>=0.27.0        # HTTP client
pydantic>=2.5.0      # Validation
typer>=0.9.0         # CLI
structlog>=24.1.0    # Logging
pyyaml>=6.0.1        # Config parsing
```

**Dev Dependencies**:
```
pytest>=8.0.0
pytest-httpx>=0.30.0
freezegun>=1.2.0
ruff>=0.1.0
pyright>=1.1.350
```

---

## 3. State Storage Research

### Decision: Storage Backend

**Chosen**: SQLite (stdlib `sqlite3`)

**Rationale**:
- Zero external dependencies
- ACID transactions for data integrity
- Queryable with standard SQL tools
- Single-file portability
- Handles 1M+ rows easily (our scale: ~10K/year)

**Alternatives Considered**:
| Approach   | Pros     | Cons                             | Why Rejected             |
| ---------- | -------- | -------------------------------- | ------------------------ |
| JSON file  | Simple   | No transactions, corruption risk | Data integrity           |
| TinyDB     | Pythonic | No SQL, limited querying         | Less flexible            |
| Redis      | Fast     | External dependency, overkill    | Infrastructure overhead  |
| PostgreSQL | Scalable | External dependency              | Overkill for single user |

### Schema Design

```sql
-- Version tracking for migrations
CREATE TABLE schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

-- Checkpoint for event stream position
CREATE TABLE checkpoints (
    id TEXT PRIMARY KEY,
    last_event_timestamp TEXT NOT NULL,
    last_poll_timestamp TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Processed events for deduplication
CREATE TABLE processed_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    disposition TEXT NOT NULL,  -- 'action_executed', 'no_match', 'dry_run', 'error'
    processed_at TEXT NOT NULL
);

-- Action history for per-rule deduplication
CREATE TABLE action_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    result TEXT NOT NULL,  -- 'success', 'failed', 'skipped'
    executed_at TEXT NOT NULL,
    UNIQUE(event_id, rule_id)
);

-- Full audit log
CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    event_id TEXT,
    event_type TEXT,
    event_source TEXT,
    rules_json TEXT,  -- JSON array of rule evaluations
    actions_json TEXT,  -- JSON array of actions taken
    disposition TEXT,
    message TEXT
);

-- Indexes
CREATE INDEX idx_processed_events_timestamp ON processed_events(processed_at);
CREATE INDEX idx_action_history_event ON action_history(event_id);
CREATE INDEX idx_audit_log_timestamp ON audit_log(timestamp);
```

---

## 4. Rules Configuration Research

### Decision: Configuration Format

**Chosen**: YAML

**Rationale**:
- Human-readable and editable
- Comments supported
- Good tooling ecosystem
- Standard for DevOps/automation configs

**Alternatives Considered**:
| Format     | Pros         | Cons                              | Why Rejected         |
| ---------- | ------------ | --------------------------------- | -------------------- |
| JSON       | Universal    | No comments, verbose              | Poor editability     |
| TOML       | Clean syntax | Less familiar, nested limits      | YAML more common     |
| Python DSL | Flexible     | Execution risks, debugging harder | Security, complexity |

### Configuration Schema (Summary)

```yaml
# ~/.concierge/config.yaml
version: 1

github:
  poll_interval: 60  # seconds (30-300)
  lookback_window: 3600  # seconds on first run

actions:
  slack:
    webhook_url: "${SLACK_WEBHOOK_URL}"  # env var expansion
  github_comment:
    enabled: false  # opt-in required

rules:
  - id: mention-notify
    name: "Notify on mentions"
    enabled: true
    trigger:
      event_type: mention
    action:
      type: slack
      message: "You were mentioned in {{ event.source }}"

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
      type: console
      message: "PR {{ event.pr_number }} has no review after 48h"
```

---

## 5. Testing Strategy Research

### Decision: Test Framework

**Chosen**: `pytest` with domain-specific plugins

**Plugins**:
- `pytest-httpx` — mock HTTP requests at httpx layer
- `freezegun` — freeze/control time
- `pytest-cov` — coverage reporting

### Fixture Strategy

**Recorded Fixtures**: Store real GitHub API responses in `tests/fixtures/`
- Captured once, versioned with tests
- Anonymized (no real usernames/tokens)
- Easy to update when API changes

**Time Control**: All time-dependent code uses injectable `TimeProvider`
```python
# Production: real time
# Tests: frozen time via freezegun
```

---

## 6. Operational Research

### Logging Best Practices

**Format**: Structured JSON to stderr
- Machine-parseable for log aggregation
- Human-readable via `jq` or structlog's dev console

**Levels**:
| Level   | Usage                                           |
| ------- | ----------------------------------------------- |
| ERROR   | Failures requiring attention                    |
| WARNING | Degraded operation (rate limits, retries)       |
| INFO    | Normal operations (poll complete, action taken) |
| DEBUG   | Detailed tracing (event processing, rule eval)  |

### Rate Limit Safety Margin

Research on GitHub rate limits:
- Authenticated: 5000 req/hour (core), 30 req/min (search)
- Notifications endpoint: included in core limit
- Safety buffer: pause when remaining < 100

**Calculation**:
- 60s poll interval = 60 polls/hour
- Each poll: 1 notifications + 0-2 pagination = ~3 req
- Total: ~180 req/hour (3.6% of limit)
- Safe for continuous 7+ day operation

---

## 7. Resolved NEEDS CLARIFICATION Items

| Item                 | Resolution                                      |
| -------------------- | ----------------------------------------------- |
| Language/Version     | Python 3.11+ (dataclasses, typing improvements) |
| Primary Dependencies | httpx, pydantic, typer, structlog, pyyaml       |
| Storage              | SQLite (sqlite3 stdlib)                         |
| Testing              | pytest + pytest-httpx + freezegun               |
| Target Platform      | macOS/Linux CLI                                 |
| Performance Goals    | < 60s detection, < 5s startup                   |
| Constraints          | 5000 req/hour rate limit, < 50MB memory         |

---

## 8. Future Considerations (Out of v1 Scope)

- **Webhook ingestion**: Add HTTP server mode for real-time events
- **Multiple config files**: Include directive for rule libraries
- **Rule templates**: Shareable rule patterns
- **Prometheus metrics**: Export for observability
- **Container distribution**: Docker image for easy deployment
