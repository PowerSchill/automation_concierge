# Data Model: Personal Automation Concierge

**Feature**: 001-github-automation-concierge
**Date**: 2026-01-10
**Status**: Complete

## Overview

This document defines the canonical data models used throughout the system. Models are implementation-agnostic but include typing hints for clarity.

---

## 1. Core Entities

### Event

The canonical representation of a GitHub activity, normalized from various GitHub API responses.

```
Event
├── id: string (unique identifier, e.g., "notif_123456")
├── github_id: string (original GitHub notification/event ID)
├── event_type: EventType (enum: mention, assignment, review_request, label_change, pr_open, issue_open, comment)
├── timestamp: datetime (UTC, when event occurred on GitHub)
├── source: EventSource
│   ├── owner: string (repo owner)
│   ├── repo: string (repo name)
│   ├── type: SourceType (enum: issue, pull_request)
│   └── number: integer (issue/PR number)
├── actor: string (GitHub username who triggered event)
├── subject: string (title of issue/PR)
├── url: string (GitHub web URL)
├── payload: object (raw GitHub payload, preserved for debugging)
└── received_at: datetime (UTC, when we received it)
```

**Validation Rules**:
- `id` must be non-empty and unique within processing window
- `timestamp` must be valid ISO-8601 datetime
- `source.number` must be positive integer
- `event_type` must be a recognized enum value

### Rule

A user-defined condition-action pair that determines when and how to react to events.

```
Rule
├── id: string (unique identifier, user-defined, e.g., "mention-notify")
├── name: string (human-readable name)
├── enabled: boolean (default: true)
├── trigger: Trigger
│   ├── event_type: EventType (required, what event to match)
│   └── conditions: list[Condition] (optional, additional filters)
├── action: ActionConfig
│   ├── type: ActionType (enum: console, slack, github_comment)
│   ├── message: string (template with {{ event.field }} placeholders)
│   └── config: object (action-specific settings)
└── metadata: RuleMetadata
    ├── created_at: datetime
    └── description: string (optional)
```

**Validation Rules**:
- `id` must match pattern `^[a-z0-9-]+$` (lowercase, alphanumeric, hyphens)
- `id` must be unique across all rules
- `name` must be non-empty, max 100 characters
- `trigger.event_type` must be valid EventType
- `action.type` must be valid ActionType
- If `action.type` is `github_comment`, the action section must have `opt_in: true`

### Condition

A filter applied to an event to determine if a rule should trigger.

```
Condition (union type)
├── EventTypeCondition
│   └── event_type: EventType (matches specific event type)
│
├── LabelCondition
│   ├── type: "label_present" | "label_added" | "label_removed"
│   └── label: string (label name to match)
│
├── TimeSinceCondition
│   ├── type: "time_since"
│   ├── field: "created_at" | "updated_at"
│   └── threshold: duration (e.g., "48h", "7d")
│
├── NoActivityCondition
│   ├── type: "no_activity"
│   ├── activity: "review" | "comment" | "commit"
│   └── since: "created_at" | "updated_at"
│
└── RepoCondition
    ├── type: "repo_match"
    └── pattern: string (glob pattern, e.g., "myorg/*")
```

### Action

An operation to perform when a rule matches an event.

```
ActionConfig
├── type: ActionType (console, slack, github_comment)
├── message: string (message template)
└── [type-specific fields]

ConsoleAction (type: console)
└── (no additional fields)

SlackAction (type: slack)
├── channel: string (optional, for display only; actual target is webhook)
└── (webhook_url from global config)

GitHubCommentAction (type: github_comment)
├── opt_in: boolean (MUST be true)
└── (uses GITHUB_TOKEN from env)
```

### ActionResult

The outcome of executing an action.

```
ActionResult
├── action_type: ActionType
├── status: ResultStatus (enum: success, failed, skipped, dry_run)
├── message: string (what was sent/would be sent)
├── target: string (where it was sent, e.g., "slack:#channel")
├── error: string (if status is failed)
├── executed_at: datetime (UTC)
└── retry_count: integer (how many retries were attempted)
```

---

## 2. State Entities

### Checkpoint

Tracks the system's position in the event stream for resumability.

```
Checkpoint
├── id: string (default: "main", supports future multi-stream)
├── last_event_timestamp: datetime (UTC, timestamp of last processed event)
├── last_poll_timestamp: datetime (UTC, when we last polled GitHub)
└── updated_at: datetime (UTC, when checkpoint was saved)
```

**Invariants**:
- `last_event_timestamp` is monotonically increasing (never goes backward)
- `last_poll_timestamp >= last_event_timestamp` (poll happens after event)

### ProcessedEvent

Records that an event has been evaluated, preventing duplicate processing.

```
ProcessedEvent
├── event_id: string (primary key, matches Event.id)
├── event_type: EventType
├── disposition: Disposition (enum: action_executed, no_match, dry_run, error, skipped)
├── processed_at: datetime (UTC)
└── ttl_expires_at: datetime (UTC, for cleanup; default: processed_at + 30 days)
```

**Dispositions**:
| Value             | Meaning                                                |
| ----------------- | ------------------------------------------------------ |
| `action_executed` | At least one rule matched and action succeeded         |
| `no_match`        | No rules matched this event                            |
| `dry_run`         | Rules matched but dry-run mode prevented execution     |
| `error`           | Processing failed (rule eval or action execution)      |
| `skipped`         | Event was filtered out (e.g., outside lookback window) |

### ActionHistory

Tracks which actions have been executed for each event-rule pair (for idempotency).

