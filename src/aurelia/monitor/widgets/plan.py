"""Plan pane widget showing improvement plan items."""

from __future__ import annotations

from textual.containers import Vertical
from textual.widgets import DataTable, Static

from aurelia.core.models import Plan, PlanItem, PlanItemStatus


class PlanPane(Vertical):
    """Current improvement plan with status indicators."""

    DEFAULT_CSS = """
    PlanPane {
        height: 1fr;
        padding: 1;
    }

    PlanPane #plan-summary {
        height: 3;
        padding: 0 1;
        background: $surface;
        border-bottom: solid $primary-darken-2;
    }

    PlanPane DataTable {
        height: 1fr;
    }
    """

    def compose(self):
        """Compose the pane layout."""
        yield Static(id="plan-summary")
        yield DataTable(id="plan-table", cursor_type="row")

    def on_mount(self) -> None:
        """Initialize the data table."""
        table = self.query_one("#plan-table", DataTable)
        table.add_columns("", "ID", "Description", "Status", "Pri")

    def update_plan(self, plan: Plan | None) -> None:
        """Update the plan display."""
        summary = self.query_one("#plan-summary", Static)
        table = self.query_one("#plan-table", DataTable)

        if plan is None:
            summary.update("[dim italic]No plan loaded - using default dispatcher[/]")
            table.clear()
            return

        # Count items by status
        todo = sum(1 for it in plan.items if it.status == PlanItemStatus.todo)
        assigned = sum(1 for it in plan.items if it.status == PlanItemStatus.assigned)
        complete = sum(1 for it in plan.items if it.status == PlanItemStatus.complete)
        failed = sum(1 for it in plan.items if it.status == PlanItemStatus.failed)

        summary.update(
            f"[bold]{plan.summary}[/] [dim](rev {plan.revision})[/]\n"
            f"[blue]○ {todo}[/] todo  "
            f"[yellow]◐ {assigned}[/] assigned  "
            f"[green]● {complete}[/] complete  "
            f"[red]✗ {failed}[/] failed"
        )

        table.clear()

        # Sort by status (todo/assigned first), then priority
        def sort_key(item: PlanItem) -> tuple:
            status_order = {
                PlanItemStatus.assigned: 0,
                PlanItemStatus.todo: 1,
                PlanItemStatus.complete: 2,
                PlanItemStatus.failed: 3,
            }
            return (status_order.get(item.status, 4), item.priority)

        sorted_items = sorted(plan.items, key=sort_key)

        for item in sorted_items:
            icon = self._get_status_icon(item.status)
            status_style = self._get_status_style(item.status)

            # Truncate description
            desc = item.description
            if len(desc) > 50:
                desc = desc[:47] + "..."

            table.add_row(
                icon,
                item.id,
                desc,
                f"{status_style}{item.status}[/]",
                str(item.priority),
            )

    def _get_status_icon(self, status: PlanItemStatus) -> str:
        """Get icon for plan item status."""
        icons = {
            PlanItemStatus.todo: "[blue]○[/]",
            PlanItemStatus.assigned: "[yellow]◐[/]",
            PlanItemStatus.complete: "[green]●[/]",
            PlanItemStatus.failed: "[red]✗[/]",
        }
        return icons.get(status, "○")

    def _get_status_style(self, status: PlanItemStatus) -> str:
        """Get rich markup style for status."""
        styles = {
            PlanItemStatus.todo: "[blue]",
            PlanItemStatus.assigned: "[yellow]",
            PlanItemStatus.complete: "[green]",
            PlanItemStatus.failed: "[red]",
        }
        return styles.get(status, "[white]")
