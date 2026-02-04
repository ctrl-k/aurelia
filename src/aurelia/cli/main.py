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
def start(mock: bool, project_dir: Path) -> None:
    """Start the Aurelia runtime."""
    import asyncio
    import logging

    from aurelia.core.runtime import Runtime

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    runtime = Runtime(project_dir=project_dir, use_mock=mock)
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


@cli.command()
def replay() -> None:
    """Replay a previous run from the event log."""
    click.echo("Not yet implemented.")


@cli.command()
def monitor() -> None:
    """Open the live monitoring dashboard."""
    click.echo("Not yet implemented.")


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
    run_report(project_dir)
