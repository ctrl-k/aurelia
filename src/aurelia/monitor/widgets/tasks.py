"""Tasks pane widget showing running and pending tasks."""

from __future__ import annotations

from datetime import UTC, datetime

from textual.containers import Vertical
from textual.widgets import DataTable, Static

from aurelia.core.models import Task, TaskStatus


class TasksPane(Vertical):
    """Left sidebar showing running and pending tasks."""

    DEFAULT_CSS = """
    TasksPane {
        width: 38;
        border: solid $accent;
        padding: 0 1;
    }

    TasksPane .pane-title {
        text-style: bold;
        padding: 1 0;
        color: $text;
    }

    TasksPane DataTable {
        height: 1fr;
    }
    """

    def compose(self):
        """Compose the pane layout."""
        yield Static("[bold]Tasks[/]", classes="pane-title")
        yield DataTable(id="tasks-table", cursor_type="row")

    def on_mount(self) -> None:
        """Initialize the data table."""
        table = self.query_one("#tasks-table", DataTable)
        table.add_columns("ID", "Component", "Status", "Time")

    def update_tasks(self, tasks: list[Task]) -> None:
        """Update the tasks table with current tasks."""
        table = self.query_one("#tasks-table", DataTable)
        table.clear()

        # Sort: running first, then pending, then recent completed/failed
        def sort_key(t: Task) -> tuple:
            status_order = {
                TaskStatus.running: 0,
                TaskStatus.pending: 1,
                TaskStatus.success: 2,
                TaskStatus.failed: 2,
                TaskStatus.cancelled: 3,
            }
            return (status_order.get(t.status, 4), t.created_at)

        sorted_tasks = sorted(tasks, key=sort_key)

        # Show last 25 tasks
        for task in sorted_tasks[-25:]:
            status_style = self._get_status_style(task.status)
            status_icon = self._get_status_icon(task.status)
            duration = self._format_duration(task)

            # Truncate component name if needed
            component = task.component[:10]

            table.add_row(
                task.id[-8:],  # Last 8 chars (e.g., "task-0012")
                component,
                f"{status_style}{status_icon}[/]",
                duration,
            )

    def _get_status_style(self, status: TaskStatus) -> str:
        """Get rich markup style for status."""
        styles = {
            TaskStatus.running: "[yellow]",
            TaskStatus.pending: "[blue]",
            TaskStatus.success: "[green]",
            TaskStatus.failed: "[red]",
            TaskStatus.cancelled: "[dim]",
        }
        return styles.get(status, "[white]")

    def _get_status_icon(self, status: TaskStatus) -> str:
        """Get icon for task status."""
        icons = {
            TaskStatus.running: "● run",
            TaskStatus.pending: "○ wait",
            TaskStatus.success: "✓ done",
            TaskStatus.failed: "✗ fail",
            TaskStatus.cancelled: "- skip",
        }
        return icons.get(status, "? ???")

    def _format_duration(self, task: Task) -> str:
        """Format task duration."""
        if task.started_at is None:
            return "-"

        if task.completed_at is not None:
            end = task.completed_at
        else:
            end = datetime.now(UTC)
            if task.started_at.tzinfo is None:
                end = datetime.now()

        delta = end - task.started_at
        secs = int(delta.total_seconds())

        if secs < 0:
            return "-"
        if secs < 60:
            return f"{secs}s"
        mins, secs = divmod(secs, 60)
        if mins < 60:
            return f"{mins}m{secs}s"
        hours, mins = divmod(mins, 60)
        return f"{hours}h{mins}m"
