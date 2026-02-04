"""Report generation for Aurelia runs."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import click


def run_report(project_dir: Path) -> None:
    """Generate and print a summary report of the last Aurelia run."""
    state_dir = project_dir / ".aurelia" / "state"

    if not state_dir.exists():
        click.echo("No .aurelia/state directory found.")
        return

    runtime = _load_json(state_dir / "runtime.json")
    candidates = _load_json(state_dir / "candidates.json")
    evaluations = _load_json(state_dir / "evaluations.json")
    tasks = _load_json(state_dir / "tasks.json")

    if runtime is None:
        click.echo("No runtime state found.")
        return

    _print_run_summary(runtime)
    _print_candidate_summary(candidates or [], evaluations or [])
    _print_best_candidate(evaluations or [])
    _print_task_stats(tasks or [])
    _print_metric_progression(evaluations or [])
    _print_failures(candidates or [], tasks or [])


def _load_json(path: Path) -> dict | list | None:
    """Load a JSON file, returning None if missing or corrupt."""
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _print_run_summary(runtime: dict) -> None:
    click.echo("=" * 60)
    click.echo("  Run Summary")
    click.echo("=" * 60)

    status = runtime.get("status", "unknown")
    click.echo(f"  Status          : {status}")

    started = runtime.get("started_at")
    stopped = runtime.get("stopped_at")
    if started:
        click.echo(f"  Started         : {_fmt_time(started)}")
    if stopped:
        click.echo(f"  Stopped         : {_fmt_time(stopped)}")
    if started and stopped:
        duration = _parse_time(stopped) - _parse_time(started)
        total_s = int(duration.total_seconds())
        mins, secs = divmod(total_s, 60)
        click.echo(f"  Duration        : {mins}m {secs}s")

    click.echo(
        f"  Heartbeats      : {runtime.get('heartbeat_count', 0)}"
    )
    click.echo(
        f"  Tasks dispatched: {runtime.get('total_tasks_dispatched', 0)}"
    )
    click.echo(
        f"  Tasks completed : {runtime.get('total_tasks_completed', 0)}"
    )
    click.echo(
        f"  Tasks failed    : {runtime.get('total_tasks_failed', 0)}"
    )
    click.echo()


def _print_candidate_summary(
    candidates: list, evaluations: list
) -> None:
    if not candidates:
        return

    eval_by_branch = {}
    for ev in evaluations:
        eval_by_branch.setdefault(
            ev.get("candidate_branch"), []
        ).append(ev)

    succeeded = sum(
        1 for c in candidates if c.get("status") == "succeeded"
    )
    failed = sum(
        1 for c in candidates if c.get("status") == "failed"
    )

    click.echo("-" * 60)
    click.echo("  Candidates")
    click.echo("-" * 60)
    click.echo(
        f"  Total: {len(candidates)}"
        f"  |  Succeeded: {succeeded}"
        f"  |  Failed: {failed}"
    )
    click.echo()

    # Table
    click.echo(
        f"  {'ID':<12} {'Status':<12} {'Branch':<30} {'Metrics'}"
    )
    click.echo(f"  {'─' * 12} {'─' * 12} {'─' * 30} {'─' * 20}")

    for cand in candidates:
        cid = cand.get("id", "?")
        status = cand.get("status", "?")
        branch = cand.get("branch", "?")

        # Find metrics for this candidate
        evals = eval_by_branch.get(branch, [])
        if evals:
            metrics = evals[-1].get("metrics", {})
            metrics_str = ", ".join(
                f"{k}={v:.4f}" if isinstance(v, float) else f"{k}={v}"
                for k, v in metrics.items()
            )
        else:
            metrics_str = "-"

        click.echo(
            f"  {cid:<12} {status:<12} {branch:<30} {metrics_str}"
        )

    click.echo()


def _print_best_candidate(evaluations: list) -> None:
    passed = [e for e in evaluations if e.get("passed")]
    if not passed:
        return

    # Find evaluation with highest average metric
    best = None
    best_score = -1.0
    for ev in passed:
        metrics = ev.get("metrics", {})
        nums = [
            v for v in metrics.values() if isinstance(v, (int, float))
        ]
        if nums:
            score = sum(nums) / len(nums)
            if score > best_score:
                best_score = score
                best = ev

    if best is None:
        return

    click.echo("-" * 60)
    click.echo("  Best Candidate")
    click.echo("-" * 60)
    click.echo(
        f"  Branch : {best.get('candidate_branch', '?')}"
    )
    click.echo(f"  Commit : {best.get('commit_sha', '?')}")
    metrics = best.get("metrics", {})
    for key, val in metrics.items():
        if isinstance(val, float):
            click.echo(f"  {key:<9}: {val:.6f}")
        else:
            click.echo(f"  {key:<9}: {val}")
    click.echo()


def _print_task_stats(tasks: list) -> None:
    if not tasks:
        return

    click.echo("-" * 60)
    click.echo("  Task Breakdown by Component")
    click.echo("-" * 60)

    by_component: dict[str, dict[str, int]] = {}
    for task in tasks:
        comp = task.get("component", "unknown")
        status = task.get("status", "unknown")
        if comp not in by_component:
            by_component[comp] = {}
        by_component[comp][status] = (
            by_component[comp].get(status, 0) + 1
        )

    click.echo(
        f"  {'Component':<12} {'Success':<10} {'Failed':<10}"
        f" {'Other':<10}"
    )
    click.echo(f"  {'─' * 12} {'─' * 10} {'─' * 10} {'─' * 10}")

    for comp, statuses in sorted(by_component.items()):
        success = statuses.get("success", 0)
        failed = statuses.get("failed", 0)
        other = sum(
            v for k, v in statuses.items()
            if k not in ("success", "failed")
        )
        click.echo(
            f"  {comp:<12} {success:<10} {failed:<10} {other:<10}"
        )

    click.echo()


def _print_metric_progression(evaluations: list) -> None:
    if not evaluations:
        return

    click.echo("-" * 60)
    click.echo("  Evaluation History")
    click.echo("-" * 60)

    for ev in evaluations:
        eid = ev.get("id", "?")
        branch = ev.get("candidate_branch", "?")
        passed = "PASS" if ev.get("passed") else "FAIL"
        metrics = ev.get("metrics", {})
        metrics_str = ", ".join(
            f"{k}={v:.4f}" if isinstance(v, float) else f"{k}={v}"
            for k, v in metrics.items()
        )
        click.echo(
            f"  {eid:<12} {passed:<6} {branch:<30} {metrics_str}"
        )

    click.echo()


def _print_failures(candidates: list, tasks: list) -> None:
    failed_cands = [
        c for c in candidates if c.get("status") == "failed"
    ]
    if not failed_cands:
        return

    # Build task error lookup by branch
    task_errors: dict[str, str] = {}
    for task in tasks:
        if task.get("status") == "failed" and task.get("result"):
            branch = task.get("branch", "")
            error = task["result"].get("error", "unknown")
            task_errors[branch] = error

    click.echo("-" * 60)
    click.echo("  Failures")
    click.echo("-" * 60)

    for cand in failed_cands:
        cid = cand.get("id", "?")
        branch = cand.get("branch", "?")
        error = task_errors.get(branch, "unknown")
        click.echo(f"  {cid}: {error[:80]}")

    click.echo()


def _fmt_time(iso_str: str) -> str:
    """Format an ISO timestamp for display."""
    try:
        dt = _parse_time(iso_str)
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except (ValueError, TypeError):
        return iso_str


def _parse_time(iso_str: str) -> datetime:
    """Parse an ISO timestamp string."""
    # Handle trailing Z
    s = iso_str.replace("Z", "+00:00")
    return datetime.fromisoformat(s)
