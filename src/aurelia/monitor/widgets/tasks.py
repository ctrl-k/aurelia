"""Tasks pane widget showing running and pending tasks."""

from __future__ import annotations

from datetime import UTC, datetime

from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Static

from aurelia.core.models import Task, TaskStatus
from aurelia.monitor.widgets.task_detail import TaskDetailModal


class TasksPane(Vertical):
    """Left sidebar showing running and pending tasks."""

    BINDINGS = [
        Binding("enter", "show_detail", "Details", show=True),
    ]

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

    TasksPane .hint-text {
        text-align: center;
        color: $text-muted;
        padding: 0 0 1 0;
    }
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._tasks: list[Task] = []
        self._task_id_to_row: dict[str, int] = {}

    def compose(self):
        """Compose the pane layout."""
        yield Static("[bold]Tasks[/]", classes="pane-title")
        yield Static("[dim]Press Enter for details[/]", classes="hint-text")
        yield DataTable(id="tasks-table", cursor_type="row")

    def on_mount(self) -> None:
        """Initialize the data table."""
        table = self.query_one("#tasks-table", DataTable)
        table.add_columns("ID", "Component", "Status", "Time")

    def update_tasks(self, tasks: list[Task]) -> None:
        """Update the tasks table with current tasks."""
        self._tasks = tasks
        self._task_id_to_row.clear()

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
        display_tasks = sorted_tasks[-25:]
        for row_idx, task in enumerate(display_tasks):
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
            self._task_id_to_row[task.id] = row_idx

    def action_show_detail(self) -> None:
        """Show detail modal for the selected task."""
        table = self.query_one("#tasks-table", DataTable)
        if table.cursor_row is None:
            return

        # Find the task for this row
        # The row index corresponds to the display order
        display_tasks = sorted(self._tasks, key=lambda t: (
            {TaskStatus.running: 0, TaskStatus.pending: 1,
             TaskStatus.success: 2, TaskStatus.failed: 2,
             TaskStatus.cancelled: 3}.get(t.status, 4),
            t.created_at
        ))[-25:]

        if 0 <= table.cursor_row < len(display_tasks):
            task = display_tasks[table.cursor_row]
            self.app.push_screen(TaskDetailModal(task))

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
