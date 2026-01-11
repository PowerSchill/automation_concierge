# Implementation Plan: Personal Automation Concierge

**Branch**: `001-github-automation-concierge` | **Date**: 2026-01-10 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-github-automation-concierge/spec.md`

## Summary

Build a single-user CLI tool that polls GitHub for events (mentions, assignments, labels), evaluates user-defined rules against those events, and executes notification actions (console, Slack, GitHub comment). The system prioritizes correctness, debuggability, and safe continuous operation over feature breadth.

**Technical Approach**: Python CLI application with polling-based GitHub ingestion, YAML rules configuration, SQLite state persistence, and structured JSON logging for audit trails.

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: httpx (HTTP client), pydantic (validation), typer (CLI), structlog (logging), pyyaml (config)
**Storage**: SQLite (via sqlite3 stdlib) for state; YAML files for configuration
**Testing**: pytest with pytest-httpx for mocking, freezegun for time control
**Target Platform**: macOS/Linux (CLI tool, runs locally or in containers)
**Project Type**: Single project
**Performance Goals**: Process events within 60s of detection; startup validation < 5s
**Constraints**: Must respect GitHub rate limits (5000 req/hour authenticated); <50MB memory steady state
**Scale/Scope**: Single user, ~10-50 rules, ~1000 events/day max

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### I. Code Quality

| Requirement              | Compliance | Notes                                                   |
| ------------------------ | ---------- | ------------------------------------------------------- |
| Style guides and linting | ✅ PASS     | ruff for linting/formatting, pyright for type checking  |
| Single responsibility    | ✅ PASS     | Architecture separates ingestion, rules, actions, state |
| Public API documentation | ✅ PASS     | Docstrings required on all public functions             |
| No code duplication      | ✅ PASS     | Shared utilities in `lib/` module                       |
| Dependencies pinned      | ✅ PASS     | requirements.txt with pinned versions + hash            |
| No dead code             | ✅ PASS     | Enforced via linting rules                              |

### II. Testing Standards

| Requirement                         | Compliance | Notes                                                |
| ----------------------------------- | ---------- | ---------------------------------------------------- |
| Test-First Development              | ✅ PASS     | Tests defined in tasks before implementation         |
| Red-Green-Refactor                  | ✅ PASS     | Workflow enforced in task structure                  |
| 80% coverage for business logic     | ✅ PASS     | Target: rules engine, action executor, state manager |
| Integration tests for external APIs | ✅ PASS     | GitHub API mocked via httpx fixtures                 |
| Contract tests                      | ✅ PASS     | Config schema validation, event schema tests         |
| Deterministic tests                 | ✅ PASS     | freezegun for time, recorded fixtures for API        |
| Given-When-Then naming              | ✅ PASS     | Test naming convention enforced                      |

### III. User Experience Consistency

| Requirement                 | Compliance | Notes                                            |
| --------------------------- | ---------- | ------------------------------------------------ |
| Actionable error messages   | ✅ PASS     | All errors include context and remediation hints |
| Feedback within 100ms       | N/A        | CLI tool, not interactive UI                     |
| Consistent terminology      | ✅ PASS     | Terms defined in glossary (event, rule, action)  |
| Breaking changes documented | ✅ PASS     | CHANGELOG.md + semantic versioning               |

### IV. Performance Requirements

| Requirement                   | Compliance | Notes                                            |
| ----------------------------- | ---------- | ------------------------------------------------ |
| Response times < 200ms        | ✅ PASS     | Per-event processing target < 100ms              |
| Memory stable over time       | ✅ PASS     | No unbounded caches; SQLite for persistence      |
| No N+1 queries                | ✅ PASS     | Batch event fetching; indexed SQLite queries     |
| Background tasks non-blocking | ✅ PASS     | Synchronous single-threaded design (no blocking) |

**Constitution Check Result**: ✅ ALL GATES PASS

## Project Structure

### Documentation (this feature)

```text
specs/001-github-automation-concierge/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── rules-schema.yaml
│   ├── config-schema.yaml
│   └── event-schema.yaml
└── tasks.md             # Phase 2 output
```

### Source Code (repository root)

```text
src/
├── concierge/
│   ├── __init__.py
│   ├── cli.py                 # Typer CLI entrypoint
│   ├── config/
│   │   ├── __init__.py
│   │   ├── loader.py          # Config file loading + validation
│   │   └── schema.py          # Pydantic models for config
│   ├── github/
│   │   ├── __init__.py
│   │   ├── client.py          # GitHub API client with rate limiting
│   │   ├── auth.py            # Token validation
│   │   └── events.py          # Event normalization
│   ├── rules/
│   │   ├── __init__.py
│   │   ├── engine.py          # Rule evaluation logic
│   │   ├── matchers.py        # Event matchers (type, label, time)
│   │   └── schema.py          # Rule pydantic models
│   ├── actions/
│   │   ├── __init__.py
│   │   ├── executor.py        # Action dispatch
│   │   ├── console.py         # Console action
│   │   ├── slack.py           # Slack webhook action
│   │   └── github_comment.py  # GitHub comment action
│   ├── state/
│   │   ├── __init__.py
│   │   ├── store.py           # SQLite state store
│   │   ├── checkpoint.py      # Checkpoint management
│   │   └── migrations.py      # Schema migrations
│   └── logging/
│       ├── __init__.py
│       └── audit.py           # Audit log formatting

