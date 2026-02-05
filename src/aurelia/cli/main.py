"""Aurelia CLI entry point."""

from __future__ import annotations

from pathlib import Path

import click


@click.group()
@click.version_option(package_name="aurelia")
def cli() -> None:
    """Aurelia — automated discovery from the command line."""


@cli.command()
def init() -> None:
    """Initialize an Aurelia project in the current directory."""
    from aurelia.cli.init_cmd import run_init

    run_init()


@cli.command()
@click.option("--mock", is_flag=True, default=False, help="Use mock adapters.")
@click.option(
    "--project-dir",
    type=click.Path(exists=True, path_type=Path),
    default=Path.cwd,
    help="Project root directory.",
)
@click.option("--json-logs", is_flag=True, default=False, help="Output logs as JSON.")
@click.option(
    "--metrics-port",
    type=int,
    default=0,
    help="Prometheus metrics port (0=disabled).",
)
def start(mock: bool, project_dir: Path, json_logs: bool, metrics_port: int) -> None:
    """Start the Aurelia runtime."""
    import asyncio

    from aurelia.core.logging import configure_logging
    from aurelia.core.runtime import Runtime

    configure_logging(json_output=json_logs)

    # Start Prometheus metrics server if requested
    if metrics_port > 0:
        from aurelia.metrics.server import start_metrics_server

        start_metrics_server(metrics_port)

    # Resolve to absolute path to avoid path duplication in git operations
    runtime = Runtime(project_dir=project_dir.resolve(), use_mock=mock)
    asyncio.run(runtime.start())


@cli.command()
@click.option(
    "--project-dir",
    type=click.Path(exists=True, path_type=Path),
    default=Path.cwd,
    help="Project root directory.",
)
def stop(project_dir: Path) -> None:
    """Stop the Aurelia runtime."""
    import os
    import signal

    project_dir = project_dir.resolve()
    pid_file = project_dir / ".aurelia" / "state" / "pid"
    if not pid_file.exists():
        click.echo("No PID file found — is the runtime running?")
        raise SystemExit(1)

    pid = int(pid_file.read_text().strip())
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        click.echo(f"Process {pid} not running; removing stale PID file.")
        pid_file.unlink(missing_ok=True)
        raise SystemExit(1)

    click.echo(f"Sent SIGTERM to process {pid}.")


@cli.command()
@click.option(
    "--project-dir",
    type=click.Path(exists=True, path_type=Path),
    default=Path.cwd,
    help="Project root directory.",
)
def status(project_dir: Path) -> None:
    """Show runtime status."""
    import json

    project_dir = project_dir.resolve()
    state_dir = project_dir / ".aurelia" / "state"
    if not state_dir.exists():
        click.echo("No state directory found — has the runtime been started?")
        raise SystemExit(1)

    runtime_file = state_dir / "runtime.json"
    if not runtime_file.exists():
        click.echo("No runtime state found.")
        raise SystemExit(1)

    data = json.loads(runtime_file.read_text())
    click.echo(f"Runtime status : {data.get('status', 'unknown')}")
    click.echo(f"Heartbeat count: {data.get('heartbeat_count', 0)}")
    click.echo(f"Tasks dispatched: {data.get('total_tasks_dispatched', 0)}")
    click.echo(f"Tasks completed : {data.get('total_tasks_completed', 0)}")
    click.echo(f"Tasks failed    : {data.get('total_tasks_failed', 0)}")
    click.echo(f"Tokens used     : {data.get('total_tokens_used', 0):,}")
    click.echo(f"Estimated cost  : ${data.get('total_cost_usd', 0.0):.4f}")


@cli.command()
def replay() -> None:
    """Replay a previous run from the event log."""
    click.echo("Not yet implemented.")


@cli.command()
@click.option(
    "--project-dir",
    type=click.Path(exists=True, path_type=Path),
    default=Path.cwd,
    help="Project root directory.",
)
@click.option(
    "--poll-interval",
    type=float,
    default=2.0,
    help="State polling interval in seconds.",
)
def monitor(project_dir: Path, poll_interval: float) -> None:
    """Open the live monitoring dashboard."""
    from aurelia.monitor import run_monitor

    run_monitor(project_dir.resolve(), poll_interval)


@cli.command()
@click.option(
    "--project-dir",
    type=click.Path(exists=True, path_type=Path),
    default=Path.cwd,
    help="Project root directory.",
)
def report(project_dir: Path) -> None:
    """Generate a summary report of the last run."""
    from aurelia.cli.report_cmd import run_report

    run_report(project_dir.resolve())
