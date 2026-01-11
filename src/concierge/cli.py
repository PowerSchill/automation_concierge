"""CLI entry point for Personal Automation Concierge.

This module provides the Typer-based CLI with commands:
- concierge run: Run in daemon mode (continuous polling)
- concierge run-once: Run a single poll cycle
- concierge validate: Validate configuration
- concierge status: Show current state
- concierge audit: Query audit log

Exit codes:
- 0: Success
- 1: Configuration error
- 2: Authentication error
- 3: Partial failure
- 4: Fatal error
"""

from __future__ import annotations

import asyncio
import random
import signal
import time
from datetime import UTC, datetime, timedelta
from enum import IntEnum
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

from concierge import __version__
from concierge.actions import ActionExecutor, ActionStatus
from concierge.config import load_config
from concierge.config.loader import (
    ConfigError,
    ConfigNotFoundError,
    ConfigValidationError,
    EnvironmentVariableError,
)
from concierge.github import GitHubClient, normalize_notification, validate_token
from concierge.github.auth import AuthenticationError
from concierge.logging import configure_logging, get_logger
from concierge.paths import get_default_state_dir
from concierge.rules import RulesEngine
from concierge.state import StateStore
from concierge.state.store import Disposition, ResultStatus

if TYPE_CHECKING:
    import structlog

    from concierge.config.schema import Config


# Exit codes per plan.md specification
class ExitCode(IntEnum):
    """CLI exit codes."""

    SUCCESS = 0
    CONFIG_ERROR = 1
    AUTH_ERROR = 2
    PARTIAL_FAILURE = 3
    FATAL_ERROR = 4


# Create the Typer app
app = typer.Typer(
    name="concierge",
    help="Personal Automation Concierge - GitHub activity monitoring and automated actions.",
    add_completion=False,
    no_args_is_help=True,
)


def version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        typer.echo(f"concierge {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            "-V",
            help="Show version and exit.",
            callback=version_callback,
            is_eager=True,
        ),
    ] = None,
) -> None:
    """Personal Automation Concierge - GitHub activity monitoring."""


@app.command()
def validate(
    config: Annotated[
        Path | None,
        typer.Option(
            "--config",
            "-c",
            help="Path to configuration file.",
            exists=False,  # We handle existence check ourselves
        ),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            "-v",
            help="Enable verbose output.",
        ),
    ] = False,
) -> None:
    """Validate configuration without running.

    Loads the configuration file, expands environment variables,
    and validates against the schema. Exits with code 0 if valid,
    or code 1 if there are errors.
    """
    configure_logging(verbose=verbose, json_output=False)
    log = get_logger("concierge.cli")

    try:
        cfg = load_config(config)
        typer.echo(typer.style("✓ Configuration is valid", fg=typer.colors.GREEN))

        if verbose:
            typer.echo("\nConfiguration summary:")
            typer.echo(f"  Version: {cfg.version}")
            typer.echo(f"  Poll interval: {cfg.github.poll_interval}s")
            typer.echo(f"  Rules: {len(cfg.rules)} ({len(cfg.get_enabled_rules())} enabled)")

            if cfg.actions.slack:
                typer.echo("  Slack: configured")
            if cfg.actions.github_comment and cfg.actions.github_comment.enabled:
                typer.echo("  GitHub comments: enabled")

        raise typer.Exit(ExitCode.SUCCESS)

    except ConfigNotFoundError as e:
        typer.echo(
            typer.style(f"✗ {e}", fg=typer.colors.RED),
            err=True,
        )
        raise typer.Exit(ExitCode.CONFIG_ERROR) from e

    except EnvironmentVariableError as e:
        typer.echo(
            typer.style(f"✗ {e}", fg=typer.colors.RED),
            err=True,
        )
        raise typer.Exit(ExitCode.CONFIG_ERROR) from e

    except ConfigValidationError as e:
        typer.echo(
            typer.style(f"✗ {e}", fg=typer.colors.RED),
            err=True,
        )
        raise typer.Exit(ExitCode.CONFIG_ERROR) from e

    except ConfigError as e:
        typer.echo(
            typer.style(f"✗ {e}", fg=typer.colors.RED),
            err=True,
        )
        log.exception("Configuration error")
        raise typer.Exit(ExitCode.CONFIG_ERROR) from e


