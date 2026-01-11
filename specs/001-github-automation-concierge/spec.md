# Feature Specification: Personal Automation Concierge

**Feature Branch**: `001-github-automation-concierge`
**Created**: 2026-01-10
**Status**: Draft
**Input**: User description: "Build a Personal Automation Concierge that monitors my GitHub activity and performs automated follow-up actions based on explicit, user-defined rules."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Define and Trigger a Simple Rule (Priority: P1)

As a developer, I want to define a rule that detects when I am mentioned in a GitHub issue or PR comment, so that I receive a notification and never miss important conversations.

**Why this priority**: This is the core value proposition—without the ability to define a rule and have it trigger an action, the system provides no value. This story validates the entire event-to-action pipeline.

**Independent Test**: Can be fully tested by creating a rule file, running the system, generating a GitHub mention, and verifying a notification is delivered. Delivers immediate value: awareness of mentions.

**Acceptance Scenarios**:

1. **Given** a rule configuration that matches "user mentioned in comment", **When** I am mentioned in a GitHub issue comment, **Then** a notification is sent within 60 seconds of the event being detected.
2. **Given** the same rule configuration, **When** the mention has already triggered a notification, **Then** the system does NOT send a duplicate notification for the same event.
3. **Given** a rule configuration exists, **When** I run the system in dry-run mode, **Then** the system logs what action WOULD be taken without actually sending a notification.

---

### User Story 2 - Understand Why an Action Was Taken (Priority: P2)

As a developer, I want to inspect logs and state to understand exactly why a notification was sent (or not sent), so that I can debug rules and trust the system's behavior.

**Why this priority**: Debuggability is essential for trust. Without the ability to explain actions, users cannot confidently rely on or troubleshoot the system.

**Independent Test**: Can be tested by triggering a rule, then querying logs/state to see the full decision trail (event received → rule matched → action taken → result recorded).

**Acceptance Scenarios**:

1. **Given** a notification was sent, **When** I inspect the audit log, **Then** I can see the event that triggered it, the rule that matched, and the action result.
2. **Given** a matching event occurred but no notification was sent, **When** I inspect the audit log, **Then** I can see why (e.g., "already processed", "rate limit", "dry-run mode").
3. **Given** the system is running, **When** I query the current state, **Then** I can see which events have been processed and their disposition.

---

### User Story 3 - Safe Continuous Operation (Priority: P3)

As a developer, I want the system to run continuously without missing events or exceeding rate limits, so that I can trust it to operate unattended.

**Why this priority**: Long-running reliability is critical for a monitoring system, but only matters once the core rule-trigger-notify loop works.

**Independent Test**: Can be tested by running the system for an extended period and verifying no duplicate actions, no missed events, and no rate limit violations.

**Acceptance Scenarios**:

1. **Given** the system has been running for 24 hours, **When** I check the logs, **Then** there are zero rate limit errors from GitHub.
2. **Given** a transient network failure occurs, **When** the system recovers, **Then** it resumes from the last known state without reprocessing already-handled events.
3. **Given** the system is started after being stopped, **When** it resumes, **Then** it picks up from the last checkpoint and does not miss events that occurred while stopped (within polling window).

---

### User Story 4 - Time-Based Rule Triggers (Priority: P4)

As a developer, I want to define rules that trigger based on time conditions (e.g., "PR open for more than 48 hours without review"), so that I can catch stale items.

**Why this priority**: Time-based rules extend the system's utility beyond immediate event reactions but depend on the core infrastructure being solid.

**Independent Test**: Can be tested by creating a time-based rule, having a PR exist beyond the threshold, and verifying the notification triggers.

**Acceptance Scenarios**:

1. **Given** a rule "notify if my PR has no review after 48 hours", **When** a PR I authored has been open for 49 hours without review, **Then** a notification is sent.
2. **Given** the same rule, **When** the PR receives a review before 48 hours, **Then** no notification is sent.
3. **Given** a time-based notification was already sent for a PR, **When** the same PR remains without review, **Then** no duplicate notification is sent (unless rule specifies repeat interval).

---

### User Story 5 - Label-Based Rule Triggers (Priority: P5)

As a developer, I want to define rules that trigger based on label changes (e.g., "notify when 'needs-response' label is added to my issue"), so that I can react to workflow signals.

**Why this priority**: Label-based rules add flexibility for team workflows but are an enhancement beyond the MVP.

**Independent Test**: Can be tested by creating a label-based rule, adding the target label to an issue, and verifying notification delivery.

**Acceptance Scenarios**:

1. **Given** a rule "notify when 'needs-response' label added to issues I'm assigned to", **When** that label is added to an assigned issue, **Then** a notification is sent.
2. **Given** the same rule, **When** a different label is added, **Then** no notification is sent.

---

### User Story 6 - Multiple Action Types (Priority: P6)

As a developer, I want rules to support multiple action types (at minimum: console/CLI output, Slack message, and GitHub comment), so that I can choose the right notification channel for each situation.

**Why this priority**: Multiple action types increase utility but require the core action execution framework to be stable first.

**Independent Test**: Can be tested by configuring different action types for different rules and verifying each action type executes correctly.

**Acceptance Scenarios**:

