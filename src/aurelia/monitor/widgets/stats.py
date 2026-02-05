"""Stats pane widget showing summary metrics."""

from __future__ import annotations

from textual.containers import Vertical
from textual.widgets import Static

from aurelia.monitor.state import MonitorState


class StatsPane(Vertical):
    """Summary statistics and metrics."""

    DEFAULT_CSS = """
    StatsPane {
        height: 1fr;
        padding: 1;
    }

    StatsPane Static {
        padding: 0 1;
        margin-bottom: 1;
    }

    StatsPane .stats-section {
        border: solid $surface-darken-1;
        padding: 1;
        margin-bottom: 1;
    }
    """

    def compose(self):
        """Compose the pane layout."""
        yield Static(id="stats-overview", classes="stats-section")
        yield Static(id="stats-tasks", classes="stats-section")
        yield Static(id="stats-candidates", classes="stats-section")
        yield Static(id="stats-usage", classes="stats-section")

    def update_stats(self, state: MonitorState) -> None:
        """Update all stats displays."""
        runtime = state.runtime

        # Overview section
        overview = self.query_one("#stats-overview", Static)
        overview.update(
            "[bold cyan]Overview[/]\n\n"
            f"  Status:      {self._format_status(runtime.status)}\n"
            f"  Heartbeats:  [cyan]{runtime.heartbeat_count}[/]\n"
            f"  Last update: {state.last_updated.strftime('%H:%M:%S')}"
        )

        # Tasks section
        tasks = self.query_one("#stats-tasks", Static)
        total = runtime.total_tasks_dispatched
        completed = runtime.total_tasks_completed
        failed = runtime.total_tasks_failed
        in_progress = len(state.running_tasks)
        pending = len(state.pending_tasks)
        success_rate = (completed / total * 100) if total > 0 else 0

        tasks.update(
            "[bold cyan]Tasks[/]\n\n"
            f"  Dispatched:   {total}\n"
            f"  In Progress:  [yellow]{in_progress}[/]\n"
            f"  Pending:      [blue]{pending}[/]\n"
            f"  Completed:    [green]{completed}[/]\n"
            f"  Failed:       [red]{failed}[/]\n"
            f"  Success Rate: {success_rate:.1f}%"
        )

        # Candidates section
        candidates = self.query_one("#stats-candidates", Static)
        total_cands = len(state.candidates)
        active = len(state.active_candidates)
        succeeded = len(state.succeeded_candidates)
        cand_failed = len(state.failed_candidates)
        abandoned = sum(1 for c in state.candidates if c.status.value == "abandoned")

        # Find best candidate metrics
        best_metrics = self._get_best_metrics(state)

        candidates.update(
            "[bold cyan]Candidates[/]\n\n"
            f"  Total:     {total_cands}\n"
            f"  Active:    [yellow]{active}[/]\n"
            f"  Succeeded: [green]{succeeded}[/]\n"
            f"  Failed:    [red]{cand_failed}[/]\n"
            f"  Abandoned: [dim]{abandoned}[/]\n"
            f"  Best:      {best_metrics}"
        )

        # Usage section
        usage = self.query_one("#stats-usage", Static)
        tokens = runtime.total_tokens_used
        cost = runtime.total_cost_usd

        usage.update(f"[bold cyan]Usage[/]\n\n  Tokens: {tokens:,}\n  Cost:   ${cost:.4f}")

    def _format_status(self, status: str) -> str:
        """Format runtime status with color."""
        if status == "running":
            return "[green bold]running[/]"
        elif status == "stopped":
            return "[red]stopped[/]"
        else:
            return f"[yellow]{status}[/]"

    def _get_best_metrics(self, state: MonitorState) -> str:
        """Get the best metrics from succeeded candidates."""
        if not state.evaluations:
            return "[dim]-[/]"

        # Find passed evaluations
        passed = [e for e in state.evaluations if e.passed]
        if not passed:
            # Fall back to any evaluation
            if state.evaluations:
                latest = max(state.evaluations, key=lambda e: e.timestamp)
                if latest.metrics:
                    first_key = next(iter(latest.metrics))
                    return f"{first_key}={latest.metrics[first_key]:.3f}"
            return "[dim]-[/]"

        # Get the best from passed evaluations
        latest_passed = max(passed, key=lambda e: e.timestamp)
        if latest_passed.metrics:
            # Show first metric
            first_key = next(iter(latest_passed.metrics))
            value = latest_passed.metrics[first_key]
            return f"[green]{first_key}={value:.3f}[/]"

        return "[dim]-[/]"
