"""Task detail modal showing full task information."""

from __future__ import annotations

from datetime import UTC, datetime

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from aurelia.core.models import Task, TaskStatus


class TaskDetailModal(ModalScreen[None]):
    """Modal showing full task details."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close", show=True),
        Binding("q", "dismiss", "Close", show=False),
    ]

    DEFAULT_CSS = """
    TaskDetailModal {
        align: center middle;
    }

    TaskDetailModal > Vertical {
        width: 80;
        max-width: 90%;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }

    TaskDetailModal .modal-title {
        text-style: bold;
        text-align: center;
        padding: 1;
        background: $primary;
        color: $text;
        margin-bottom: 1;
    }

    TaskDetailModal .field-label {
        text-style: bold;
        color: $accent;
    }

    TaskDetailModal .field-value {
        padding-left: 2;
        margin-bottom: 1;
    }

    TaskDetailModal .section-title {
        text-style: bold;
        margin-top: 1;
        padding-bottom: 1;
        border-bottom: solid $primary;
    }

    TaskDetailModal .error-text {
        color: $error;
        padding-left: 2;
    }

    TaskDetailModal .success-text {
        color: $success;
    }

    TaskDetailModal .metrics-list {
        padding-left: 2;
    }

    TaskDetailModal VerticalScroll {
        height: auto;
        max-height: 20;
    }

    TaskDetailModal Button {
        margin-top: 1;
        width: 100%;
    }
    """

    def __init__(self, task: Task) -> None:
        super().__init__()
        self._task = task

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        task = self._task

        with Vertical():
            yield Static(f"Task: {task.id}", classes="modal-title")

            yield Static("Component:", classes="field-label")
            yield Static(task.component, classes="field-value")

            yield Static("Branch:", classes="field-label")
            yield Static(task.branch, classes="field-value")

            yield Static("Status:", classes="field-label")
            status_style = self._get_status_style(task.status)
            yield Static(f"{status_style}{task.status.value}[/]", classes="field-value")

            yield Static("Duration:", classes="field-label")
            yield Static(self._format_duration(task), classes="field-value")

            yield Static("Instruction", classes="section-title")
            with VerticalScroll():
                yield Static(task.instruction or "[dim]No instruction[/]", classes="field-value")

            if task.result:
                yield Static("Result", classes="section-title")
                yield Static(task.result.summary or "[dim]No summary[/]", classes="field-value")

                if task.result.error:
                    yield Static("Error:", classes="field-label")
                    yield Static(task.result.error[:500], classes="error-text")

                if task.result.metrics:
                    yield Static("Metrics:", classes="field-label")
                    metrics_lines = []
                    for key, value in task.result.metrics.items():
                        if isinstance(value, float):
                            metrics_lines.append(f"  {key}: {value:.4f}")
                        else:
                            metrics_lines.append(f"  {key}: {value}")
                    yield Static("\n".join(metrics_lines), classes="metrics-list")

            yield Button("Close", id="close-btn", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        if event.button.id == "close-btn":
            self.dismiss()

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

    def _format_duration(self, task: Task) -> str:
        """Format task duration."""
        if task.started_at is None:
            return "Not started"

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
            return f"{secs} seconds"
        mins, secs = divmod(secs, 60)
        if mins < 60:
            return f"{mins}m {secs}s"
        hours, mins = divmod(mins, 60)
        return f"{hours}h {mins}m {secs}s"