@app.command("run")
def run_daemon(
    config: Annotated[
        Path | None,
        typer.Option(
            "--config",
            "-c",
            help="Path to configuration file.",
        ),
    ] = None,
    state_dir: Annotated[
        Path | None,
        typer.Option(
            "--state-dir",
            help="State directory path.",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Log actions without executing them.",
        ),
    ] = False,
    once: Annotated[
        bool,
        typer.Option(
            "--once",
            help="Run one poll cycle and exit (same as run-once).",
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            "-v",
            help="Enable debug logging.",
        ),
    ] = False,
    poll_interval: Annotated[
        int | None,
        typer.Option(
            "--poll-interval",
            help="Override poll interval in seconds (30-300).",
            min=30,
            max=300,
        ),
    ] = None,
) -> None:
    """Run the concierge in daemon mode (continuous polling).

    Fetches GitHub notifications, evaluates rules, and executes actions.
    Runs continuously until interrupted (Ctrl+C).
    """
    configure_logging(verbose=verbose)
    log = get_logger("concierge.cli")

    # Load configuration
    try:
        cfg = load_config(config)
    except ConfigError as e:
        typer.echo(
            typer.style(f"✗ Configuration error: {e}", fg=typer.colors.RED),
            err=True,
        )
        raise typer.Exit(ExitCode.CONFIG_ERROR) from e

    # Override poll interval if specified
    effective_poll_interval = poll_interval or cfg.github.poll_interval

    if once:
        # Delegate to run_once
        _run_once_impl(cfg, state_dir, dry_run, verbose, log)
    else:
        # Run continuous polling loop
        _run_daemon_impl(cfg, state_dir, dry_run, effective_poll_interval, log)


@app.command("run-once")
def run_once(
    config: Annotated[
        Path | None,
        typer.Option(
            "--config",
            "-c",
            help="Path to configuration file.",
        ),
    ] = None,
    state_dir: Annotated[
        Path | None,
        typer.Option(
            "--state-dir",
            help="State directory path.",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Log actions without executing them.",
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            "-v",
            help="Enable debug logging.",
        ),
    ] = False,
) -> None:
    """Run a single poll cycle and exit.

    Fetches current GitHub notifications, evaluates rules, executes
    matching actions, then exits.
    """
    configure_logging(verbose=verbose)
    log = get_logger("concierge.cli")

    # Load configuration
    try:
        cfg = load_config(config)
    except ConfigError as e:
        typer.echo(
            typer.style(f"✗ Configuration error: {e}", fg=typer.colors.RED),
            err=True,
        )
        raise typer.Exit(ExitCode.CONFIG_ERROR) from e

    _run_once_impl(cfg, state_dir, dry_run, verbose, log)


