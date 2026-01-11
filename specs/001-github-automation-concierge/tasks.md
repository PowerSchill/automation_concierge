# Tasks: Personal Automation Concierge

**Input**: Design documents from `/specs/001-github-automation-concierge/`
**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, contracts/ ✓

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2)
- All paths are relative to repository root

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization, dependencies, and tooling configuration

- [x] T001 Create project structure: `src/concierge/`, `tests/unit/`, `tests/integration/`, `tests/e2e/`, `tests/fixtures/`
- [x] T002 Initialize Python project with pyproject.toml (Python 3.11+, dependencies: httpx, pydantic, typer, structlog, pyyaml)
- [x] T003 [P] Create requirements.txt with pinned versions and hashes
- [x] T004 [P] Configure ruff (linting/formatting) in pyproject.toml
- [x] T005 [P] Configure pyright (type checking) in pyproject.toml
- [x] T006 [P] Create pytest configuration in pyproject.toml with pytest-httpx, freezegun, pytest-cov
- [x] T007 Create src/concierge/__init__.py with version string
- [x] T008 [P] Create .gitignore for Python project (venv, __pycache__, .db files, .env)
- [x] T009 [P] Create CHANGELOG.md with initial structure

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

### Configuration Infrastructure

- [x] T010 Create src/concierge/config/__init__.py
- [x] T011 Implement Pydantic models for Config schema in src/concierge/config/schema.py (Config, GitHubConfig, ActionsConfig, StateConfig, Rule, Trigger, Condition, Action per data-model.md)
- [x] T012 [P] Implement environment variable expansion for config values (${VAR} syntax) in src/concierge/config/loader.py
- [x] T013 Implement config file loader with YAML parsing and Pydantic validation in src/concierge/config/loader.py
- [x] T014 Implement config discovery (--config, $CONCIERGE_CONFIG, ./concierge.yaml, ~/.concierge/config.yaml) in src/concierge/config/loader.py

### State Store Infrastructure

- [x] T015 Create src/concierge/state/__init__.py
- [x] T016 Implement SQLite state store with schema initialization in src/concierge/state/store.py (tables: schema_version, checkpoints, processed_events, action_history, audit_log)
- [x] T017 Implement schema migrations framework in src/concierge/state/migrations.py
- [x] T018 [P] Implement Checkpoint model and checkpoint save/load operations in src/concierge/state/checkpoint.py
- [x] T019 Implement file permissions (chmod 600) on database creation in src/concierge/state/store.py

### Logging Infrastructure

- [x] T020 Create src/concierge/logging/__init__.py
- [x] T021 Implement structured JSON logging configuration with structlog in src/concierge/logging/audit.py
- [x] T022 Implement secret redaction for GITHUB_TOKEN and webhook URLs in log output in src/concierge/logging/audit.py

### CLI Skeleton

- [x] T023 Create src/concierge/cli.py with Typer app skeleton
- [x] T024 Implement `concierge --help` and `--version` commands in src/concierge/cli.py
- [x] T025 Implement `concierge validate` command (loads and validates config, exits with code 0/1) in src/concierge/cli.py
- [x] T026 Implement exit codes (0: success, 1: config error, 2: auth error, 3: partial failure, 4: fatal) in src/concierge/cli.py
- [x] T027 Create __main__.py entry point in src/concierge/__main__.py

### Shared Test Infrastructure

- [x] T028 Create tests/conftest.py with shared fixtures (temp config files, mock time, test database)
- [x] T029 [P] Create tests/fixtures/ directory with sample GitHub API response JSON files

**Checkpoint**: Foundation ready - user story implementation can now begin

---

## Phase 3: User Story 1 - Define and Trigger a Simple Rule (Priority: P1) 🎯 MVP

**Goal**: User can define a rule that detects GitHub mentions and receives console notifications

**Independent Test**: Create rule file → Run system → Generate mention event (mocked) → Verify console output

### GitHub Client (required for event ingestion)

- [x] T030 Create src/concierge/github/__init__.py
- [x] T031 Implement GitHub authentication with GITHUB_TOKEN env var in src/concierge/github/auth.py
- [x] T032 Implement token scope validation (GET /user, check scopes) in src/concierge/github/auth.py
- [x] T033 Implement GitHub API client with httpx in src/concierge/github/client.py (GET /notifications, GET /rate_limit)
- [x] T034 Implement rate limit checking and pause/resume logic in src/concierge/github/client.py
- [x] T035 Implement pagination handling (Link header parsing) in src/concierge/github/client.py

