"""Header widget showing runtime status."""

from __future__ import annotations

from datetime import UTC, datetime

from textual.widgets import Static

from aurelia.core.models import RuntimeState


class HeaderWidget(Static):
    """Runtime status bar with uptime, heartbeat indicator, and key metrics."""

    DEFAULT_CSS = """
    HeaderWidget {
        height: 3;
        background: $surface;
        border-bottom: solid $primary;
        padding: 0 2;
        content-align: left middle;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._status = "unknown"
        self._heartbeat_count = 0
        self._last_heartbeat: datetime | None = None
        self._started_at: datetime | None = None
        self._tasks_dispatched = 0
        self._tasks_completed = 0
        self._tasks_failed = 0

    def update_state(self, runtime: RuntimeState) -> None:
        """Update with new runtime state."""
        self._status = runtime.status
        self._heartbeat_count = runtime.heartbeat_count
        self._last_heartbeat = runtime.last_heartbeat_at
        self._started_at = runtime.started_at
        self._tasks_dispatched = runtime.total_tasks_dispatched
        self._tasks_completed = runtime.total_tasks_completed
        self._tasks_failed = runtime.total_tasks_failed
        self.refresh()

    def render(self) -> str:
        """Render the header content."""
        # Status with color
        status_styles = {
            "running": "[green bold]",
            "stopped": "[red]",
            "unknown": "[yellow]",
        }
        status_style = status_styles.get(self._status, "[white]")

        # Heartbeat indicator (pulsing dot)
        heartbeat_icon = self._get_heartbeat_icon()

        # Uptime
        uptime = self._format_uptime()

        # Task summary
        task_summary = (
            f"[green]{self._tasks_completed}[/]/"
            f"[red]{self._tasks_failed}[/]/"
            f"{self._tasks_dispatched}"
        )

        return (
            f" {heartbeat_icon} "
            f"Status: {status_style}{self._status}[/] "
            f"[dim]|[/] Heartbeats: [cyan]{self._heartbeat_count}[/] "
            f"[dim]|[/] Uptime: {uptime} "
            f"[dim]|[/] Tasks: {task_summary} "
            f"[dim](done/fail/total)[/]"
        )

    def _get_heartbeat_icon(self) -> str:
        """Get heartbeat indicator based on recency."""
        if self._last_heartbeat is None:
            return "[dim]○[/]"

        now = datetime.now(UTC)
        if self._last_heartbeat.tzinfo is None:
            # Handle naive datetime
            age = (datetime.now() - self._last_heartbeat).total_seconds()
        else:
            age = (now - self._last_heartbeat).total_seconds()

        if age < 10:
            return "[green bold]●[/]"
        elif age < 60:
            return "[yellow]●[/]"
        elif age < 120:
            return "[red]●[/]"
        else:
            return "[dim]○[/]"

    def _format_uptime(self) -> str:
        """Format runtime uptime."""
        if self._started_at is None:
            return "[dim]-[/]"

        now = datetime.now(UTC)
        if self._started_at.tzinfo is None:
            delta = datetime.now() - self._started_at
        else:
            delta = now - self._started_at

        total_secs = int(delta.total_seconds())
        if total_secs < 0:
            return "[dim]-[/]"

        hours, remainder = divmod(total_secs, 3600)
        minutes, seconds = divmod(remainder, 60)

        if hours > 0:
            return f"[cyan]{hours}h{minutes}m[/]"
        elif minutes > 0:
            return f"[cyan]{minutes}m{seconds}s[/]"
        else:
            return f"[cyan]{seconds}s[/]"