def _run_once_impl(
    cfg: Config,
    state_dir: Path | None,
    dry_run: bool,
    _verbose: bool,
    log: structlog.stdlib.BoundLogger,
) -> None:
    """Implementation of single poll cycle.

    Args:
        cfg: Configuration object
        state_dir: State directory
        dry_run: Whether to skip action execution
        _verbose: Verbosity flag (unused in stub)
        log: Logger instance
    """
    if dry_run:
        typer.echo(
            typer.style(
                "🔍 Dry-run mode: actions will be logged but not executed",
                fg=typer.colors.CYAN,
            )
        )

    # Determine state directory
    if state_dir is None:
        if cfg.state and cfg.state.directory:
            state_dir = Path(cfg.state.directory)
        else:
            state_dir = get_default_state_dir()

    state_dir.mkdir(parents=True, exist_ok=True)
    db_path = state_dir / "state.db"

    # Initialize state store
    store = StateStore(db_path)
    log.info("Initialized state store", path=str(db_path))

    try:
        # Load checkpoint
        checkpoint = store.get_checkpoint()
        log.info(
            "Loaded checkpoint",
            last_poll=checkpoint.last_poll_timestamp,
            last_event=checkpoint.last_event_timestamp,
        )

        # Validate GitHub token
        try:
            asyncio.run(_validate_auth(log))
        except AuthenticationError as e:
            typer.echo(
                typer.style(f"✗ Authentication error: {e}", fg=typer.colors.RED),
                err=True,
            )
            raise typer.Exit(ExitCode.AUTH_ERROR) from e

        # Calculate 'since' for notifications
        since = checkpoint.last_event_timestamp
        if since is None:
            # First run: look back by lookback_window (default 1 hour)
            lookback = getattr(cfg.github, "lookback_window", 3600)
            since = datetime.now(UTC) - timedelta(seconds=lookback)

        # Fetch and process notifications
        events_processed = 0
        actions_executed = 0
        errors = 0

        try:
            results = asyncio.run(
                _poll_cycle(
                    cfg=cfg,
                    store=store,
                    since=since,
                    dry_run=dry_run,
                    log=log,
                )
            )
            events_processed = results["events_processed"]
            actions_executed = results["actions_executed"]
            errors = results["errors"]

        except Exception as e:
            log.exception("Poll cycle failed")
            typer.echo(
                typer.style(f"✗ Poll cycle error: {e}", fg=typer.colors.RED),
                err=True,
            )
            raise typer.Exit(ExitCode.FATAL_ERROR) from e

        # Update checkpoint
        checkpoint.last_poll_timestamp = datetime.now(UTC)
        store.save_checkpoint(checkpoint)
        log.info("Updated checkpoint", last_poll=checkpoint.last_poll_timestamp)

        # Report results
        typer.echo()
        typer.echo(typer.style("Poll cycle complete", bold=True))
        typer.echo(f"  Events processed: {events_processed}")
        typer.echo(f"  Actions executed: {actions_executed}")

        if errors > 0:
            typer.echo(
                typer.style(f"  Errors: {errors}", fg=typer.colors.YELLOW)
            )
            raise typer.Exit(ExitCode.PARTIAL_FAILURE)

        raise typer.Exit(ExitCode.SUCCESS)

    finally:
        store.close()


async def _validate_auth(log: structlog.stdlib.BoundLogger) -> None:
    """Validate GitHub authentication.

    Args:
        log: Logger instance

    Raises:
        AuthenticationError: If authentication fails
    """
    result = await validate_token()
    log.info("GitHub authentication successful", user=result["user"])