### Event Normalization

- [x] T036 Create Pydantic Event model in src/concierge/github/events.py (per data-model.md: Event, EventSource, EventType enum)
- [x] T037 Implement notification-to-Event normalization in src/concierge/github/events.py
- [x] T038 Implement event ID generation (notif_{github_id}) in src/concierge/github/events.py

### Rules Engine (event-type matching only for US1)

- [x] T039 Create src/concierge/rules/__init__.py
- [x] T040 Create Pydantic Rule and Match models in src/concierge/rules/schema.py
- [x] T041 Implement event-type matcher in src/concierge/rules/matchers.py
- [x] T042 Implement rule evaluation engine in src/concierge/rules/engine.py (evaluate Event against list of Rules, return list of Matches)

### Action Execution (console only for US1)

- [x] T043 Create src/concierge/actions/__init__.py
- [x] T044 Create ActionResult model in src/concierge/actions/executor.py (per data-model.md)
- [x] T045 Implement console action (print to stdout) in src/concierge/actions/console.py
- [x] T046 Implement action executor dispatch in src/concierge/actions/executor.py

### State Management (dedupe for US1)

- [x] T047 Implement ProcessedEvent model and is_processed() check in src/concierge/state/store.py
- [x] T048 Implement mark_processed() with disposition in src/concierge/state/store.py
- [x] T049 Implement ActionHistory save for event+rule deduplication in src/concierge/state/store.py

### Main Loop (single poll cycle for US1)

- [x] T050 Implement `concierge run-once` command in src/concierge/cli.py (single poll cycle: fetch → normalize → evaluate → execute → persist)
- [x] T051 Implement `concierge run` command with continuous polling loop in src/concierge/cli.py
- [x] T052 [US1] Implement dry-run mode (--dry-run flag) in src/concierge/cli.py (logs actions without executing, marks disposition as "dry_run")
- [x] T053 [US1] Implement graceful shutdown (SIGTERM/SIGINT handlers) in src/concierge/cli.py

**Checkpoint**: User Story 1 complete - user can define mention rule and receive console notifications

---

## Phase 4: User Story 2 - Understand Why an Action Was Taken (Priority: P2)

**Goal**: User can inspect logs and audit trail to understand exactly why notifications were sent

**Independent Test**: Trigger rule → Query audit log → Verify complete decision trail is visible

### Audit Logging

- [ ] T054 [US2] Implement AuditLogEntry model in src/concierge/state/store.py (per data-model.md: rules_evaluated, actions_taken, disposition)
- [ ] T055 [US2] Implement audit log write on each event processing in src/concierge/state/store.py
- [ ] T056 [US2] Implement log_decision() function with full decision trail in src/concierge/logging/audit.py

### Audit Query CLI

- [ ] T057 [US2] Implement `concierge audit` command in src/concierge/cli.py (--since, --rule, --limit options)
- [ ] T058 [US2] Implement `concierge status` command in src/concierge/cli.py (show last checkpoint, pending events count)

### Enhanced Logging

- [ ] T059 [US2] Add structured log events: event_received, rule_evaluated, action_taken in src/concierge/logging/audit.py
- [ ] T060 [US2] Implement match_reason string generation for each rule evaluation in src/concierge/rules/engine.py

**Checkpoint**: User Story 2 complete - user can explain any action via audit log or CLI

---

## Phase 5: User Story 3 - Safe Continuous Operation (Priority: P3)

**Goal**: System runs continuously without missing events, duplicates, or rate limit violations

**Independent Test**: Run system for extended period (simulated) → Verify zero duplicates, zero rate limit errors, correct checkpoint resume

### Rate Limit Handling

- [ ] T061 [US3] Implement proactive rate limit check (pause when remaining < 100) in src/concierge/github/client.py
- [ ] T062 [US3] Implement rate limit pause with jitter (sleep until reset + 10s) in src/concierge/github/client.py
- [ ] T063 [US3] Implement 403 rate limit response handling with retry in src/concierge/github/client.py

### Retry & Resilience

- [ ] T064 [US3] Implement exponential backoff for transient failures (5xx, network errors) in src/concierge/github/client.py
- [ ] T065 [US3] Implement secondary rate limit handling (abuse detection 403) in src/concierge/github/client.py

### Checkpoint Resume

- [ ] T066 [US3] Implement checkpoint load on startup in src/concierge/cli.py
- [ ] T067 [US3] Implement lookback_window for first run (default 3600s) in src/concierge/github/client.py
- [ ] T068 [US3] Implement checkpoint atomic save after each successful poll cycle in src/concierge/state/checkpoint.py

