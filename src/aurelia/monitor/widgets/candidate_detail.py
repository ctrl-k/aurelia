"""Candidate detail modal showing full candidate information."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from aurelia.core.models import Candidate, CandidateStatus, Evaluation


class CandidateDetailModal(ModalScreen[None]):
    """Modal showing candidate details and evaluation history."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close", show=True),
        Binding("q", "dismiss", "Close", show=False),
    ]

    DEFAULT_CSS = """
    CandidateDetailModal {
        align: center middle;
    }

    CandidateDetailModal > Vertical {
        width: 80;
        max-width: 90%;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }

    CandidateDetailModal .modal-title {
        text-style: bold;
        text-align: center;
        padding: 1;
        background: $primary;
        color: $text;
        margin-bottom: 1;
    }

    CandidateDetailModal .field-label {
        text-style: bold;
        color: $accent;
    }

    CandidateDetailModal .field-value {
        padding-left: 2;
        margin-bottom: 1;
    }

    CandidateDetailModal .section-title {
        text-style: bold;
        margin-top: 1;
        padding-bottom: 1;
        border-bottom: solid $primary;
    }

    CandidateDetailModal .eval-pass {
        color: $success;
    }

    CandidateDetailModal .eval-fail {
        color: $error;
    }

    CandidateDetailModal .eval-item {
        padding: 1;
        margin-bottom: 1;
        border: solid $surface-lighten-2;
    }

    CandidateDetailModal VerticalScroll {
        height: auto;
        max-height: 15;
    }

    CandidateDetailModal Button {
        margin-top: 1;
        width: 100%;
    }
    """

    def __init__(
        self, candidate: Candidate, evaluations: list[Evaluation]
    ) -> None:
        super().__init__()
        self._candidate = candidate
        # Filter evaluations for this candidate
        self._evaluations = [
            e for e in evaluations if e.candidate_branch == candidate.branch
        ]

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        cand = self._candidate

        with Vertical():
            yield Static(f"Candidate: {cand.id}", classes="modal-title")

            yield Static("Branch:", classes="field-label")
            yield Static(cand.branch, classes="field-value")

            yield Static("Parent Branch:", classes="field-label")
            yield Static(cand.parent_branch or "main", classes="field-value")

            yield Static("Status:", classes="field-label")
            status_style = self._get_status_style(cand.status)
            yield Static(f"{status_style}{cand.status.value}[/]", classes="field-value")

            yield Static("Created:", classes="field-label")
            created_str = cand.created_at.strftime("%Y-%m-%d %H:%M:%S")
            yield Static(created_str, classes="field-value")

            yield Static("Worktree:", classes="field-label")
            yield Static(cand.worktree_path or "[dim]Not set[/]", classes="field-value")

            yield Static("Evaluation History", classes="section-title")

            if self._evaluations:
                with VerticalScroll():
                    # Sort by timestamp, newest first
                    sorted_evals = sorted(
                        self._evaluations,
                        key=lambda e: e.timestamp,
                        reverse=True,
                    )
                    for ev in sorted_evals:
                        yield self._render_evaluation(ev)
            else:
                yield Static("[dim]No evaluations yet[/]", classes="field-value")

            yield Button("Close", id="close-btn", variant="primary")

    def _render_evaluation(self, ev: Evaluation) -> Static:
        """Render a single evaluation entry."""
        status_class = "eval-pass" if ev.passed else "eval-fail"
        status_icon = "[green]PASS[/]" if ev.passed else "[red]FAIL[/]"

        # Format timestamp
        time_str = ev.timestamp.strftime("%H:%M:%S")

        # Format metrics
        if ev.metrics:
            metrics_parts = []
            for key, value in list(ev.metrics.items())[:4]:
                if isinstance(value, float):
                    metrics_parts.append(f"{key}={value:.3f}")
                else:
                    metrics_parts.append(f"{key}={value}")
            metrics_str = ", ".join(metrics_parts)
        else:
            metrics_str = "[dim]no metrics[/]"

        # Commit SHA (truncated)
        commit_str = ev.commit_sha[:8] if ev.commit_sha else "unknown"

        content = f"{time_str} {status_icon} commit:{commit_str}\n  {metrics_str}"
        return Static(content, classes=f"eval-item {status_class}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        if event.button.id == "close-btn":
            self.dismiss()

    def _get_status_style(self, status: CandidateStatus) -> str:
        """Get rich markup style for status."""
        styles = {
            CandidateStatus.active: "[yellow]",
            CandidateStatus.evaluating: "[blue]",
            CandidateStatus.succeeded: "[green]",
            CandidateStatus.failed: "[red]",
            CandidateStatus.abandoned: "[dim]",
        }
        return styles.get(status, "[white]")