async def _poll_cycle(  # noqa: PLR0912
    cfg: Config,
    store: StateStore,
    since: datetime,
    dry_run: bool,
    log: structlog.stdlib.BoundLogger,
) -> dict[str, int]:
    """Execute a single poll cycle.

    Args:
        cfg: Configuration object
        store: State store instance
        since: Fetch notifications since this time
        dry_run: Whether to skip action execution
        log: Logger instance

    Returns:
        Dictionary with counts: events_processed, actions_executed, errors
    """
    events_processed = 0
    actions_executed = 0
    errors = 0

    # Get enabled rules
    rules = cfg.get_enabled_rules()
    if not rules:
        log.warning("No enabled rules found")
        return {"events_processed": 0, "actions_executed": 0, "errors": 0}

    log.info("Starting poll cycle", since=since, rules_count=len(rules))

    # Initialize components
    engine = RulesEngine(rules)
    executor = ActionExecutor(dry_run=dry_run)

    # Fetch notifications
    async with GitHubClient() as client:
        async for notification in client.get_notifications(since=since):
            # Normalize to Event
            event = normalize_notification(notification)
            log.debug("Received event", event_id=event.id, event_type=event.event_type)

            # Check if already processed
            if store.is_processed(event.id):
                log.debug("Event already processed, skipping", event_id=event.id)
                continue

            events_processed += 1

            # Evaluate rules
            result = engine.evaluate(event)
            log.info(
                "Evaluated event",
                event_id=event.id,
                rules_evaluated=result.rules_evaluated,
                matches=len(result.matches),
            )

            # Track rule evaluations for audit
            rules_evaluated = []
            actions_taken = []

            for match in result.matches:
                rule = match.rule
                rules_evaluated.append({
                    "rule_id": rule.id,
                    "matched": True,
                    "match_reason": match.match_reason,
                })

                # Check if action already executed for this event+rule
                if store.has_action_executed(event.id, rule.id):
                    log.debug(
                        "Action already executed for event+rule, skipping",
                        event_id=event.id,
                        rule_id=rule.id,
                    )
                    continue

                # Execute actions
                action_results = executor.execute_all(match)

                for action_result in action_results:
                    if action_result.status == ActionStatus.SUCCESS:
                        actions_executed += 1
                        store.record_action(
                            event.id,
                            rule.id,
                            action_result.action_type.value,
                            ResultStatus.SUCCESS,
                        )
                        actions_taken.append({
                            "action_type": action_result.action_type.value,
                            "result": "success",
                            "target": event.entity_id,
                        })
                    elif action_result.status == ActionStatus.FAILURE:
                        errors += 1
                        store.record_action(
                            event.id,
                            rule.id,
                            action_result.action_type.value,
                            ResultStatus.FAILED,
                            action_result.message,
                        )
                        actions_taken.append({
                            "action_type": action_result.action_type.value,
                            "result": "failed",
                            "message": action_result.message,
                        })
                    elif action_result.status == ActionStatus.DRY_RUN:
                        actions_taken.append({
                            "action_type": action_result.action_type.value,
                            "result": "dry_run",
                            "target": event.entity_id,
                        })

            # Determine disposition
            if result.has_matches:
                if dry_run:
                    disposition = Disposition.DRY_RUN
                elif errors > 0:
                    disposition = Disposition.ERROR
                else:
                    disposition = Disposition.ACTION_EXECUTED
            else:
                disposition = Disposition.NO_MATCH

            # Mark as processed
            store.mark_processed(event.id, event.event_type.value, disposition)

            # Write audit entry
            store.write_audit_entry(
                disposition=disposition,
                message=f"Processed {event.event_type.value} event from {event.repo_full_name}",
                event_id=event.id,
                event_type=event.event_type.value,
                event_source=event.entity_id,
                rules_evaluated=rules_evaluated,
                actions_taken=actions_taken,
            )

    log.info(
        "Poll cycle complete",
        events_processed=events_processed,
        actions_executed=actions_executed,
        errors=errors,
    )

    return {
        "events_processed": events_processed,
        "actions_executed": actions_executed,
        "errors": errors,
    }


# Global flag for graceful shutdown
_shutdown_requested = False


def _signal_handler(signum: int, _frame: object) -> None:
    """Handle shutdown signals."""
    global _shutdown_requested  # noqa: PLW0603
    _shutdown_requested = True
    signal_name = signal.Signals(signum).name
    typer.echo(f"\n⚡ Received {signal_name}, shutting down gracefully...")