### Poll Loop Refinements

- [ ] T069 [US3] Implement poll interval with jitter (0-10% random) in src/concierge/cli.py
- [ ] T070 [US3] Implement poll_interval CLI override (--poll-interval, 30-300 range validation) in src/concierge/cli.py

**Checkpoint**: User Story 3 complete - system operates reliably for extended periods

---

## Phase 6: User Story 4 - Time-Based Rule Triggers (Priority: P4)

**Goal**: User can define rules that trigger based on time conditions (e.g., "PR open > 48h without review")

**Independent Test**: Create time-based rule → Have PR exist beyond threshold (mocked time) → Verify notification triggers

### Time-Based Matchers

- [ ] T071 [US4] Implement TimeSinceCondition matcher in src/concierge/rules/matchers.py (parse "48h", "7d" thresholds)
- [ ] T072 [US4] Implement NoActivityCondition matcher in src/concierge/rules/matchers.py (check for review/comment/commit since)
- [ ] T073 [US4] Implement injectable TimeProvider for testability in src/concierge/rules/matchers.py

### Entity Fetching

- [ ] T074 [US4] Implement issue/PR detail fetching (GET /repos/{owner}/{repo}/issues/{number}) in src/concierge/github/client.py
- [ ] T075 [US4] Implement entity cache (avoid re-fetching within poll cycle) in src/concierge/github/client.py

### Time-Based Dedupe

- [ ] T076 [US4] Implement time-based rule dedupe key (entity_id, rule_id, threshold) in src/concierge/state/store.py
- [ ] T077 [US4] Implement threshold crossing detection (only fire once per threshold) in src/concierge/rules/engine.py

**Checkpoint**: User Story 4 complete - time-based rules functional

---

## Phase 7: User Story 5 - Label-Based Rule Triggers (Priority: P5)

**Goal**: User can define rules that trigger on label changes

**Independent Test**: Create label rule → Add target label (mocked) → Verify notification

### Label Matchers

- [ ] T078 [US5] Implement LabelCondition matcher (label_present, label_added, label_removed) in src/concierge/rules/matchers.py
- [ ] T079 [US5] Implement label change detection from GitHub event payload in src/concierge/github/events.py

### Label Event Normalization

- [ ] T080 [US5] Extend event normalization for label_change event type in src/concierge/github/events.py
- [ ] T081 [US5] Add label list to Event model (current labels, added labels, removed labels) in src/concierge/github/events.py

**Checkpoint**: User Story 5 complete - label-based rules functional

---

## Phase 8: User Story 6 - Multiple Action Types (Priority: P6)

**Goal**: Rules support console, Slack, and GitHub comment actions

**Independent Test**: Configure each action type → Trigger rules → Verify each action executes correctly

### Slack Action

- [ ] T082 [P] [US6] Implement Slack webhook action in src/concierge/actions/slack.py
- [ ] T083 [US6] Implement Slack retry semantics (3 attempts, 1s→2s→4s backoff) in src/concierge/actions/slack.py
- [ ] T084 [US6] Implement Slack rate limiting (max 10 messages/minute) in src/concierge/actions/slack.py

### GitHub Comment Action

- [ ] T085 [P] [US6] Implement GitHub comment action (POST /repos/{owner}/{repo}/issues/{number}/comments) in src/concierge/actions/github_comment.py
- [ ] T086 [US6] Implement opt_in validation (require opt_in: true in action config) in src/concierge/actions/github_comment.py
- [ ] T087 [US6] Implement GitHub comment retry semantics (2 attempts, 2s→5s backoff) in src/concierge/actions/github_comment.py
- [ ] T088 [US6] Implement GitHub comment rate limiting (max 1 per issue per hour) in src/concierge/actions/github_comment.py

### Message Templating

- [ ] T089 [US6] Implement message template expansion ({{ event.field }} placeholders) in src/concierge/actions/executor.py

### Action Executor Enhancement

