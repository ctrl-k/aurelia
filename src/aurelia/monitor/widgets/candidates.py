"""Candidates pane widget showing solution branches."""

from __future__ import annotations

from textual.containers import Vertical
from textual.widgets import DataTable

from aurelia.core.models import Candidate, CandidateStatus, Evaluation


class CandidatesPane(Vertical):
    """Table of candidates with branch, status, and latest metrics."""

    DEFAULT_CSS = """
    CandidatesPane {
        height: 1fr;
        padding: 1;
    }

    CandidatesPane DataTable {
        height: 1fr;
    }
    """

    def compose(self):
        """Compose the pane layout."""
        yield DataTable(id="candidates-table", cursor_type="row")

    def on_mount(self) -> None:
        """Initialize the data table."""
        table = self.query_one("#candidates-table", DataTable)
        table.add_columns("ID", "Branch", "Status", "Best Metrics")

    def update_candidates(
        self,
        candidates: list[Candidate],
        evaluations: list[Evaluation],
    ) -> None:
        """Update the candidates table."""
        table = self.query_one("#candidates-table", DataTable)
        table.clear()

        # Build evaluation lookup by branch
        eval_by_branch: dict[str, list[Evaluation]] = {}
        for ev in evaluations:
            eval_by_branch.setdefault(ev.candidate_branch, []).append(ev)

        # Sort candidates: active first, then by creation time (newest first)
        def sort_key(c: Candidate) -> tuple:
            status_order = {
                CandidateStatus.active: 0,
                CandidateStatus.evaluating: 1,
                CandidateStatus.succeeded: 2,
                CandidateStatus.failed: 3,
                CandidateStatus.abandoned: 4,
            }
            return (status_order.get(c.status, 5), -c.created_at.timestamp())

        sorted_candidates = sorted(candidates, key=sort_key)

        for cand in sorted_candidates:
            status_style = self._get_status_style(cand.status)
            status_text = self._get_status_text(cand.status)

            # Get best metrics from evaluations
            evals = eval_by_branch.get(cand.branch, [])
            metrics_str = self._format_metrics(evals)

            # Truncate branch name to fit
            branch_display = cand.branch
            if len(branch_display) > 25:
                branch_display = "..." + branch_display[-22:]

            table.add_row(
                cand.id,
                branch_display,
                f"{status_style}{status_text}[/]",
                metrics_str,
            )

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

    def _get_status_text(self, status: CandidateStatus) -> str:
        """Get display text for status."""
        texts = {
            CandidateStatus.active: "● active",
            CandidateStatus.evaluating: "◐ eval",
            CandidateStatus.succeeded: "✓ pass",
            CandidateStatus.failed: "✗ fail",
            CandidateStatus.abandoned: "- drop",
        }
        return texts.get(status, "? ???")

    def _format_metrics(self, evals: list[Evaluation]) -> str:
        """Format the best metrics from evaluations."""
        if not evals:
            return "[dim]-[/]"

        # Get the latest evaluation
        latest = max(evals, key=lambda e: e.timestamp)

        if not latest.metrics:
            return "[dim]-[/]"

        # Format up to 3 metrics
        parts = []
        for key, value in list(latest.metrics.items())[:3]:
            if isinstance(value, float):
                parts.append(f"{key}={value:.3f}")
            else:
                parts.append(f"{key}={value}")

        result = ", ".join(parts)

        # Color based on passed status
        if latest.passed:
            return f"[green]{result}[/]"
        else:
            return result