tests/
├── conftest.py                # Shared fixtures
├── fixtures/                  # Recorded GitHub API responses
├── unit/
│   ├── test_rules_engine.py
│   ├── test_matchers.py
│   ├── test_config_loader.py
│   └── test_event_normalization.py
├── integration/
│   ├── test_github_client.py
│   ├── test_state_store.py
│   └── test_action_executor.py
└── e2e/
    └── test_mention_to_notification.py
```

**Structure Decision**: Single project structure selected. This is a CLI tool with no separate frontend/backend; all components are Python modules under `src/concierge/`.

---

## 1. Architecture

### v1 Architecture Overview

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                              CLI Entry Point                                 │
│                         (typer: run, run-once, validate)                    │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Config Loader                                   │
│                    (YAML parsing, Pydantic validation)                      │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
            ┌─────────────────────────┼─────────────────────────┐
            ▼                         ▼                         ▼
┌───────────────────┐   ┌───────────────────────┐   ┌───────────────────────┐
│   GitHub Client   │   │     Rules Engine      │   │    Action Executor    │
│   (httpx + auth)  │   │   (matchers + eval)   │   │ (console/slack/gh)    │
└───────────────────┘   └───────────────────────┘   └───────────────────────┘
            │                         │                         │
            └─────────────────────────┼─────────────────────────┘
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              State Store                                     │
│                  (SQLite: checkpoints, processed events, audit)             │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            Structured Logger                                 │
│                     (structlog: JSON to stderr)                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Data Flow

```text
INPUT                     PROCESSING                           OUTPUT
─────                     ──────────                           ──────
GitHub API     ─────►    Event Ingestion    ─────►    Normalized Events
(notifications,          (poll + normalize)            (canonical schema)
 events API)                   │
                               ▼
                         Rule Evaluation     ─────►    Match Results
                         (for each event,              (rule_id, matched: bool)
                          check all rules)
                               │
                               ▼
                         Action Execution    ─────►    Action Results
                         (if matched +                 (success/failure + details)
                          not duplicate)
                               │
                               ▼
                         State Persistence   ─────►    SQLite DB
                         (checkpoint,                  (durable state)
                          processed events)
                               │
                               ▼
                         Audit Logging       ─────►    stderr (JSON)
                         (decision trail)              + audit table