- [ ] T090 [US6] Extend action executor to dispatch to slack and github_comment handlers in src/concierge/actions/executor.py
- [ ] T091 [US6] Implement action failure isolation (one failure doesn't block others) in src/concierge/actions/executor.py

**Checkpoint**: User Story 6 complete - all action types functional

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, cleanup, and final validation

- [ ] T092 [P] Create sample config file at examples/concierge.yaml
- [ ] T093 [P] Create README.md with installation, configuration, and usage instructions
- [ ] T094 Update CHANGELOG.md with v1.0.0 release notes
- [ ] T095 [P] Add docstrings to all public functions per constitution
- [ ] T096 Run ruff and pyright, fix all errors
- [ ] T097 Run pytest with coverage, ensure 80%+ on business logic (rules, actions, state)
- [ ] T098 Validate quickstart.md scenarios work end-to-end
- [ ] T099 Security review: verify no plaintext secrets in logs, file permissions, webhook URL redaction

---

## Dependencies & Execution Order

### Phase Dependencies

```
Phase 1 (Setup) ─────────────────┐
                                 │
                                 ▼
Phase 2 (Foundational) ──────────┤ BLOCKS ALL USER STORIES
                                 │
         ┌───────────────────────┼───────────────────────┐
         │                       │                       │
         ▼                       ▼                       ▼
Phase 3 (US1: P1)          Phase 4 (US2: P2)       Phase 5 (US3: P3)
Rule + Console             Audit + Debug          Reliability
         │                       │                       │
         │                       │                       │
         ▼                       ▼                       ▼
Phase 6 (US4: P4)          Phase 7 (US5: P5)       Phase 8 (US6: P6)
Time-based rules           Label rules            Multi-action
         │                       │                       │
         └───────────────────────┴───────────────────────┘
                                 │
                                 ▼
                         Phase 9 (Polish)
```

### User Story Dependencies

| Story    | Depends On                  | Can Parallel With  |
| -------- | --------------------------- | ------------------ |
| US1 (P1) | Phase 2 only                | -                  |
| US2 (P2) | US1 (needs events to audit) | -                  |
| US3 (P3) | US1 (needs poll loop)       | US2                |
| US4 (P4) | US1 (needs rules engine)    | US2, US3, US5, US6 |
| US5 (P5) | US1 (needs rules engine)    | US2, US3, US4, US6 |
| US6 (P6) | US1 (needs action executor) | US2, US3, US4, US5 |

### Parallel Opportunities Within Phases

**Phase 1 (Setup)**:
```
T003, T004, T005, T006, T008, T009 can all run in parallel
```

**Phase 2 (Foundational)**:
```
T012, T018, T022, T029 can run in parallel (different files)
```

**Phase 3 (User Story 1)**:
```
T030-T038 (GitHub) can parallel with T039-T042 (Rules) after T011 (schemas)
T045 (console action) can parallel with T041-T042 (matchers/engine)
```

**Phase 8 (User Story 6)**:
```
T082-T084 (Slack) can parallel with T085-T088 (GitHub comment)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (config, state, logging, CLI skeleton)
3. Complete Phase 3: User Story 1 (GitHub client, events, rules, console action, main loop)
4. **STOP and VALIDATE**: Test `concierge run-once` with mock GitHub response
5. Deploy/demo: User can define mention rule → get console notification

### Incremental Delivery

| Increment      | Stories     | Value Delivered                         |
| -------------- | ----------- | --------------------------------------- |
| MVP            | US1         | Define rules, get console notifications |
| +Debuggability | US1+US2     | Explain any action via audit log        |
| +Reliability   | US1+US2+US3 | Run unattended for days                 |
| +Time Rules    | +US4        | Catch stale PRs/issues                  |
| +Labels        | +US5        | React to workflow signals               |
| +Channels      | +US6        | Slack and GitHub comment notifications  |

### Task Count Summary

| Phase                 | Tasks  | Parallel Opportunities |
| --------------------- | ------ | ---------------------- |
| Phase 1: Setup        | 9      | 6 parallelizable       |
| Phase 2: Foundational | 20     | 4 parallelizable       |
| Phase 3: US1          | 24     | Many within subsystems |
| Phase 4: US2          | 7      | 0 (sequential flow)    |
| Phase 5: US3          | 10     | 0 (sequential flow)    |
| Phase 6: US4          | 7      | 0 (sequential flow)    |
| Phase 7: US5          | 4      | 0 (sequential flow)    |
| Phase 8: US6          | 10     | 2 parallelizable       |
| Phase 9: Polish       | 8      | 4 parallelizable       |
| **TOTAL**             | **99** |                        |

---

## Notes

- All tasks follow format: `- [ ] T### [P?] [US?] Description with file path`
- Tests are NOT included per template guidance (not explicitly requested)
- Each user story can be independently tested per spec.md acceptance criteria
- Commit after each task or logical group
- Run linter after each phase completion