1. **Given** a rule configured with action type "slack", **When** the rule triggers, **Then** a message is posted to the configured Slack channel.
2. **Given** a rule configured with action type "github-comment", **When** the rule triggers, **Then** a comment is posted to the relevant issue/PR (only if user has explicitly opted in).
3. **Given** a rule configured with action type "console", **When** the rule triggers, **Then** the notification is printed to stdout.

---

### Edge Cases

- What happens when GitHub returns a 5xx error during event polling? System retries with exponential backoff and logs the failure.
- What happens when the rules configuration file is malformed? System fails loudly at startup with a clear error message indicating the problem.
- What happens when a rule references an action type that isn't configured? System fails loudly at startup with a validation error.
- What happens when the same event matches multiple rules? All matching rules trigger their respective actions (no short-circuit).
- What happens when the notification channel (e.g., Slack) is unavailable? System logs the failure, marks action as failed, and continues processing other events.

## Requirements *(mandatory)*

### Functional Requirements

#### Authentication & Authorization
- **FR-001**: System MUST authenticate with GitHub using a personal access token provided via environment variable.
- **FR-002**: System MUST validate the token has required scopes at startup and fail loudly if insufficient.
- **FR-003**: System MUST NOT store or log the authentication token in plaintext.

#### Event Ingestion
- **FR-004**: System MUST poll GitHub for events relevant to the authenticated user (notifications, mentions, assigned issues/PRs).
- **FR-005**: System MUST track the last processed event timestamp to avoid reprocessing.
- **FR-006**: System MUST respect GitHub API rate limits by checking remaining quota before each request.
- **FR-007**: System MUST pause polling when rate limit is near exhaustion and resume when quota resets.

#### Rules Engine
- **FR-008**: System MUST load rules from a declarative configuration file at startup.
- **FR-009**: System MUST validate all rules at startup and fail loudly if any rule is invalid.
- **FR-010**: System MUST evaluate each incoming event against all active rules.
- **FR-011**: System MUST support rules that match on event type (mention, assignment, label change, etc.).
- **FR-012**: System MUST support rules that include time-based conditions (e.g., "PR open > 48 hours").
- **FR-013**: System MUST support rules that match on label presence or changes.

#### Action Execution
- **FR-014**: System MUST execute the configured action when a rule matches an event.
- **FR-015**: System MUST support at minimum console output as a notification action.
- **FR-016**: System MUST support Slack webhook as a notification action.
- **FR-017**: System MUST support posting a GitHub comment as an action (opt-in only, requires explicit configuration).
- **FR-018**: System MUST record the result of each action execution (success/failure with details).

#### State Management
- **FR-019**: System MUST persist state to avoid duplicate actions on the same event.
- **FR-020**: System MUST track which events have been processed and their disposition.
- **FR-021**: System MUST survive restarts without losing critical state (last checkpoint, processed events).

#### Observability & Debugging
- **FR-022**: System MUST log all significant events with structured output (event received, rule evaluated, action taken).
- **FR-023**: System MUST provide an audit trail explaining why each action was or was not taken.
- **FR-024**: System MUST support a dry-run mode that logs what would happen without executing actions.

#### Operational Safety
- **FR-025**: System MUST fail loudly on startup if configuration is invalid (bad rules, missing credentials).
- **FR-026**: System MUST NOT modify GitHub state (create issues, merge PRs) unless explicitly configured with a write action.
- **FR-027**: System MUST handle transient failures gracefully with retries and exponential backoff.

### Key Entities

- **Event**: A GitHub activity relevant to the user (mention, assignment, label change, comment, PR review request). Key attributes: event type, timestamp, source (repo/issue/PR), actor, payload.
- **Rule**: A user-defined condition-action pair. Key attributes: unique ID, name, event matcher (type, filters), optional time condition, action to execute, enabled/disabled flag.
- **Action**: An operation to perform when a rule matches. Key attributes: action type (console/slack/github-comment), configuration (webhook URL, message template), result status.
- **ProcessedEvent**: A record that an event was evaluated. Key attributes: event ID, timestamp processed, matching rules (if any), action results, disposition.
- **Checkpoint**: The system's position in the event stream. Key attributes: last event timestamp, last poll time.

### Assumptions

- The user has a GitHub personal access token with appropriate read scopes (notifications, repo access).
- The user will configure Slack webhook URLs if Slack notifications are desired.
- The system runs on a machine with persistent storage (file system access for state).
- The polling interval will be configurable, defaulting to 60 seconds to balance responsiveness with rate limit conservation.
- Rules configuration uses a standard format (assumed YAML or JSON—implementation choice).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: User can create a rule configuration file and have it validated within 5 seconds of system startup.
- **SC-002**: System detects and processes a new GitHub mention within 2 polling intervals (default: under 2 minutes).
- **SC-003**: 100% of triggered actions are recorded in the audit log with complete decision trail.
- **SC-004**: System operates for 7+ days without duplicate notifications for the same event.
- **SC-005**: System operates for 7+ days without rate limit violations from GitHub.
- **SC-006**: User can determine why any notification was sent by inspecting logs within 30 seconds.
- **SC-007**: System correctly resumes from checkpoint after restart, missing zero events within the lookback window.
- **SC-008**: Dry-run mode produces identical log output to normal mode except action execution is skipped.
- **SC-009**: Invalid configuration causes immediate startup failure with clear error message (no silent failures).