```

### Polling vs Webhooks: Decision

**v1 Decision**: Polling

**Justification**:
1. **No infrastructure required**: Webhooks need a publicly accessible endpoint (requires ngrok, cloud hosting, or similar)
2. **Single-user simplicity**: For one user, polling 1-2 times per minute uses ~100 API calls/hour (2% of rate limit)
3. **Debuggability**: Easier to test and simulate without HTTP server complexity
4. **Failure modes simpler**: Transient failures just delay the next poll; no missed webhook delivery concerns

**Future Webhook Migration Path**:
- Add `webhook` ingestion mode alongside `polling` (config flag)
- Extract event normalization to shared module (already planned)
- Add lightweight HTTP server (e.g., uvicorn + starlette) for webhook receiver
- Webhook handler calls same `normalize_event()` → `evaluate_rules()` pipeline
- State store already handles idempotency, so dual-ingestion is safe

### Component Responsibilities

| Component            | Responsibility                                      | Key Interfaces                                |
| -------------------- | --------------------------------------------------- | --------------------------------------------- |
| **CLI**              | Parse args, orchestrate startup/shutdown, main loop | `run()`, `run_once()`, `validate()`           |
| **Config Loader**    | Load YAML, validate against schema, fail loudly     | `load_config(path) → Config`                  |
| **GitHub Client**    | Authenticate, poll events, handle rate limits       | `fetch_events(since) → list[RawEvent]`        |
| **Event Normalizer** | Convert GitHub payloads to canonical Event          | `normalize(RawEvent) → Event`                 |
| **Rules Engine**     | Evaluate events against rules, determine matches    | `evaluate(Event, list[Rule]) → list[Match]`   |
| **Action Executor**  | Dispatch actions, record results, handle failures   | `execute(Action, Event) → ActionResult`       |
| **State Store**      | Persist checkpoints, track processed events         | `save_checkpoint()`, `is_processed(event_id)` |
| **Audit Logger**     | Structured logging with decision trail              | `log_decision(event, rule, action, result)`   |

---

## 2. GitHub Integration Details

### API Endpoints Used

| Endpoint                                    | Purpose                                                    | Polling Frequency        |
| ------------------------------------------- | ---------------------------------------------------------- | ------------------------ |
| `GET /notifications`                        | User's notification inbox (mentions, assignments, reviews) | Every poll (60s default) |
| `GET /users/{user}/events`                  | Backup for events not in notifications                     | Every 5 polls (5 min)    |
| `GET /repos/{owner}/{repo}/issues/{number}` | Fetch full issue/PR for time-based rules                   | On-demand (cached)       |
| `GET /rate_limit`                           | Check remaining quota                                      | Before each poll cycle   |

### Authentication

**v1 Decision**: Personal Access Token (PAT)

**Justification**:
1. **Single-user tool**: PAT is the simplest auth for personal use
2. **No OAuth dance**: No need for callback URLs or token refresh flows
3. **Fine-grained tokens available**: GitHub now offers fine-grained PATs with minimal scopes
4. **GitHub Apps overkill**: Apps are designed for multi-user/org scenarios

**Required Scopes**:
- `notifications` (read notifications)
- `repo` (read issues/PRs for repositories, required for private repos)

**Token Handling**:
- Read from `GITHUB_TOKEN` environment variable
- Never logged (redacted in debug output)
- Validated at startup: `GET /user` to confirm auth works + check scopes

### Rate Limit Handling

```text
Rate Limit Strategy:
─────────────────────
1. Before each poll cycle:
   - Call GET /rate_limit
   - If remaining < 100 (safety buffer):
     - Log warning with reset timestamp
     - Sleep until reset + 10s jitter
   - Otherwise proceed

2. On 403 with X-RateLimit-Remaining: 0:
   - Parse X-RateLimit-Reset header
   - Sleep until reset + 10s jitter
   - Retry once

3. Secondary rate limits (abuse detection):
   - On 403 with "abuse" message:
     - Exponential backoff: 1min → 2min → 4min → 8min (max)
     - Log as warning, not error
     - Never exceed 4 retries per poll cycle

4. Poll interval tuning:
   - Default: 60s
   - Configurable: 30s–300s range
   - Conservative default ensures 7+ days operation