def _run_daemon_impl(  # noqa: PLR0915
    cfg: Config,
    state_dir: Path | None,
    dry_run: bool,
    poll_interval: int,
    log: structlog.stdlib.BoundLogger,
) -> None:
    """Implementation of continuous polling daemon.

    Args:
        cfg: Configuration object
        state_dir: State directory
        dry_run: Whether to skip action execution
        poll_interval: Seconds between poll cycles
        log: Logger instance
    """
    global _shutdown_requested  # noqa: PLW0603
    _shutdown_requested = False

    # Install signal handlers for graceful shutdown
    original_sigint = signal.signal(signal.SIGINT, _signal_handler)
    original_sigterm = signal.signal(signal.SIGTERM, _signal_handler)

    if dry_run:
        typer.echo(
            typer.style(
                "🔍 Dry-run mode: actions will be logged but not executed",
                fg=typer.colors.CYAN,
            )
        )

    typer.echo(
        typer.style(
            f"🚀 Starting continuous polling (interval: {poll_interval}s)",
            fg=typer.colors.GREEN,
            bold=True,
        )
    )
    typer.echo("Press Ctrl+C to stop.")

    # Determine state directory
    if state_dir is None:
        if cfg.state and cfg.state.directory:
            state_dir = Path(cfg.state.directory)
        else:
            state_dir = get_default_state_dir()

    state_dir.mkdir(parents=True, exist_ok=True)
    db_path = state_dir / "state.db"

    # Initialize state store
    store = StateStore(db_path)
    log.info("Initialized state store", path=str(db_path))

    # Validate GitHub token once at startup
    try:
        asyncio.run(_validate_auth(log))
    except AuthenticationError as e:
        typer.echo(
            typer.style(f"✗ Authentication error: {e}", fg=typer.colors.RED),
            err=True,
        )
        store.close()
        raise typer.Exit(ExitCode.AUTH_ERROR) from e

    total_events = 0
    total_actions = 0
    total_errors = 0
    cycles = 0

    try:
        while not _shutdown_requested:
            cycles += 1
            log.info("Starting poll cycle", cycle=cycles)

            # Load checkpoint
            checkpoint = store.get_checkpoint()

            # Calculate 'since' for notifications
            since = checkpoint.last_event_timestamp
            if since is None:
                # First run: look back by lookback_window (default 1 hour)
                lookback = getattr(cfg.github, "lookback_window", 3600)
                since = datetime.now(UTC) - timedelta(seconds=lookback)

            try:
                results = asyncio.run(
                    _poll_cycle(
                        cfg=cfg,
                        store=store,
                        since=since,
                        dry_run=dry_run,
                        log=log,
                    )
                )
                total_events += results["events_processed"]
                total_actions += results["actions_executed"]
                total_errors += results["errors"]

                # Update checkpoint
                checkpoint.last_poll_timestamp = datetime.now(UTC)
                store.save_checkpoint(checkpoint)

            except Exception:
                log.exception("Poll cycle failed", cycle=cycles)
                total_errors += 1

            if _shutdown_requested:
                break

            # Sleep with jitter (0-10% of poll_interval)
            jitter = random.uniform(0, poll_interval * 0.1)
            sleep_time = poll_interval + jitter
            log.debug("Sleeping until next cycle", sleep_seconds=sleep_time)

            # Sleep in small increments to check for shutdown signal
            sleep_end = time.time() + sleep_time
            while time.time() < sleep_end and not _shutdown_requested:
                time.sleep(min(1.0, sleep_end - time.time()))

    finally:
        # Restore original signal handlers
        signal.signal(signal.SIGINT, original_sigint)
        signal.signal(signal.SIGTERM, original_sigterm)
        store.close()

    # Report final summary
    typer.echo()
    typer.echo(typer.style("Daemon stopped", bold=True))
    typer.echo(f"  Poll cycles: {cycles}")
    typer.echo(f"  Total events: {total_events}")
    typer.echo(f"  Total actions: {total_actions}")

    if total_errors > 0:
        typer.echo(
            typer.style(f"  Total errors: {total_errors}", fg=typer.colors.YELLOW)
        )
        raise typer.Exit(ExitCode.PARTIAL_FAILURE)

    raise typer.Exit(ExitCode.SUCCESS)


@app.command()
def status(
    state_dir: Annotated[
        Path | None,
        typer.Option(
            "--state-dir",
            help="State directory path.",
        ),
    ] = None,
) -> None:
    """Show current state (last checkpoint, pending events).

    Displays information about the current polling position and
    processed event statistics.
    """
    # Determine state directory
    if state_dir is None:
        state_dir = get_default_state_dir()

    db_path = state_dir / "state.db"

    if not db_path.exists():
        typer.echo(
            typer.style(f"No state database found at {db_path}", fg=typer.colors.YELLOW)
        )
        typer.echo("Run 'concierge run-once' to initialize.")
        raise typer.Exit(ExitCode.SUCCESS)

    store = StateStore(db_path)

    try:
        checkpoint = store.get_checkpoint()
        processed_count = store.get_processed_count()
        audit_count = store.get_audit_count()

        typer.echo(typer.style("Concierge Status", bold=True))
        typer.echo("─" * 40)

        typer.echo(f"State directory: {state_dir}")
        typer.echo(f"Database: {db_path}")
        typer.echo()

        typer.echo(typer.style("Checkpoint:", bold=True))
        if checkpoint.last_event_timestamp:
            typer.echo(f"  Last event: {checkpoint.last_event_timestamp.isoformat()}")
        else:
            typer.echo("  Last event: (none)")

        if checkpoint.last_poll_timestamp:
            typer.echo(f"  Last poll: {checkpoint.last_poll_timestamp.isoformat()}")
        else:
            typer.echo("  Last poll: (none)")

        typer.echo()
        typer.echo(typer.style("Statistics:", bold=True))
        typer.echo(f"  Processed events: {processed_count}")
        typer.echo(f"  Audit log entries: {audit_count}")

    finally:
        store.close()

    raise typer.Exit(ExitCode.SUCCESS)