```
ActionHistory
├── id: integer (auto-increment primary key)
├── event_id: string (foreign key to Event.id)
├── rule_id: string (foreign key to Rule.id)
├── action_type: ActionType
├── result: ResultStatus
├── message: string (what was sent)
├── executed_at: datetime (UTC)
└── UNIQUE(event_id, rule_id)
```

### AuditLogEntry

Full decision trail for debugging and explainability.

```
AuditLogEntry
├── id: integer (auto-increment primary key)
├── timestamp: datetime (UTC)
├── event_id: string (nullable, for system events)
├── event_type: EventType (nullable)
├── event_source: string (e.g., "owner/repo#123")
├── rules_evaluated: list[RuleEvaluation]
│   ├── rule_id: string
│   ├── rule_name: string
│   ├── matched: boolean
│   └── match_reason: string (human-readable explanation)
├── actions_taken: list[ActionSummary]
│   ├── action_type: ActionType
│   ├── target: string
│   ├── result: ResultStatus
│   └── message_preview: string (first 100 chars)
├── disposition: Disposition
└── message: string (overall summary)
```

---

## 3. Configuration Entities

### Config

Top-level configuration loaded from YAML.

```
Config
├── version: integer (schema version, currently 1)
├── github: GitHubConfig
│   ├── poll_interval: integer (seconds, 30-300, default: 60)
│   └── lookback_window: integer (seconds, default: 3600)
├── actions: ActionsConfig
│   ├── slack: SlackConfig (optional)
│   │   └── webhook_url: string (or env var reference)
│   └── github_comment: GitHubCommentConfig (optional)
│       └── enabled: boolean (default: false)
├── rules: list[Rule]
└── state: StateConfig (optional)
    ├── directory: string (default: ~/.concierge/)
    └── retention_days: integer (default: 30)
```

**Environment Variable Expansion**:
- Values like `"${SLACK_WEBHOOK_URL}"` are expanded at load time
- Missing env vars cause validation failure (fail loudly)

---

## 4. Enumerations

### EventType

```
EventType (enum)
├── mention          # User was @mentioned
├── assignment       # User was assigned to issue/PR
├── review_request   # User was requested to review PR
├── label_change     # Label was added/removed (if user is involved)
├── pr_open          # PR was opened (if user is author)
├── issue_open       # Issue was opened (if user is author)
├── comment          # Comment was added (if user is involved)
└── review           # Review was submitted (if user is involved)
```

### ActionType

```
ActionType (enum)
├── console          # Print to stdout
├── slack            # POST to Slack webhook
└── github_comment   # Comment on GitHub issue/PR
```

### Disposition

```
Disposition (enum)
├── action_executed  # Action(s) successfully executed
├── no_match         # No rules matched
├── dry_run          # Would have executed (dry-run mode)
├── error            # Processing failed
└── skipped          # Intentionally skipped
```

### ResultStatus

```
ResultStatus (enum)
├── success          # Action completed successfully
├── failed           # Action failed after retries
├── skipped          # Action was skipped (dry-run or rate limit)
└── pending          # Action queued but not yet executed
```

---

## 5. Entity Relationships

```text
                    ┌─────────────────┐
                    │     Config      │
                    └────────┬────────┘
                             │ contains
                             ▼
┌──────────────┐       ┌─────────────────┐
│ GitHubConfig │◄──────│      Rule       │
└──────────────┘       └────────┬────────┘
                                │ defines
                                ▼
                       ┌─────────────────┐
                       │    Trigger      │
                       │  (conditions)   │
                       └────────┬────────┘
                                │ matches
                                ▼
┌──────────────┐       ┌─────────────────┐       ┌─────────────────┐
│  Checkpoint  │◄──────│     Event       │──────►│ ProcessedEvent  │
└──────────────┘       └────────┬────────┘       └─────────────────┘
     tracks                     │ triggers
                                ▼
                       ┌─────────────────┐
                       │  ActionResult   │──────►┌─────────────────┐
                       └─────────────────┘       │  ActionHistory  │
                                │                └─────────────────┘
                                │ logged to
                                ▼
                       ┌─────────────────┐
                       │ AuditLogEntry   │
                       └─────────────────┘
```

---

## 6. Data Flow

```text
1. GitHub API Response (raw JSON)
        │
        ▼
2. Event (normalized canonical format)
        │
        ├──► Checkpoint (update stream position)
        │
        ▼
3. Rule Evaluation (for each rule)
        │
        ├──► no match ──► ProcessedEvent (disposition: no_match)
        │
        ▼ match
4. ActionResult (execute action)
        │
        ├──► ActionHistory (record event+rule pair)
        │
        ▼
5. ProcessedEvent (disposition: action_executed)
        │
        ▼
6. AuditLogEntry (full decision trail)
```

---

## 7. Storage Schema (SQLite)

See [research.md](./research.md#schema-design) for full SQL schema.

### Table Summary

| Table              | Primary Key | Purpose                |
| ------------------ | ----------- | ---------------------- |
| `schema_version`   | `version`   | Migration tracking     |
| `checkpoints`      | `id`        | Stream position        |
| `processed_events` | `event_id`  | Deduplication          |
| `action_history`   | `id`        | Per-rule deduplication |
| `audit_log`        | `id`        | Full audit trail       |

### Indexes

| Index                            | Table              | Columns        | Purpose            |
| -------------------------------- | ------------------ | -------------- | ------------------ |
| `idx_processed_events_timestamp` | `processed_events` | `processed_at` | Cleanup queries    |
| `idx_action_history_event`       | `action_history`   | `event_id`     | Lookup by event    |
| `idx_audit_log_timestamp`        | `audit_log`        | `timestamp`    | Time-range queries |