```

### Pagination

- `/notifications` returns up to 50 items per page
- Use `Link` header for pagination (parse `rel="next"`)
- Fetch all pages in a single poll cycle (typically 1-2 pages for active user)
- Stop pagination if total items exceed 500 (safety limit, log warning)

---

## 3. Data Model & State

> See [data-model.md](./data-model.md) for full entity definitions.

### State for Correctness & Idempotency

| State Type           | Purpose                               | Storage                            |
| -------------------- | ------------------------------------- | ---------------------------------- |
| **Checkpoint**       | Last successfully processed timestamp | SQLite: `checkpoints` table        |
| **Processed Events** | Dedupe key → disposition              | SQLite: `processed_events` table   |
| **Action History**   | event_id + rule_id → action result    | SQLite: `action_history` table     |
| **Audit Log**        | Full decision trail                   | SQLite: `audit_log` table + stderr |

### v1 Storage Choice: SQLite

**Justification**:
1. **Zero dependencies**: sqlite3 is in Python stdlib
2. **ACID transactions**: Checkpoint + event marking in single transaction
3. **Queryable audit log**: Can inspect state with standard SQL tools
4. **Portable**: Single file, easy backup/restore
5. **Sufficient scale**: Handles 1M+ rows trivially for single-user workload

**Location**: `~/.concierge/state.db` (configurable via `--state-dir`)

### Migration Path

```text
v1: SQLite (file)
    │
    ▼ (if needed)
v2: SQLite with WAL mode for better concurrency
    │
    ▼ (if needed)
v3: PostgreSQL for multi-user/distributed scenarios

Migration strategy:
- All state access via StateStore abstraction
- Migrations versioned in `migrations.py`
- Export/import commands for data portability
- Schema version stored in DB metadata table
```

---

## 4. Rule Engine Semantics

### When Rules Run

Rules are evaluated **per-event** after each poll cycle:

```text
Poll Cycle:
1. Fetch new events since last checkpoint
2. For each event:
   a. Check if already processed (dedupe)
   b. If new: evaluate against ALL active rules
   c. For each matching rule: queue action
   d. Execute queued actions
   e. Mark event as processed with disposition
3. Update checkpoint to latest event timestamp
4. Sleep until next poll interval
```

### Evaluation Window (Time-Based Rules)

For rules like "PR open > 48 hours without review":

- **Activity definition**: Configurable per rule, defaults:
  - For "no review": any review or review comment
  - For "no comment": any comment from non-author
  - For "no merge": PR merged or closed
- **Time source**: GitHub's `created_at` / `updated_at` timestamps (UTC)
- **Clock skew assumption**: System clock within 5 minutes of GitHub's (reasonable for NTP-synced hosts)
- **Evaluation timing**: Time-based rules checked every poll cycle; if threshold crossed, trigger fires

### Idempotency Guarantees

```text
Dedupe Strategy:
────────────────
1. Event-level dedupe:
   - Key: (github_event_id, event_type)
   - Stored in processed_events table
   - Checked before rule evaluation

2. Action-level dedupe:
   - Key: (event_id, rule_id)
   - Stored in action_history table
   - Checked before action execution
   - Prevents re-notification on restart

3. Time-based rule dedupe:
   - Key: (entity_id, rule_id, threshold_key)
   - Example: (PR-123, stale-pr-rule, 48h)
   - Only fires once per threshold crossing
```

### Error Handling During Evaluation

| Error Scenario                     | Behavior                                                   |
| ---------------------------------- | ---------------------------------------------------------- |
| Rule references missing config     | Fail loudly at startup (validation)                        |
| API failure during fetch           | Retry with backoff; skip event if persistent               |
| Matcher throws exception           | Log error, mark rule as "errored" for this event, continue |
| Time-based rule can't fetch entity | Skip this rule for this cycle, log warning                 |

---

## 5. Action Execution & Safety

### Supported Actions (v1)

| Action Type      | Description           | Config Required           |
| ---------------- | --------------------- | ------------------------- |
| `console`        | Print to stdout       | None (default)            |
| `slack`          | POST to Slack webhook | `webhook_url`             |
| `github-comment` | Comment on issue/PR   | `opt_in: true` (explicit) |

### Dry-Run Mode

```text
Dry-run behavior:
─────────────────
- Enabled via: --dry-run flag
- What it logs:
  ✓ Event received: {event details}
  ✓ Rule matched: {rule_id, rule_name}
  ✓ Action WOULD execute: {action_type, target, message}
  ✓ Action skipped: dry-run mode