@app.command()
def audit(
    since: Annotated[
        str | None,
        typer.Option(
            "--since",
            help="Filter by timestamp (ISO format).",
        ),
    ] = None,
    rule: Annotated[
        str | None,
        typer.Option(
            "--rule",
            help="Filter by rule ID.",
        ),
    ] = None,
    limit: Annotated[
        int,
        typer.Option(
            "--limit",
            "-n",
            help="Maximum records to show.",
        ),
    ] = 50,
    state_dir: Annotated[
        Path | None,
        typer.Option(
            "--state-dir",
            help="State directory path.",
        ),
    ] = None,
) -> None:
    """Query audit log.

    Shows the decision trail for processed events, including which
    rules were evaluated and what actions were taken.
    """
    # Determine state directory
    if state_dir is None:
        state_dir = get_default_state_dir()

    db_path = state_dir / "state.db"

    if not db_path.exists():
        typer.echo(
            typer.style(f"No state database found at {db_path}", fg=typer.colors.YELLOW)
        )
        raise typer.Exit(ExitCode.SUCCESS)

    store = StateStore(db_path)

    try:
        # Parse since timestamp
        since_dt = None
        if since:
            try:
                since_dt = datetime.fromisoformat(since)
            except ValueError:
                typer.echo(
                    typer.style(
                        f"Invalid timestamp format: {since}",
                        fg=typer.colors.RED,
                    ),
                    err=True,
                )
                raise typer.Exit(ExitCode.CONFIG_ERROR) from None

        entries = store.query_audit_log(since=since_dt, rule_id=rule, limit=limit)

        if not entries:
            typer.echo("No audit log entries found.")
            raise typer.Exit(ExitCode.SUCCESS)

        typer.echo(typer.style(f"Audit Log ({len(entries)} entries)", bold=True))
        typer.echo("─" * 60)

        for entry in entries:
            typer.echo()
            typer.echo(typer.style(f"[{entry['timestamp']}]", bold=True))
            event_id = entry.get("event_id", "N/A")
            event_type = entry.get("event_type", "N/A")
            typer.echo(f"  Event: {event_id} ({event_type})")
            typer.echo(f"  Source: {entry.get('event_source', 'N/A')}")
            typer.echo(f"  Disposition: {entry.get('disposition', 'N/A')}")
            typer.echo(f"  Message: {entry.get('message', 'N/A')}")

            rules = entry.get("rules_evaluated", [])
            if rules:
                typer.echo(f"  Rules evaluated: {len(rules)}")
                for r in rules[:3]:  # Show first 3
                    match_status = "✓" if r.get("matched") else "✗"
                    rule_id = r.get("rule_id", "?")
                    reason = r.get("match_reason", "?")
                    typer.echo(f"    {match_status} {rule_id}: {reason}")
                if len(rules) > 3:
                    typer.echo(f"    ... and {len(rules) - 3} more")

            actions = entry.get("actions_taken", [])
            if actions:
                typer.echo(f"  Actions taken: {len(actions)}")
                for a in actions:
                    action_status = "✓" if a.get("result") == "success" else "✗"
                    action_type = a.get("action_type", "?")
                    target = a.get("target", "?")
                    typer.echo(f"    {action_status} {action_type} → {target}")

    finally:
        store.close()

    raise typer.Exit(ExitCode.SUCCESS)
