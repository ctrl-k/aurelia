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
@click.option(
    "--reset",
    is_flag=True,
    default=False,
    help="Clear all state and start fresh.",
)
def start(
    mock: bool, project_dir: Path, json_logs: bool, metrics_port: int, reset: bool
) -> None:
    """Start the Aurelia runtime."""
    import asyncio

    from aurelia.core.logging import configure_logging
    from aurelia.core.runtime import Runtime

    configure_logging(json_output=json_logs)

    project_dir = project_dir.resolve()

    # Reset state if requested
    if reset:
        _reset_state(project_dir)

    # Start Prometheus metrics server if requested
    if metrics_port > 0:
        from aurelia.metrics.server import start_metrics_server

        start_metrics_server(metrics_port)

    # Resolve to absolute path to avoid path duplication in git operations
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
@click.option(
    "--project-dir",
    type=click.Path(exists=True, path_type=Path),
    default=Path.cwd,
    help="Project root directory.",
)
@click.option(
    "--keep-worktrees",
    is_flag=True,
    default=False,
    help="Keep git worktrees (just clear state files).",
)
def reset(project_dir: Path, keep_worktrees: bool) -> None:
    """Clear all Aurelia state and start fresh.

    This removes all candidates, tasks, evaluations, and event logs.
    Git worktrees are cleaned up by default.
    """
    _reset_state(project_dir.resolve(), keep_worktrees=keep_worktrees)
    click.echo("State cleared. Ready for a fresh start.")


def _reset_state(project_dir: Path, keep_worktrees: bool = False) -> None:
    """Clear all Aurelia state files and optionally git worktrees."""
    import shutil

    aurelia_dir = project_dir / ".aurelia"

    # Clear state files
    state_dir = aurelia_dir / "state"
    if state_dir.exists():
        for f in state_dir.iterdir():
            if f.is_file():
                f.unlink()
        click.echo("Cleared state files.")

    # Clear event logs
    logs_dir = aurelia_dir / "logs"
    if logs_dir.exists():
        shutil.rmtree(logs_dir)
        logs_dir.mkdir(parents=True)
        click.echo("Cleared logs.")

    # Clear worktrees
    if not keep_worktrees:
        import subprocess

        worktrees_dir = aurelia_dir / "worktrees"

        # First, prune any stale worktree references
        subprocess.run(
            ["git", "worktree", "prune"],
            cwd=project_dir,
            capture_output=True,
        )

        # List all worktrees and remove aurelia ones
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=project_dir,
            capture_output=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            if line.startswith("worktree ") and "/aurelia/" in line:
                wt_path = line.replace("worktree ", "").strip()
                subprocess.run(
                    ["git", "worktree", "remove", "--force", wt_path],
                    cwd=project_dir,
                    capture_output=True,
                )

        # Clean up any remaining directories
        if worktrees_dir.exists():
            shutil.rmtree(worktrees_dir, ignore_errors=True)
            worktrees_dir.mkdir(parents=True)
        click.echo("Cleared worktrees.")

        # Prune again to clean up any newly stale references
        subprocess.run(
            ["git", "worktree", "prune"],
            cwd=project_dir,
            capture_output=True,
        )

        # Clean up aurelia branches
        try:
            result = subprocess.run(
                ["git", "branch", "--list", "aurelia/*"],
                cwd=project_dir,
                capture_output=True,
                text=True,
            )
            deleted = 0
            for line in result.stdout.splitlines():
                # Strip leading whitespace, '*' (current), and '+' (worktree)
                branch = line.lstrip(" *+").strip()
                if branch and branch.startswith("aurelia/"):
                    subprocess.run(
                        ["git", "branch", "-D", branch],
                        cwd=project_dir,
                        capture_output=True,
                    )
                    deleted += 1
            if deleted:
                click.echo(f"Deleted {deleted} aurelia branches.")
        except Exception:
            pass


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