- What it NEVER does:
  ✗ POST to Slack webhook
  ✗ POST to GitHub API (comments)
  ✗ Mark events as "action_executed" (only "dry_run_matched")

- State behavior:
  - Checkpoint IS updated (to track progress)
  - processed_events marked with disposition="dry_run"
  - Allows re-running in live mode to actually notify
```

### Retry Semantics

```text
Action Retry Policy:
────────────────────
1. Console: No retry (always succeeds)

2. Slack webhook:
   - Retry: 3 attempts
   - Backoff: 1s → 2s → 4s
   - On persistent failure: log error, mark as "failed", continue
   - No notification storm: max 10 Slack messages per minute (queue + throttle)

3. GitHub comment:
   - Retry: 2 attempts
   - Backoff: 2s → 5s
   - On persistent failure: log error, mark as "failed", continue
   - Rate limit: max 1 comment per issue per hour (prevent spam)
```

### Explainability: Audit Record Format

```json
{
  "timestamp": "2026-01-10T15:30:00Z",
  "event_id": "gh_notif_12345",
  "event_type": "mention",
  "event_source": "repo/issue#42",
  "rules_evaluated": [
    {
      "rule_id": "mention-notify",
      "rule_name": "Notify on mention",
      "matched": true,
      "match_reason": "event_type=mention AND user=@me"
    },
    {
      "rule_id": "stale-pr",
      "rule_name": "Stale PR reminder",
      "matched": false,
      "match_reason": "event_type != pr_open"
    }
  ],
  "actions_taken": [
    {
      "action_type": "slack",
      "target": "#notifications",
      "result": "success",
      "message_preview": "You were mentioned in repo/issue#42"
    }
  ],
  "disposition": "action_executed"
}
```

---

## 6. CLI / UX

### Commands

```text
concierge run [OPTIONS]
    Run the concierge in daemon mode (continuous polling)

    --config PATH       Config file path (default: ~/.concierge/config.yaml)
    --state-dir PATH    State directory (default: ~/.concierge/)
    --dry-run           Log actions without executing
    --once              Run one poll cycle and exit (same as run-once)
    --verbose           Enable debug logging
    --poll-interval N   Override poll interval in seconds (30-300)

concierge run-once [OPTIONS]
    Run a single poll cycle and exit
    (same options as run)

concierge validate [OPTIONS]
    Validate configuration without running

    --config PATH       Config file path

concierge status [OPTIONS]
    Show current state (last checkpoint, pending events)

    --state-dir PATH    State directory

concierge audit [OPTIONS]
    Query audit log

    --since DATETIME    Filter by timestamp
    --rule RULE_ID      Filter by rule
    --limit N           Max records to show (default: 50)
```

### Configuration Discovery

```text
Config search order:
1. --config PATH (explicit)
2. $CONCIERGE_CONFIG (env var)
3. ./concierge.yaml (current directory)
4. ~/.concierge/config.yaml (default location)

State directory:
1. --state-dir PATH (explicit)
2. $CONCIERGE_STATE_DIR (env var)
3. ~/.concierge/ (default)
```

### Exit Codes

| Code | Meaning                                               |
| ---- | ----------------------------------------------------- |
| 0    | Success (clean exit or run-once completed)            |
| 1    | Configuration error (invalid config, missing file)    |
| 2    | Authentication error (invalid token, missing scopes)  |
| 3    | Partial failure (some actions failed, some succeeded) |
| 4    | Fatal error (unrecoverable, e.g., state corruption)   |

---

## 7. Testing Strategy

### Unit Tests

| Module              | Test Focus            | Example Scenarios                                      |
| ------------------- | --------------------- | ------------------------------------------------------ |
| `rules/engine.py`   | Rule evaluation logic | Match on event type, no match, multiple matches        |
| `rules/matchers.py` | Individual matchers   | Time threshold, label presence, mention detection      |
| `config/loader.py`  | Config validation     | Valid config, missing fields, invalid types            |
| `github/events.py`  | Event normalization   | Notification → Event, raw event → Event                |
| `state/store.py`    | State operations      | Save/load checkpoint, dedupe check, transaction safety |

### Integration Tests

| Scenario                      | Setup                              | Assertions                      |
| ----------------------------- | ---------------------------------- | ------------------------------- |
| GitHub client with rate limit | Mock httpx with rate limit headers | Client pauses and retries       |
| State store persistence       | Create DB, write, close, reopen    | Data survives restart           |
| Action executor with Slack    | Mock webhook endpoint              | Correct payload sent            |
| Full poll cycle               | Mock GitHub API, real rules        | Events processed, state updated |

### End-to-End Test Scenario

```text
Scenario: Mention triggers Slack notification

Initial State:
- Config with rule: "on mention → slack"
- Empty state database
- Mock GitHub returning one mention notification

Incoming Events:
- GitHub /notifications returns:
  { id: "123", reason: "mention", subject: { type: "Issue" } }

Expected Actions:
1. Event normalized to canonical format
2. Rule "mention-notify" matches
3. Slack action queued
4. Slack webhook POST sent (mocked)
5. Event marked as processed
6. Audit log entry written

Assertions:
- Slack POST request matches expected payload
- processed_events has entry for "123"
- audit_log has decision trail
- Checkpoint updated to event timestamp
```

### Determinism Strategy

```text
Time Control:
- freezegun for all time-dependent tests
- All modules use `time_provider` abstraction (injectable)
- Time-based rules tested at exact threshold boundaries

API Fixtures:
- Recorded responses stored in tests/fixtures/
- pytest-httpx for request/response mocking
- Fixtures versioned alongside tests

Random/UUID:
- Seed random generators in tests
- Use deterministic UUIDs via factory functions
```

---

## 8. Operational Concerns

### Logging Format

```text
Format: Structured JSON to stderr

Log Levels:
- ERROR: Action failures, API errors, state corruption
- WARNING: Rate limit approaching, transient failures
- INFO: Poll cycle start/end, actions taken
- DEBUG: Individual event processing, rule evaluation

Example:
{"timestamp": "2026-01-10T15:30:00Z", "level": "INFO",
 "event": "poll_cycle_complete", "events_processed": 5,
 "actions_taken": 2, "duration_ms": 1234}
```

### Metrics (v1: Logging Only)

```text
Metrics to log (for future Prometheus/StatsD export):
- poll_cycle_duration_ms
- events_processed_total
- rules_matched_total
- actions_executed_total (by type)
- actions_failed_total (by type)
- rate_limit_remaining
- rate_limit_pauses_total
```

### Continuous Operation

```text
Run Loop:
1. Poll for events
2. Process events
3. Sleep for poll_interval + random jitter (0-10%)
4. Repeat

Graceful Shutdown:
- SIGTERM/SIGINT handlers
- Complete current poll cycle (don't interrupt mid-action)
- Flush pending audit logs
- Exit with code 0

Jitter: Prevents thundering herd if multiple instances exist (future)
```

### Secret Handling

```text
Secrets:
- GITHUB_TOKEN: Read from env, never logged
- SLACK_WEBHOOK_URL: Read from config, URL redacted in logs
- State DB: chmod 600 on creation

Validation:
- Token validated at startup (GET /user)
- Webhook URL format validated at startup
- Missing secrets = exit code 2
```

---

## 9. Deliverables & Milestones

### v1 Milestone Breakdown

| #   | Deliverable                       | Dependencies | Definition of Done                           |
| --- | --------------------------------- | ------------ | -------------------------------------------- |
| M1  | Project scaffold + CLI skeleton   | None         | `concierge --help` works, CI green           |
| M2  | Config loader + validation        | M1           | `concierge validate` passes/fails correctly  |
| M3  | GitHub client + auth              | M1           | Can fetch notifications, handles rate limits |
| M4  | Event normalization               | M3           | Notifications → canonical Event format       |
| M5  | Rules engine (event-type matcher) | M2, M4       | Simple rules match events correctly          |
| M6  | State store + checkpointing       | M1           | Survives restart, no duplicate processing    |
| M7  | Action executor (console + Slack) | M5, M6       | Actions fire, dry-run works                  |
| M8  | Integration + E2E tests           | M1-M7        | All success criteria verified                |

### Sequencing

```text
Week 1: M1 (scaffold) → M2 (config) → M3 (GitHub client)
Week 2: M4 (events) → M5 (rules engine)
Week 3: M6 (state) → M7 (actions)
Week 4: M8 (testing) → Documentation → Release
```

### Success Criteria Mapping

| Success Criterion                      | Verified By                      |
| -------------------------------------- | -------------------------------- |
| SC-001: Config validated < 5s          | M2 unit tests + benchmark        |
| SC-002: Detect mention < 2 poll cycles | M7 E2E test                      |
| SC-003: 100% audit logging             | M7 integration tests             |
| SC-004: No duplicates over 7 days      | M6 state store tests + soak test |
| SC-005: No rate limit violations       | M3 integration tests + soak test |
| SC-006: Explainable in 30s             | M7 audit log query test          |
| SC-007: Resume from checkpoint         | M6 restart test                  |
| SC-008: Dry-run identical logs         | M7 dry-run comparison test       |
| SC-009: Invalid config fails loudly    | M2 validation tests              |

---

## 10. Risks & Open Questions

### Risks and Mitigations

| #   | Risk                                         | Likelihood | Impact   | Mitigation                                                                               |
| --- | -------------------------------------------- | ---------- | -------- | ---------------------------------------------------------------------------------------- |
| R1  | **GitHub API rate limit exhaustion**         | Medium     | High     | Conservative default poll interval (60s); quota monitoring; pause when < 100 remaining   |
| R2  | **Missed events during downtime**            | Medium     | Medium   | GitHub notifications persist ~30 days; lookback on restart; document missed event window |
| R3  | **Duplicate notifications on restart**       | High       | Medium   | Strong dedupe via event_id + rule_id in state store; verified in tests                   |
| R4  | **Config errors causing silent misbehavior** | Medium     | High     | Strict schema validation at startup; fail loudly on any ambiguity                        |
| R5  | **Notification spam from rule loops**        | Low        | High     | Action rate limits (10/min Slack, 1/hour/issue GitHub); dedupe keys                      |
| R6  | **State database corruption**                | Low        | Critical | SQLite WAL mode; regular checkpoint; export command for backup                           |
| R7  | **Slack webhook URL leakage in logs**        | Low        | Medium   | URL redaction in log output; env var option for sensitive config                         |

### Open Questions

| #   | Question                                                           | Proposed Resolution                            | Decision Owner             |
| --- | ------------------------------------------------------------------ | ---------------------------------------------- | -------------------------- |
| Q1  | Should time-based rules use poll-time or event-time for threshold? | Event-time (GitHub timestamps) for consistency | Confirmed: event-time      |
| Q2  | How long to retain processed events in state DB?                   | 30 days default, configurable                  | Configurable               |
| Q3  | Should GitHub comment action require explicit per-rule opt-in?     | Yes, too risky otherwise                       | Confirmed: explicit opt-in |
| Q4  | Support multiple config files (rules separate from main config)?   | v1: single file; v2: include directive         | Deferred to v2             |
| Q5  | Timezone handling for user-facing timestamps?                      | UTC in storage/logs; local time in CLI output  | UTC + local display        |

---

## Complexity Tracking

> No violations to justify. Design follows minimal patterns aligned with Constitution.
